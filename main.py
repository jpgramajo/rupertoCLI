import os
import io
import sys
import json
import hashlib
import pathspec
import threading
import concurrent.futures
from datetime import datetime
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload

SCOPES = ['https://www.googleapis.com/auth/drive']
RUPERTO_FILE = 'ruperto.json'
RUPERTO_CONFIG = 'ruperto.config'

# Bloqueo global para impresiones seguras desde hilos
_print_lock = threading.Lock()

# Almacén de datos para el progreso de subida concurrente
_upload_progress = {'completed': 0, 'total': 0}
_upload_progress_lock = threading.Lock()

# Almacén de datos para el progreso de descarga concurrente
_download_progress = {'completed': 0, 'total': 0}
_download_progress_lock = threading.Lock()

class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    DIM = '\033[2m'

def print_header(text):
    print(f"\n{Colors.BOLD}{Colors.CYAN}{'='*60}{Colors.ENDC}")
    print(f"{Colors.BOLD}{Colors.CYAN}{text.center(60)}{Colors.ENDC}")
    print(f"{Colors.BOLD}{Colors.CYAN}{'='*60}{Colors.ENDC}\n")

def safe_print(text):
    """Imprime de forma segura para hilos"""
    with _print_lock:
        print(text)

def print_info(text):
    safe_print(f"{Colors.BLUE}ℹ{Colors.ENDC} {text}")

def print_success(text):
    safe_print(f"{Colors.GREEN}✓{Colors.ENDC} {text}")

def print_warning(text):
    safe_print(f"{Colors.YELLOW}⚠{Colors.ENDC} {text}")

def print_error(text):
    safe_print(f"{Colors.RED}✗{Colors.ENDC} {text}")

def print_download(text):
    safe_print(f"{Colors.GREEN}⬇{Colors.ENDC} {text}")

def print_upload(text):
    safe_print(f"{Colors.CYAN}⬆{Colors.ENDC} {text}")

def print_delete(text):
    safe_print(f"{Colors.RED}🗑{Colors.ENDC} {text}")

def print_progress(filename, percent):
    bar_length = 40
    filled = int(bar_length * percent / 100)
    bar = '█' * filled + '░' * (bar_length - filled)
    print(f"\r  {Colors.DIM}{bar}{Colors.ENDC} {percent:.1f}% - {filename}", end='', flush=True)

def extract_folder_id(link):
    """Extrae el ID de la carpeta del link de Google Drive"""
    if '/folders/' in link:
        return link.split('/folders/')[-1].split('?')[0]
    return link

def get_script_dir():
    """Obtiene el directorio del script"""
    if getattr(sys, 'frozen', False):
        # Estamos en un ejecutable (PyInstaller)
        return os.path.dirname(sys.executable)
    else:
        # Estamos en un script normal
        return os.path.dirname(os.path.realpath(__file__))

def get_local_md5(filepath):
    """Calcula el MD5 de un archivo local. Devuelve None si no existe."""
    if not os.path.exists(filepath):
        return None
    hash_md5 = hashlib.md5()
    try:
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()
    except IOError:
        print_warning(f"No se pudo leer el archivo local: {filepath}")
        return None

def authenticate():
    """Autentica con Google Drive API y guarda el token"""
    creds = None
    
    script_dir = get_script_dir()
    token_path = os.path.join(script_dir, 'token.json')
    credentials_path = os.path.join(script_dir, 'credentials.json')
    
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    
    if not creds or not creds.valid:
        try:
            if creds and creds.expired and creds.refresh_token:
                print_info("Refrescando token de autenticación...")
                creds.refresh(Request())
            else:
                # Si no hay credenciales o no se pueden refrescar, se lanza una excepción
                # para forzar el flujo de autenticación completo.
                raise Exception("No hay credenciales válidas para refrescar.")
        except Exception as e:
            print_warning(f"No se pudo refrescar el token ({e}). Se requiere nueva autenticación.")
            
            if not os.path.exists(credentials_path):
                print_error(f"No se encontró 'credentials.json' en {script_dir}")
                print_info("Descarga 'credentials.json' desde Google Cloud Console y colócalo junto al ejecutable.")
                sys.exit(1)
                
            print_info("Iniciando proceso de autenticación (esto abrirá tu navegador)...")
            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
            creds = flow.run_local_server(port=8085)
        finally:
            with open(token_path, 'w') as token:
                token.write(creds.to_json())
    
    return creds

def download_file(service, file_id, file_path, file_name, show_progress=True):
    """Descarga un archivo de Google Drive"""
    request = service.files().get_media(fileId=file_id)
    
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    
    fh = io.FileIO(file_path, 'wb')
    downloader = MediaIoBaseDownload(fh, request)
    
    done = False
    while not done:
        status, done = downloader.next_chunk()
        if status and show_progress:
            progress = int(status.progress() * 100)
            print_progress(file_name, progress)
    
    if show_progress:
        print()
    fh.close()

def upload_file(service, file_path, parent_id, file_name, file_id=None, show_progress=True):
    """Sube o actualiza un archivo en Google Drive"""
    media = MediaFileUpload(file_path, resumable=True)
    
    if file_id:
        # Actualizar archivo existente
        request = service.files().update(
            fileId=file_id,
            media_body=media
        )
    else:
        # Crear archivo nuevo
        file_metadata = {
            'name': file_name,
            'parents': [parent_id]
        }
        request = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id, md5Checksum, modifiedTime'
        )
    
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status and show_progress:
            progress = int(status.progress() * 100)
            print_progress(file_name, progress)
    
    if show_progress:
        print()
    return response

def create_folder(service, folder_name, parent_id):
    """Crea una carpeta en Google Drive"""
    file_metadata = {
        'name': folder_name,
        'mimeType': 'application/vnd.google-apps.folder',
        'parents': [parent_id]
    }
    folder = service.files().create(body=file_metadata, fields='id').execute()
    return folder['id']

def delete_file(service, file_id):
    """Elimina un archivo o carpeta de Google Drive"""
    service.files().delete(fileId=file_id).execute()

def get_remote_files_map(service, folder_id, base_path=""):
    """
    Obtiene un mapa de todos los archivos remotos con sus metadatos (incluyendo md5Checksum)
    """
    files_map = {}
    page_token = None
    
    while True:
        query = f"'{folder_id}' in parents and trashed=false"
        results = service.files().list(
            q=query,
            fields="nextPageToken, files(id, name, mimeType, modifiedTime, md5Checksum, size)", # MD5CHECKSUM ES CLAVE
            pageSize=1000,
            pageToken=page_token
        ).execute()
        
        items = results.get('files', [])
        
        for item in items:
            item_name = item['name']
            item_path = os.path.join(base_path, item_name).replace(os.sep, '/') # Usar /
            
            if item['mimeType'] == 'application/vnd.google-apps.folder':
                subfolder_files = get_remote_files_map(service, item['id'], item_path)
                files_map[item_path] = {
                    'id': item['id'],
                    'name': item_name,
                    'mimeType': 'application/vnd.google-apps.folder',
                    'is_folder': True
                }
                files_map.update(subfolder_files)
            elif not item['mimeType'].startswith('application/vnd.google-apps.'):
                files_map[item_path] = {
                    'id': item['id'],
                    'name': item_name,
                    'modified': item.get('modifiedTime'),
                    'md5': item.get('md5Checksum'), # ¡Aquí está!
                    'size': item.get('size'),
                    'mimeType': item['mimeType'],
                    'is_folder': False
                }
        
        page_token = results.get('nextPageToken', None)
        if page_token is None:
            break
            
    return files_map

def get_local_files_map(folder_path, gitignore_specs, keep_patterns, ignore_patterns):
    """
    Obtiene un mapa de todos los archivos locales, respetando .gitignore y ruperto.config
    Usa topdown=True para podar directorios ignorados.
    """
    files_map = {}
    ignored_file_count = 0
    folder_path = os.path.abspath(folder_path)

    for root, dirs, files in os.walk(folder_path, topdown=True):
        rel_root = os.path.relpath(root, folder_path)
        if rel_root == '.':
            rel_root = ''

        # Podar directorios (dirs)
        dirs_to_remove = []
        for i, dir_name in enumerate(dirs):
            rel_path = os.path.join(rel_root, dir_name).replace(os.sep, '/')
            if should_ignore_file(rel_path, gitignore_specs, keep_patterns, ignore_patterns, is_dir=True):
                dirs_to_remove.append(dir_name)
        
        for dir_name in dirs_to_remove:
            dirs.remove(dir_name) # Esto evita que os.walk entre en este directorio

        # Procesar archivos (files)
        for file in files:
            if file == RUPERTO_FILE:
                continue
            
            rel_path = os.path.join(rel_root, file).replace(os.sep, '/')
            
            if should_ignore_file(rel_path, gitignore_specs, keep_patterns, ignore_patterns, is_dir=False):
                ignored_file_count += 1
                continue
                
            full_path = os.path.join(root, file)
            files_map[rel_path] = {
                'path': full_path,
                'is_folder': False
            }
        
        # Añadir las carpetas que SÍ se procesaron
        for dir_name in dirs: # 'dirs' ya está podado
            rel_path = os.path.join(rel_root, dir_name).replace(os.sep, '/')
            files_map[rel_path] = {
                'path': os.path.join(root, dir_name),
                'is_folder': True
            }
    
    return files_map, ignored_file_count

def save_ruperto_metadata(folder_path, folder_id, folder_name):
    """
    Guarda los metadatos mínimos en ruperto.json (solo IDs).
    El mapa de archivos ya no es necesario.
    """
    metadata = {
        'version': '1.1-md5', # Versión actualizada
        'folder_id': folder_id,
        'folder_name': folder_name,
        'last_sync': datetime.now().isoformat()
    }
    
    ruperto_path = os.path.join(folder_path, RUPERTO_FILE)
    with open(ruperto_path, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

def load_ruperto_metadata(folder_path):
    """Carga los metadatos desde ruperto.json"""
    ruperto_path = os.path.join(folder_path, RUPERTO_FILE)
    if not os.path.exists(ruperto_path):
        return None
    
    try:
        with open(ruperto_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError:
        print_error(f"Error: El archivo {RUPERTO_FILE} está corrupto (JSON inválido).")
        return None

def load_ruperto_config():
    """Carga la configuración desde ruperto.config"""
    script_dir = get_script_dir()
    config_path = os.path.join(script_dir, RUPERTO_CONFIG)
    
    defaults = {
        'keep': [],
        'ignore': [],
        'parallel_uploads': 8,
        'parallel_downloads': 8
    }
    
    if not os.path.exists(config_path):
        print_info(f"No se encontró {RUPERTO_CONFIG}, usando valores por defecto.")
        return defaults
    
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
            defaults.update(config) # Sobreescribe defaults con lo que hay en config
            return defaults
    except json.JSONDecodeError:
        print_error(f"Error: {RUPERTO_CONFIG} está corrupto (JSON inválido). Usando valores por defecto.")
        return defaults

def load_gitignore_patterns(folder_path):
    """Carga todos los .gitignore en la carpeta y subcarpetas"""
    gitignore_specs = {}
    
    for root, dirs, files in os.walk(folder_path):
        if '.gitignore' in files:
            gitignore_path = os.path.join(root, '.gitignore')
            rel_root = os.path.relpath(root, folder_path)
            if rel_root == '.':
                rel_root = ''
            else:
                rel_root = rel_root.replace(os.sep, '/')
            
            try:
                with open(gitignore_path, 'r', encoding='utf-8') as f:
                    patterns = f.read()
                    spec = pathspec.PathSpec.from_lines('gitwildmatch', patterns.splitlines())
                    gitignore_specs[rel_root] = spec
            except Exception as e:
                print_warning(f"No se pudo leer {gitignore_path}: {e}")
    
    return gitignore_specs

def should_ignore_file(rel_path, gitignore_specs, keep_patterns, ignore_patterns, is_dir=False):
    """
    Determina si un archivo debe ser ignorado.
    Prioridad: 1) ignore (config), 2) keep (config), 3) .gitignore
    """
    rel_path_posix = rel_path.replace(os.sep, '/')
    file_name = os.path.basename(rel_path_posix)

    # 1. Lista "ignore" (máxima prioridad)
    if ignore_patterns:
        # Usar PathSpec para "ignore" también, para que coincida con patrones como 'node_modules/'
        ignore_spec = pathspec.PathSpec.from_lines('gitwildmatch', ignore_patterns)
        if ignore_spec.match_file(rel_path_posix) or (is_dir and ignore_spec.match_file(rel_path_posix + '/')):
             return True

    # 2. Lista "keep" (segunda prioridad)
    if keep_patterns:
        keep_spec = pathspec.PathSpec.from_lines('gitwildmatch', keep_patterns)
        if keep_spec.match_file(rel_path_posix) or (is_dir and keep_spec.match_file(rel_path_posix + '/')):
            return False # Es "keep", no ignorar

    # 3. Patrones .gitignore (última prioridad)
    for base_path, spec in gitignore_specs.items():
        if base_path == '':
            check_path = rel_path_posix
        elif rel_path_posix.startswith(base_path + '/'):
            check_path = os.path.relpath(rel_path_posix, base_path).replace(os.sep, '/')
        else:
            continue
        
        # Añadir '/' a los directorios para que gitwildmatch los trate como tal
        if is_dir:
            check_path += '/'

        if spec.match_file(check_path):
            return True
    
    return False

def count_items(service, folder_id):
    """Cuenta recursivamente el total de archivos en la carpeta"""
    query = f"'{folder_id}' in parents and trashed=false"
    page_token = None
    count = 0

    while True:
        results = service.files().list(
            q=query,
            fields="nextPageToken, files(id, mimeType)",
            pageSize=1000,
            pageToken=page_token
        ).execute()
        
        items = results.get('files', [])
        
        for item in items:
            if item['mimeType'] == 'application/vnd.google-apps.folder':
                count += count_items(service, item['id']) # Recursión
            elif not item['mimeType'].startswith('application/vnd.google-apps.'):
                count += 1
        
        page_token = results.get('nextPageToken', None)
        if page_token is None:
            break
            
    return count

def _download_worker(creds, remote_info, local_path, rel_path, total_files):
    """Trabajador para descargar un archivo en un hilo"""
    try:
        # Cada hilo necesita su propio servicio
        service = build('drive', 'v3', credentials=creds)
        
        with _download_progress_lock:
            _download_progress['completed'] += 1
            completed = _download_progress['completed']
        
        # Usar safe_print para mostrar el progreso general
        safe_print(f" {Colors.CYAN}[{completed}/{total_files}]{Colors.ENDC} {Colors.GREEN}⬇{Colors.ENDC} {rel_path}")
        
        download_file(service, remote_info['id'], local_path, remote_info['name'], show_progress=False)
    except Exception as e:
        print_error(f"Error al descargar {rel_path}: {e}")

def download_command(service, folder_path, creds, config):
    """Descarga cambios desde Drive, sobreescribiendo archivos locales (paralelo y con MD5)"""
    metadata = load_ruperto_metadata(folder_path)
    
    if not metadata:
        print_error(f"No se encontró {RUPERTO_FILE} en la carpeta actual")
        print_info("Esta carpeta no fue clonada con RupertoCLI")
        return
    
    folder_id = metadata['folder_id']
    folder_name = metadata['folder_name']
    
    print_info(f"Descargando cambios de: {Colors.BOLD}{folder_name}{Colors.ENDC}")
    print_warning("Los cambios locales modificados serán sobreescritos\n")
    
    print_info("Obteniendo estado de Google Drive (MD5)...")
    remote_files = get_remote_files_map(service, folder_id)
    
    print_info("Analizando estado local (MD5)...")
    # Para 'download', no necesitamos filtrar archivos locales, solo obtener el mapa
    local_files_map, _ = get_local_files_map(folder_path, {}, [], [])
    
    to_download = []
    to_delete = []
    unchanged_count = 0
    
    # --- Lógica de Sincronización MD5 ---
    
    # 1. Archivos a descargar/actualizar
    for rel_path, remote_info in remote_files.items():
        if remote_info.get('is_folder'):
            continue # Ignorar carpetas aquí
            
        local_path = os.path.join(folder_path, rel_path.replace('/', os.sep))
        local_md5 = get_local_md5(local_path)
        remote_md5 = remote_info.get('md5')

        if local_md5 is None:
            # Archivo no existe localmente, descargar
            to_download.append((rel_path, remote_info))
        elif local_md5 != remote_md5:
            # Archivo modificado, descargar
            to_download.append((rel_path, remote_info))
        else:
            # Archivo sin cambios
            unchanged_count += 1

    # 2. Archivos locales a eliminar (no existen en remoto)
    for rel_path in local_files_map:
        if rel_path not in remote_files and not local_files_map[rel_path]['is_folder']:
            to_delete.append(rel_path)

    # --- Fin de Lógica MD5 ---

    if not to_download and not to_delete:
        print_success("Todo está sincronizado. No hay cambios.")
        print_info(f"  {Colors.DIM}Archivos sin cambios: {unchanged_count}{Colors.ENDC}")
        save_ruperto_metadata(folder_path, folder_id, folder_name) # Actualizar 'last_sync'
        return
    
    print(f"\n{Colors.BOLD}Resumen:{Colors.ENDC}")
    print(f"  {Colors.GREEN}A descargar (nuevos/modificados):{Colors.ENDC} {len(to_download)}")
    print(f"  {Colors.RED}A eliminar (locales):{Colors.ENDC} {len(to_delete)}")
    print(f"  {Colors.DIM}Archivos sin cambios:{Colors.ENDC} {unchanged_count}\n")
    
    if to_download:
        parallel_downloads = config.get('parallel_downloads', 8)
        print(f"{Colors.BOLD}Descargando archivos ({parallel_downloads} hilos)...{Colors.ENDC}")
        
        with _download_progress_lock:
            _download_progress['completed'] = 0
        
        total_downloads = len(to_download)
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=parallel_downloads) as executor:
            futures = []
            for rel_path, remote_info in to_download:
                local_path = os.path.join(folder_path, rel_path.replace('/', os.sep))
                futures.append(executor.submit(_download_worker, creds, remote_info, local_path, rel_path, total_downloads))
            
            concurrent.futures.wait(futures)

    if to_delete:
        print(f"\n{Colors.BOLD}Eliminando archivos locales...{Colors.ENDC}")
        for rel_path in to_delete:
            local_path = os.path.join(folder_path, rel_path.replace('/', os.sep))
            print_delete(f"{rel_path}")
            if os.path.exists(local_path):
                os.remove(local_path)
    
    # Limpiar carpetas locales vacías
    print_info("Limpiando directorios vacíos...")
    for root, dirs, files in os.walk(folder_path, topdown=False):
        # No eliminar directorios ignorados aunque estén vacíos (ej. .git)
        rel_root = os.path.relpath(root, folder_path).replace(os.sep, '/')
        if rel_root != '.' and should_ignore_file(rel_root, {}, [], config.get('ignore', []), is_dir=True):
            continue

        for dir_name in dirs:
            dir_path = os.path.join(root, dir_name)
            try:
                if not os.listdir(dir_path):
                    os.rmdir(dir_path)
                    print_delete(f"Directorio vacío: {os.path.relpath(dir_path, folder_path)}")
            except OSError as e:
                print_warning(f"No se pudo eliminar {dir_path}: {e}")
    
    save_ruperto_metadata(folder_path, folder_id, folder_name) # Actualizar 'last_sync'
    print(f"\n{Colors.GREEN}{Colors.BOLD}✓ Descarga completada!{Colors.ENDC}\n")

# Almacén de datos para el callback de creación de carpetas en lote
_batch_folder_data = {}
_batch_folder_lock = threading.Lock()

def _batch_folder_create_callback(request_id, response, exception):
    """Callback para el lote de creación de carpetas"""
    with _batch_folder_lock:
        request_map = _batch_folder_data.get('request_id_to_path', {})
        folder_ids_map = _batch_folder_data.get('folder_ids_map', {})
        rel_path = request_map.get(request_id, "RutaDesconocida")

        if exception:
            print_error(f"Error creando carpeta {rel_path}: {exception}")
        else:
            new_id = response.get('id')
            if new_id:
                folder_ids_map[rel_path] = new_id
                print_success(f"Carpeta creada: {rel_path} (ID: {new_id})")

def _upload_worker(creds, local_path, parent_id, file_name, existing_id, rel_path, total_files):
    """Trabajador para subir un archivo en un hilo"""
    try:
        # Cada hilo necesita su propio objeto 'service'
        service = build('drive', 'v3', credentials=creds)
        
        with _upload_progress_lock:
            _upload_progress['completed'] += 1
            completed = _upload_progress['completed']
        
        # Imprimir progreso general
        action_color = Colors.CYAN if existing_id else Colors.GREEN
        action_symbol = "⬆" if existing_id else "✚"
        safe_print(f" {Colors.CYAN}[{completed}/{total_files}]{Colors.ENDC} {action_color}{action_symbol}{Colors.ENDC} {rel_path}")
        
        # Ejecutar la subida (sin la barra de progreso individual)
        upload_file(service, local_path, parent_id, file_name, existing_id, show_progress=False)
        
    except Exception as e:
        print_error(f"Error al subir {rel_path}: {e}")

def upload_command(service, folder_path, creds, config):
    """Sube cambios locales a Drive (paralelo y con MD5)"""
    metadata = load_ruperto_metadata(folder_path)
    
    if not metadata:
        print_warning(f"No se encontró {RUPERTO_FILE} en la carpeta actual")
        print_info("Esta carpeta no fue clonada con RupertoCLI\n")
        
        print(f"{Colors.BOLD}¿Deseas subir esta carpeta a Google Drive?{Colors.ENDC}")
        print(f"{Colors.DIM}Se creará como una nueva carpeta en Drive{Colors.ENDC}\n")
        
        parent_link = input(f"Ingresa el link de la carpeta padre en Drive (o 'cancelar'): ").strip()
        
        if parent_link.lower() == 'cancelar':
            print_info("Operación cancelada")
            return
        
        parent_id = extract_folder_id(parent_link)
        folder_name = os.path.basename(os.path.abspath(folder_path))
        
        print_info(f"\nCreando carpeta '{Colors.BOLD}{folder_name}{Colors.ENDC}' en Drive...")
        
        try:
            new_folder_id = create_folder(service, folder_name, parent_id)
            print_success(f"Carpeta creada con ID: {new_folder_id}")
            
            print_info("Creando archivo de metadatos...")
            save_ruperto_metadata(folder_path, new_folder_id, folder_name) # Metadata mínima
            print_success(f"Archivo {RUPERTO_FILE} creado\n")
            
            metadata = load_ruperto_metadata(folder_path)
        except Exception as e:
            print_error(f"Error al crear la carpeta: {e}")
            print_info("Verifica que el link sea correcto y tengas permisos")
            return
    
    folder_id = metadata['folder_id']
    folder_name = metadata['folder_name']
    
    print_info(f"Subiendo cambios a: {Colors.BOLD}{folder_name}{Colors.ENDC}")
    print_warning("Los archivos modificados en Drive serán sobreescritos\n")
    
    print_info("Cargando configuración de RupertoCLI...")
    keep_patterns = config.get('keep', [])
    ignore_patterns = config.get('ignore', [])
    print_info(f"  Patrones a mantener (config): {Colors.DIM}{', '.join(keep_patterns) or 'Ninguno'}{Colors.ENDC}")
    print_info(f"  Patrones a ignorar (config): {Colors.DIM}{', '.join(ignore_patterns) or 'Ninguno'}{Colors.ENDC}")
    
    print_info("Cargando patrones de .gitignore...")
    gitignore_specs = load_gitignore_patterns(folder_path)
    if gitignore_specs:
        print_info(f"  Encontrados {len(gitignore_specs)} archivo(s) .gitignore")
    
    print_info("Analizando cambios locales (calculando MD5)...")
    local_files_map, ignored_count = get_local_files_map(folder_path, gitignore_specs, keep_patterns, ignore_patterns)
    
    print_info("Obteniendo estado de Google Drive (MD5)...")
    remote_files = get_remote_files_map(service, folder_id)
    
    folders_to_create = []
    files_to_upload = [] # Lista de tuplas (rel_path, local_path, parent_id, file_name, existing_id)
    files_to_delete = [] # Lista de tuplas (rel_path, file_id)
    unchanged_files_count = 0
    
    # Mapa de IDs de carpetas (remotas y locales)
    folder_ids = {'.': folder_id}
    # Añadir todas las carpetas remotas existentes
    for rel_path, remote_info in remote_files.items():
        if remote_info.get('is_folder'):
            folder_ids[rel_path] = remote_info['id']

    # --- Lógica de Sincronización MD5 ---

    # 1. Archivos a subir y carpetas a crear
    for rel_path, local_info in local_files_map.items():
        if local_info['is_folder']:
            if rel_path not in remote_files:
                folders_to_create.append(rel_path)
        else: # Es archivo
            local_path = local_info['path']
            local_md5 = get_local_md5(local_path)
            
            remote_info = remote_files.get(rel_path)
            
            if local_md5 is None:
                print_warning(f"No se pudo leer el archivo local {rel_path}, omitiendo.")
                continue

            if not remote_info:
                # Archivo nuevo, subir
                files_to_upload.append((rel_path, local_path, os.path.basename(rel_path), None))
            elif local_md5 != remote_info.get('md5'):
                # Archivo modificado, subir (actualizar)
                files_to_upload.append((rel_path, local_path, os.path.basename(rel_path), remote_info['id']))
            else:
                # Archivo sin cambios
                unchanged_files_count += 1
            
    # 2. Archivos remotos a eliminar
    for rel_path, remote_info in remote_files.items():
        if rel_path not in local_files_map and not remote_info.get('is_folder'):
            files_to_delete.append((rel_path, remote_info['id']))
            
    # --- Fin de Lógica MD5 ---
            
    if not folders_to_create and not files_to_upload and not files_to_delete:
        print_success("Todo está sincronizado. No hay cambios.")
        if ignored_count > 0:
            print_info(f"  {Colors.DIM}Archivos ignorados (config + .gitignore): {ignored_count}{Colors.ENDC}")
        if unchanged_files_count > 0:
            print_info(f"  {Colors.DIM}Archivos sin cambios (MD5): {unchanged_files_count}{Colors.ENDC}")
        save_ruperto_metadata(folder_path, folder_id, folder_name) # Actualizar 'last_sync'
        return
        
    print(f"\n{Colors.BOLD}Resumen:{Colors.ENDC}")
    print(f"  {Colors.YELLOW}Carpetas a crear:{Colors.ENDC} {len(folders_to_create)}")
    print(f"  {Colors.CYAN}Archivos a subir (nuevos/modificados):{Colors.ENDC} {len(files_to_upload)}")
    print(f"  {Colors.RED}Archivos a eliminar (en Drive):{Colors.ENDC} {len(files_to_delete)}")
    if ignored_count > 0:
        print(f"  {Colors.DIM}Ignorados (config + .gitignore):{Colors.ENDC} {ignored_count}")
    if unchanged_files_count > 0:
        print(f"  {Colors.DIM}Sin cambios (MD5):{Colors.ENDC} {unchanged_files_count}")
    print()
    
    if folders_to_create:
        print(f"{Colors.BOLD}Creando carpetas (en lotes por nivel)...{Colors.ENDC}")
        
        # 1. Agrupar carpetas por nivel de profundidad
        folders_by_depth = {}
        for rel_path in folders_to_create:
            depth = rel_path.count('/')
            if depth not in folders_by_depth:
                folders_by_depth[depth] = []
            folders_by_depth[depth].append(rel_path)
            
        # 2. Iterar por profundidad (Nivel 0, Nivel 1, ...)
        for depth in sorted(folders_by_depth.keys()):
            print_info(f"Creando Nivel {depth} ({len(folders_by_depth[depth])} carpetas)...")
            
            batch = service.new_batch_http_request(callback=_batch_folder_create_callback)
            request_counter = 0
            request_id_to_path = {}
            
            with _batch_folder_lock:
                _batch_folder_data['request_id_to_path'] = request_id_to_path
                _batch_folder_data['folder_ids_map'] = folder_ids

            for rel_path in folders_by_depth[depth]:
                parent_path = os.path.dirname(rel_path)
                if parent_path == '':
                    parent_path = '.'
                
                parent_id = folder_ids.get(parent_path)
                
                if not parent_id:
                    print_warning(f"No se encontró ID padre para '{rel_path}', omitiendo.")
                    continue
                    
                folder_name_only = os.path.basename(rel_path)
                file_metadata = {
                    'name': folder_name_only,
                    'mimeType': 'application/vnd.google-apps.folder',
                    'parents': [parent_id]
                }
                
                request_id = f"create-{rel_path}"
                request_id_to_path[request_id] = rel_path
                
                batch.add(
                    service.files().create(body=file_metadata, fields='id'),
                    request_id=request_id
                )
                request_counter += 1

                # Ejecutar el lote si alcanza el límite de 100
                if request_counter >= 100:
                    print_info(f"  Ejecutando lote parcial (100 carpetas)...")
                    try:
                        batch.execute()
                    except Exception as e:
                        print_error(f"  Error al ejecutar lote: {e}")
                    
                    # Reiniciar para el siguiente lote
                    request_counter = 0
                    batch = service.new_batch_http_request(callback=_batch_folder_create_callback)
                    request_id_to_path.clear()
                    with _batch_folder_lock:
                            _batch_folder_data['request_id_to_path'] = request_id_to_path
            
            # Ejecutar el lote final para este nivel
            if request_counter > 0:
                print_info(f"  Ejecutando lote final ({request_counter} carpetas)...")
                try:
                    batch.execute()
                except Exception as e:
                    print_error(f"  Error al ejecutar lote final: {e}")
    
    if files_to_upload:
        parallel_uploads = config.get('parallel_uploads', 8)
        print(f"\n{Colors.BOLD}Subiendo archivos ({parallel_uploads} hilos)...{Colors.ENDC}")
        
        with _upload_progress_lock:
            _upload_progress['completed'] = 0
        
        total_uploads = len(files_to_upload)
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=parallel_uploads) as executor:
            futures = []
            for rel_path, local_path, file_name, existing_id in files_to_upload:
                parent_path = os.path.dirname(rel_path)
                if parent_path == '':
                    parent_path = '.'
                
                parent_id = folder_ids.get(parent_path, folder_id) # Usar raíz si falla
                if parent_id == folder_id and parent_path != '.':
                     print_warning(f"Subiendo {rel_path} a la raíz (no se encontró ID de {parent_path})")
                
                futures.append(executor.submit(
                    _upload_worker, creds, local_path, parent_id, file_name, existing_id, rel_path, total_uploads
                ))
            
            concurrent.futures.wait(futures)

    if files_to_delete:
        print(f"\n{Colors.BOLD}Eliminando archivos en Drive...{Colors.ENDC}")
        for rel_path, file_id in files_to_delete:
            print_delete(f"{rel_path}")
            try:
                delete_file(service, file_id)
            except Exception as e:
                print_error(f"No se pudo eliminar {rel_path}: {e}")
    
    print_info(f"\nActualizando {RUPERTO_FILE}...")
    save_ruperto_metadata(folder_path, folder_id, folder_name) # Actualizar 'last_sync'
    
    print(f"\n{Colors.GREEN}{Colors.BOLD}✓ Subida completada!{Colors.ENDC}\n")

def clone_command(folder_link, config):
    """Comando para clonar una carpeta de Google Drive"""
    folder_id = extract_folder_id(folder_link)
    
    print_header("RupertoCLI - Clone")
    
    print_info("Autenticando con Google Drive...")
    creds = authenticate()
    service = build('drive', 'v3', credentials=creds)
    
    print_info("Obteniendo información de la carpeta...")
    try:
        folder_info = service.files().get(fileId=folder_id, fields='name').execute()
    except Exception as e:
        print_error(f"No se pudo obtener información de la carpeta (ID: {folder_id})")
        print_error(f"Error: {e}")
        print_info("Verifica el link y tus permisos.")
        return
        
    folder_name = folder_info['name']
    
    print_success(f"Carpeta encontrada: {Colors.BOLD}{folder_name}{Colors.ENDC}")
    
    print_info("Contando archivos...")
    total_files = count_items(service, folder_id)
    print_success(f"Total de archivos a descargar: {Colors.BOLD}{total_files}{Colors.ENDC}")
    
    current_dir = os.getcwd()
    destination = os.path.join(current_dir, folder_name)
    os.makedirs(destination, exist_ok=True)
    
    print_info(f"Destino: {Colors.BOLD}{destination}{Colors.ENDC}\n")
    
    # --- Iniciar descarga paralela ---
    parallel_downloads = config.get('parallel_downloads', 8)
    print(f"{Colors.BOLD}Descargando archivos ({parallel_downloads} hilos)...{Colors.ENDC}\n")
    
    print_info("Obteniendo mapa de archivos remotos...")
    remote_files = get_remote_files_map(service, folder_id)
    
    to_download = []
    for rel_path, remote_info in remote_files.items():
        if not remote_info.get('is_folder'):
            to_download.append((rel_path, remote_info))

    with _download_progress_lock:
        _download_progress['completed'] = 0
    
    total_downloads = len(to_download)

    with concurrent.futures.ThreadPoolExecutor(max_workers=parallel_downloads) as executor:
        futures = []
        for rel_path, remote_info in to_download:
            local_path = os.path.join(destination, rel_path.replace('/', os.sep))
            futures.append(executor.submit(_download_worker, creds, remote_info, local_path, rel_path, total_downloads))
        
        concurrent.futures.wait(futures)
    
    print_info(f"\nCreando archivo {RUPERTO_FILE}...")
    save_ruperto_metadata(destination, folder_id, folder_name) # Metadata mínima
    print_success(f"Archivo {RUPERTO_FILE} creado")
    
    print(f"\n{Colors.GREEN}{Colors.BOLD}✓ Clonación completada exitosamente!{Colors.ENDC}")
    print(f"{Colors.DIM}Archivos guardados en: {destination}{Colors.ENDC}\n")

def show_help():
    """Muestra la ayuda de RupertoCLI"""
    print_header("RupertoCLI - Google Drive Sync Tool")
    print(f"{Colors.BOLD}Comandos disponibles:{Colors.ENDC}\n")
    
    print(f"  {Colors.CYAN}clone{Colors.ENDC} <link>")
    print(f"    Clona una carpeta de Google Drive al directorio actual")
    print(f"    {Colors.DIM}Ejemplo: ruperto clone https://drive.google.com/drive/folders/...{Colors.ENDC}\n")
    
    print(f"  {Colors.CYAN}download{Colors.ENDC}")
    print(f"    Descarga solo los archivos nuevos o modificados (basado en MD5)")
    print(f"    {Colors.DIM}Debe ejecutarse dentro de una carpeta clonada{Colors.ENDC}")
    print(f"    {Colors.YELLOW}⚠ Los archivos locales modificados se sobreescribirán{Colors.ENDC}\n")
    
    print(f"  {Colors.CYAN}upload{Colors.ENDC}")
    print(f"    Sube solo los archivos locales nuevos o modificados (basado en MD5)")
    print(f"    {Colors.DIM}Debe ejecutarse dentro de una carpeta clonada{Colors.ENDC}")
    print(f"    {Colors.YELLOW}⚠ Los archivos en Drive se sobreescribirán{Colors.ENDC}\n")
    
    print(f"  {Colors.CYAN}help{Colors.ENDC}")
    print(f"    Muestra esta ayuda\n")

def main():
    try:
        if len(sys.argv) < 2:
            show_help()
            sys.exit(1)
        
        command = sys.argv[1].lower()
        config = load_ruperto_config() # Cargar config al inicio
        
        if command == 'clone':
            if len(sys.argv) < 3:
                print_error("Falta el link de Google Drive")
                print(f"\n{Colors.BOLD}Uso:{Colors.ENDC} ruperto clone <link>\n")
                sys.exit(1)
            clone_command(sys.argv[2], config)
        
        elif command == 'download':
            print_header("RupertoCLI - Download (Sincronización MD5)")
            print_info("Autenticando con Google Drive...")
            creds = authenticate()
            service = build('drive', 'v3', credentials=creds)
            download_command(service, os.getcwd(), creds, config)
        
        elif command == 'upload':
            print_header("RupertoCLI - Upload (Sincronización MD5)")
            print_info("Autenticando con Google Drive...")
            creds = authenticate()
            service = build('drive', 'v3', credentials=creds)
            upload_command(service, os.getcwd(), creds, config)
        
        elif command == 'help':
            show_help()
        
        else:
            print_error(f"Comando desconocido: {command}")
            show_help()
            sys.exit(1)
            
    except Exception as e:
        print_error(f"\nHa ocurrido un error inesperado: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    main()

import os
import io
import sys
import json
import hashlib
import pathspec
from datetime import datetime
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload

SCOPES = ['https://www.googleapis.com/auth/drive']
RUPERTO_FILE = 'ruperto.json'
RUPERTO_CONFIG = 'ruperto.config'

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

def print_info(text):
    print(f"{Colors.BLUE}ℹ{Colors.ENDC} {text}")

def print_success(text):
    print(f"{Colors.GREEN}✓{Colors.ENDC} {text}")

def print_warning(text):
    print(f"{Colors.YELLOW}⚠{Colors.ENDC} {text}")

def print_error(text):
    print(f"{Colors.RED}✗{Colors.ENDC} {text}")

def print_download(text):
    print(f"{Colors.GREEN}⬇{Colors.ENDC} {text}")

def print_upload(text):
    print(f"{Colors.CYAN}⬆{Colors.ENDC} {text}")

def print_delete(text):
    print(f"{Colors.RED}🗑{Colors.ENDC} {text}")

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

def authenticate():
    """Autentica con Google Drive API y guarda el token"""
    creds = None
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    token_path = os.path.join(script_dir, 'token.json')
    credentials_path = os.path.join(script_dir, 'credentials.json')
    
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print_info("Refrescando token de autenticación...")
            creds.refresh(Request())
        else:
            print_info("Iniciando proceso de autenticación...")
            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
            creds = flow.run_local_server(port=0)
        
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

def upload_file(service, file_path, parent_id, file_name, file_id=None):
    """Sube o actualiza un archivo en Google Drive"""
    media = MediaFileUpload(file_path, resumable=True)
    
    if file_id:
        request = service.files().update(
            fileId=file_id,
            media_body=media
        )
    else:
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
        if status:
            progress = int(status.progress() * 100)
            print_progress(file_name, progress)
    
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
    """Obtiene un mapa de todos los archivos remotos con sus metadatos"""
    files_map = {}
    query = f"'{folder_id}' in parents and trashed=false"
    results = service.files().list(
        q=query,
        fields="files(id, name, mimeType, modifiedTime, md5Checksum, size)",
        pageSize=1000
    ).execute()
    
    items = results.get('files', [])
    
    for item in items:
        item_name = item['name']
        item_path = os.path.join(base_path, item_name) if base_path else item_name
        
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
                'md5': item.get('md5Checksum'),
                'size': item.get('size'),
                'mimeType': item['mimeType'],
                'is_folder': False
            }
    
    return files_map

def get_local_files_map(folder_path):
    """Obtiene un mapa de todos los archivos locales"""
    files_map = {}
    
    for root, dirs, files in os.walk(folder_path):
        rel_root = os.path.relpath(root, folder_path)
        if rel_root == '.':
            rel_root = ''
        
        for file in files:
            if file == RUPERTO_FILE:
                continue
            
            rel_path = os.path.join(rel_root, file) if rel_root else file
            full_path = os.path.join(root, file)
            
            files_map[rel_path] = {
                'path': full_path,
                'is_folder': False
            }
        
        for dir_name in dirs:
            rel_path = os.path.join(rel_root, dir_name) if rel_root else dir_name
            files_map[rel_path] = {
                'path': os.path.join(root, dir_name),
                'is_folder': True
            }
    
    return files_map

def save_ruperto_metadata(folder_path, folder_id, folder_name, files_map):
    """Guarda los metadatos en ruperto.json"""
    metadata = {
        'version': '1.0',
        'folder_id': folder_id,
        'folder_name': folder_name,
        'last_sync': datetime.now().isoformat(),
        'files': files_map
    }
    
    ruperto_path = os.path.join(folder_path, RUPERTO_FILE)
    with open(ruperto_path, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

def load_ruperto_metadata(folder_path):
    """Carga los metadatos desde ruperto.json"""
    ruperto_path = os.path.join(folder_path, RUPERTO_FILE)
    if not os.path.exists(ruperto_path):
        return None
    
    with open(ruperto_path, 'r', encoding='utf-8') as f:
        return json.load(f)

def load_ruperto_config():
    """Carga la configuración desde ruperto.config"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, RUPERTO_CONFIG)
    
    if not os.path.exists(config_path):
        return {'keep': []}
    
    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)
        return config

def load_gitignore_patterns(folder_path):
    """Carga todos los .gitignore en la carpeta y subcarpetas"""
    gitignore_specs = {}
    
    for root, dirs, files in os.walk(folder_path):
        if '.gitignore' in files:
            gitignore_path = os.path.join(root, '.gitignore')
            rel_root = os.path.relpath(root, folder_path)
            if rel_root == '.':
                rel_root = ''
            
            with open(gitignore_path, 'r', encoding='utf-8') as f:
                patterns = f.read()
                spec = pathspec.PathSpec.from_lines('gitwildmatch', patterns.splitlines())
                gitignore_specs[rel_root] = spec
    
    return gitignore_specs

def should_ignore_file(rel_path, gitignore_specs, keep_patterns):
    """Determina si un archivo debe ser ignorado según .gitignore y ruperto.config"""
    file_name = os.path.basename(rel_path)
    
    for keep_pattern in keep_patterns:
        if keep_pattern == file_name or pathspec.match_tree_pattern([keep_pattern], rel_path):
            return False
    
    for base_path, spec in gitignore_specs.items():
        if base_path == '':
            check_path = rel_path
        elif rel_path.startswith(base_path + os.sep):
            check_path = os.path.relpath(rel_path, base_path)
        else:
            continue
        
        if spec.match_file(check_path):
            return True
    
    return False

def count_items(service, folder_id):
    """Cuenta recursivamente el total de archivos en la carpeta"""
    query = f"'{folder_id}' in parents and trashed=false"
    results = service.files().list(
        q=query,
        fields="files(id, mimeType)",
        pageSize=1000
    ).execute()
    
    items = results.get('files', [])
    count = 0
    
    for item in items:
        if item['mimeType'] == 'application/vnd.google-apps.folder':
            count += count_items(service, item['id'])
        elif not item['mimeType'].startswith('application/vnd.google-apps.'):
            count += 1
    
    return count

def download_folder_recursive(service, folder_id, destination_path, stats, depth=0):
    """Descarga recursivamente todos los archivos y subcarpetas"""
    query = f"'{folder_id}' in parents and trashed=false"
    results = service.files().list(
        q=query,
        fields="files(id, name, mimeType)",
        pageSize=1000
    ).execute()
    
    items = results.get('files', [])
    indent = "  " * depth
    
    for item in items:
        item_name = item['name']
        item_id = item['id']
        item_mime = item['mimeType']
        item_path = os.path.join(destination_path, item_name)
        
        if item_mime == 'application/vnd.google-apps.folder':
            print(f"{indent}{Colors.YELLOW}📁 {item_name}/{Colors.ENDC}")
            os.makedirs(item_path, exist_ok=True)
            download_folder_recursive(service, item_id, item_path, stats, depth + 1)
        else:
            if item_mime.startswith('application/vnd.google-apps.'):
                continue
            
            stats['current'] += 1
            print(f"{indent}{Colors.CYAN}[{stats['current']}/{stats['total']}]{Colors.ENDC} {item_name}")
            
            download_file(service, item_id, item_path, item_name)

def download_command(service, folder_path):
    """Descarga cambios desde Drive, sobreescribiendo archivos locales"""
    metadata = load_ruperto_metadata(folder_path)
    
    if not metadata:
        print_error(f"No se encontró {RUPERTO_FILE} en la carpeta actual")
        print_info("Esta carpeta no fue clonada con RupertoCLI")
        return
    
    folder_id = metadata['folder_id']
    folder_name = metadata['folder_name']
    
    print_info(f"Descargando cambios de: {Colors.BOLD}{folder_name}{Colors.ENDC}")
    print_warning("Los cambios locales serán sobreescritos\n")
    
    print_info("Obteniendo estado de Google Drive...")
    remote_files = get_remote_files_map(service, folder_id)
    local_files = get_local_files_map(folder_path)
    
    to_download = []
    to_delete = []
    
    for rel_path, remote_info in remote_files.items():
        if not remote_info.get('is_folder'):
            to_download.append((rel_path, remote_info))
    
    for rel_path in local_files:
        if rel_path not in remote_files and not local_files[rel_path]['is_folder']:
            to_delete.append(rel_path)
    
    if not to_download and not to_delete:
        print_success("Todo está sincronizado. No hay cambios.")
        save_ruperto_metadata(folder_path, folder_id, folder_name, remote_files)
        return
    
    print(f"\n{Colors.BOLD}Resumen:{Colors.ENDC}")
    print(f"  {Colors.GREEN}A descargar/actualizar:{Colors.ENDC} {len(to_download)}")
    print(f"  {Colors.RED}A eliminar:{Colors.ENDC} {len(to_delete)}\n")
    
    if to_download:
        print(f"{Colors.BOLD}Descargando archivos...{Colors.ENDC}")
        for rel_path, remote_info in to_download:
            local_path = os.path.join(folder_path, rel_path)
            print_download(f"{rel_path}")
            download_file(service, remote_info['id'], local_path, remote_info['name'])
    
    if to_delete:
        print(f"\n{Colors.BOLD}Eliminando archivos locales...{Colors.ENDC}")
        for rel_path in to_delete:
            local_path = os.path.join(folder_path, rel_path)
            print_delete(f"{rel_path}")
            if os.path.exists(local_path):
                os.remove(local_path)
    
    for root, dirs, files in os.walk(folder_path, topdown=False):
        for dir_name in dirs:
            dir_path = os.path.join(root, dir_name)
            if not os.listdir(dir_path):
                os.rmdir(dir_path)
    
    save_ruperto_metadata(folder_path, folder_id, folder_name, remote_files)
    print(f"\n{Colors.GREEN}{Colors.BOLD}✓ Descarga completada!{Colors.ENDC}\n")

def upload_command(service, folder_path):
    """Sube cambios locales a Drive, sobreescribiendo archivos remotos"""
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
            save_ruperto_metadata(folder_path, new_folder_id, folder_name, {})
            print_success(f"Archivo {RUPERTO_FILE} creado\n")
            
            metadata = load_ruperto_metadata(folder_path)
        except Exception as e:
            print_error(f"Error al crear la carpeta: {e}")
            print_info("Verifica que el link sea correcto y tengas permisos")
            return
    
    folder_id = metadata['folder_id']
    folder_name = metadata['folder_name']
    
    print_info(f"Subiendo cambios a: {Colors.BOLD}{folder_name}{Colors.ENDC}")
    print_warning("Los archivos en Drive serán sobreescritos\n")
    
    print_info("Cargando configuración de RupertoCLI...")
    config = load_ruperto_config()
    keep_patterns = config.get('keep', [])
    
    if keep_patterns:
        print_info(f"Patrones a mantener: {Colors.BOLD}{', '.join(keep_patterns)}{Colors.ENDC}")
    
    print_info("Cargando patrones de .gitignore...")
    gitignore_specs = load_gitignore_patterns(folder_path)
    
    if gitignore_specs:
        print_info(f"Encontrados {len(gitignore_specs)} archivo(s) .gitignore")
    
    print_info("Analizando cambios locales...")
    local_files = get_local_files_map(folder_path)
    remote_files = get_remote_files_map(service, folder_id)
    
    folders_to_create = []
    files_to_upload = []
    files_to_delete = []
    ignored_count = 0
    
    folder_ids = {'.': folder_id}
    
    for rel_path in sorted(local_files.keys()):
        local_info = local_files[rel_path]
        
        if local_info['is_folder']:
            if rel_path not in remote_files:
                folders_to_create.append(rel_path)
        else:
            if should_ignore_file(rel_path, gitignore_specs, keep_patterns):
                ignored_count += 1
                continue
            
            files_to_upload.append(rel_path)
    
    for rel_path, remote_info in remote_files.items():
        if rel_path not in local_files and not remote_info.get('is_folder'):
            files_to_delete.append((rel_path, remote_info['id']))
    
    if not folders_to_create and not files_to_upload and not files_to_delete:
        print_success("Todo está sincronizado. No hay cambios.")
        if ignored_count > 0:
            print_info(f"Archivos ignorados por .gitignore: {Colors.DIM}{ignored_count}{Colors.ENDC}")
        return
    
    print(f"\n{Colors.BOLD}Resumen:{Colors.ENDC}")
    print(f"  {Colors.YELLOW}Carpetas a crear:{Colors.ENDC} {len(folders_to_create)}")
    print(f"  {Colors.CYAN}Archivos a subir/actualizar:{Colors.ENDC} {len(files_to_upload)}")
    print(f"  {Colors.RED}Archivos a eliminar:{Colors.ENDC} {len(files_to_delete)}")
    if ignored_count > 0:
        print(f"  {Colors.DIM}Ignorados por .gitignore:{Colors.ENDC} {ignored_count}")
    print()
    
    if folders_to_create:
        print(f"{Colors.BOLD}Creando carpetas...{Colors.ENDC}")
        for rel_path in folders_to_create:
            parent_path = os.path.dirname(rel_path) if os.path.dirname(rel_path) else '.'
            parent_id = folder_ids.get(parent_path, folder_id)
            
            folder_name_only = os.path.basename(rel_path)
            print_info(f"Creando carpeta: {rel_path}")
            new_folder_id = create_folder(service, folder_name_only, parent_id)
            folder_ids[rel_path] = new_folder_id
    
    for rel_path, remote_info in remote_files.items():
        if remote_info.get('is_folder'):
            folder_ids[rel_path] = remote_info['id']
    
    if files_to_upload:
        print(f"\n{Colors.BOLD}Subiendo archivos...{Colors.ENDC}")
        for rel_path in files_to_upload:
            local_path = local_files[rel_path]['path']
            parent_path = os.path.dirname(rel_path) if os.path.dirname(rel_path) else '.'
            parent_id = folder_ids.get(parent_path, folder_id)
            file_name = os.path.basename(rel_path)
            
            existing_id = remote_files.get(rel_path, {}).get('id')
            
            print_upload(f"{rel_path}")
            upload_file(service, local_path, parent_id, file_name, existing_id)
    
    if files_to_delete:
        print(f"\n{Colors.BOLD}Eliminando archivos en Drive...{Colors.ENDC}")
        for rel_path, file_id in files_to_delete:
            print_delete(f"{rel_path}")
            delete_file(service, file_id)
    
    print_info("\nActualizando metadatos...")
    remote_files = get_remote_files_map(service, folder_id)
    save_ruperto_metadata(folder_path, folder_id, folder_name, remote_files)
    
    print(f"\n{Colors.GREEN}{Colors.BOLD}✓ Subida completada!{Colors.ENDC}\n")

def clone_command(folder_link):
    """Comando para clonar una carpeta de Google Drive"""
    folder_id = extract_folder_id(folder_link)
    
    print_header("RupertoCLI - Clone")
    
    print_info("Autenticando con Google Drive...")
    creds = authenticate()
    service = build('drive', 'v3', credentials=creds)
    
    print_info("Obteniendo información de la carpeta...")
    folder_info = service.files().get(fileId=folder_id, fields='name').execute()
    folder_name = folder_info['name']
    
    print_success(f"Carpeta encontrada: {Colors.BOLD}{folder_name}{Colors.ENDC}")
    
    print_info("Contando archivos...")
    total_files = count_items(service, folder_id)
    print_success(f"Total de archivos a descargar: {Colors.BOLD}{total_files}{Colors.ENDC}")
    
    current_dir = os.getcwd()
    destination = os.path.join(current_dir, folder_name)
    os.makedirs(destination, exist_ok=True)
    
    print_info(f"Destino: {Colors.BOLD}{destination}{Colors.ENDC}\n")
    
    stats = {'current': 0, 'total': total_files}
    
    print(f"{Colors.BOLD}Descargando archivos...{Colors.ENDC}\n")
    download_folder_recursive(service, folder_id, destination, stats)
    
    print_info("\nCreando archivo de metadatos...")
    remote_files = get_remote_files_map(service, folder_id)
    save_ruperto_metadata(destination, folder_id, folder_name, remote_files)
    print_success(f"Archivo {RUPERTO_FILE} creado")
    
    print(f"\n{Colors.GREEN}{Colors.BOLD}✓ Clonación completada exitosamente!{Colors.ENDC}")
    print(f"{Colors.DIM}Archivos guardados en: {destination}{Colors.ENDC}\n")

def show_help():
    """Muestra la ayuda de RupertoCLI"""
    print_header("RupertoCLI - Google Drive Sync Tool")
    print(f"{Colors.BOLD}Comandos disponibles:{Colors.ENDC}\n")
    
    print(f"  {Colors.CYAN}clone{Colors.ENDC} <link>")
    print(f"    Clona una carpeta de Google Drive al directorio actual")
    print(f"    {Colors.DIM}Ejemplo: python main.py clone https://drive.google.com/drive/folders/...{Colors.ENDC}\n")
    
    print(f"  {Colors.CYAN}download{Colors.ENDC}")
    print(f"    Descarga cambios desde Drive y sobreescribe archivos locales")
    print(f"    {Colors.DIM}Debe ejecutarse dentro de una carpeta clonada{Colors.ENDC}")
    print(f"    {Colors.YELLOW}⚠ Los cambios locales se perderán{Colors.ENDC}\n")
    
    print(f"  {Colors.CYAN}upload{Colors.ENDC}")
    print(f"    Sube cambios locales a Drive y sobreescribe archivos remotos")
    print(f"    {Colors.DIM}Debe ejecutarse dentro de una carpeta clonada{Colors.ENDC}")
    print(f"    {Colors.YELLOW}⚠ Los archivos en Drive se sobreescribirán{Colors.ENDC}\n")
    
    print(f"  {Colors.CYAN}help{Colors.ENDC}")
    print(f"    Muestra esta ayuda\n")

def main():
    if len(sys.argv) < 2:
        show_help()
        sys.exit(1)
    
    command = sys.argv[1].lower()
    
    if command == 'clone':
        if len(sys.argv) < 3:
            print_error("Falta el link de Google Drive")
            print(f"\n{Colors.BOLD}Uso:{Colors.ENDC} python main.py clone <link>\n")
            sys.exit(1)
        clone_command(sys.argv[2])
    
    elif command == 'download':
        print_header("RupertoCLI - Download")
        print_info("Autenticando con Google Drive...")
        creds = authenticate()
        service = build('drive', 'v3', credentials=creds)
        download_command(service, os.getcwd())
    
    elif command == 'upload':
        print_header("RupertoCLI - Upload")
        print_info("Autenticando con Google Drive...")
        creds = authenticate()
        service = build('drive', 'v3', credentials=creds)
        upload_command(service, os.getcwd())
    
    elif command == 'help':
        show_help()
    
    else:
        print_error(f"Comando desconocido: {command}")
        show_help()
        sys.exit(1)

if __name__ == '__main__':
    main()
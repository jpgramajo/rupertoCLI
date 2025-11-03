# rupertoCLI - Herramienta de Sincronización con Google Drive

rupertoCLI es una herramienta de línea de comandos (CLI) para sincronizar directorios locales con carpetas de Google Drive. Facilita la clonación, subida y descarga de proyectos, manteniendo la estructura de carpetas y detectando cambios de forma eficiente mediante la comparación de hashes MD5.

## Características

- **Autenticación Segura:** Utiliza OAuth 2.0 para una conexión segura con tu cuenta de Google.
- **Sincronización Inteligente:** Compara archivos usando hashes MD5 para transferir únicamente los archivos nuevos o modificados, ahorrando tiempo y ancho de banda.
- **Clonación de Proyectos:** Descarga una carpeta completa de Google Drive a tu máquina local con un solo comando.
- **Control de Cambios:** Sube o descarga cambios específicos después de la clonación inicial.
- **Respeto a `.gitignore`:** Ignora automáticamente los archivos y carpetas especificados en tus archivos `.gitignore`.
- **Configuración Personalizada:** Permite definir reglas adicionales para incluir o excluir archivos a través de un archivo `ruperto.config`.
- **Procesamiento Paralelo:** Acelera las transferencias mediante la subida y descarga de múltiples archivos en hilos paralelos.

## 1. Configuración en Google Cloud Console

Para usar rupertoCLI, primero debes habilitar la API de Google Drive y obtener tus credenciales.

### Pasos:

1.  **Crear un Nuevo Proyecto:**
    *   Ve a la [Consola de Google Cloud](https://console.cloud.google.com/).
    *   Haz clic en el selector de proyectos (junto al logo de Google Cloud) y selecciona **"Proyecto Nuevo"**.
    *   Dale un nombre (ej. "rupertoCLI Project") y haz clic en **"Crear"**.

2.  **Habilitar la API de Google Drive:**
    *   En el menú de navegación, ve a **"APIs y Servicios" > "Biblioteca"**.
    *   Busca **"Google Drive API"** y selecciónala.
    *   Haz clic en **"Habilitar"**.

3.  **Configurar la Pantalla de Consentimiento (OAuth):**
    *   En el menú de navegación, ve a **"APIs y Servicios" > "Pantalla de consentimiento de OAuth"**.
    *   Selecciona el tipo de usuario **"Externo"** y haz clic en **"Crear"**.
    *   Rellena los campos obligatorios:
        *   **Nombre de la aplicación:** rupertoCLI
        *   **Correo electrónico de asistencia del usuario:** Tu correo electrónico.
        *   **Datos de contacto del desarrollador:** Tu correo electrónico.
    *   Haz clic en **"Guardar y Continuar"** en todas las secciones hasta volver al panel.

4.  **Añadir Usuario de Prueba:**
    *   Mientras la app está en modo de prueba, debes añadir tu cuenta de Google como usuario autorizado.
    *   En la sección **"Pantalla de consentimiento de OAuth"**, ve a **"Usuarios de prueba"**.
    *   Haz clic en **"Añadir usuarios"** e introduce tu dirección de correo de Google.

5.  **Crear Credenciales:**
    *   En el menú de navegación, ve a **"APIs y Servicios" > "Credenciales"**.
    *   Haz clic en **"Crear Credenciales"** y selecciona **"ID de cliente de OAuth"**.
    *   En **"Tipo de aplicación"**, elige **"Aplicación de escritorio"**.
    *   Dale un nombre (ej. "rupertoCLI Credentials") y haz clic en **"Crear"**.
    *   Aparecerá una ventana con tu ID y secreto de cliente. Haz clic en **"Descargar JSON"**.

6.  **Mover y Renombrar Credenciales:**
    *   El archivo descargado se llamará algo como `client_secret_xxxxxxxx.json`.
    *   Renómbralo a `credentials.json`.
    *   Mueve este archivo `credentials.json` al mismo directorio donde se encuentra el ejecutable de rupertoCLI.

## 2. Funcionamiento de la Aplicación

rupertoCLI funciona a través de tres comandos principales.

### `clone <link>`

Este comando clona una carpeta de Google Drive en tu directorio actual.

-   **Uso:** `rupertocli clone [URL_de_la_carpeta_en_Google_Drive]`
-   **Proceso:**
    1.  Pide autenticación la primera vez.
    2.  Descarga todos los archivos y carpetas, replicando la estructura de Drive.
    3.  Crea un archivo `ruperto.json` en el directorio raíz del proyecto clonado para vincularlo con la carpeta de Drive.

### `download`

Sincroniza los cambios desde Google Drive a tu directorio local.

-   **Uso:** `rupertocli download` (debe ejecutarse dentro de un directorio clonado).
-   **Proceso:**
    1.  Compara los archivos locales con los de Google Drive usando hashes MD5.
    2.  Descarga únicamente los archivos que son nuevos o han sido modificados en Drive.
    3.  Elimina los archivos locales que ya no existen en Drive.
    4.  **Advertencia:** Los cambios locales en archivos que también fueron modificados en Drive serán sobreescritos.

### `upload`

Sincroniza los cambios desde tu directorio local a Google Drive.

-   **Uso:** `rupertocli upload` (debe ejecutarse dentro de un directorio clonado).
-   **Proceso:**
    1.  Compara los archivos de Google Drive con los locales usando hashes MD5.
    2.  Sube únicamente los archivos locales que son nuevos o han sido modificados.
    3.  Elimina los archivos en Drive que ya no existen localmente.
    4.  **Advertencia:** Los cambios en Drive serán sobreescritos si el archivo local ha sido modificado.

## 3. Crear un Alias en la Terminal

Para usar `rupertocli` como un comando global, puedes crear un alias.

### macOS y Linux (bash/zsh)

1.  **Abre tu archivo de configuración de shell:**
    *   Para **bash**, usa `nano ~/.bash_profile` o `nano ~/.bashrc`.
    *   Para **zsh** (el shell por defecto en macOS modernos), usa `nano ~/.zshrc`.

2.  **Añade el alias:**
    Agrega la siguiente línea al final del archivo, reemplazando `/ruta/completa/a/` con la ruta real donde guardaste `main.py`.

    ```bash
    alias rupertocli='python3 /ruta/completa/a/main.py'
    ```

3.  **Aplica los cambios:**
    *   Para **bash**, ejecuta `source ~/.bash_profile` o `source ~/.bashrc`.
    *   Para **zsh**, ejecuta `source ~/.zshrc`.

### Windows (Símbolo del sistema)

1.  **Crea un archivo `.bat`:**
    *   Abre el bloc de notas y escribe la siguiente línea, reemplazando `C:\ruta\completa\a\main.py` por la ruta real de tu script:

    ```batch
    @python C:\ruta\completa\a\main.py %*
    ```

2.  **Guarda el archivo:**
    *   Guárdalo como `rupertocli.bat` en una carpeta que esté incluida en el PATH del sistema (por ejemplo, `C:\Windows\System32`, aunque es mejor crear una carpeta personal para scripts y añadirla al PATH).

3.  **Añadir la carpeta al PATH (si es necesario):**
    *   Busca "Editar las variables de entorno del sistema" en el menú de inicio.
    *   Haz clic en "Variables de entorno...".
    *   En "Variables del sistema", selecciona "Path" y haz clic en "Editar".
    *   Añade una nueva entrada con la ruta a la carpeta donde guardaste `rupertocli.bat`.

## 4. Descripción de Funciones Principales

-   `authenticate()`: Gestiona la autenticación OAuth 2.0. Refresca el token si ha expirado o inicia un nuevo flujo de autenticación si no existe.
-   `get_remote_files_map()`: Construye un mapa de todos los archivos y carpetas en la carpeta de Google Drive, incluyendo sus IDs, hashes MD5 y fechas de modificación.
-   `get_local_files_map()`: Construye un mapa similar para los archivos locales, respetando las reglas de `.gitignore` y `ruperto.config`.
-   `upload_command()` / `download_command()`: Orquestan la sincronización comparando los mapas de archivos locales y remotos para determinar qué archivos necesitan ser subidos, descargados o eliminados.
-   `_upload_worker()` / `_download_worker()`: Funciones trabajadoras que se ejecutan en hilos separados para gestionar la subida o descarga de un único archivo, permitiendo transferencias paralelas.
-   `should_ignore_file()`: Decide si un archivo debe ser ignorado basándose en las reglas de `ruperto.config` y los patrones de `.gitignore`.

## 5. Archivos de Configuración

-   `credentials.json`: (No incluido en el repo) Contiene tus credenciales de la API de Google. **¡NUNCA COMPARTAS ESTE ARCHIVO!**
-   `token.json`: (Generado automáticamente) Almacena el token de acceso para no tener que autenticarte cada vez. Se genera en el mismo directorio que `credentials.json`.
-   `ruperto.json`: (Generado en carpetas clonadas) Contiene el ID de la carpeta de Google Drive y la fecha del último sincronizado.
-   `ruperto.config`: (Opcional) Un archivo JSON que puedes crear junto a `credentials.json` para definir reglas globales:
    -   `keep`: Una lista de patrones de archivos a incluir siempre (prioridad sobre `.gitignore`).
    -   `ignore`: Una lista de patrones de archivos a excluir siempre (prioridad sobre `keep` y `.gitignore`).
    -   `parallel_uploads`: Número de subidas paralelas (defecto: 8).
    -   `parallel_downloads`: Número de descargas paralelas (defecto: 8).

    **Ejemplo de `ruperto.config`:**
    ```json
    {
      "keep": ["*.log", "dist/"],
      "ignore": ["node_modules/", ".env"],
      "parallel_uploads": 10
    }
    ```

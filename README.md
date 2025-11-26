# Instalador con Dashboard (PowerShell)

Dashboard tipo WordPress para lanzar instalaciones por PowerShell (winget/choco/msiexec) con opción de agregar más apps sin tocar código.

## Requisitos
- Python 3.10+ (ya viene en la mayoría de instalaciones)
- PowerShell disponible (Windows)
- Permiso de red para que winget/choco puedan descargar.

## Puesta en marcha
```powershell
python -m venv .venv
.\\.venv\\Scripts\\activate
pip install -r requirements.txt
python app.py
```
Abre http://localhost:5000 en el navegador. El backend sirve el dashboard y la API.

## Uso rápido
- El catálogo inicial tiene Git, VS Code y 7zip (`data/apps.json`).
- Botón **Instalar** ejecuta el comando en PowerShell con `ExecutionPolicy Bypass` y devuelve el log.
- El formulario **Agregar aplicación** guarda nuevos comandos (quedan persistidos en `data/apps.json`).

## Añadir o editar apps manualmente
Edita `data/apps.json` y sigue la estructura:
```json
[
  {
    "id": 1,
    "name": "Git",
    "command": "winget install --id Git.Git -e --source winget",
    "description": "Cliente Git oficial por winget",
    "category": "Control de versiones"
  }
]
```
El backend asigna `id` automáticamente si usas el formulario.

## Seguridad
- Los comandos se ejecutan tal cual en PowerShell; incluye solo fuentes confiables.
- Revisa antes de instalar en equipos sensibles. Si necesitas mayor seguridad, limita los comandos permitidos o ejecuta en cuentas restringidas.

## Extender
- Añade validaciones o autenticación en `app.py`.
- Ajusta el diseño en `static/styles.css` y comportamiento en `static/app.js`.

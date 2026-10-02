# Despliegue en Ubuntu

Esta guía supone el usuario Linux `mbustos`, el repositorio en `/home/mbustos/AtencionCliente`, Nginx como proxy y Uvicorn escuchando solamente en `127.0.0.1:8000`.

## 1. Dependencias del sistema

```bash
sudo apt-get update
sudo apt-get install -y git curl ca-certificates python3 python3-venv python3-dev build-essential unixodbc-dev nginx
```

Instala Microsoft ODBC Driver 17 usando el repositorio correspondiente a la versión de Ubuntu:

```bash
source /etc/os-release
curl -sSL -O "https://packages.microsoft.com/config/ubuntu/${VERSION_ID}/packages-microsoft-prod.deb"
sudo dpkg -i packages-microsoft-prod.deb
rm packages-microsoft-prod.deb
sudo apt-get update
sudo ACCEPT_EULA=Y apt-get install -y msodbcsql17
```

Confirma el nombre del controlador:

```bash
odbcinst -q -d
```

Debe aparecer `ODBC Driver 17 for SQL Server`.

## 2. Clonar y preparar Python

```bash
cd /home/mbustos
git clone https://github.com/Mauricio-Bustos-DrSimi/AtencionCliente.git
cd AtencionCliente
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
mkdir -p data
chmod 700 data
```

## 3. Configuración privada

```bash
cp .env.example .env
chmod 600 .env
python3 -c "import secrets; print(secrets.token_urlsafe(64))"
nano .env
```

Completa `APP_SECRET_KEY`, `APP_ADMIN_PASSWORD`, las dos conexiones SQL y deja:

```dotenv
APP_HOST=127.0.0.1
APP_PORT=8000
APP_DATABASE_PATH=/home/mbustos/AtencionCliente/data/app_atencion.sqlite3
APP_SESSION_HTTPS_ONLY=false
```

Usa `APP_SESSION_HTTPS_ONLY=true` únicamente después de habilitar HTTPS en el proxy. En la primera ejecución se crea `admin` con `APP_ADMIN_PASSWORD`; los reinicios posteriores no reemplazan una contraseña cambiada desde la aplicación.

## 4. Prueba previa

```bash
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

En otra terminal:

```bash
curl --fail http://127.0.0.1:8000/api/health
```

Detén la prueba con `Ctrl+C` antes de instalar el servicio.

## 5. Servicio systemd

```bash
sudo cp deploy/atencion-cliente.service /etc/systemd/system/atencion-cliente.service
sudo systemctl daemon-reload
sudo systemctl enable --now atencion-cliente
sudo systemctl status atencion-cliente --no-pager
journalctl -u atencion-cliente -n 100 --no-pager
```

El servicio usa un solo proceso para compartir de manera consistente la SQLite local de usuarios y planes.

## 6. Nginx

Instala la plantilla y edita la copia del sistema para reemplazar `SERVER_NAME` por el DNS o la IP del servidor:

```bash
sudo cp deploy/nginx-atencion-cliente.conf /etc/nginx/sites-available/atencion-cliente
sudo nano /etc/nginx/sites-available/atencion-cliente
sudo ln -s /etc/nginx/sites-available/atencion-cliente /etc/nginx/sites-enabled/atencion-cliente
sudo nginx -t
sudo systemctl reload nginx
```

Antes de abrir puertos, limita el acceso a la red corporativa según las reglas de firewall del servidor. Para un despliegue definitivo, configura un certificado HTTPS en Nginx, cambia `APP_SESSION_HTTPS_ONLY=true` y reinicia el servicio.

## 7. Verificación y actualizaciones

```bash
curl --fail http://127.0.0.1:8000/api/health
sudo systemctl is-active atencion-cliente
sudo journalctl -u atencion-cliente -n 100 --no-pager
```

Para actualizar desde GitHub:

```bash
cd /home/mbustos/AtencionCliente
git pull --ff-only origin main
.venv/bin/pip install -r requirements.txt
sudo systemctl restart atencion-cliente
curl --fail http://127.0.0.1:8000/api/health
```

Respalda periódicamente `data/app_atencion.sqlite3`; contiene usuarios, planes e historial. El archivo `.env` contiene secretos y no debe copiarse al repositorio.

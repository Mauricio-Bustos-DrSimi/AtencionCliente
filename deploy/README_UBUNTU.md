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

Completa `APP_SECRET_KEY`, las dos conexiones SQL y deja:

```dotenv
APP_HOST=127.0.0.1
APP_PORT=8000
APP_DATABASE_PATH=/home/mbustos/AtencionCliente/data/app_atencion.sqlite3
APP_SESSION_HTTPS_ONLY=false
```

Usa `APP_SESSION_HTTPS_ONLY=true` únicamente después de habilitar HTTPS en el proxy. En la primera ejecución se crea `admin` con contraseña fija `admin123`; cada reinicio restaura esa contraseña.

## 4. Crear las tablas y ejecutar la primera sincronización

La aplicación conserva en SQLite los usuarios, planes de acción, evaluaciones históricas, cortes semanales y la auditoría de cada sincronización. Ejecuta una primera carga antes de abrir el panel:

```bash
.venv/bin/python -m app.sync --trigger initial
```

La consulta es de solo lectura para SQL Server. La carga local guarda el histórico consolidado y el corte de la última semana completa, de lunes a domingo.

## 5. Prueba previa

```bash
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

En otra terminal:

```bash
curl --fail http://127.0.0.1:8000/api/health
```

Detén la prueba con `Ctrl+C` antes de instalar el servicio.

## 6. Servicio web y sincronización semanal con systemd

```bash
sudo cp deploy/atencion-cliente.service /etc/systemd/system/atencion-cliente.service
sudo cp deploy/atencion-cliente-sync.service /etc/systemd/system/atencion-cliente-sync.service
sudo cp deploy/atencion-cliente-sync.timer /etc/systemd/system/atencion-cliente-sync.timer
sudo systemctl daemon-reload
sudo systemctl enable --now atencion-cliente
sudo systemctl enable --now atencion-cliente-sync.timer
sudo systemctl status atencion-cliente --no-pager
systemctl list-timers atencion-cliente-sync.timer --no-pager
journalctl -u atencion-cliente -n 100 --no-pager
journalctl -u atencion-cliente-sync.service -n 100 --no-pager
```

El temporizador ejecuta la consulta todos los días a las 07:00 en la zona `America/Santiago`. La carga intenta usar la última semana completa de lunes a domingo; si la fuente todavía no contiene registros de ese corte, conserva como período visible la última semana que realmente tiene datos. `Persistent=true` hace que systemd ejecute una carga pendiente al volver a encender el servidor. El servicio web usa un solo proceso para compartir de manera consistente la SQLite local.

## 7. Nginx

Instala la plantilla y edita la copia del sistema para reemplazar `SERVER_NAME` por el DNS o la IP del servidor:

```bash
sudo cp deploy/nginx-atencion-cliente.conf /etc/nginx/sites-available/atencion-cliente
sudo nano /etc/nginx/sites-available/atencion-cliente
sudo ln -s /etc/nginx/sites-available/atencion-cliente /etc/nginx/sites-enabled/atencion-cliente
sudo nginx -t
sudo systemctl reload nginx
```

Antes de abrir puertos, limita el acceso a la red corporativa según las reglas de firewall del servidor. Para un despliegue definitivo, configura un certificado HTTPS en Nginx, cambia `APP_SESSION_HTTPS_ONLY=true` y reinicia el servicio.

## 8. Verificación y actualizaciones

```bash
curl --fail http://127.0.0.1:8000/api/health
sudo systemctl is-active atencion-cliente
sudo systemctl is-active atencion-cliente-sync.timer
sudo systemctl start atencion-cliente-sync.service
sudo journalctl -u atencion-cliente -n 100 --no-pager
sudo journalctl -u atencion-cliente-sync.service -n 100 --no-pager
```

Para actualizar desde GitHub:

```bash
cd /home/mbustos/AtencionCliente
git pull --ff-only origin main
.venv/bin/pip install -r requirements.txt
sudo systemctl restart atencion-cliente
sudo systemctl restart atencion-cliente-sync.timer
curl --fail http://127.0.0.1:8000/api/health
```

Respalda periódicamente `data/app_atencion.sqlite3`; contiene usuarios, planes e historial. El archivo `.env` contiene secretos y no debe copiarse al repositorio.

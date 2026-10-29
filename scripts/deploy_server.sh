#!/bin/bash
set -e

echo "🚀 Iniciando despliegue de SoftEdu (FastAPI + pgvector) en CloudPanel AWS..."

SITE_USER="${SITE_USER:-softedu}"
APP_DIR="${SITE_DIR:-/home/$SITE_USER/htdocs/softedu.com}"

if [ ! -d "$APP_DIR" ]; then
    echo "⚠️ Directorio $APP_DIR no existe aún. Creándolo..."
    mkdir -p "$APP_DIR"
fi

cd "$APP_DIR"

# 1. Crear directorios de soporte si no existen
mkdir -p logs

# 2. Verificar entorno virtual Python (estándar venv de CloudPanel)
if [ ! -d "venv" ]; then
    echo "📦 Creando entorno virtual Python 3..."
    python3 -m venv venv
fi

# 3. Activar venv e instalar dependencias
echo "⚡ Instalando dependencias desde requirements.txt..."
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# 4. Crear .env si no existe
if [ ! -f ".env" ]; then
    echo "⚙️ Creando archivo .env inicial desde .env.example..."
    cp .env.example .env
fi

# 5. Reiniciar servicio
echo "🔄 Reiniciando servicio de aplicación SoftEdu..."
if systemctl is-active --quiet softedu.service; then
    sudo systemctl restart softedu.service
elif systemctl is-active --quiet softedu; then
    sudo systemctl restart softedu
else
    # Si aún no está como servicio systemd, recargar Gunicorn por señal si está activo
    pkill -HUP gunicorn || true
fi

echo "✅ ¡Despliegue de SoftEdu completado exitosamente con 0 downtime!"

#!/usr/bin/env bash
# ==============================================================================
# Script de Aprovisionamiento Inicial en AWS EC2 (CloudPanel / Ubuntu)
# Configurado con el mismo estándar de producción que C:\Proyectos\FacCol
# ==============================================================================
set -e

SITE_USER="${SITE_USER:-softedu}"
SITE_DIR="${SITE_DIR:-/home/softedu/htdocs/softedu.com}"
DB_NAME="${DB_NAME:-softedu_db}"
DB_USER="${DB_USER:-postgres}"
SERVICE_PORT="${SERVICE_PORT:-8005}"

echo "🚀 [1/5] Verificando base de datos PostgreSQL y extensión pgvector..."
sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname = '$DB_NAME'" | grep -q 1 || \
    sudo -u postgres psql -c "CREATE DATABASE $DB_NAME;"
sudo -u postgres psql -d "$DB_NAME" -c "CREATE EXTENSION IF NOT EXISTS vector;" || \
    echo "⚠️ Aviso: pgvector no está instalado o requiere permisos de superusuario. Se usará el fallback nativo de SoftEdu."

echo "🚀 [2/5] Configurando directorio y repositorio Git en $SITE_DIR..."
sudo mkdir -p "$SITE_DIR"
sudo mkdir -p "/home/$SITE_USER/logs"
sudo chown -R "$SITE_USER:$SITE_USER" "$SITE_DIR" "/home/$SITE_USER/logs"
sudo git config --global --add safe.directory "$SITE_DIR"

sudo -u "$SITE_USER" bash << EOF
set -e
cd "$SITE_DIR"
if [ ! -d ".git" ]; then
  git init
  git remote add origin https://github.com/osdavene/SoftEdu.git
fi
git fetch origin main
git reset --hard origin/main
if [ ! -d "venv" ]; then
  python3 -m venv venv
fi
venv/bin/pip install --upgrade pip
venv/bin/pip install -r requirements.txt
if [ ! -f ".env" ]; then
  cp .env.example .env
fi
EOF

echo "🚀 [3/5] Instalando servicio systemd /etc/systemd/system/softedu.service..."
if [ -f "$SITE_DIR/softedu.service" ]; then
  sudo cp "$SITE_DIR/softedu.service" /etc/systemd/system/softedu.service
else
  sudo tee /etc/systemd/system/softedu.service > /dev/null << EOF
[Unit]
Description=SoftEdu AI-Powered LMS/SIS Web Application (FastAPI + Gunicorn/Uvicorn)
After=network.target postgresql.service

[Service]
User=$SITE_USER
Group=$SITE_USER
WorkingDirectory=$SITE_DIR
Environment="PATH=$SITE_DIR/venv/bin:/usr/local/bin:/usr/bin:/bin"
EnvironmentFile=$SITE_DIR/.env
ExecStart=$SITE_DIR/venv/bin/gunicorn --config $SITE_DIR/gunicorn.conf.py main:app
ExecReload=/bin/kill -s HUP \$MAINPID
Restart=always
RestartSec=3
KillMode=mixed
TimeoutStopSec=5
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF
fi

echo "🚀 [4/5] Habilitando e iniciando servicio softedu.service..."
sudo systemctl daemon-reload
sudo systemctl enable softedu.service
sudo systemctl restart softedu.service

echo "✅ [5/5] Servicio SoftEdu activo en http://127.0.0.1:$SERVICE_PORT"
sudo systemctl status softedu.service --no-pager

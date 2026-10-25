#!/usr/bin/env bash
# ==============================================================================
# Script de Aprovisionamiento Inicial en AWS EC2 (CloudPanel / Ubuntu)
# Configurado con el mismo patrón de servidor que C:\Proyectos\Dian2676Py
# ==============================================================================
set -e

SITE_USER="${SITE_USER:-softedu}"
SITE_DIR="${SITE_DIR:-/home/softedu/htdocs/softedu.duckdns.org}"
DB_NAME="${DB_NAME:-softedu_db}"
DB_USER="${DB_USER:-postgres}"
SERVICE_PORT="${SERVICE_PORT:-8002}"

echo "🚀 [1/5] Verificando base de datos PostgreSQL y extensión pgvector..."
sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname = '$DB_NAME'" | grep -q 1 || \
    sudo -u postgres psql -c "CREATE DATABASE $DB_NAME;"
sudo -u postgres psql -d "$DB_NAME" -c "CREATE EXTENSION IF NOT EXISTS vector;" || \
    echo "⚠️ Aviso: instala postgresql-16-pgvector si aún no está instalado en el host."

echo "🚀 [2/5] Configurando repositorio Git en $SITE_DIR..."
sudo mkdir -p "$SITE_DIR"
sudo chown -R "$SITE_USER:$SITE_USER" "$SITE_DIR"
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
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
if [ ! -f ".env" ]; then
  cp .env.example .env
fi
EOF

echo "🚀 [3/5] Creando servicio systemd /etc/systemd/system/softedu.service..."
sudo tee /etc/systemd/system/softedu.service > /dev/null << EOF
[Unit]
Description=SoftEdu AI-Powered LMS/SIS (FastAPI + SQLAlchemy 2.0 + pgvector)
After=network.target postgresql.service

[Service]
User=$SITE_USER
Group=$SITE_USER
WorkingDirectory=$SITE_DIR
Environment="PATH=$SITE_DIR/.venv/bin"
EnvironmentFile=$SITE_DIR/.env
ExecStart=$SITE_DIR/.venv/bin/uvicorn main:app --host 127.0.0.1 --port $SERVICE_PORT --workers 2
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

echo "🚀 [4/5] Habilitando e iniciando servicio softedu.service..."
sudo systemctl daemon-reload
sudo systemctl enable softedu.service
sudo systemctl restart softedu.service

echo "✅ [5/5] Servicio SoftEdu activo en http://127.0.0.1:$SERVICE_PORT"
sudo systemctl status softedu.service --no-pager

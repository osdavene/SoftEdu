r"""
Configuración de Gunicorn + UvicornWorker para producción en AWS / CloudPanel (SoftEdu)
Siguiendo los mismos estándares de despliegue que C:\Proyectos\FacCol
"""
import multiprocessing
import os

# Puerto de escucha (8005 para SoftEdu, evitando colisiones con FacCol en 8002)
PORT = os.getenv("SERVICE_PORT", "8005")
bind = f"127.0.0.1:{PORT}"

# Trabajadores asíncronos basados en UvicornWorker
workers = min(multiprocessing.cpu_count() * 2 + 1, 4)
worker_class = "uvicorn.workers.UvicornWorker"
timeout = 120
keepalive = 5

# Rutas de logs compatibles con CloudPanel
SITE_USER = os.getenv("SITE_USER", "softedu")
log_dir = f"/home/{SITE_USER}/logs"
if os.path.isdir(log_dir):
    accesslog = f"{log_dir}/gunicorn_access.log"
    errorlog = f"{log_dir}/gunicorn_error.log"
else:
    accesslog = "-"
    errorlog = "-"

loglevel = "info"
daemon = False
max_requests = 1000
max_requests_jitter = 50
reload = False

@echo off
title SoftEdu AI-Powered LMS/SIS - Python FastAPI
cd /d "%~dp0"
echo ====================================================================
echo   SOFTEDU AI-POWERED LMS/SIS (FastAPI + SQLAlchemy 2.0 + pgvector)
echo ====================================================================
echo.
echo Iniciando servidor web en http://127.0.0.1:8000 ...
echo Documentacion interactiva Swagger: http://127.0.0.1:8000/docs
echo Presiona Ctrl+C para detener el servidor.
echo.
python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
pause

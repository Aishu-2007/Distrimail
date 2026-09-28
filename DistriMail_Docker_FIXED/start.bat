@echo off
cd /d "%~dp0"
echo Starting DistriMail with Docker...
docker compose up --build --scale worker=3
pause

@echo off
title JARVIS - Launching Autonomous Agent Workspace
echo ========================================================
echo          Starting JARVIS Autonomous Agent Workspace
echo ========================================================
echo.

echo [1/3] Starting Python FastAPI AI Core (Port 8005)...
if exist "%~dp0backend\.venv\Scripts\python.exe" (
    start "JARVIS Python AI Core" /d "%~dp0backend" cmd /k ".venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8005"
) else (
    start "JARVIS Python AI Core" /d "%~dp0backend" cmd /k "python -m uvicorn app.main:app --host 0.0.0.0 --port 8005"
)

echo [2/3] Starting Next.js Web UI Workspace (Port 3000)...
start "JARVIS Web UI" /d "%~dp0frontend" cmd /k "npm run dev"

echo.
echo [3/3] Opening JARVIS Workspace in default browser...
start http://localhost:3000

echo.
echo ========================================================
echo  JARVIS is now running!
echo  - Python Core API : http://localhost:8005
echo  - Full-Stack UI   : http://localhost:3000
echo ========================================================
echo.
pause

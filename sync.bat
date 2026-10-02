@echo off
title Jarvis - Git Auto-Sync
echo ========================================================
echo          Syncing Jarvis Repository with Git (main)
echo ========================================================
echo.

cd /d "%~dp0"

echo [1/4] Checking Git status...
git status

echo.
echo [2/4] Staging changes...
git add .

echo.
echo [3/4] Committing changes...
if "%~1"=="" (
    git commit -m "chore: automated sync for Jarvis %date% %time%"
) else (
    git commit -m "%~1"
)

echo.
echo [4/4] Pushing to remote main branch...
git push origin main
git push jarvis main

echo.
echo ========================================================
echo  Git Sync Completed!
echo ========================================================
echo.
pause

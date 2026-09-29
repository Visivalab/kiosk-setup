@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0kiosk-gui.ps1"
exit /b %ERRORLEVEL%

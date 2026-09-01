@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\Preflight-GPIV69CommercialFederation.ps1"
set "RC=%ERRORLEVEL%"
endlocal & exit /b %RC%

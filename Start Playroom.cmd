@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\Start-Playroom.ps1" -Mode Live
set "exitCode=%ERRORLEVEL%"
if not "%exitCode%"=="0" pause
exit /b %exitCode%

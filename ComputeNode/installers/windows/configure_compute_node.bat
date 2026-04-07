@echo off
chcp 65001 >nul 2>&1
set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "ROOT_DIR=%%~fI"
start "" notepad "%ROOT_DIR%\config.json"

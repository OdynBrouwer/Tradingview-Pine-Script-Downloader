@echo off
REM Wrapper to run the periodic PowerShell runner (used by scheduled task)
set SCRIPT_DIR=%~dp0
powershell -ExecutionPolicy Bypass -File "%SCRIPT_DIR%run_periodic_collection.ps1"

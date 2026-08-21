@echo off
powershell -ExecutionPolicy Bypass -File "%~dp0watch_quotes.ps1" %*
if errorlevel 1 pause

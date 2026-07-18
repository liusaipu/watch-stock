@echo off
where python >nul 2>nul
if %errorlevel%==0 (
    python "%~dp0watch_quotes.py" %*
) else (
    py -3 "%~dp0watch_quotes.py" %*
)
if errorlevel 1 pause

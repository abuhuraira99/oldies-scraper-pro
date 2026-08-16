@echo off
echo Starting Oldies.com Scraper Server...
echo ------------------------------------------

if not exist "venv\Scripts\activate.bat" (
    echo [ERROR] Virtual environment not found!
    echo Please double-click "setup.bat" first to install dependencies.
    pause
    exit /b
)

call venv\Scripts\activate
python server.py

pause

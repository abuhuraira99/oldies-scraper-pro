@echo off
echo Setting up Oldies.com Scraper Environment...
echo ------------------------------------------

:: Check if Python is installed
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not added to PATH.
    echo Please install Python 3.10+ and ensure "Add to PATH" is checked.
    pause
    exit /b
)

:: Create Virtual Environment
echo Creating virtual environment...
python -m venv venv

:: Activate and install dependencies
echo Activating virtual environment and installing dependencies...
call venv\Scripts\activate
pip install --upgrade pip
pip install -r requirements.txt

echo ------------------------------------------
echo Setup Complete!
echo You can now double-click run.bat to start the application.
pause

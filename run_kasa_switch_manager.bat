@echo off
REM === Kasa Alpaca Switch Manager Launcher ===

REM Set up venv if not present
if not exist venv (
    echo Creating Python virtual environment...
    python -m venv venv
)

REM Activate venv
call venv\Scripts\activate

REM Install required packages
pip install --upgrade pip
pip install python-kasa keyring keyrings.alt falcon pillow

REM Run the Alpaca service as a module to support relative imports
python -m device.app

REM Pause so the window stays open if there's an error
pause

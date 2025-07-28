@echo off
REM === Kasa Alpaca Switch Manager Credential Updater ===

REM Set up venv if not present
if not exist venv (
    echo Creating Python virtual environment...
    python -m venv venv
)

REM Activate venv
call venv\Scripts\activate

REM Install required packages
pip install --upgrade pip
pip install keyring keyrings.alt

REM Run credential update prompt as a module to support relative imports
python -m device.switch credentials

REM Pause so the window stays open if there's an error
pause

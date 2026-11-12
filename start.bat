@echo off
cd /d "%~dp0"
python -c "import flask, pymupdf, requests, openpyxl" 2>nul
if errorlevel 1 (
  echo Installing required packages...
  python -m pip install -r requirements.txt
)
python app.py
pause

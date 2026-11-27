@echo off
setlocal DisableDelayedExpansion
cd /d "%~dp0" || exit /b 1
rem Prefer an existing isolated environment, then installed Python.
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -c "import sys;sys.exit(sys.version_info < (3,11))" >nul 2>&1
  if not errorlevel 1 goto localpython
)
py -3 -c "import sys;sys.exit(sys.version_info < (3,11))" >nul 2>&1
if not errorlevel 1 goto pylauncher
python -c "import sys;sys.exit(sys.version_info < (3,11))" >nul 2>&1
if not errorlevel 1 goto systempython
if exist "%LocalAppData%\Programs\Python\Python313\python.exe" goto installedpython
rem Installation is optional and requires the user's confirmation.
if /i not "%~1"=="setup" goto missing
where winget >nul 2>&1
if errorlevel 1 goto missing
choice /c YN /n /m "Python not found. Install Python 3.13 using WinGet? [Y/N] "
if errorlevel 2 goto missing
winget install --id Python.Python.3.13 --exact --source winget
if errorlevel 1 goto missing
echo Installation finished. Close this window and run setup_windows.bat again.
exit /b 0
:localpython
".venv\Scripts\python.exe" windows_setup.py %*
exit /b %errorlevel%
:pylauncher
py -3 windows_setup.py %*
exit /b %errorlevel%
:systempython
python windows_setup.py %*
exit /b %errorlevel%
:installedpython
"%LocalAppData%\Programs\Python\Python313\python.exe" windows_setup.py %*
exit /b %errorlevel%
:missing
echo Python 3.11 or newer is required. Run setup_windows.bat, or install Python from:
echo https://www.python.org/downloads/windows/
exit /b 1

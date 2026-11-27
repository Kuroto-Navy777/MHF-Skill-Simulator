@echo off
setlocal DisableDelayedExpansion
pushd "%~dp0"
if errorlevel 1 goto failed
rem Build machine only. End users do not install Python.
py -3.12-64 -m venv .build-venv
if errorlevel 1 goto failed
".build-venv\Scripts\python.exe" -m pip install -r requirements_build.txt
if errorlevel 1 goto failed
set "KEYARG="
if exist "update_public_key.bin" set "KEYARG=--public-key update_public_key.bin"
if not exist "mhf_master.sqlite" goto nodb
choice /c YN /n /m "Build private DB copy AND public no-DB copy? [Y/N] "
if errorlevel 2 goto nodb
".build-venv\Scripts\python.exe" build_windows.py --db mhf_master.sqlite --pair %KEYARG%
if errorlevel 1 goto failed
 goto done
:nodb
".build-venv\Scripts\python.exe" build_windows.py %KEYARG%
if errorlevel 1 goto failed
:done
echo Build complete. See release folder.
popd
pause
exit /b 0
:failed
echo Build failed. Check errors above. Python 3.12 x64 is required on the build PC.
pause
exit /b 1

@echo off
setlocal DisableDelayedExpansion
pushd "%~dp0"
if errorlevel 1 goto fail_no_pop
set /p "VER=" < VERSION
set "ARCHIVE=release\MHF_SkillSimulator_%VER%_win_x64_no_DB.zip"
set "PREVIOUS=release\MHF_SkillSimulator_1.1.0_win_x64_no_DB.zip"
if not exist ".build-venv\Scripts\python.exe" goto fail
if not exist "%ARCHIVE%.update.json.sig" goto fail
if not exist "%PREVIOUS%" goto fail
if not exist "update_public_key.bin" goto fail
if not "%VER%"=="1.1.1" goto fail
rem An explicit choice is required to package a DB. No upload is performed.
choice /c YN /n /m "Include local DB in Setup for testing or authorized distribution? [Y/N] "
if errorlevel 2 goto nodb
if not exist "mhf_master.sqlite" goto fail
".build-venv\Scripts\python.exe" build_installer.py --archive "%ARCHIVE%" --previous "%PREVIOUS%" --public-key update_public_key.bin --db mhf_master.sqlite
if errorlevel 1 goto fail
 goto done
:nodb
".build-venv\Scripts\python.exe" build_installer.py --archive "%ARCHIVE%" --previous "%PREVIOUS%" --public-key update_public_key.bin
if errorlevel 1 goto fail
:done
echo Installer built. See release\installers. No files were uploaded.
popd
pause
exit /b 0
:fail
echo Installer build failed. Check signed release, original 1.1.0 archive and Inno Setup installation.
popd
:fail_no_pop
pause
exit /b 1

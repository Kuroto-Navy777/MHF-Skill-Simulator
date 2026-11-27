@echo off
setlocal DisableDelayedExpansion
pushd "%~dp0"
if errorlevel 1 goto fail_no_pop
rem This script signs 1.1.0 against the original RC6 public archive.
set /p "VER=" < VERSION
if not "%VER%"=="1.1.0" goto fail
set "ARCHIVE=release\MHF_SkillSimulator_1.1.0_win_x64_no_DB.zip"
set "PREVIOUS=release\MHF_SkillSimulator_1.1.0-rc.6_win_x64_no_DB.zip"
set "KEY=%USERPROFILE%\MHF-release-keys\release-private.pem"
set "OUT=release\upload-v1.1.0"
if not exist "%KEY%" goto fail
if not exist "update_public_key.bin" goto fail
if not exist "%ARCHIVE%" goto fail
if not exist "%PREVIOUS%" goto fail
if not exist ".build-venv\Scripts\python.exe" goto fail
if exist "%OUT%" goto fail
rem Do not overwrite a previously signed archive or upload folder.
if not exist "%ARCHIVE%.update.json" (
  ".build-venv\Scripts\python.exe" release_sign.py sign --private "%KEY%" --archive "%ARCHIVE%" --previous "%PREVIOUS%"
  if errorlevel 1 goto fail
)
".build-venv\Scripts\python.exe" release_preflight.py --archive "%ARCHIVE%" --previous "%PREVIOUS%" --public-key update_public_key.bin --out "%OUT%"
if errorlevel 1 goto fail
echo 1.1.0 release preparation complete. Upload ONLY files in %OUT%.
popd
pause
exit /b 0
:fail
echo 1.1.0 preparation failed. Check the archives, key and errors above. Do not delete or replace your key.
popd
:fail_no_pop
pause
exit /b 1

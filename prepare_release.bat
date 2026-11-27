@echo off
setlocal DisableDelayedExpansion
pushd "%~dp0"
if errorlevel 1 goto fail
rem Only sign the no-DB archive created by the paired build.
set /p "VER=" < VERSION
set "ARCHIVE=release\MHF_SkillSimulator_%VER%_win_x64_no_DB.zip"
set "KEY=%USERPROFILE%\MHF-release-keys\release-private.pem"
set "OUT=release\upload-v%VER%"
if not exist "%KEY%" goto fail
if not exist "update_public_key.bin" goto fail
if not exist "%ARCHIVE%" goto fail
if exist "%OUT%" goto fail
if not exist "%ARCHIVE%.update.json" (
  ".build-venv\Scripts\python.exe" release_sign.py sign --private "%KEY%" --archive "%ARCHIVE%"
  if errorlevel 1 goto fail
)
".build-venv\Scripts\python.exe" release_preflight.py --archive "%ARCHIVE%" --public-key update_public_key.bin --out "%OUT%"
if errorlevel 1 goto fail
echo Upload ONLY files in %OUT% after Windows testing. Do not upload DB or keys.
popd
pause
exit /b 0
:fail
echo Release preparation failed. See errors above and RELEASE_GUIDE.md.
pause
exit /b 1

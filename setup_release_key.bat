@echo off
setlocal DisableDelayedExpansion
pushd "%~dp0"
if errorlevel 1 goto fail
rem Keep the encrypted signing private key outside the project and release folder.
set "KEYDIR=%USERPROFILE%\MHF-release-keys"
if not exist "%KEYDIR%" mkdir "%KEYDIR%"
if errorlevel 1 goto fail
if exist "%KEYDIR%\release-private.pem" goto existing
if exist "update_public_key.bin" goto existing
if not exist ".build-venv\Scripts\python.exe" (
  py -3.12-64 -m venv .build-venv
  if errorlevel 1 goto fail
)
".build-venv\Scripts\python.exe" -m pip install "cryptography>=44,<48"
if errorlevel 1 goto fail
".build-venv\Scripts\python.exe" release_sign.py keygen --private "%KEYDIR%\release-private.pem" --public update_public_key.bin
if errorlevel 1 goto fail
echo Signing key created. Keep the private key and password safe. Never upload them.
popd
pause
exit /b 0
:existing
echo A signing key file already exists. Do not overwrite it. See RELEASE_GUIDE.md.
:fail
echo Key generation stopped.
pause
exit /b 1

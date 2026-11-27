@echo off
setlocal DisableDelayedExpansion
title MHF Skill Simulator - Desktop Setup
pushd "%~dp0"
if errorlevel 1 goto failed
call run_windows.bat desktop-setup %*
set "RESULT=%errorlevel%"
popd
if not "%RESULT%"=="0" pause
exit /b %RESULT%
:failed
echo ERROR: Cannot open application folder.
pause
exit /b 1

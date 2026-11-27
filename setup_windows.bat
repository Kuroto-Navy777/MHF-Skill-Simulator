@echo off
setlocal DisableDelayedExpansion
title MHF Skill Simulator - Setup
echo MHF Skill Simulator - Setup
echo Opening application folder...
pushd "%~dp0"
if errorlevel 1 goto directory_error
if not exist "run_windows.bat" goto files_missing
if not exist "windows_setup.py" goto files_missing
if not exist "requirements.txt" goto files_missing
echo Checking Python and starting setup...
call run_windows.bat setup %*
set "RESULT=%errorlevel%"
if "%RESULT%"=="0" goto finished
echo ERROR: Setup returned exit code %RESULT%.
echo Copy the error message above or take a screenshot.
goto finished
:files_missing
echo ERROR: Application files are missing.
echo Extract ALL files from the complete ZIP to a local folder first.
set "RESULT=1"
:finished
popd
echo.
pause
exit /b %RESULT%
:directory_error
echo ERROR: Unable to open the application folder.
echo Extract the complete ZIP to a local folder, then try again.
pause
exit /b 1

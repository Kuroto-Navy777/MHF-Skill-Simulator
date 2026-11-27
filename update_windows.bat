@echo off
setlocal
cd /d "%~dp0" || exit /b 1
call run_windows.bat update %*
set "RESULT=%errorlevel%"
if not "%RESULT%"=="0" echo Failed. See the message above.
pause
exit /b %RESULT%

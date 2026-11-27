@echo off
setlocal
cd /d "%~dp0" || exit /b 1
call run_windows.bat doctor %*
set "RESULT=%errorlevel%"
if not "%RESULT%"=="0" echo Check the diagnostic output above.
pause
exit /b %RESULT%

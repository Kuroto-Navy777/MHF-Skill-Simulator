@echo off
cd /d "%~dp0"
rem Run once with the simulator stopped and the original ZIPs next to mhf.sqlite.
if exist "mhf_master.sqlite" (
  echo mhf_master.sqlite already exists. Nothing was overwritten.
  pause
  exit /b 1
)
python build_master.py --db "mhf.sqlite" --out "mhf_master.sqlite"
if errorlevel 1 (
  echo Master creation failed. Original database is unchanged.
  pause
  exit /b 1
)
echo Master creation completed. Run start_web.bat next.
pause

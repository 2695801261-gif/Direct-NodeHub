@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-mainland-probe.ps1"
if errorlevel 1 (
  echo.
  echo Mainland probe did not complete. Read the error above.
)
echo.
pause
endlocal

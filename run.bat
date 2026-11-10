@echo off
rem Double-click to start the packaged PDF Validation app. All the work happens in scripts\launch.ps1.
rem   run.bat -Build      build the app and its validation engine first (needs Node.js and Python), then start it
rem   run.bat -Dev        development mode from source (npm run dev)
rem   run.bat -CheckOnly  report what is ready and what is missing without starting anything
setlocal
title PDF Validation Launcher
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\launch.ps1" %*
set "CODE=%ERRORLEVEL%"
if not "%CODE%"=="0" (
    echo.
    echo The launcher stopped with an error ^(code %CODE%^).
    echo The messages above explain the problem. Full details are in: "%~dp0logs"
    echo.
    pause
)
exit /b %CODE%

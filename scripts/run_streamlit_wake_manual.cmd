@echo off
setlocal
title PUDU Streamlit Manual Wake
echo Checking and waking the PUDU Streamlit application...
echo.
call "%~dp0run_streamlit_wake.cmd"
set "WAKE_EXIT_CODE=%ERRORLEVEL%"
echo.
if "%WAKE_EXIT_CODE%"=="0" (
    echo The application is awake and ready.
) else (
    echo The wake check failed. Please review work\streamlit-wake.log.
)
echo.
pause
exit /b %WAKE_EXIT_CODE%

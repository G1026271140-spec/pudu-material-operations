@echo off
setlocal
set "REPO_PATH=%~dp0.."
"C:\Program Files\nodejs\node.exe" "%~dp0wake_streamlit_app.mjs" --url "https://pudu-material-inventory-ndgbxrpkkrzgkbapvhzvix.streamlit.app/" --log "%REPO_PATH%\work\streamlit-wake.log" --profile "%REPO_PATH%\work\streamlit-wake-edge-profile" --timeout-ms 150000
exit /b %ERRORLEVEL%

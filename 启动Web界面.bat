@echo off
cd /d "%~dp0"
echo =======================================================
echo   DEEPSEEK Usage Export Tool  v1.0.7  -  Web UI
echo   Browser will open  http://127.0.0.1:8321
echo   Close this window to stop the server.
echo =======================================================
echo.
start "" http://127.0.0.1:8321
python dsu.py serve
echo.
echo Server stopped.
pause

@echo off
cd /d "%~dp0"
echo =======================================================
echo   One-click export: Excel + CSV + HTML report
echo   + official raw data, then open the report
echo =======================================================
echo.
set /p DSTART=Start date (YYYY-MM-DD, Enter = last 30 days): 
set /p DEND=End date (YYYY-MM-DD, Enter = today): 
if "%DSTART%"=="" for /f %%i in ('powershell -NoProfile -Command "Get-Date (Get-Date).AddDays(-29) -Format yyyy-MM-dd"') do set DSTART=%%i
if "%DEND%"=="" for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd"') do set DEND=%%i
echo.
echo Range: %DSTART% ~ %DEND%
echo Exporting...
echo.
python dsu.py go --start %DSTART% --end %DEND%
echo.
pause

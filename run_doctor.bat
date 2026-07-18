@echo off
setlocal
cd /d "%~dp0"
call "%~dp0run_srtspeak.bat" doctor
exit /b %ERRORLEVEL%

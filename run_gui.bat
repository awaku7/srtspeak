@echo off
setlocal
cd /d "%~dp0"

if not defined XAI_API_KEY if defined UAGENT_GROK_API_KEY (
  set "XAI_API_KEY=%UAGENT_GROK_API_KEY%"
)

where srtspeak >nul 2>&1
if %ERRORLEVEL%==0 (
  srtspeak gui %*
  exit /b %ERRORLEVEL%
)

set "PYTHONPATH=%CD%\src;%PYTHONPATH%"
python -m srtspeak gui %*
exit /b %ERRORLEVEL%

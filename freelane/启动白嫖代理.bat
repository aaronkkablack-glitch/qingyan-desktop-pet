@echo off
rem Start the freelane proxy silently (logs go to freelane.log).
rem Safe to run repeatedly: config migration is idempotent,
rem and a second instance exits by itself if the port is taken.
cd /d "%~dp0"
for /f "delims=" %%i in ('python -c "import sys,os;print(os.path.join(os.path.dirname(sys.executable),'pythonw.exe'))"') do set PYW=%%i
if not exist "%PYW%" set PYW=pythonw
start "freelane-proxy" "%PYW%" "%~dp0freelane.py"

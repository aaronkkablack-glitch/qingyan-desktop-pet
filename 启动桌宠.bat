@echo off
rem GLM 桌宠启动脚本：优先用 pythonw（无黑窗）
cd /d "%~dp0"
for /f "delims=" %%i in ('python -c "import sys,os;print(os.path.join(os.path.dirname(sys.executable),'pythonw.exe'))"') do set PYW=%%i
if exist "%PYW%" (
    start "GLM桌宠" "%PYW%" main.py
) else (
    start "GLM桌宠" pythonw main.py
)

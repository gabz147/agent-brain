@echo off
rem Agent Brain launcher: `brain <command>` runs the installed controller (vaultctl.py) with the
rem first Python 3.10+ it finds. Setup writes this file with the controller's folder filled in.
setlocal
if not defined BRAIN_AUTOMATION_DIR set "BRAIN_AUTOMATION_DIR={{AUTOMATION_DIR}}"
set "BRAIN_PROBE=import sys; sys.exit(sys.version_info < (3, 10))"
if defined BRAIN_PYTHON goto run_configured
py -3 -c "%BRAIN_PROBE%" >nul 2>&1 && goto run_py
python -c "%BRAIN_PROBE%" >nul 2>&1 && goto run_python
python3 -c "%BRAIN_PROBE%" >nul 2>&1 && goto run_python3
echo Agent Brain needs Python 3.10+ on PATH: https://www.python.org/downloads/windows/ 1>&2
exit /b 127
:run_configured
"%BRAIN_PYTHON%" "%BRAIN_AUTOMATION_DIR%\vaultctl.py" %*
exit /b %errorlevel%
:run_py
py -3 "%BRAIN_AUTOMATION_DIR%\vaultctl.py" %*
exit /b %errorlevel%
:run_python
python "%BRAIN_AUTOMATION_DIR%\vaultctl.py" %*
exit /b %errorlevel%
:run_python3
python3 "%BRAIN_AUTOMATION_DIR%\vaultctl.py" %*
exit /b %errorlevel%

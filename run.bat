@echo off
rem Run SentientMilk from this checkout: the control panel, or any command (run.bat chat, run.bat config).
rem It runs under the signed Python in .venv, so Windows Smart App Control does not block it the way
rem it may block an unsigned SentientMilk.exe. The first run creates .venv with Python 3.12.
setlocal
set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" (
    py -3.12 -m venv "%~dp0.venv" || goto failed
    "%PY%" -m pip install --disable-pip-version-check -q -e "%~dp0.[mcp]" || goto failed
)
"%PY%" -m sentientmilk_framework %*
exit /b %ERRORLEVEL%

:failed
echo [SentientMilk] Setup failed: install Python 3.12 with the Windows Python launcher (py). 1>&2
exit /b 1

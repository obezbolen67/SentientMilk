@echo off
rem Build dist\windows\SentientMilk: Python's own signed runtime with SentientMilk's packages and
rem source, started by SentientMilk.exe (once signed; scripts/bundle.py explains it), or until then
rem by SentientMilk.lnk or SentientMilk.cmd. MilkChan's installer includes it.
rem Built from %SENTIENTMILK_PYTHON% if set, otherwise from .venv (run.bat creates it).
setlocal
pushd "%~dp0" || exit /b 1
set "PY=%SENTIENTMILK_PYTHON%"
if not defined PY set "PY=%~dp0.venv\Scripts\python.exe"
"%PY%" scripts\bundle.py --name SentientMilk --module sentientmilk_framework --console --package sentientmilk_framework --project pyproject.toml --extra mcp
if errorlevel 1 goto failed
call "dist\windows\SentientMilk\SentientMilk.cmd" --version
if errorlevel 1 goto failed
echo [SentientMilk] Built: %CD%\dist\windows\SentientMilk (start it with SentientMilk.lnk)
popd
exit /b 0

:failed
echo [SentientMilk] Build failed. See the error above. 1>&2
popd
exit /b 1

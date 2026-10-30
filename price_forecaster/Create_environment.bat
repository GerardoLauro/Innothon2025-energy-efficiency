@echo off
setlocal
pushd "%~dp0.."
python -m venv .venv
if errorlevel 1 goto fail
.venv\Scripts\python.exe -m pip install -r requirements-forecasting.txt
if errorlevel 1 goto fail
popd
exit /b 0
:fail
popd
exit /b 1

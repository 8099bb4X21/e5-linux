@echo off
rem 荣悦 E5 OpenWrt 一键刷入 (Windows): flash.exe needs no Python; flash.py does.
chcp 65001 >nul
cd /d "%~dp0"
if exist "flash.exe" (
  flash.exe %*
  pause
  exit /b %errorlevel%
)
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY (
  echo 这个包没有 flash.exe，且系统没有 Python 3。
  echo No flash.exe in this package and no Python 3: https://www.python.org/downloads/
  pause
  exit /b 1
)
%PY% flash.py %*
pause

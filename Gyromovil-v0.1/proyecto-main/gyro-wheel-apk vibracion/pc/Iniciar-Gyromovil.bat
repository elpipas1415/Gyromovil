@echo off
setlocal
cd /d "%~dp0"
title Gyromovil - Servidor

python --version >nul 2>&1
if errorlevel 1 (
  echo.
  echo [ERROR] No se encontro Python.
  echo Instalalo desde https://www.python.org/downloads/ y marca
  echo "Add python.exe to PATH" durante la instalacion.
  echo.
  pause
  exit /b 1
)

echo Python detectado:
python --version

python -c "import vgamepad" >nul 2>&1
if errorlevel 1 (
  echo Instalando dependencias ^(solo la primera vez^)...
  python -m pip install --upgrade pip >nul 2>&1
  python -m pip install -r requirements.txt
  python -c "import vgamepad" >nul 2>&1
  if errorlevel 1 (
    echo.
    echo [ERROR] No se pudo instalar vgamepad.
    echo Prueba con Python 3.11 o 3.12 de 64 bits:
    echo   https://www.python.org/downloads/windows/
    echo.
    pause
    exit /b 1
  )
)

sc query ViGEmBus >nul 2>&1
if errorlevel 1 (
  echo.
  echo [AVISO] El driver ViGEmBus no esta instalado, asi que el mando
  echo virtual no funcionara. Descargalo aqui:
  echo   https://github.com/nefarius/ViGEmBus/releases
  echo Instala el .exe, reinicia el PC y vuelve a abrir este archivo.
  echo.
  pause
)

echo.
echo  1 = Servidor normal ^(mando + telemetria + FFB^)
echo  2 = Diagnostico de telemetria ^(sin mando virtual^)
echo.
set /p OPCION=Elige 1 o 2 [1]: 
if "%OPCION%"=="2" (
  python diagnostico.py
) else (
  python server.py
)
pause

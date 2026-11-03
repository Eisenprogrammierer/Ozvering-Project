@echo off
rem Сборка onedir-дистрибутива для Windows.
rem Требуется PyInstaller: python -m pip install -e ".[build]"
setlocal

set ROOT=%~dp0..
if "%PYTHON%"=="" set PYTHON=python

pushd "%ROOT%"

%PYTHON% -c "import PyInstaller" >nul 2>&1
if errorlevel 1 (
    echo PyInstaller не установлен. Выполните:
    echo   %PYTHON% -m pip install -e ".[build]"
    popd
    exit /b 1
)

%PYTHON% -m PyInstaller --noconfirm --clean packaging\ozvering.spec
if errorlevel 1 (
    popd
    exit /b 1
)

echo Готово: %ROOT%\dist\ozvering\
echo Запуск: %ROOT%\dist\ozvering\ozvering.exe
popd
endlocal

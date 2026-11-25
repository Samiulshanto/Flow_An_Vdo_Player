@echo off
setlocal EnableExtensions
title Flow~ manager
cd /d "%~dp0"
set "APP_DIR=%~dp0"
if "%APP_DIR:~-1%"=="\" set "APP_DIR=%APP_DIR:~0,-1%"
set "VENV=%APP_DIR%\.venv"
set "PYW=%VENV%\Scripts\pythonw.exe"
set "ICO=%APP_DIR%\icons\app_master.ico"
set "STARTMENU=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Flow~.lnk"
set "PINDIR=%APPDATA%\Microsoft\Internet Explorer\Quick Launch\User Pinned\TaskBar"
set "LNKPS=%TEMP%\flow_mklink.ps1"
set "PINPS=%TEMP%\flow_pin.ps1"

for /f %%a in ('echo prompt $E ^| cmd') do set "ESC=%%a"
set "C1=%ESC%[96m"
set "C2=%ESC%[95m"
set "C3=%ESC%[93m"
set "C4=%ESC%[92m"
set "CR=%ESC%[91m"
set "C0=%ESC%[0m"

:menu
cls
echo.
echo   %C1%###%C2%###%C3%###%C4%###%C0%   Flow~  media player
echo   %C1%###%C2%###%C3%###%C4%###%C0%   install manager
echo.
echo   %C4%[ I ]%C0%  Install     venv, packages, shortcuts
echo   %CR%[ U ]%C0%  Uninstall   remove shortcuts, optional venv
echo   %C3%[ Q ]%C0%  Quit
echo.
choice /c IUQ /n /m "  Pick one: "
if errorlevel 3 goto :eof
if errorlevel 2 goto uninstall
if errorlevel 1 goto install
goto menu

:: ------------------------------------------------------------ install
:install
echo.
echo   %C1%[1/4]%C0% looking for python...
set "PYC="
where py >nul 2>&1 && set "PYC=py -3"
if not defined PYC where python >nul 2>&1 && set "PYC=python"
if not defined PYC goto nopython
%PYC% -c "import sys;sys.exit(0 if sys.version_info>=(3,10) else 1)" >nul 2>&1
if errorlevel 1 goto nopython

echo   %C1%[2/4]%C0% making .venv
if not exist "%PYW%" %PYC% -m venv "%VENV%"
if not exist "%PYW%" goto failed

echo   %C1%[3/4]%C0% installing packages, this can take a minute
"%VENV%\Scripts\python.exe" -m pip install --upgrade pip -q
"%VENV%\Scripts\python.exe" -m pip install -r "%APP_DIR%\requirements.txt" -q
if errorlevel 1 goto failed

echo   %C1%[4/4]%C0% shortcuts
call :writeps
set "FLOW_PY=%PYW%"
set "FLOW_DIR=%APP_DIR%"
set "FLOW_ICO=%ICO%"

set "DESK="
for /f "usebackq delims=" %%d in (`powershell -NoProfile -Command "[Environment]::GetFolderPath('Desktop')"`) do set "DESK=%%d"
if not defined DESK set "DESK=%USERPROFILE%\Desktop"

powershell -NoProfile -ExecutionPolicy Bypass -File "%LNKPS%" "%STARTMENU%"
powershell -NoProfile -ExecutionPolicy Bypass -File "%LNKPS%" "%DESK%\Flow~.lnk"
echo        %C4%+%C0% start menu
echo        %C4%+%C0% desktop

powershell -NoProfile -ExecutionPolicy Bypass -File "%PINPS%" "%STARTMENU%"
echo        %C4%+%C0% taskbar

echo.
choice /c YN /n /m "  Restart Explorer so the taskbar icon shows up now? [Y/N] "
if errorlevel 2 goto donei
taskkill /f /im explorer.exe >nul 2>&1
start "" explorer.exe

:donei
echo.
echo   %C4%Done.%C0% Look for the Flow~ icon. If the taskbar one is missing,
echo   right click the Start menu entry and choose Pin to taskbar.
goto end

:nopython
echo.
echo   %CR%Python 3.10 or newer was not found.%C0%
echo   Get it from python.org, tick "Add python.exe to PATH", run this again.
goto end

:failed
echo.
echo   %CR%Something failed above.%C0% Scroll up to read the message.
goto end

:: ------------------------------------------------------------ uninstall
:uninstall
echo.
set "DESK="
for /f "usebackq delims=" %%d in (`powershell -NoProfile -Command "[Environment]::GetFolderPath('Desktop')"`) do set "DESK=%%d"
if not defined DESK set "DESK=%USERPROFILE%\Desktop"

if exist "%STARTMENU%" del /q "%STARTMENU%" & echo        %CR%-%C0% start menu
if exist "%DESK%\Flow~.lnk" del /q "%DESK%\Flow~.lnk" & echo        %CR%-%C0% desktop
if exist "%PINDIR%\Flow~.lnk" del /q "%PINDIR%\Flow~.lnk" & echo        %CR%-%C0% taskbar

echo.
choice /c YN /n /m "  Also delete the .venv folder? Your data stays. [Y/N] "
if errorlevel 2 goto doneu
if exist "%VENV%" rmdir /s /q "%VENV%" & echo        %CR%-%C0% .venv

:doneu
echo.
choice /c YN /n /m "  Restart Explorer so the taskbar icon disappears now? [Y/N] "
if errorlevel 2 goto doneu2
taskkill /f /im explorer.exe >nul 2>&1
start "" explorer.exe
:doneu2
echo.
echo   %C4%Removed.%C0% The Flow~ folder and ./data are untouched, delete them by hand if you want.
goto end

:: ------------------------------------------------------------ helpers
:writeps
> "%LNKPS%" echo param([string]$Path)
>> "%LNKPS%" echo $s = (New-Object -ComObject WScript.Shell).CreateShortcut($Path)
>> "%LNKPS%" echo $s.TargetPath = $env:FLOW_PY
>> "%LNKPS%" echo $s.Arguments = '-m flow'
>> "%LNKPS%" echo $s.WorkingDirectory = $env:FLOW_DIR
>> "%LNKPS%" echo $s.IconLocation = $env:FLOW_ICO
>> "%LNKPS%" echo $s.Description = 'Flow~ media player'
>> "%LNKPS%" echo $s.Save()

> "%PINPS%" echo param([string]$Path)
>> "%PINPS%" echo $d = Join-Path $env:APPDATA 'Microsoft\Internet Explorer\Quick Launch\User Pinned\TaskBar'
>> "%PINPS%" echo New-Item -ItemType Directory -Force $d ^| Out-Null
>> "%PINPS%" echo Copy-Item $Path (Join-Path $d 'Flow~.lnk') -Force
exit /b

:end
del /q "%LNKPS%" "%PINPS%" >nul 2>&1
echo.
pause
goto menu
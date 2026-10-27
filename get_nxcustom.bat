@echo off
:: get_nxcustom.bat - clone the NXcustom repo, or update it if it is already there.
::
:: Usage:  get_nxcustom.bat [target_dir] [branch]
::   target_dir  defaults to %USERPROFILE%\nxcustom
::   branch      defaults to master
::
:: Requires Git for Windows (https://git-scm.com/download/win).

setlocal

set REPO_URL=https://github.com/MCBailey-CTS/nxcustom.git
set TARGET_DIR=%~1
set BRANCH=%~2
if "%TARGET_DIR%"=="" set TARGET_DIR=%USERPROFILE%\nxcustom
if "%BRANCH%"=="" set BRANCH=master

where git >nul 2>&1
if errorlevel 1 (
    echo ERROR: git was not found on PATH. Install Git for Windows and try again.
    goto :fail
)

if exist "%TARGET_DIR%\.git" goto :update

if exist "%TARGET_DIR%\*" (
    dir /b /a "%TARGET_DIR%" | findstr "^" >nul && (
        echo ERROR: %TARGET_DIR% exists, is not empty, and is not a git repo.
        echo Pick another folder: get_nxcustom.bat C:\some\other\folder
        goto :fail
    )
)

echo Cloning %REPO_URL% [%BRANCH%] into %TARGET_DIR% ...
git clone --branch "%BRANCH%" "%REPO_URL%" "%TARGET_DIR%"
if errorlevel 1 goto :fail
goto :done

:update
echo Updating existing repo in %TARGET_DIR% [%BRANCH%] ...
git -C "%TARGET_DIR%" fetch origin
if errorlevel 1 goto :fail
git -C "%TARGET_DIR%" checkout "%BRANCH%"
if errorlevel 1 goto :fail
git -C "%TARGET_DIR%" pull --ff-only origin "%BRANCH%"
if errorlevel 1 (
    echo ERROR: pull failed - the local copy probably has changes of its own.
    echo Run "git -C "%TARGET_DIR%" status" to see them.
    goto :fail
)

:done
echo.
echo Done. NXcustom is at %TARGET_DIR%
echo Launch NX with %TARGET_DIR%\NXstartup\NX2306.bat
endlocal
pause
exit /b 0

:fail
echo.
echo FAILED.
endlocal
pause
exit /b 1

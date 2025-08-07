@echo off

:: Launch NXcustom
:: Last Modified: 19Dec2019

:: Edit this line to define NX release number
set NXCUSTOM_NUMBER=2306

:: Edit this line to show NX package name (nx, view, nxcam, mechatronics, powerdrafting)
set NXCUSTOM_PACKAGE_NAME=NX

:: Edit this line for Routing units (set to metric or inch)
set UGII_ROUTING_KIT_UNITS=metric

:: The "Start in Folder" is determined by the "Start in" location in the Shortcut.
:: when the "Start in" location is the same (default behavior) as the start script itself, the "Start in folder" is determined by NXcustom 
:: To fully disable the Windows shortcut "Start in" functionality and use the NXcustom method, comment the line below!!
set USE_START_DIR=%cd%

:: **** DO NOT EDIT THE FOLLOWING LINES (start) ****
:: Determine location of NXcustom folder and call NXcommon.bat
set NXCUSTOM_START_DIR=%~dp0
set NXCUSTOM_START_DIR=%NXCUSTOM_START_DIR:~0,-1%
set NXCUSTOM_DIR=%NXCUSTOM_START_DIR:\NXstartup=%
set NXCUSTOM_LIB=%NXCUSTOM_DIR%\NX%NXCUSTOM_NUMBER%library

:: Common settings for all NX and PTS sessions
Call "%NXCUSTOM_LIB%\NX_common.bat"
:: **** DO NOT EDIT THE PREVIOUS LINES (end) ****

:: Set Bundle(s) - Separate 2 bundle names with a space "BUNDLE1" "BUNDLE2"
:: "%UGII_BASE_DIR%\UGFLEXLM\lictool" --setbundle "STUDIO4DS"

:: Unset Bundles
:: "%UGII_BASE_DIR%\UGFLEXLM\lictool" --unsetbundle --all

:: start "" <== Add this to start of command to hide console window
:: Start NX (remove the :: from only one of the NX lines below)

:: Starts individual NX sessions 
start "" "%UGII_BASE_DIR%\nxbin\ugraf" -%NXCUSTOM_PACKAGE_NAME% %*

:: Uses one NX session 

:: start "" "%UGII_BASE_DIR%\nxbin\ugs_router" -message="Starting %NXCUSTOM_PACKAGE_NAME%" -ug -version=%NXCUSTOM_UG_VERSION% %* -opts -%NXCUSTOM_PACKAGE_NAME%
:: timeout %CMD_PAUSE%
@echo on

:: NXcustom common settings
:: Last Modified: 8Jan2020

:: Set location of user NX User files
:: 1 = %NXCUSTOM_LIB%\CustomerDefaults\Users\%USERNAME% (default)
:: 2 = %HOMEDRIVE%%HOMEPATH%\NXcustom\%NXCUSTOM_NUMBER%
:: 3 = %APPDATA%\NXcustom\%NXCUSTOM_NUMBER%
:: 4 = %LOCALAPPDATA%\Siemens\%NXCUSTOM_NUMBER% (Siemens default) 
:: Any other value will be presumed as an existing path where "\%USERNAME%\%NXCUSTOM_NUMBER%" will be appended. If path is missing, it will be reported.
set NXCUSTOM_USER_SETTINGS_LOCATION=2

:: Set if you want to store the Customer defaults in Managed Mode at a different location (true/false)
:: true  = Managed Customer Defaults will be stored in the folder TC under the default ..\CustomerDefaults folder.
::         Be aware that it requires 2 sets of Customer defaults to be managed on Site and Group level!!
:: false = Managed Customer Defaults will be used from the same location as native
set NXCUSTOM_MANAGED_CUSTOMER_DEFAULTS=true

:: Edit this line for Routing units (set to metric or inch)
:: When this variable is already set earlier it will not be changed anymore!!!!!!!!!!!!!!
if not defined UGII_ROUTING_KIT_UNITS set UGII_ROUTING_KIT_UNITS=metric

:: Custom Environment Variable File
set UGII_ENV_FILE=%NXCUSTOM_LIB%\NX_env.dat

:: Location of the preferred folder where NX has to start in. When this folder does not exist, several alternatives are used to find a suitable folder.
set HOME=%HOMEDRIVE%%HOMEPATH%\NX

:: setting defaults paths in case it is not allowed to read the registry.
:: please modify this path to the correct one when NX is not installed at the default location and NXcustom cannot start NX
set NXCUSTOM_UGII_BASE_DIR=C:\Program Files\Siemens\NX2306

:: ************************************************************************************
:: **** DO NOT EDIT THE FOLLOWING LINES UNLESS YOU KNOW WHAT YOU ARE DOING !!!!!!! ****
:: ************************************************************************************

:: Set default commmand window size and color 
mode con: cols=140 lines=40
color 2f

:: Set pause for command window display to read the settings after start
set CMD_PAUSE=60

:: **** DO NOT EDIT THE FOLLOWING LINES UNLESS YOU KNOW WHAT YOU ARE DOING (start) ****

:: NXcustom Version for User Reference(please do not edit)
set NXCUSTOM_VERSION=NX%NXCUSTOM_NUMBER% Revision A
:: Convert the NX versions (NXCUSTOM_NUMBER) to the old UG versions (NXCUSTOM_UG_VERSION) for startup through ugs_router
if %NXCUSTOM_NUMBER%==1847 set NXCUSTOM_UG_VERSION=V31.0
if %NXCUSTOM_NUMBER%==1872 set NXCUSTOM_UG_VERSION=V32.0
if %NXCUSTOM_NUMBER% GEQ 1899 set NXCUSTOM_UG_VERSION=V%NXCUSTOM_NUMBER%
if %NXCUSTOM_UG_VERSION%=="" (
	color 4f
	echo No installed version of NX found for NX%NXCUSTOM_NUMBER% !
	pause
	exit
)

:: Determine where NX is installed
set rk=hklm\software\wow6432node\Unigraphics Solutions\Installed Applications
for /f "tokens=3,* usebackq" %%h in (`reg query "%rk%" /v "Unigraphics %NXCUSTOM_UG_VERSION%" ^| findstr /i %NXCUSTOM_UG_VERSION%` ) do (set str1=%%~dpi)
set UGII_BASE_DIR_BACKUP=%UGII_BASE_DIR%
set UGII_BASE_DIR=%str1:\ugii\=%
set UGII_BASE_DIR=%UGII_BASE_DIR:\nxbin\=%
set str1=

if not exist "%UGII_BASE_DIR%" (
    set UGII_BASE_DIR=%UGII_BASE_DIR_BACKUP%
)
if not exist "%UGII_BASE_DIR%" (
    set UGII_BASE_DIR=%NXCUSTOM_UGII_BASE_DIR%
)
if not exist "%UGII_BASE_DIR%" (
    color 4f
    echo The path to the NX installation cannot correctly be determined. 
    echo Probably because your are not authorised to read the registry from your system.
    echo please set NXCUSTOM_UGII_BASE_DIR to the correct path in the file:
    echo %NXCUSTOM_LIB%\NX_common.bat
    pause
    exit
)

for /f "usebackq" %%i in (`"%UGII_BASE_DIR%\NXBIN\env_print" NX_COMPATIBLE_BASE_RELEASE_VERSION`) do (set NXCUSTOM_INSTALLED_VERSION=%%~i)
if not %NXCUSTOM_INSTALLED_VERSION%==%NXCUSTOM_NUMBER% (
color 4f
echo You are not running the correct version of NXcustom "NX%NXCUSTOM_NUMBER%" against the installed NX version "NX%NXCUSTOM_INSTALLED_VERSION%"
echo There is a different main version of NX installed. If so please download the NXcustom for "NX%NXCUSTOM_INSTALLED_VERSION%". 
pause
exit
)

:: Customer Defaults Folder Location
set NXCUSTOM_CUSTOMER_DEFAULTS_DIR=%NXCUSTOM_LIB%\CustomerDefaults

if %NXCUSTOM_MANAGED_CUSTOMER_DEFAULTS%=="true" (
	if defined NXCUSTOM_TEAMCENTER_ACTIVE set NXCUSTOM_CUSTOMER_DEFAULTS_DIR=%NXCUSTOM_LIB%\CustomerDefaults\Tc
)

if defined NXCUSTOM_GROUP_DIR set UGII_GROUP_DIR=%NXCUSTOM_CUSTOMER_DEFAULTS_DIR%\%NXCUSTOM_GROUP_DIR%
  
:: Define location of User Settings Folder
if %NXCUSTOM_USER_SETTINGS_LOCATION%==1 (
    set TMP_USER_DIR=%NXCUSTOM_CUSTOMER_DEFAULTS_DIR%\Users
    set UGII_USER_PROFILE_DIR=%NXCUSTOM_CUSTOMER_DEFAULTS_DIR%\Users\%USERNAME%
    goto user_folder_define
)
if %NXCUSTOM_USER_SETTINGS_LOCATION%==2 (
    set TMP_USER_DIR=%HOMEDRIVE%%HOMEPATH%
    set UGII_USER_PROFILE_DIR=%HOMEDRIVE%%HOMEPATH%\NXcustom\%NXCUSTOM_NUMBER%
    goto user_folder_define
)
if %NXCUSTOM_USER_SETTINGS_LOCATION%==3 (
    set TMP_USER_DIR=%APPDATA%
    set UGII_USER_PROFILE_DIR=%APPDATA%\NXcustom\%NXCUSTOM_NUMBER%
    goto user_folder_define
)
if %NXCUSTOM_USER_SETTINGS_LOCATION%==4 (
    set TMP_USER_DIR=%LOCALAPPDATA%
    set UGII_USER_PROFILE_DIR=%LOCALAPPDATA%\Siemens\%NXCUSTOM_NUMBER%
    goto user_folder_define
)
set TMP_USER_DIR=%NXCUSTOM_USER_SETTINGS_LOCATION%
set UGII_USER_PROFILE_DIR=%NXCUSTOM_USER_SETTINGS_LOCATION%\%USERNAME%\%NXCUSTOM_NUMBER%
goto user_folder_define

:user_option_error
:: Report Missing Path
color 4f
echo Could not create the "%UGII_USER_PROFILE_DIR%" folder
echo Check permissions or existence of %TMP_USER_DIR% folder
pause
exit /b

:user_folder_define
if not exist "%UGII_USER_PROFILE_DIR%" mkdir "%UGII_USER_PROFILE_DIR%"
if not exist "%UGII_USER_PROFILE_DIR%" goto user_option_error

:: Use to set location of default Load Options in user folder
:: set UGII_LOAD_OPTIONS=%UGII_USER_PROFILE_DIR%\load_options.def

set TMP_USER_DIR=

:: Import Saved Assembly Navigator Column Settings when available
if exist "%NXCUSTOM_LIB%\_NXCustom_Management\bin\Restore_Assembly_Navigator_Settings.bat" call "%NXCUSTOM_LIB%\_NXCustom_Management\bin\Restore_Assembly_Navigator_Settings.bat"

:: Import Saved Part Navigator Column Settings when available
if exist "%NXCUSTOM_LIB%\_NXCustom_Management\bin\Restore_Part_Navigator_Settings.bat" call "%NXCUSTOM_LIB%\_NXCustom_Management\bin\Restore_Part_Navigator_Settings.bat"

:: Import Saved Operation Navigator Column Settings when available
if exist "%NXCUSTOM_LIB%\_NXCustom_Management\bin\Restore_Operation_Navigator_Settings.bat" call "%NXCUSTOM_LIB%\_NXCustom_Management\bin\Restore_Operation_Navigator_Settings.bat"

set START_DIR=%USE_START_DIR%
if defined USE_START_DIR (
	if NOT %NXCUSTOM_START_DIR% == %USE_START_DIR% (
		set START_DIR=%NXCUSTOM_START_DIR%
	)
)
 
if %START_DIR:~0,2% == "\\" set START_DIR=%HOME%

if not exist "%START_DIR%" set START_DIR=%HOME%
if not exist "%START_DIR%" set START_DIR=%HOMEDRIVE%%HOMEPATH%
if not exist "%START_DIR%" set START_DIR=%TC_TMP_DIR%
if not exist "%START_DIR%" set START_DIR=%UGII_TMP_DIR%
if not exist "%START_DIR%" set START_DIR=%TEMP%

cd /d %START_DIR% 2> nul

:: ***********************************************************************************
:: **** DO NOT EDIT THE PREVIOUS LINES UNLESS YOU KNOW WHAT YOU ARE DOING!!!!!!!! ****
:: ***********************************************************************************

:: #########################################################################
::
::  ERROR and HELP Variables.
::
::  NX Documentation and online help is now based on a web server.
::  When UGII_UGDOC_BASE is not defined, NX will try to access the online 
::  NX Documentation on the Siemens servers
::  When users do not have access to the internet, UGII_UGDOC_BASE must be defined
::  In that case UGII_UGDOC_BASE should point to the server that is being used, e.g.
::  UGII_UGDOC_BASE=http://localhost:8282 or any other internal server.
::  The rest of the documentation and context sensitive help variables are
::  based on this one setting and should not change.
::  To make sure that the UGII_UGDOC_BASE is not set so the Siemens Server will be used, 
::  remove the :: in the folowing line:
::set UGII_UGDOC_BASE=
::

:: Output Variables when required
if defined NXCUSTOM_SUPPRESS_VARIABLES_DISPLAY goto END
SETLOCAL EnableDelayedExpansion
echo *********************************** NX%NXCUSTOM_NUMBER% Package = %NXCUSTOM_PACKAGE_NAME% ***********************************
for /f "usebackq delims=v" %%i in (`"%UGII_BASE_DIR%\NXBIN\env_print" NX_VERSION`) do (
	echo Installed NX Version        = %%~i
)
                                       echo Start in folder             = %cd%
if defined NXCUSTOM_VERSION            echo NXCUSTOM_VERSION            = %NXCUSTOM_VERSION%
if defined NXCUSTOM_DIR                echo NXCUSTOM_DIR                = %NXCUSTOM_DIR%
if defined NXCUSTOM_LIB                echo NXCUSTOM_LIB                = %NXCUSTOM_LIB%
if defined UGII_USER_PROFILE_DIR       echo UGII_USER_PROFILE_DIR       = %UGII_USER_PROFILE_DIR%
if defined UGII_BASE_DIR               echo UGII_BASE_DIR               = %UGII_BASE_DIR%
if defined UGII_SITE_DIR (
	echo UGII_SITE_DIR               = %UGII_SITE_DIR%
) ELSE (
	for /f "usebackq delims=|" %%i in (`"%UGII_BASE_DIR%\NXBIN\env_print" UGII_SITE_DIR`) do (
		set NXCUSTOM_UGII_SITE_DIR=%%~i
		echo UGII_SITE_DIR               = !NXCUSTOM_UGII_SITE_DIR!
	)
)
if defined UGII_GROUP_DIR (
	echo UGII_GROUP_DIR              = %UGII_GROUP_DIR%
) ELSE (
	for /f "usebackq delims=|" %%i in (`"%UGII_BASE_DIR%\NXBIN\env_print" UGII_GROUP_DIR`) do (
		set NXCUSTOM_UGII_GROUP_DIR=%%~i
		echo UGII_GROUP_DIR              = !NXCUSTOM_UGII_GROUP_DIR!
	)
)
if defined UGII_ROUTING_KIT_UNITS      echo UGII_ROUTING_KIT_UNITS      = %UGII_ROUTING_KIT_UNITS%
if defined NTIER_ARG                   echo NTIER_ARG                   = %NTIER_ARG%
if defined TC_DATA                     echo TC_DATA                     = %TC_DATA%
if defined SE_DIR                      echo SE_DIR                      = %SE_DIR%
echo *******************************************************************************************
ENDLOCAL
: END
:: Remove variables to keep NX log clean 
:: Comment the lines below if the environment variables because they are used somewhere else.
set NXCUSTOM_GROUP_DIR=
set NXCUSTOM_MANAGED_CUSTOMER_DEFAULTS=
set NXCUSTOM_USER_SETTINGS_LOCATION=
set NXCUSTOM_INSTALLED_VERSION=
set NXCUSTOM_SUPPRESS_VARIABLES_DISPLAY=
set NXCUSTOM_UGII_BASE_DIR=

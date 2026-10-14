UGZIPC V1.0.5

Purpose:
  Exports components from an UG-assembly into a ZIP file

Requirements for this package:
  NX8.5
  WindowsXP/Vista,7 32Bit and 64Bit editions
  UG/Gateway
  UG/Open API Execute

Restrictions:
  - Does not support Teamcenter environment
  - Does not support filenames longer than 126 characters

Author:
  Heinrich Wiedemann
  Werkmeisterstrasse 1b
  87629 Fuessen / Germany
  Phone +49 171 5090 371  FAX +49 8362 8475
  email: hwiedemann@w-eng.de
  http://www.w-eng.de/ugzipc.htm

Quick installation:
  - Move the provided 'application'-directory and the 'startup'-directory' to one
    of the following directories:
      %UGII_USER_DIR% 
      %UGII_SITE_DIR% 
      %UGII_VENDOR_DIR% 
  - Copy ugzipc.dll from either folder windows_x32 or folder windows_x64 to your
    'application'-directory
  - The required enironment-variable (i.e. UGII_USER_DIR or UGII_SITE_DIR or
    UGII_VENDOR_DIR) must be set properly on your system to point to a directory.
  Example:
    - Set UGII_USER_DIR=c:\temp by Start->Settings->Control Panel->System->
      Advanced->Environment Variables
    - In directory c:\temp\application, the files ugzipc.dll and ugzipc.dlg are located
    - In directory c:\temp\startup, the file ugzipc.men is located

Starting UG Zip Components:
  Within Unigraphics: File->Export->Zip Assembly

Most common problems:
  - In File->Export, there is no entry 'Zip Assembly':
    Make sure, your environment variable UGII_USER_DIR, UGII_SITE_DIR or
    UGII_VENDOR_DIR is set properly on your system and check, if the files have been
    placed properly in the correct directories (see above)
    You can verify the setting of UGII_USER_DIR, UGII_SITE_DIR or UGII_VENDOR_DIR
    by inspecting the UG syslog-file or by 'Help -> UG Log File'. In the
    **** System Environment Variables **** or in the
    *** Unlocked Unigraphics Configuration Variables *** - section you should find
    an entry like
       UGII_USER_DIR c:\temp
    If you change the value of UGII_USER_DIR, UGII_SITE_DIR or UGII_VENDOR_DIR,
    please restart NX as it picks up the environment variables at startup only.
  - UGZipC does not start and an error 'Menu Button Definition Error' is displayed:
    Probably, you did not copy the ugzipc.dll image into the application folder.

Copyright & remarks:
  Thanks to Jean-loup Gailly and Mark Adler, the authors of zlib - a free
  zip-library (http://www.gzip.org/zlib).
  Permission is granted to any individual/institution/corporate entity
  to use, copy, redistribute or modify UGZIPC for any purpose.
  If you have added an interesting enhancement/port or want to report
  an error, please contact the author at hwiedemann@w-eng.de

History:
  09-Oct-2012: NX8.5, Windows x32 and x64 editions released
  20-Dec-2008: UG NX5/NX6, Windows x32 and x64 editions released
  28-Sep-2004: UG NX3
  23-Jul-2003: V1.05: Removed compiler error/warnings on HP-UX - contributed by
               Rafael Portela/Sony Ericsson. Using zlib 1.1.4 now. Removed a bug
               in ugzipc.men - reported by Rick Hebert/EDS PLM Solutions
  05-Sep-2002: V1.04: UG NX1, issues a warning when being run under iMAN or UG/Manager
  03-Aug-2001: V1.03: UG V18, contributions by Steven L. Alexander/Delphi
               Automotive Systems for Unix-compatiblity
  01-Dec-2000: V1.02: UG V17, support for UG/Menuscript
  03-Feb-2000: V1.01: UG V16, dialog file reworked, common code for V15 and V16
  16-Sep-1999: Recompiled (VC 6.0) and packaged for UG BBS
  27-May-1999: UG V15
  13-Jan-1998: Initial release V1.0, UG V13

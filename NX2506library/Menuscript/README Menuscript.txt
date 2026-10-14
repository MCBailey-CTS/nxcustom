NXcustom Menuscript                                 Last Modified: 8Jan2020

Use the Menuscript folder to share modifications to NX menus with multiple users.  These modificaitons can be referenced by ribbon files.

The following line in the NXcustom\NX1899library\NX_env.dat file controls the location and folder name of the Menuscript folder:

	NXCUSTOM_MENUS=${NXCUSTOM_LIB}\Menuscript
	
This variable is referenced in the NXcustom\NX1899library\custom_dirs.dat file.

Within this folder you will find modifications to the main and pop-up menus.  The Zip Assembly (UGZipC) utility is also in the Menuscript folder.

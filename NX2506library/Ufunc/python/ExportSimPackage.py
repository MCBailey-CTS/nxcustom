"""
Python port of the export-sim-package UFunc: the selected components of a simulation part into a dated
"{date}-{customer}-Simulation-Package-for-Design" folder under the job's Simulation folder - .prt copies, or IGES /
STEP exports - 7-zipped there, and optionally copied to "Process and Sim Data for Design".

ALL PYTHON since 2026-10-23: the export-sim-package menu button runs this file. main() records the run
(usage_db.run("export-sim-package")) and shows a Block UI Styler dialog (ExportSimPackage.dlx, built by
tools\\make-dlx.py) in place of the WinForms form: its File Type radio pair (.prt / .stp - .igs), Copy to check box
and the Select button's component pick. It replaced src\\UFuncs\\ExportSimPackage.cs (the form) and
src\\Static\\ExportSimPackage.cs (Static.ExportSimPackageExport, the Select button's body) - both are in git at
5d6e47f. This file used to be src\\python\\ExportSimPackage.py, the port of the IGES export alone. The dialog has NEVER
BEEN RUN IN NX, nor has the export.

Ported from:
  - Static.ExportSimPackageExport                -> _export
  - Static.ExportSimPackageIges                  -> ExportSimPackage.iges
  - Ucf("...SimulationControlFile.ucf").SingleValue -> _ucf_single_value
  - AssemblyExportDesignDataExport1.Stp          -> AssemblyExportDesignData._stp
  - AssemblyExportDesignDataExport1.SevenZip(path, true, files) -> _seven_zip
  - GFolder.create_or_null(work part)            -> ExportStrip._GFolder.create (exception printed, None)

Differences from the C#:
  - The job-folder check and the "already exists, replace it?" question come before the dialog, as they came
    before the Select button's pick; but the package folder is only (re)created once the dialog is accepted with
    components picked. The C# created it before the pick, so a cancelled pick left an empty folder behind.
  - The form opened with neither radio button checked (Select then exported nothing but an empty zip); the dialog
    always has one: .prt, the .dlx's default.
  - The .NET named groups in SIM_SPECIAL_REGEX ("(?<CustomerNumber>...)") are rewritten to Python's "(?P<...>)".
  - Kept from the C#: with Copy ticked, the zip goes both to "Process and Sim Data for Design\\{package folder}\\"
    (the loop over the package folder, which by then holds only the zip) and to "Process and Sim Data for Design\\"
    itself.
  - ExportSimPackage.iges raises a plain Exception where the C# threw ArgumentException(message, nameof(igesPath)),
    so the printed "Message:" line lacks "Parameter name: igesPath".
  - IgesCreator property names are confirmed only as strings in NXOpen.pyd.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from typing import Dict, List, Optional

# Session.Execute does not put the script's folder on sys.path, so the shared module would not import.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

_shared_python = os.path.join(os.path.dirname(_here), "python")
if os.path.isdir(_shared_python) and _shared_python not in sys.path:
    sys.path.insert(1, _shared_python)

import NXOpen  # noqa: E402
import NXOpen.Assemblies  # noqa: E402
import NXOpen.BlockStyler  # noqa: E402

import tsg_nx as nx  # noqa: E402
import ExportStrip as exportstrip  # noqa: E402
from tsg_dialog import Dialog, components_of, title_with_version  # noqa: E402

# _UFunc.ufunc_export_sim_package (deleted with the form)
ufunc_export_sim_package = "export-sim-package"

# The form's static SimUcf.
_SimUcf = "U:\\nxFiles\\UfuncFiles\\SimulationControlFile.ucf"
_StepSettingsFile = "U:\\nxFiles\\Step Translator\\214ug.def"
_SevenZip = "C:\\Program Files\\7-Zip\\7z"

# NX will not build a Block Styler dialog from inside some callbacks (a menu or toolbar launch, it seems).
_ErrorCannotLaunchDialog = 3520048


class ExportSimPackage(object):

    @staticmethod
    def iges(part_path: str, iges_path: str, wait: bool) -> None:
        """Static.ExportSimPackageIges - exports part_path to iges_path with the NX 11 igesexport.def settings;
        when wait, the translator is waited on and the result printed."""
        try:
            if os.path.isfile(iges_path):
                raise Exception("Path for iges file already exists.")

            dex_manager = NXOpen.Session.GetSession().DexManager
            iges_creator = dex_manager.CreateIgesCreator()

            # sql
            try:
                iges_creator.ExportModelData = True
                iges_creator.ExportFrom = NXOpen.IgesCreator.ExportFromOption.ExistingPart
                iges_creator.ObjectTypes.Curves = True
                iges_creator.ObjectTypes.Surfaces = True
                iges_creator.ObjectTypes.Annotations = True
                iges_creator.ObjectTypes.Structures = True
                iges_creator.ObjectTypes.Solids = True
                iges_creator.SettingsFile = "C:\\Program Files\\Siemens\\NX 11.0\\iges\\igesexport.def"
                iges_creator.ExportDrawings = True
                iges_creator.InputFile = part_path
                iges_creator.OutputFile = iges_path
                iges_creator.FileSaveFlag = False
                iges_creator.LayerMask = "1-256"
                iges_creator.DrawingList = ""
                iges_creator.ViewList = "Top,Front,Right,Back,Bottom,Left,Isometric,Trimetric,User Defined"
                iges_creator.ProcessHoldFlag = wait
                iges_creator.Commit()
            finally:
                # session_.__UsingBuilderDestroyer(igesCreator)
                iges_creator.Destroy()

            if wait:
                nx.print_("Successfully created \"{}\".".format(iges_path)
                          if os.path.isfile(iges_path)
                          else "Unsuccessfully created \"{}\".".format(iges_path))
        except Exception as ex:
            nx.print_exception(ex, "Error when creating Iges file for " + part_path)


# ---------------------------------------------------------------------------------------------------
# The export: Static.ExportSimPackageExport, split around the dialog
# ---------------------------------------------------------------------------------------------------

class _Package(object):
    """What the C# worked out before its component pick: the customer number, job folder and package folder."""

    def __init__(self, customer_number: str, folder: exportstrip._GFolder) -> None:
        self.customer_number = customer_number
        self.folder = folder
        self.directory = "{}\\{}-{}-Simulation-Package-for-Design".format(
            folder.DirSimulation, exportstrip._todays_date(), customer_number)


def _package_or_none() -> Optional[_Package]:
    """The checks before the pick: the display part is a simulation part (SIM_SPECIAL_REGEX), the work part is in a
    job folder, and an existing package folder for today may be replaced. None (with the reason printed) when not."""
    pattern = _dotnet_regex(_ucf_single_value(_SimUcf, "SIM_SPECIAL_REGEX"))
    match = re.match(pattern, nx.display_part().Leaf)

    if not match:
        nx.print_("Current DisplayPart not in a valid Job Folder.")
        return None

    try:
        folder = exportstrip._GFolder.create(nx.work_part().FullPath)
    except Exception as ex:
        nx.print_exception(ex, "Exception caught for GFolder '{}'".format(nx.work_part().FullPath))
        nx.print_("The current work part does not reside within a GFolder.")
        return None

    package = _Package(match.group("CustomerNumber"), folder)

    if os.path.isdir(package.directory) and not _yes_no(
            "Warning", "{} already exists, would you like to replace it?".format(package.directory)):
        nx.mark_cancelled("replace the existing package folder")
        return None

    return package


def _export(package: _Package, components: List[NXOpen.Assemblies.Component], is_prt: bool, is_stp_iges: bool,
            copy: bool) -> None:
    """The rest of Static.ExportSimPackageExport, after the pick: per-component .prt copy / IGES / STEP, the zip,
    and the copy to "Process and Sim Data for Design". Per-item exceptions are printed, as in the C#."""
    import AssemblyExportDesignData as aedd

    customer_number = package.customer_number
    directory = package.directory

    if os.path.isdir(directory):
        shutil.rmtree(directory)

    os.makedirs(directory)

    for comp in components:
        try:
            display_name = comp.DisplayName.lower()

            if not nx.is_loaded(comp):
                continue

            proto = comp.Prototype

            if is_prt:
                try:
                    leaf = comp.Name if "master" in display_name else proto.Leaf
                    comp_path = "{}\\{}.prt".format(directory, leaf)

                    if os.path.isfile(comp_path):
                        os.remove(comp_path)

                    shutil.copyfile(proto.FullPath, comp_path)

                    nx.print_("Successfully created \"{}\".".format(comp_path)
                              if os.path.isfile(comp_path)
                              else "Unsuccessfully created \"{}\".".format(comp_path))
                except Exception as ex:
                    nx.print_exception(ex)

            export_file_no_extension = "{}\\{}".format(directory, proto.Leaf)

            try:
                if is_stp_iges and ("fshape" in display_name
                                    or "{}-t".format(customer_number) in display_name
                                    or "pad" in display_name
                                    or "profile" in display_name
                                    or "{}-b".format(customer_number) in display_name):
                    ExportSimPackage.iges(proto.FullPath, export_file_no_extension + ".igs", True)
            except Exception as ex:
                nx.print_exception(ex)

            try:
                if is_stp_iges and ("{}-d".format(customer_number) in display_name
                                    or "ref-data" in display_name
                                    or "refdata" in display_name
                                    or "master" in display_name):
                    aedd._stp(proto.FullPath, export_file_no_extension + ".stp", _StepSettingsFile)
            except Exception as ex:
                nx.print_exception(ex)
        except Exception as ex:
            nx.print_exception(ex)

    # Deletes the log files created.
    for f in exportstrip._get_files(directory):
        if f.lower().endswith(".log"):
            os.remove(f)

    files_to_zip = exportstrip._get_files(directory)
    zip_file_name = "{}-Simulation-Package-for-Design-{}.7z".format(customer_number, exportstrip._todays_date())
    zip_file = "{}\\{}".format(directory, zip_file_name)
    process_directory = package.folder.DirProcessSimDataDesign

    try:
        _seven_zip(zip_file, files_to_zip)

        for f in files_to_zip:
            os.remove(f)

        if copy:
            os.makedirs(process_directory, exist_ok=True)

            dest_dir = "{}\\{}".format(process_directory, os.path.basename(directory))
            os.makedirs(dest_dir, exist_ok=True)

            # Overwrite, as the zip copy below does: a re-export with the same name replaces it.
            for f in exportstrip._get_files(directory):
                shutil.copyfile(f, "{}\\{}".format(dest_dir, os.path.basename(f)))
    except Exception as ex:
        nx.print_exception(ex)

    try:
        if copy:
            os.makedirs(process_directory, exist_ok=True)

            target = "{}\\{}".format(process_directory, zip_file_name)

            if os.path.isfile(target):
                os.remove(target)

            shutil.copyfile(zip_file, target)
    except Exception as ex:
        nx.print_exception(ex)


def _seven_zip(path: str, file_names: List[str]) -> None:
    """AssemblyExportDesignDataExport1.SevenZip(path, wait: true, fileNames) - the list goes to a zipData.txt
    beside the archive (deleted afterwards), 7-Zip is waited on and the result printed."""
    list_file = os.path.join(os.path.dirname(path), "zipData.txt")

    try:
        # StreamWriter: UTF-8 without a BOM, WriteLine = CRLF.
        with open(list_file, "w", encoding="utf-8", newline="\r\n") as writer:
            for f in file_names:
                writer.write(f + "\n")

        if not path:
            raise ValueError("Invalid path.\r\nParameter name: path")

        if os.path.isfile(path):
            raise IOError("The specified output_path already exists.")

        # sql
        # UseShellExecute, normal window. CreateProcess appends ".exe" to the extension-less 7z.
        subprocess.Popen('"{}" a -t7z "{}" "@{}" -mx9'.format(_SevenZip, path, list_file)).wait()

        nx.print_("Successfully created \"{}\".".format(path)
                  if os.path.isfile(path)
                  else "Unsuccessfully created \"{}\".".format(path))
    finally:
        if os.path.isfile(list_file):
            os.remove(list_file)


def _yes_no(title: str, message: str) -> bool:
    """The C#'s WinForms MessageBox.Show(..., YesNo) - a logged NX Question box here."""
    return nx.message_box(title, NXOpen.NXMessageBox.DialogType.Question, message) == nx.MessageBoxYes


def _ucf_single_value(file_path: str, key: str) -> str:
    """new Ucf(file_path).SingleValue(key) - the one line between ":KEY:" and ":END:", ignoring blank lines and
    "//" comments. The <rec>...</rec> substitution is not ported (the sim control file has none)."""
    with open(file_path, "r", encoding="utf-8-sig", errors="replace") as reader:
        lines = [line for line in reader.read().splitlines() if line.strip() and not line.startswith("//")]

    values: Dict[str, List[str]] = {}
    index = 0
    while index < len(lines):
        start_line = lines[index]
        if start_line.startswith(":") and start_line.endswith(":") and len(start_line) > 1:
            content: List[str] = []
            for end_index in range(index + 1, len(lines)):
                if lines[end_index] == ":END:":
                    index = end_index
                    break
                content.append(lines[end_index])
            values[start_line[1:-1]] = content
        index += 1

    if key not in values:
        raise ValueError("Dictionary doesn't contain key: {}.".format(key))
    if len(values[key]) != 1:
        raise ValueError("Dictionary[{}] contains more than one element.".format(key))
    return values[key][0]


def _dotnet_regex(pattern: str) -> str:
    """A .NET pattern's named groups, (?<name>...), as Python's (?P<name>...) - lookbehinds are left alone."""
    return re.sub(r"\(\?<(?![=!])", "(?P<", pattern)


# ---------------------------------------------------------------------------------------------------
# The export-sim-package UFunc: a modal dialog (ExportSimPackage.dlx) in place of the WinForms form
# ---------------------------------------------------------------------------------------------------

class _ExportSimPackageDialog(Dialog):
    """The form's File Type radio pair, Copy to check box and the Select button's component pick. OK is greyed out
    until a component is picked; the C# returned without exporting on an empty pick."""

    dlx_name = "ExportSimPackage.dlx"

    def __init__(self, title: str) -> None:
        self.title = title
        super().__init__()
        # Captured in ok(): the blocks are gone once Launch returns.
        self.is_prt = True
        self.copy = False
        self.components: List[NXOpen.Assemblies.Component] = []

    def initialize(self) -> None:
        self.component_filter(self.block("components"))

    def shown(self) -> None:
        # Every run opens with no copy, not the last run's value. File Type opens on the .dlx's .prt.
        self.block("copy").Value = False

    def enable_ok(self) -> bool:
        return len(self.selected(self.block("components"))) > 0

    def ok(self) -> bool:
        self.is_prt = self.block("file_type").ValueAsString == ".prt"
        self.copy = bool(self.block("copy").Value)
        self.components = components_of(self.selected(self.block("components")))

        if not self.components:
            self.message("Select the components to export.")
            return False

        return True


def _run() -> None:
    """ExportSimPackage.BtnSelect_Click (the deleted form): the checks, the dialog, then the export."""
    title = "Export Sim Package"

    package = _package_or_none()
    if package is None:
        return

    try:
        dialog = _ExportSimPackageDialog(title_with_version(title))
        accepted = dialog.run()
    except NXOpen.NXException as ex:
        if ex.ErrorCode != _ErrorCannotLaunchDialog:
            raise
        nx.print_exception(ex)
        nx.show_error("NX would not open the {} dialog (error {} - it will not create a dialog from inside a "
                      "callback).\n\nTry running it from File -> Execute -> NX Open rather than from a menu or "
                      "toolbar button.".format(title, _ErrorCannotLaunchDialog))
        return

    if not accepted:
        nx.print_("{} dialog was not accepted - nothing exported.".format(title))
        return

    _export(package, dialog.components, dialog.is_prt, not dialog.is_prt, dialog.copy)


def main() -> None:
    """The export-sim-package UFunc - its menu button runs this file. An escaping exception is printed."""
    import usage_db

    with usage_db.run(ufunc_export_sim_package):
        try:
            _run()
        except Exception as ex:
            nx.print_exception(ex)


if __name__ == "__main__":
    main()

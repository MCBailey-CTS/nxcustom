"""
Python port of the assembly-export-design-data UFunc's work (src\\Static\\AssemblyExportDesignData.cs): the Design
tab's RTO / Change / Review / Other export and the Data tab's Select Components / Select All export, i.e.
Static.AssemblyExportDesignDataManualExport, Static.AssemblyExportDesignDataExportDesign and the whole
AssemblyExportDesignDataExport1.Design pipeline (4-VIEW PDFs / DWGs, detail / assembly / see-3D / 999 STEPs,
burnout DWGs, casting parasolids, nitro plates, printing, the zipped assembly, the stocklist and sim report).

WIRED: the AssemblyExportDesignData form (src\\UFuncs\\AssemblyExportDesignData.cs) stays C#. Its ManualExport and
Export_Design call AssemblyExportDesignData.manual_export / export_design through RunPython. The component pick
(Selection.SelectManyComponents, used by Select Components and by the Change radio) stays in the form, which passes
the picked components as a TaggedObject[] - or "" when nothing was picked, where this module takes the display
part's descendants itself, as the C# did. The C# it replaced sits commented out in src\\Static\\AssemblyExportDesignData.cs;
AssemblyExportDesignDataExport1.Stp and both SevenZip overloads stay live there, because ExportSimPackage and
CleanJobDirectory still call them. Run it standalone with File -> Execute -> NX Open on this file: main() runs the
Design tab's defaults (50% Review, its default folder name, no printing). This module has NEVER BEEN RUN IN NX.

Ported from (Static.AssemblyExportDesignDataExport1 unless noted):
  - Static.AssemblyExportDesignDataManualExport  -> AssemblyExportDesignData.manual_export / _manual_export
  - Static.AssemblyExportDesignDataExportDesign  -> AssemblyExportDesignData.export_design / _export_design
  - Design                                        -> _design
  - DeleteOpFolders                               -> _delete_op_folders
  - WriteStpCyanFiles                             -> _write_stp_cyan_files
  - CreateDirectoriesDeleteFiles                  -> _create_directories_delete_files
  - NitroPlatesDirectory / ExportNitroPlates      -> _nitro_plates_directory / _export_nitro_plates
  - CreatePath                                    -> _create_path
  - SetLayers / Layers                            -> design_exports.set_layers / .Layers
  - CreateCasting                                 -> _create_casting
  - SetLayersInBlanksAndLayoutsAndAddDummies      -> _set_layers_in_blanks_and_layouts_and_add_dummies
  - AddDummy                                      -> ExportStrip._add_dummy (the same C#, already ported)
  - CheckAssemblyDummyFiles                       -> _check_assembly_dummy_files
  - ZipupDataDirectories                          -> _zipup_data_directories
  - GetReports                                    -> _get_reports
  - SortPartsForExport                            -> _sort_parts_for_export
  - UpdateParts(isRto, ... flags/sets ...)        -> _parts_to_update (then _update_parts_list, or the export workers)
  - UpdateParts(params Part[])                    -> _update_parts_list / design_exports.update_part
  - ZipupDirectories                              -> _zipup_directories
  - MoveSimReport                                 -> _move_sim_report
  - LaunchProcesses                               -> _launch_processes
  - SetUpStrip                                    -> _set_up_strip
  - Assembly / GetAssembly                        -> _assembly / _get_assembly
  - PrintPdfs                                     -> _print_pdfs
  - ErrorCheck                                    -> _error_check
  - ZipUpDataFolders                              -> _zip_up_data_folders
  - Print4Views                                   -> _print_4_views
  - MoveStocklist                                 -> _move_stocklist
  - Create7ZipProcess                             -> _create_7zip_process (a _Process7Zip)
  - Pdf / Stp / Dwg                               -> _pdf / _stp / _dwg
  - UnblankAssembly.execute (src\\UFuncs\\UnblankAssembly.cs), which Design runs -> _unblank_assembly
  - Globals.cs: BasePart.__IsCasting (+ Ucf.StaticRead), __IsSee3DData, __Is999, string.__IsPartDetail,
    __DescendantParts, Component.__AssemblyPathString -> private helpers below

Reused from other modules: ExportStrip._GFolder (extended with DirDesignInformation, DirStocklist, CtsNumber,
is_cts_job, dir_op and file_strip for this module), ExportStrip._add_dummy / _save / _yes_no / _get_files /
_todays_date / _assembly_path_string / _root, CopyAttributes._is_assembly_holder (string.__IsAssemblyHolder),
CreateBurnout._has_drawing_sheet (BasePart.__HasDrawingSheet) and NewCompBuild._ask_detail_op (string.__AskDetailOp).

Not ported: _printerCts (unused), and SevenZip(path, wait, params string[]) / SevenZip(path, wait, textFile) -
Design never calls them (CleanJobDirectory.py has its own port, and the C# stays live for ExportSimPackage /
CleanJobDirectory).

Preserved from the C#, deliberately (each also noted where it happens):
  - Design's `dict` (file -> Process) is never populated, so expected_files is always empty: WriteStpCyanFiles,
    CreateDirectoriesDeleteFiles and the "Recreating" loop never do anything, and ZipUpDataFolders /
    ZipupDirectories run over no directories (ZipupDirectories still runs "7z d <zip> -r" with no names).
    ErrorCheck is the exception since 2026-10-23: it checks every file the run queued plus the casting files.
  - The `parasolid` flag (the Data tab's Parasolids box) is accepted and never read.
  - The Data tab's 4-View .dwg export writes each DWG to a path ending ".pdf" under "-Dwg-4-Views"; and since Dwg's
    log clean-up is output_path.replace(".dwg", ".log"), on a ".pdf" path that is the output itself, so the
    finished file is deleted again right after its export.
  - SetUpStrip opens the op-010 strip but does not display it: the blank/layout layers and the dummy-file check
    run against the current display part (the top-level 000).
  - CreateCasting returns before its close-and-reopen when the part has no layer-1 body.
  - CheckAssemblyDummyFiles keeps checking the remaining presses after a good one (ExportStrip's copy stops).

Differences from the C#:
  - The two entry points catch, print (print_exception) and return, so the listing window shows the Python
    traceback; the form's own catch then only sees failures to start the script, and the form still prints
    "Complete" in its finally.
  - The selection happens in the form (README rule); manual_export / export_design receive the picks.
  - System.Diagnostics.Process becomes subprocess.Popen: _Process7Zip wraps Create7ZipProcess's unstarted Process
    (Start / HasExited / WaitForExit = Popen / poll / wait). "C:\\Program Files\\7-Zip\\7z" has no .exe, which
    CreateProcess appends, as ShellExecute did. The temp list file name uses id() of the file list where the C# used
    the array's GetHashCode() (as ExportStrip.py does).
  - The WinForms "already exisits, would you like to overwrite it?" Yes/No MessageBox is an NX Question box
    (ExportStrip._yes_no); anything but Yes counts as No.
  - Directory.GetFiles(dir, "*.stp") / "*.7z" are case-insensitive suffix matches, without the Win32 3-character
    extension quirk (".stp" no longer also matches ".stpx").
  - print(DateTime.Now - then) is formatted like .NET's TimeSpan ([d.]hh:mm:ss[.fffffff]); "Stp - {part}" prints
    Python's str() of the NXOpen.Part, which may not read like .NET's ToString().
  - File.Delete / File.Copy / Directory.Delete are os.remove / shutil.copy2 / shutil.rmtree, with File.Copy's
    "already exists" raised explicitly.
"""

from __future__ import annotations

import datetime
import ntpath
import os
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Set, Tuple

# Session.Execute does not put the script's folder on sys.path, so the shared module would not import.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

import NXOpen  # noqa: E402
import NXOpen.Assemblies  # noqa: E402
import NXOpen.Drawings  # noqa: E402
import NXOpen.Layer  # noqa: E402
import NXOpen.UF  # noqa: E402

import tsg_nx as nx  # noqa: E402
import design_exports  # noqa: E402
from design_exports import Job  # noqa: E402
from export_pool import ExportPool  # noqa: E402
import ExportStrip as exportstrip  # noqa: E402
from CopyAttributes import _is_assembly_holder  # noqa: E402
from CreateBurnout import _has_drawing_sheet  # noqa: E402
from NewCompBuild import _ask_detail_op  # noqa: E402

_GFolder = exportstrip._GFolder
_root = exportstrip._root

# Globals.cs regexes (.NET named groups (?<x>) are (?P<x>) in Python).
_RegexDetail = r"^(?P<customerNum>\d+)-(?P<opNum>\d+)-(?P<detailNum>\d+)$"
_RegexOp000Holder = r"^(?P<customerNum>\d+)-(?P<opNum>\d+)-000$"
_RegexLwr = r"^(?P<customerNum>\d+)-(?P<opNum>\d+)-lwr$"
_RegexStrip = r"^(?P<customerNum>\d+)-(?P<opNum>\d+)-strip$"
_RegexLayout = r"^(?P<customerNum>\d+)-(?P<opNum>\d+)-layout$"
_RegexBlank = r"^(?P<customerNum>\d+)-(?P<opNum>\d+)-blank$"
_RegexPressAssembly = r"^(?P<customerNum>\d+)-Press-(?P<opNum>\d+)-Assembly$"
_DetailNumberRegex = r"^(?P<jobNum>\d+)-(?P<opNum>\d+)-(?P<detailNum>\d+)$"

# Globals.cs paths.
_FilePathExternalStepAssemblyDef = "U:\\nxFiles\\Step Translator\\ExternalStep_Assembly.def"
# Put in front of every op data folder name ({prefix}{job}-{op}-Step-Details, ...), so a test RTO on a real job
# writes beside the real data instead of over it. The delete step only matches folders that carry it. Empty in
# normal use (2026-10-25).
_DataPrefix = os.environ.get("TSG_EXPORT_DATA_PREFIX", "")
_FilePathExternalStepDetailDef = "U:\\nxFiles\\Step Translator\\ExternalStep_Detail.def"
_DummyPath = "G:\\0Library\\SeedFiles\\Components\\Dummy.prt"
_ConceptControlFile = "U:\\nxFiles\\UfuncFiles\\ConceptControlFile.ucf"

# sql
# The per-file exporters live in design_exports (2026-10-23) so the headless export workers can run them.

# Design's File.Exists check; Create7ZipProcess / SevenZip use the name without ".exe".
_SevenZipExe = "C:\\Program Files\\7-Zip\\7z.exe"
_SevenZip = "C:\\Program Files\\7-Zip\\7z"

_Printer = "\\\\ctsfps1.cts.toolingsystemsgroup.com\\CTS Office MFC"

# Export dictionary keys (SortPartsForExport).
_PDF_4_VIEW = "PDF_4-VIEW"
_STP_DETAIL = "STP_DETAIL"
_DWG_BURNOUT = "DWG_BURNOUT"
_STP_999 = "STP_999"
_STP_SEE3D = "STP_SEE3D"
_X_T_CASTING = "X_T_CASTING"

# HashSet<Part>, keyed by tag, insertion-ordered.
_PartSet = Dict[object, NXOpen.Part]


class AssemblyExportDesignData(object):

    @staticmethod
    def manual_export(select_all: bool, components: object, pdf4_views: bool, dwg4_views: bool, stp_details: bool,
                      stp_see3d_data: bool, dwg_burnout: bool, parasolid: bool, para_casting: bool,
                      print4_views: bool, is_change: bool, nitro_plates: bool) -> None:
        """Static.AssemblyExportDesignDataManualExport - the Data tab's Select Components (select_all False) and
        Select All (True). components is the form's pick (a sequence of Components) for Select Components, ""
        for Select All. The flags are chk4ViewPDF, chk4ViewDwg, chkDetailStep, chkSee3DData, chkBurnout,
        chkParasolids, chkCastings, chkPrintData, rdoChange and chkNitroPlates. Prints any exception."""
        try:
            _manual_export(select_all, _as_components(components), pdf4_views, dwg4_views, stp_details,
                           stp_see3d_data, dwg_burnout, parasolid, para_casting, print4_views, is_change,
                           nitro_plates)
        except Exception as ex:
            nx.print_exception(ex)

    @staticmethod
    def export_design(rto: bool, change: bool, review50: bool, review90: bool, review100: bool, other: bool,
                      folder_name: str, print_design: bool, components: object, skip_unchanged: bool = False) -> None:
        """Static.AssemblyExportDesignDataExportDesign - the Design tab's Execute / Select. The flags are the
        rdoRto / rdoChange / rdoReview50 / rdoReview90 / rdoReview100 / rdoOther radios, folder_name txtFolderName
        and print_design chkPrintDesign. components is the form's pick for Change (a sequence of Components), ""
        otherwise. skip_unchanged is chkSkipUnchanged (Full Design only, see _design). Prints any exception."""
        try:
            _export_design(rto, change, review50, review90, review100, other, folder_name, print_design,
                           _as_components(components), rto and skip_unchanged)
        except Exception as ex:
            nx.print_exception(ex)

    @staticmethod
    def default_folder_name() -> str:
        """The folder name the form shows on load: ResetForm checks rdoReview50, whose CheckedChanged sets
        txtFolderName to "{TodaysDate}-----{display leaf}-----50% Review"."""
        return "{}-----{}-----50% Review".format(exportstrip._todays_date(), nx.display_part().Leaf)


def _as_components(components: object) -> List[NXOpen.Assemblies.Component]:
    """Session.Execute cannot pass null: "" (or anything empty) means no pick."""
    if not components or isinstance(components, str):
        return []
    return list(components)  # type: ignore[call-overload]


def _confirm_unloaded_components(disp: NXOpen.Part) -> bool:
    """RTO collects its parts with nx.descendants, which skips unloaded components and everything under them, so
    an unloaded subassembly would quietly get no update and no exports (2026-10-25). Lists the unloaded,
    unsuppressed components (the top-most of each unloaded branch) and asks whether to go on. True when there are
    none or the user says Yes."""
    root = disp.ComponentAssembly.RootComponent
    if root is None:
        return True

    unloaded: List[NXOpen.Assemblies.Component] = []

    def walk(component: NXOpen.Assemblies.Component) -> None:
        for child in component.GetChildren():
            if child.IsSuppressed:
                continue
            if not nx.is_loaded(child):
                unloaded.append(child)
                continue
            walk(child)

    walk(root)

    if len(unloaded) == 0:
        return True

    for component in unloaded:
        nx.syslog("AssemblyExportDesignData: unloaded component {}".format(
            exportstrip._assembly_path_string(component)))

    shown = 20
    lines = [exportstrip._assembly_path_string(c) for c in unloaded[:shown]]
    if len(unloaded) > shown:
        lines.append("... and {} more (all of them are in the syslog)".format(len(unloaded) - shown))

    return exportstrip._yes_no(
        "Unloaded Components",
        "{} unsuppressed component(s) are not loaded. They and everything under them will be left out of the RTO "
        "(no update, no exports):\n\n{}\n\nContinue anyway?".format(len(unloaded), "\n".join(lines)))


def _manual_export(select_all: bool, picked: List[NXOpen.Assemblies.Component], pdf4_views: bool,
                   dwg4_views: bool, stp_details: bool, stp_see3d_data: bool, dwg_burnout: bool, parasolid: bool,
                   para_casting: bool, print4_views: bool, is_change: bool, nitro_plates: bool) -> None:
    """Static.AssemblyExportDesignDataManualExport - after the pick, which the form now does."""
    disp = nx.display_part()

    components = list(nx.descendants(_root(disp))) if select_all else picked

    if len(components) == 0:
        return

    components.append(_root(disp))

    _design(
        disp,
        components,
        None,
        False,
        False,
        pdf4_views,
        dwg4_views,
        False,
        stp_details,
        stp_see3d_data,
        dwg_burnout,
        parasolid,
        para_casting,
        print4_views,
        is_change,
        nitro_plates=nitro_plates)


def _export_design(rto: bool, change: bool, review50: bool, review90: bool, review100: bool, other: bool,
                   folder_name: str, print_design: bool, picked: List[NXOpen.Assemblies.Component],
                   skip_unchanged: bool = False) -> None:
    """Static.AssemblyExportDesignDataExportDesign - after the pick, which the form now does for Change."""
    disp = nx.display_part()

    is_rto = False

    if rto:
        is_rto = True
        if not _confirm_unloaded_components(disp):
            nx.mark_cancelled("the unloaded components warning")
            return
        components = list(nx.descendants(_root(disp)))
    elif change:
        is_rto = True
        components = picked
    elif review50 or review90 or review100 or other:
        is_rto = False
        components = list(nx.descendants(_root(disp)))
    else:
        # new ArgumentException()
        raise ValueError("Value does not fall within the expected range.")

    if len(components) == 0:
        return

    _design(
        disp,
        components,
        folder_name,
        is_rto or change,
        True,
        print4_views=is_rto and print_design,
        is_change=change,
        skip_unchanged=skip_unchanged)


# ---------------------------------------------------------------------------------------------------
# Design
# ---------------------------------------------------------------------------------------------------

def _design(top_level_assembly: NXOpen.Part,
            components: Sequence[NXOpen.Assemblies.Component],
            outgoing_directory_name: Optional[str] = None,
            is_rto: bool = False,
            zip_assembly: bool = False,
            pdf4_views: bool = False,
            dwg4_views: bool = False,
            stp999: bool = False,
            stp_details: bool = False,
            stp_see3d_data: bool = False,
            dwg_burnout: bool = False,
            parasolid: bool = False,
            para_casting: bool = False,
            print4_views: bool = False,
            is_change: bool = False,
            nitro_plates: bool = False,
            skip_unchanged: bool = False) -> None:
    """AssemblyExportDesignDataExport1.Design. `parasolid` is never read - preserved from the C#.

    skip_unchanged (Full Design's "Skip unchanged", 2026-10-23): instead of deleting the op data folders and
    rebuilding everything, a part keeps its files - and is neither updated nor exported again - when it had no
    unsaved changes and every file it would export already exists and is no older than its .prt (_unchanged_parts).
    Castings likewise. Files in the op data folders that this run would not write are deleted, so what is left
    matches a full rebuild. Changes that live only in other files (a library fastener edited, a parent's WAVE
    geometry with the detail not updated and saved) are not seen; untick it for a clean rebuild."""
    with nx.display_part_reset():
        nx.prompt("Filtering components to export.")
        folder = _GFolder.create(top_level_assembly.FullPath)

        if not all(comp.OwningPart.Tag == top_level_assembly.Tag for comp in components):
            raise RuntimeError("All valid components must be under the top level display part.")

        is_six_digit = len(folder.CustomerNumber) == 6
        hashed_parts: _PartSet = {}

        for comp in components:
            part = comp.Prototype

            if not isinstance(part, NXOpen.Part):
                continue

            hashed_parts.setdefault(part.Tag, part)

        _unblank_assembly()

        valid_parts = list(hashed_parts.values())

        # sql
        if not os.path.isfile(_SevenZipExe):
            raise FileNotFoundError("Could not find \"{}\".".format(_SevenZipExe))

        parent_folder = folder.DirDesignInformation if is_six_digit else folder.DirOutgoing

        export_directory: Optional[str] = (None if not outgoing_directory_name
                                           else "{}\\{}".format(parent_folder, outgoing_directory_name))

        if not (is_rto and is_six_digit) and zip_assembly and export_directory is not None \
                and os.path.isdir(export_directory):
            if exportstrip._yes_no(
                    "Warning",
                    "{} already exisits, would you like to overwrite it?".format(export_directory)):
                shutil.rmtree(export_directory)
            else:
                return

        if not (is_rto and is_six_digit):
            if outgoing_directory_name:
                os.makedirs(export_directory, exist_ok=True)  # type: ignore[arg-type]

        # If this is an RTO, then we need to delete the data files in the appropriate op folders - or, skipping
        # unchanged parts, only the files this run will not write, once the jobs are known.
        op_data_directories: List[str] = []
        if is_rto and not is_change:
            try:
                op_data_directories = _op_data_directories(nx.display_part(), folder)
                if not skip_unchanged:
                    _delete_directories(op_data_directories)
            except Exception as ex:
                nx.print_exception(ex)

        if export_directory is not None:
            os.makedirs(export_directory, exist_ok=True)

        detail_regex = re.compile(_RegexDetail, re.IGNORECASE)
        valid_parts = nx.distinct_by(valid_parts, lambda p: p.Leaf)

        export_dict = _sort_parts_for_export(valid_parts)

        # Parts with unsaved changes count as changed, whatever their file dates say after this save.
        modified_before_save: Set[str] = {p.FullPath.lower() for p in nx.session_.Parts
                                          if p.IsModified} if skip_unchanged else set()

        exportstrip._save(nx.display_part(), True)

        then = datetime.datetime.now()

        # STEPs run as batched translator processes; any optional NX workers (TSG_EXPORT_WORKERS) start now so
        # their ~15-20 s start-up overlaps the strip set-up and the part updates.
        # Print 4-Views prints from this session's copies, which must be the updated ones: no workers then.
        pool = ExportPool(workers=0) if print4_views else ExportPool()
        pool.start()
        jobs: List[Job] = []

        def queue(kind: str, part_path: str, output: str, label: str, settings: str = "", sheet: str = "") -> None:
            jobs.append({"id": len(jobs) + 1, "kind": kind, "part": part_path, "output": output, "label": label,
                         "settings": settings, "sheet": sheet})

        try:
            assembly_process: Optional[_Process7Zip] = None

            # Sets up the strip. The nitro-plate export is the detail STEP export pointed at a
            # different folder, so it goes through the same setup and update as Details .stp.
            if is_rto or stp_details or nitro_plates or zip_assembly:
                with nx.display_part_reset():
                    _set_up_strip(folder)

            parts_to_update = _parts_to_update(
                is_rto,
                pdf4_views or nitro_plates, dwg4_views, _parts(export_dict, _PDF_4_VIEW),
                stp_details or nitro_plates, _parts(export_dict, _STP_DETAIL),
                print4_views, _parts(export_dict, _PDF_4_VIEW),
                dwg_burnout, _parts(export_dict, _DWG_BURNOUT),
                stp999, _parts(export_dict, _STP_999),
                stp_see3d_data or stp_details, _parts(export_dict, _STP_SEE3D),
                para_casting, _parts(export_dict, _X_T_CASTING),
                components)

            # With workers, each detail is updated and saved by a worker (which then runs its PDF / DWG exports,
            # its STEPs following once it is saved): pool.run below. They open the parts from disk, so anything
            # unsaved in them is saved first. Without workers, they are updated one at a time just before the
            # exports (after Skip unchanged has dropped the unchanged ones), as before.
            updates: List[Dict[str, Any]] = []
            for part in parts_to_update:
                if pool.workers > 0 and part.IsModified:
                    part.Save(NXOpen.BasePart.SaveComponents.FalseValue, NXOpen.BasePart.CloseAfterSave.FalseValue)
                updates.append({"part": part.FullPath, "casting": _is_casting(part)})

            # Never populated - preserved from the C#. Everything keyed off it below is a no-op.
            process_dict: Dict[str, _Process7Zip] = {}

            if is_rto and detail_regex.search(top_level_assembly.Leaf):
                stp_path = _create_path(folder, top_level_assembly, "-Step-Assembly", ".stp")

                directory = ntpath.dirname(stp_path)

                if not os.path.isdir(directory):
                    os.makedirs(directory, exist_ok=True)

                queue("stp", top_level_assembly.FullPath, stp_path, "Step Assembly", _FilePathExternalStepAssemblyDef)

            # Gets the processes that will create the pdf 4-Views.
            if is_rto or pdf4_views:
                parts = _parts(export_dict, _PDF_4_VIEW)

                for i, part in enumerate(parts):
                    nx.prompt("PDF {} of {} -> {}".format(i + 1, len(parts), part.Leaf))

                    try:
                        if part.Leaf.endswith("000"):
                            continue

                        pdf_path = _create_path(folder, part, "-Pdf-4-Views", ".pdf")

                        directory = ntpath.dirname(pdf_path)

                        if not os.path.isdir(directory):
                            os.makedirs(directory, exist_ok=True)

                        queue("pdf", part.FullPath, pdf_path, "PDF 4-VIEW", sheet="4-VIEW")
                    except Exception as ex:
                        nx.print_exception(ex)

            if dwg4_views:
                parts = _parts(export_dict, _PDF_4_VIEW)

                for i, part in enumerate(parts):
                    nx.prompt("DWG {} of {} -> {}".format(i + 1, len(parts), part.Leaf))

                    try:
                        if part.Leaf.endswith("-000"):
                            continue

                        # A DWG written to a ".pdf" path - preserved from the C# (see _dwg).
                        pdf_path = _create_path(folder, part, "-Dwg-4-Views", ".pdf")

                        directory = ntpath.dirname(pdf_path)

                        if not os.path.isdir(directory):
                            os.makedirs(directory, exist_ok=True)

                        queue("dwg", part.FullPath, pdf_path, "DWG 4-VIEW", sheet="4-VIEW")
                    except Exception as ex:
                        nx.print_exception(ex)

            # If this is a RTO then
            if is_rto or stp_details:
                # Every detail, not just the ones with a 4-VIEW sheet.
                parts = _parts(export_dict, _STP_DETAIL)

                for i, part in enumerate(parts):
                    nx.prompt("Step Details {} of {} -> {}".format(i + 1, len(parts), part.Leaf))

                    try:
                        stp_path = _create_path(folder, part, "-Step-Details", ".stp")

                        directory = ntpath.dirname(stp_path)

                        if not os.path.isdir(directory):
                            os.makedirs(directory, exist_ok=True)

                        queue("stp", part.FullPath, stp_path, "Step Details", _FilePathExternalStepDetailDef)
                    except Exception as ex:
                        nx.print_exception(ex)

            # Nitro plates: the same detail STEPs and 4-VIEW PDFs as the two boxes above, but
            # gathered into one folder under the display part's op instead of each detail's.
            if nitro_plates:
                try:
                    _export_nitro_plates(folder, top_level_assembly, _parts(export_dict, _STP_DETAIL),
                                         _parts(export_dict, _PDF_4_VIEW))
                except Exception as ex:
                    nx.print_exception(ex)

            if zip_assembly and not (is_rto or stp_details):
                nx.prompt("Step Assembly -> {}".format(top_level_assembly.Leaf))

                try:
                    path = "{}\\{}.stp".format(export_directory or "", top_level_assembly.Leaf)

                    directory = ntpath.dirname(path)

                    if not os.path.isdir(directory):
                        os.makedirs(directory, exist_ok=True)

                    queue("stp", top_level_assembly.FullPath, path, "Stp", _FilePathExternalStepDetailDef)
                except Exception as ex:
                    nx.print_exception(ex)

            # Gets the processes that create stp see 3d data. A detail whose DESCRIPTION
            # reads "SEE 3D DATA" (any of -, _ or space between the words) gets its see-3d
            # .stp whenever the details are exported, whether or not the box is checked -
            # the description is the part saying it needs one.
            if is_rto or stp_see3d_data or stp_details:
                parts = _parts(export_dict, _STP_SEE3D)

                for i, part in enumerate(parts):
                    nx.prompt("STEP See 3d {} of {} -> {}".format(i + 1, len(parts), part.Leaf))

                    try:
                        output = _create_path(folder, part, "-Step-See-3D-Data", ".stp")

                        directory = ntpath.dirname(output)

                        if not os.path.isdir(directory):
                            os.makedirs(directory, exist_ok=True)

                        queue("stp", part.FullPath, output, "STEP See 3d", _FilePathExternalStepDetailDef)
                    except Exception as ex:
                        nx.print_exception(ex)

            # Gets the processes that create stp 999 details.
            if is_rto or stp999:
                parts = _parts(export_dict, _STP_999)

                for i, part in enumerate(parts):
                    nx.prompt("999 {} of {} -> {}".format(i + 1, len(parts), part.Leaf))

                    try:
                        output = _create_path(folder, part, "-Step-999", ".stp")

                        directory = ntpath.dirname(output)

                        if not os.path.isdir(directory):
                            os.makedirs(directory, exist_ok=True)

                        queue("stp", part.FullPath, output, "999", "U:\\nxFiles\\Step Translator\\ExternalStep_Detail.def")
                    except Exception as ex:
                        nx.print_exception(ex)

            # Gets the processes that create burnout dwgs.
            if is_rto or dwg_burnout:
                parts = _parts(export_dict, _DWG_BURNOUT)

                for i, part in enumerate(parts):
                    nx.prompt("BURNOUT {} of {} -> {}".format(i + 1, len(parts), part.Leaf))

                    try:
                        output = _create_path(folder, part, "-Dwg-Burnouts", ".dwg")

                        directory = ntpath.dirname(output)

                        if not os.path.isdir(directory):
                            os.makedirs(directory, exist_ok=True)

                        queue("dwg", part.FullPath, output, "BURNOUT", sheet="BURNOUT")
                    except Exception as ex:
                        nx.print_exception(ex)

            unchanged: Set[str] = set()
            casting_parts = _parts(export_dict, _X_T_CASTING) if is_rto or para_casting else []
            # What ErrorCheck checks for at the end: every queued file and each casting's .stp / .x_t, including
            # the ones Skip unchanged keeps (they must still be there).
            files_to_check: List[str] = list(dict.fromkeys(
                [j["output"] for j in jobs] + [f for p in casting_parts for f in _casting_outputs(p, folder)]))
            if skip_unchanged:
                # The top level's own files (the assembly STEP) depend on every child: always rebuilt.
                unchanged = _unchanged_parts(jobs, modified_before_save, {top_level_assembly.FullPath.lower()})
                skipped_castings = [p for p in casting_parts if p.FullPath.lower() not in modified_before_save
                                    and all(_is_up_to_date(f, p.FullPath) for f in _casting_outputs(p, folder))]
                keep = {j["output"].lower() for j in jobs}
                keep.update(f.lower() for p in casting_parts for f in _casting_outputs(p, folder))
                deleted = _delete_files_except(op_data_directories, keep)
                skipped_jobs = [j for j in jobs if j["part"].lower() in unchanged]
                jobs = [j for j in jobs if j["part"].lower() not in unchanged]
                # An update saves the part, which would make it look changed next time: none for an unchanged
                # part, nor for a part whose only export is a casting that is up to date.
                with_jobs = {j["part"].lower() for j in jobs}
                skipped_casting_paths = {p.FullPath.lower() for p in skipped_castings}
                updates = [u for u in updates if u["part"].lower() not in unchanged
                           and (u["part"].lower() in with_jobs or u["part"].lower() not in skipped_casting_paths)]
                casting_parts = [p for p in casting_parts if p not in skipped_castings]
                nx.print_("Skip unchanged: {} part(s) unchanged - kept {} file(s) and {} casting(s); deleted {} "
                          "file(s) this run would not write.".format(len(unchanged), len(skipped_jobs),
                                                                     len(skipped_castings), deleted))

            if pool.workers <= 0:
                to_update = {u["part"].lower() for u in updates}
                serial = [p for p in parts_to_update if p.FullPath.lower() in to_update]
                if len(serial) > 0:
                    _update_parts_list(serial)
                updates = []

            # Prints the parts with 4-Views (after their update, as before).
            if print4_views:
                with nx.display_part_reset():
                    _print_pdfs(_parts(export_dict, _PDF_4_VIEW))

            # Existing files are replaced (an unchanged part's jobs are gone by now).
            for job in jobs:
                if os.path.isfile(job["output"]):
                    try:
                        os.remove(job["output"])
                    except OSError as ex:
                        nx.print_exception(ex)

            # Runs the detail updates (with workers) and every queued STEP / PDF / DWG export, several at a time.
            nx.prompt("Updating {} part(s) and exporting {} file(s).".format(len(updates), len(jobs)))
            with nx.display_part_reset():
                pool.run(jobs, updates)
            pool.close()

            # Creates casting parasolids.
            if is_rto or para_casting:
                for i, casting_part in enumerate(casting_parts):
                    nx.prompt("Casting {} of {} -> {}".format(i + 1, len(casting_parts), casting_part.Leaf))

                    try:
                        nx.print_("CreateCasting - {}".format(casting_part.FullPath))
                        _create_casting(casting_part, folder)
                    except Exception as ex:
                        nx.print_exception(ex)

            expected_files: List[str] = list(dict.fromkeys(process_dict.keys()))

            directories_to_export: List[str] = list(dict.fromkeys(ntpath.dirname(f) for f in expected_files))

            _create_directories_delete_files(expected_files)

            zip_path = "{}\\{}_NX.7z".format(export_directory or "", top_level_assembly.Leaf)

            if (is_rto and not is_six_digit) or (zip_assembly and not is_rto):
                nx.print_("Assembly")
                assembly_process = _assembly(top_level_assembly, False, zip_path)
                assembly_process.start()

            nx.prompt("Validating Stp Files.")

            _write_stp_cyan_files(expected_files)

            nx.prompt("Zipping up data folders.")

            # Gets all the data folders that were created and zips them up and places them in the proper
            # outgoingData folderWithCtsNumber if this is an RTO.
            if is_rto and not is_six_digit:
                _zip_up_data_folders(directories_to_export, export_directory)

            if is_rto and not is_six_digit:
                nx.print_("ZipupDirectories")
                _zipup_directories(_SevenZipExe, directories_to_export, zip_path)

            for file_key in process_dict.keys():
                try:
                    process = process_dict[file_key]

                    if os.path.isfile(file_key):
                        continue

                    nx.print_("Recreating: {}".format(file_key))
                    nx.prompt("Recreating: {}".format(file_key))

                    process.start()

                    process.wait_for_exit()
                except Exception as ex:
                    nx.print_exception(ex)

            # Checks to make sure that the expected data files were actually created. It used to check
            # expected_files - the never-populated dict, so never anything; now every file this run queued.
            if len(files_to_check) > 0:
                nx.print_("ErrorCheck")
                _error_check(is_rto, zip_assembly, files_to_check)

            # Moves the sim report to the out going folderWithCtsNumber if one exists.
            if is_rto and not is_six_digit and export_directory is not None:
                nx.print_("MoveSimReport")
                _move_sim_report(folder, export_directory)

            # Moves the stock list to the outgoing folderWithCtsNumber if one exists.
            if is_rto and not is_six_digit and export_directory is not None:
                nx.print_("MoveStocklist")
                _move_stocklist(folder, top_level_assembly.Leaf, export_directory)

            if export_directory is not None:
                nx.print_("ZipupDataDirectories")
                _zipup_data_directories(export_directory, assembly_process)
        finally:
            pool.close()
            nx.print_(_cs_timespan(datetime.datetime.now() - then))


def _parts(export_dict: Dict[str, _PartSet], key: str) -> List[NXOpen.Part]:
    """exportDict[key].ToArray()"""
    return list(export_dict[key].values())


# ---------------------------------------------------------------------------------------------------
# Folders and paths
# ---------------------------------------------------------------------------------------------------

def _delete_op_folders(part: NXOpen.Part, folder: Optional[_GFolder]) -> None:
    """AssemblyExportDesignDataExport1.DeleteOpFolders"""
    _delete_directories(_op_data_directories(part, folder))


def _delete_directories(directories: Iterable[str]) -> None:
    for directory in directories:
        if os.path.isdir(directory):
            shutil.rmtree(directory)


def _op_data_directories(part: NXOpen.Part, folder: Optional[_GFolder]) -> List[str]:
    """The data folders DeleteOpFolders deletes for the 000 `part` (raises for anything else, as it did)."""
    if folder is None:
        raise ValueError("Value does not fall within the expected range.")

    # Matches the {part.Leaf} to 000 regex.
    top_match = re.search(_RegexOp000Holder, part.Leaf, re.IGNORECASE)

    # If the {match} is not a success, then {part} is not a "000".
    if not top_match:
        raise Exception("Part \"{}\" is not a 000.".format(part.FullPath))

    # Gets the op of the {part}.
    op = top_match.group("opNum")

    # The set that holds the data directories to delete.
    directories_to_delete: Dict[str, None] = {}

    if op == "900":
        # Matches the 900 000's.
        directories_to_delete["{}\\{}{}-900-Step-Assembly".format(folder.dir_op("900"), _DataPrefix,
                                                                folder.CustomerNumber)] = None

        for component in nx.children(part):
            # RegexLwr without IgnoreCase - preserved from the C#.
            match = re.search(_RegexLwr, component.DisplayName)

            if not match:
                continue

            assembly_op = match.group("opNum")

            if len(assembly_op) % 2 != 0:
                continue

            for i in range(0, len(assembly_op) - 1, 2):
                temp_op = assembly_op[i] + assembly_op[i + 1] + "0"

                directory = folder.dir_op(temp_op)

                for tag in ("-Parasolids-Castings", "-Pdf-4-Views", "-Step-Details", "-Step-Assembly",
                            "-Dwg-Burnouts", "-Step-See-3D-Data"):
                    directories_to_delete["{}\\{}{}-{}{}".format(directory, _DataPrefix, folder.CustomerNumber,
                                                                temp_op, tag)] = None

    elif len(op) == 3:
        # This matches all the regular op 010, 020, 030 and so 000's.
        # Gets the assembly folderWithCtsNumber correpsonding to the {assemblyOp000}.
        assembly_folder = folder.dir_op(op)

        # If the directory {assemblyFolder} doesn't exist, then we want to throw.
        if not os.path.isdir(assembly_folder):
            raise FileNotFoundError("Could not find directory \"{}\".".format(assembly_folder))

        for directory in _get_directories(assembly_folder):
            dir_name = ntpath.basename(directory)

            if not dir_name.startswith("{}{}-{}".format(_DataPrefix, folder.CustomerNumber, op)):
                continue

            # Adds the {directory} to the {directoriesToDelete}.
            directories_to_delete[directory] = None

    elif len(op) % 2 == 0:
        # Matches the assembly holder by ensuring that the op has an even amount of characters.
        # Grab the op characters two at a time.
        op_list = [op[i] + op[i + 1] + "0" for i in range(0, len(op), 2)]

        for assembly_op in op_list:
            # Gets the assembly folderWithCtsNumber correpsonding to the {assemblyOp000}.
            assembly_folder = folder.dir_op(assembly_op)

            # If the directory {assemblyFolder} doesn't exist, then we want to throw.
            if not os.path.isdir(assembly_folder):
                raise FileNotFoundError("Could not find directory \"{}\".".format(assembly_folder))

            for directory in _get_directories(assembly_folder):
                dir_name = ntpath.basename(directory)

                if not dir_name.startswith("{}{}-{}".format(_DataPrefix, folder.CustomerNumber, assembly_op)):
                    continue

                # Adds the {directory} to the {directoriesToDelete}.
                directories_to_delete[directory] = None

    return list(directories_to_delete)


def _casting_outputs(part: NXOpen.Part, folder: _GFolder) -> List[str]:
    """The .stp and .x_t _create_casting writes for `part`."""
    op = _ask_detail_op(part.Leaf)
    directory = "{}\\{}-{}\\{}{}-{}-Parasolids-Castings".format(folder.DirJob, folder.CustomerNumber, op,
                                                                _DataPrefix, folder.CustomerNumber, op)
    return ["{}\\{}{}".format(directory, part.Leaf, ext) for ext in (".stp", ".x_t")]


def _is_up_to_date(output: str, part_path: str) -> bool:
    """Whether `output` exists, is not empty and is no older than the part file."""
    try:
        return os.path.getsize(output) > 0 and os.path.getmtime(output) >= os.path.getmtime(part_path)
    except OSError:
        return False


def _unchanged_parts(jobs: Sequence[Job], modified: Set[str], never: Set[str]) -> Set[str]:
    """Skip unchanged: the part paths (lower case) whose every job's output is up to date with the part file and
    that had no unsaved changes before Design's save. A part in `never` is always rebuilt."""
    by_part: Dict[str, List[Job]] = {}
    for job in jobs:
        by_part.setdefault(job["part"].lower(), []).append(job)

    return {key for key, part_jobs in by_part.items()
            if key not in modified and key not in never
            and all(_is_up_to_date(j["output"], j["part"]) for j in part_jobs)}


def _delete_files_except(directories: Iterable[str], keep: Set[str]) -> int:
    """Skip unchanged's stand-in for DeleteOpFolders: deletes every file under `directories` whose lower-case path
    is not in `keep` (a detail that left the assembly, a dropped export), then any folder left empty. Returns how
    many files it deleted."""
    deleted = 0
    for directory in directories:
        if not os.path.isdir(directory):
            continue
        for root, _dirs, files in os.walk(directory, topdown=False):
            for name in files:
                path = os.path.join(root, name)
                if path.lower() in keep:
                    continue
                try:
                    os.remove(path)
                    deleted += 1
                except OSError as ex:
                    nx.print_exception(ex)
            if root != directory and not os.listdir(root):
                os.rmdir(root)
    return deleted


def _write_stp_cyan_files(expected_files: Iterable[str]) -> None:
    """AssemblyExportDesignDataExport1.WriteStpCyanFiles - never reached with any file (the empty dict),
    preserved from the C#."""
    for expected in expected_files:
        if not expected.endswith(".stp") or not os.path.isfile(expected):
            continue

        # File.ReadAllText / WriteAllText: BOM-detected read, UTF-8 (no BOM) write, line endings untouched.
        with open(expected, "r", encoding="utf-8-sig", errors="replace", newline="") as reader:
            file_text = reader.read()

        if "Cyan" not in file_text:
            continue

        with open(expected, "w", encoding="utf-8", newline="") as writer:
            writer.write(file_text.replace("Cyan", "cyan"))


def _create_directories_delete_files(expected_files: Iterable[str]) -> None:
    """AssemblyExportDesignDataExport1.CreateDirectoriesDeleteFiles - never reached with any file (the empty
    dict), preserved from the C#."""
    for file in expected_files:
        try:
            directory = ntpath.dirname(file)
            if not directory:
                raise Exception("Exception of type 'System.Exception' was thrown.")
            os.makedirs(directory, exist_ok=True)
            _file_delete(file)
        except Exception as ex:
            nx.print_exception(ex)


def _nitro_plates_directory(folder: _GFolder, top_level_assembly: NXOpen.Part) -> str:
    """AssemblyExportDesignDataExport1.NitroPlatesDirectory - {job}\\{job}-{op}\\{job}-{op}-Nitro-Plates, off the
    display part's op."""
    op = _ask_detail_op(top_level_assembly.Leaf)

    return "{}\\{}{}-{}-Nitro-Plates".format(folder.dir_op(op), _DataPrefix, folder.CustomerNumber, op)


def _export_nitro_plates(folder: _GFolder, top_level_assembly: NXOpen.Part, step_parts: Sequence[NXOpen.Part],
                         pdf_parts: Sequence[NXOpen.Part]) -> None:
    """AssemblyExportDesignDataExport1.ExportNitroPlates - a detail STEP per step part and a 4-VIEW PDF per pdf
    part, into _nitro_plates_directory. Per-part try/except."""
    directory = _nitro_plates_directory(folder, top_level_assembly)

    if not os.path.isdir(directory):
        os.makedirs(directory, exist_ok=True)

    nx.print_("Nitro Plates -> {}".format(directory))

    parts = list(step_parts)

    for i, part in enumerate(parts):
        nx.prompt("Nitro Plates Step {} of {} -> {}".format(i + 1, len(parts), part.Leaf))

        try:
            stp_path = "{}\\{}.stp".format(directory, part.Leaf)

            if os.path.isfile(stp_path):
                os.remove(stp_path)

            nx.print_("Nitro Plates Step -> {}".format(stp_path))
            _stp(part.FullPath, stp_path, _FilePathExternalStepDetailDef)
        except Exception as ex:
            nx.print_exception(ex)

    parts = list(pdf_parts)

    for i, part in enumerate(parts):
        nx.prompt("Nitro Plates PDF {} of {} -> {}".format(i + 1, len(parts), part.Leaf))

        try:
            pdf_path = "{}\\{}.pdf".format(directory, part.Leaf)

            if os.path.isfile(pdf_path):
                os.remove(pdf_path)

            nx.print_("Nitro Plates PDF 4-VIEW -> {}".format(pdf_path))
            _pdf(part, "4-VIEW", pdf_path)
        except Exception as ex:
            nx.print_exception(ex)


def _create_path(folder: _GFolder, part: NXOpen.BasePart, directory_tag: str, extension: str) -> str:
    """AssemblyExportDesignDataExport1.CreatePath - {job}\\{job}-{op}\\{job}-{op}{tag}\\{leaf}{extension}."""
    op = _ask_detail_op(part.Leaf)
    directory = "{}\\{}-{}\\{}{}-{}{}".format(folder.DirJob, folder.CustomerNumber, op, _DataPrefix,
                                             folder.CustomerNumber, op, directory_tag)
    stp_path = "{}\\{}{}".format(directory, part.Leaf, extension)
    return stp_path


# ---------------------------------------------------------------------------------------------------
# Layers, castings, strip setup
# ---------------------------------------------------------------------------------------------------

def _create_casting(part: NXOpen.Part, folder: _GFolder) -> None:
    """AssemblyExportDesignDataExport1.CreateCasting - a detail STEP and a layer-1 (+ layer-96 child) parasolid
    into {job}-{op}-Parasolids-Castings, then closes the part and reopens it. Returns before the close-and-reopen
    when the part has no layer-1 body - preserved from the C#."""
    with nx.display_part_reset():
        nx.set_display_part(part)

        op = _ask_detail_op(part.Leaf)

        casting_directory = "{}\\{}-{}\\{}{}-{}-Parasolids-Castings".format(
            folder.DirJob, folder.CustomerNumber, op, _DataPrefix, folder.CustomerNumber, op)

        if not os.path.isdir(casting_directory):
            os.makedirs(casting_directory, exist_ok=True)

        nx.print_("Casting Step - {}".format(part.FullPath))
        step_path = "{}\\{}.stp".format(casting_directory, part.Leaf)

        if os.path.isfile(step_path):
            os.remove(step_path)
        # CreateCastingStep(part, castingDirectory);
        _stp(part.FullPath, step_path, "U:\\nxFiles\\Step Translator\\ExternalStep_Detail.def")

        casting_path = "{}\\{}.x_t".format(casting_directory, part.Leaf)

        if os.path.isfile(casting_path):
            os.remove(casting_path)

        tag_bodies = [body.Tag for body in part.Bodies if isinstance(body, NXOpen.Body) and body.Layer == 1]

        if len(tag_bodies) == 0:
            nx.print_("Did not find any solid bodies on layer 1 in part {}".format(part.Leaf))

            return

        if part.ComponentAssembly.RootComponent is not None:
            for child in nx.children(part):
                if child.IsSuppressed:
                    continue

                if child.Layer != 96:
                    continue

                if child.ReferenceSet == "Empty":
                    continue

                for body in nx.members(child):
                    if isinstance(body, NXOpen.Body) and body.IsSolidBody:
                        tag_bodies.append(body.Tag)

        casting_file = "{}\\{}.x_t".format(casting_directory, part.Leaf)

        nx.ufsession_.Ps.ExportData(tag_bodies, casting_file)

    full_path = part.FullPath

    part.Close(NXOpen.BasePart.CloseWholeTree.FalseValue, NXOpen.BasePart.CloseModified.CloseModified, None)

    nx.find_or_open(full_path)


def _set_layers_in_blanks_and_layouts_and_add_dummies(snap_strip010: NXOpen.Part) -> None:
    """AssemblyExportDesignDataExport1.SetLayersInBlanksAndLayoutsAndAddDummies. Unlike ExportStrip's copy this one
    walks only loaded, unsuppressed descendants, and of the DISPLAY part - which, called from SetUpStrip, is the
    top-level 000, not the strip it was handed (preserved from the C#)."""
    if not re.search(_RegexStrip, snap_strip010.Leaf, re.IGNORECASE):
        # ArgumentException(message, paramName).Message
        raise ValueError("Must be an op 010 strip.\r\nParameter name: snapStrip010")

    with nx.display_part_reset():
        # sql
        blank_name_regex = re.compile(r"^BLANK-([0-9]{1,})$")

        layout_name_regex = re.compile(r"^LAYOUT-([0-9]{1,})$")

        root = _root(nx.display_part())

        layout_part = next(
            (proto for proto in (c.Prototype for c in nx.descendants(root))
             if isinstance(proto, NXOpen.Part) and re.search(_RegexLayout, proto.Leaf, re.IGNORECASE)),
            None)

        blank_part = next(
            (proto for proto in (c.Prototype for c in nx.descendants(root))
             if isinstance(proto, NXOpen.Part) and re.search(_RegexBlank, proto.Leaf, re.IGNORECASE)),
            None)

        layout_layers: Dict[int, None] = {}

        blank_layers: Dict[int, None] = {}

        for child in nx.descendants(root):
            if not isinstance(child.Prototype, NXOpen.Part):
                continue

            if child.IsSuppressed:
                continue

            blank_match = blank_name_regex.search(child.Name)
            layout_match = layout_name_regex.search(child.Name)

            if blank_match:
                blank_layers[int(blank_match.group(1)) + 10] = None

            if not layout_match:
                continue

            layer = int(layout_match.group(1)) * 10
            layout_layers[layer] = None
            layout_layers[layer + 1] = None

        if len(blank_layers) != 0 and blank_part is not None:
            nx.set_display_part(blank_part)
            nx.set_work_part(nx.display_part())
            exportstrip._add_dummy(blank_part, list(blank_layers))
            nx.prompt("Saving: {}.".format(blank_part.Leaf))
            exportstrip._save(nx.display_part(), False)

        if len(layout_layers) != 0 and layout_part is not None:
            nx.set_display_part(layout_part)
            nx.set_work_part(nx.display_part())
            exportstrip._add_dummy(layout_part, list(layout_layers))
            nx.prompt("Saving: {}.".format(layout_part.Leaf))
            exportstrip._save(nx.display_part(), False)

    exportstrip._save(snap_strip010, True)


def _check_assembly_dummy_files() -> None:
    """AssemblyExportDesignDataExport1.CheckAssemblyDummyFiles - of the display part's presses. Keeps checking the
    remaining presses after a good one (the C# `break` only leaves the switch); ExportStrip's copy stops."""
    nx.prompt("Checking Dummy files exist.")

    if nx.display_part().ComponentAssembly.RootComponent is None:
        return

    for child_of_strip in nx.children(nx.display_part()):
        if child_of_strip.IsSuppressed:
            continue

        if not nx.is_loaded(child_of_strip):
            continue

        if not re.search(_RegexPressAssembly, child_of_strip.DisplayName, re.IGNORECASE):
            continue

        if len(child_of_strip.GetChildren()) == 0:
            raise RuntimeError("A press exists in your assembly without any children. {}".format(
                exportstrip._assembly_path_string(child_of_strip)))

        count = len(child_of_strip.GetChildren())

        if count == 1:
            raise RuntimeError(
                "A press exists in your assembly with only one child. Expecting a ram and a bolster. {}".format(
                    exportstrip._assembly_path_string(child_of_strip)))

        if count == 2:
            for child_of_press in child_of_strip.GetChildren():
                if not nx.is_loaded(child_of_press):
                    raise RuntimeError("The child of a press must be loaded. {}".format(
                        exportstrip._assembly_path_string(child_of_press)))

                if child_of_press.IsSuppressed:
                    raise RuntimeError("The child of a press cannot be suppressed. {}".format(
                        exportstrip._assembly_path_string(child_of_press)))

                grand_children = child_of_press.GetChildren()
                if len(grand_children) != 0 and any(
                        not c.IsSuppressed and isinstance(c.Prototype, NXOpen.Part) for c in grand_children):
                    continue

                raise RuntimeError(
                    "The child of a bolster or ram under a press must be the Dummy file: {}. {}".format(
                        _DummyPath, exportstrip._assembly_path_string(child_of_press)))


def _set_up_strip(folder: _GFolder) -> None:
    """AssemblyExportDesignDataExport1.SetUpStrip - opens the op-010 strip (when it exists) without displaying it,
    then runs the blank/layout set-up and the dummy check against the display part (preserved from the C#)."""
    try:
        strip_010 = folder.file_strip("010")

        if not os.path.isfile(strip_010):
            return

        op010_strip = nx.find_or_open(strip_010)

        _set_layers_in_blanks_and_layouts_and_add_dummies(op010_strip)

        _check_assembly_dummy_files()

        exportstrip._save(op010_strip, True)
    except Exception as ex:
        nx.print_exception(ex)


# ---------------------------------------------------------------------------------------------------
# Sorting and updating the parts
# ---------------------------------------------------------------------------------------------------

def _sort_parts_for_export(valid_parts: Iterable[NXOpen.Part]) -> Dict[str, _PartSet]:
    """AssemblyExportDesignDataExport1.SortPartsForExport"""
    detail_regex = re.compile(_RegexDetail, re.IGNORECASE)

    export_dict: Dict[str, _PartSet] = {
        _PDF_4_VIEW: {},
        _STP_DETAIL: {},
        _DWG_BURNOUT: {},
        _STP_999: {},
        _STP_SEE3D: {},
        _X_T_CASTING: {},
    }

    for part in valid_parts:
        if not detail_regex.search(part.Leaf):
            continue

        if _is_assembly_holder(part.Leaf):
            continue

        if part.Leaf.endswith("-000"):
            continue

        # Every detail that gets this far is a STEP candidate. The step-details export used to
        # run off PDF_4-VIEW, so a detail with no 4-VIEW drawing sheet silently got no .stp -
        # but a drawing sheet is a documentation concern and says nothing about whether the
        # model should be exported. Its own bucket, so the 4-VIEW one keeps meaning what its
        # name says for the PDF and DWG exports.
        export_dict[_STP_DETAIL].setdefault(part.Tag, part)

        if _has_drawing_sheet(part, "4-VIEW"):
            export_dict[_PDF_4_VIEW].setdefault(part.Tag, part)

        if _has_drawing_sheet(part, "BURNOUT"):
            export_dict[_DWG_BURNOUT].setdefault(part.Tag, part)

        if _is_see_3d_data(part):
            export_dict[_STP_SEE3D].setdefault(part.Tag, part)

        if _is_999(part):
            export_dict[_STP_999].setdefault(part.Tag, part)

        if _is_casting(part):
            export_dict[_X_T_CASTING].setdefault(part.Tag, part)

    return export_dict


def _parts_to_update(is_rto: bool,
                  pdf4_views: bool, dwg4_views: bool, parts_with_4_views_no_assembly_holders: Iterable[NXOpen.Part],
                  stp_details: bool, step_detail_parts: Iterable[NXOpen.Part],
                  print4_views: bool, parts_with_4_views: Iterable[NXOpen.Part],
                  dwg_burnout: bool, burnout_parts: Iterable[NXOpen.Part],
                  stp999: bool, nine99_parts: Iterable[NXOpen.Part],
                  stp_see3d_data: bool, see3d_data_parts: Iterable[NXOpen.Part],
                  para_casting: bool, casting_parts: Iterable[NXOpen.Part],
                  selected_components: Sequence[NXOpen.Assemblies.Component]) -> List[NXOpen.Part]:
    """AssemblyExportDesignDataExport1.UpdateParts(isRto, ...) - the selected parts each enabled export needs,
    without assembly holders, distinct by Leaf (what UpdateParts(params Part[]) then updated)."""
    selected_parts: Set[object] = {c.Prototype.Tag for c in selected_components
                                   if isinstance(c.Prototype, NXOpen.Part)}

    parts_to_update: _PartSet = {}

    def add_selected(parts: Iterable[NXOpen.Part]) -> None:
        for part in parts:
            if part.Tag in selected_parts:
                parts_to_update.setdefault(part.Tag, part)

    if is_rto or pdf4_views or dwg4_views:
        add_selected(parts_with_4_views_no_assembly_holders)

    # Split out of the 4-VIEW group above: the step details are now their own, wider set,
    # and a detail with no 4-VIEW still has to be updated before it is exported.
    if is_rto or stp_details:
        add_selected(step_detail_parts)

    if is_rto or dwg_burnout:
        add_selected(burnout_parts)

    if is_rto or print4_views:
        add_selected(parts_with_4_views)

    if is_rto or para_casting:
        add_selected(casting_parts)

    if is_rto or stp999:
        add_selected(nine99_parts)

    if is_rto or stp_see3d_data:
        add_selected(see3d_data_parts)

    return nx.distinct_by([p for p in parts_to_update.values() if not _is_assembly_holder(p.Leaf)],
                          lambda p: p.Leaf)


def _update_parts_list(parts: Sequence[NXOpen.Part]) -> None:
    """AssemblyExportDesignDataExport1.UpdateParts(params Part[]) - per part, in this session: display it, set the
    export layers, unblank what is on them, update the drafting views, back to modeling, save with its components
    (design_exports.update_part). Per-part try/except."""
    with nx.display_part_reset():
        for i, part in enumerate(parts):
            try:
                nx.prompt("Updating: {} of {}. {}".format(i + 1, len(parts), part.Leaf))
                for message in design_exports.update_part(part, _is_casting(part), save_components=True):
                    nx.print_(message)
            except Exception as ex:
                nx.print_exception(ex, part.Leaf)


def _unblank_assembly() -> None:
    """UnblankAssembly.execute (src\\UFuncs\\UnblankAssembly.cs) - shows the root component's blanked solid
    members, then each descendant part's blanked layer-1 bodies (in that part), and prints the total."""
    disp = nx.display_part()
    root = _root(disp)

    # BasePart.__DescendantParts: __Descendants(true, true), distinct by DisplayName, the loaded prototypes.
    parts1 = [c.Prototype for c in nx.distinct_by(list(nx.descendants(root, True, True)), lambda c: c.DisplayName)
              if isinstance(c.Prototype, NXOpen.Part)]

    total = 0

    solids: List[NXOpen.Body] = [b for b in nx.solid_body_members(root) if b.IsBlanked]

    if len(solids) > 0:
        nx.session_.DisplayManager.ShowObjects(solids, NXOpen.DisplayManager.LayerSetting.ChangeLayerToSelectable)
        nx.display_part().ModelingViews.WorkView.FitAfterShowOrHide(NXOpen.View.ShowOrHideType.ShowOnly)
        total += len(solids)

    with nx.display_part_reset():
        for i, part in enumerate(parts1):
            nx.prompt("{} of {} -> {}".format(i + 1, len(parts1), part.Leaf))

            solids = [b for b in part.Bodies if b.Layer == 1 and b.IsBlanked]

            if len(solids) == 0:
                continue

            nx.set_display_part(part)
            nx.session_.DisplayManager.ShowObjects(solids,
                                                   NXOpen.DisplayManager.LayerSetting.ChangeLayerToSelectable)
            nx.display_part().ModelingViews.WorkView.FitAfterShowOrHide(NXOpen.View.ShowOrHideType.ShowOnly)
            total += len(solids)

    nx.print_("total == {}".format(total))


# ---------------------------------------------------------------------------------------------------
# Part predicates (Globals.cs)
# ---------------------------------------------------------------------------------------------------

def _is_part_detail(leaf: str) -> bool:
    """string.__IsPartDetail"""
    return re.search(_DetailNumberRegex, leaf) is not None


def _is_casting(part: NXOpen.BasePart) -> bool:
    """BasePart.__IsCasting - a detail whose MATERIAL contains one of the ConceptControlFile.ucf
    :CASTING_MATERIALS: (the file is read on every call, as in the C#)."""
    if not _is_part_detail(part.Leaf):
        return False

    materials = _ucf_static_read(_ConceptControlFile, ":CASTING_MATERIALS:", ":END_CASTING_MATERIALS:")
    material = "MATERIAL"

    if not re.search(_RegexDetail, part.Leaf):
        return False

    if not part.HasUserAttribute(material, NXOpen.NXObject.AttributeType.String, -1):
        return False

    material_value = part.GetUserAttributeAsString(material, NXOpen.NXObject.AttributeType.String, -1)

    return material_value is not None and any(s in material_value for s in materials)


def _is_see_3d_data(part: NXOpen.BasePart) -> bool:
    """BasePart.__IsSee3DData - DESCRIPTION matches SEE[-_ ]3D[-_ ]DATA (upper-cased)."""
    if not part.HasUserAttribute("DESCRIPTION", NXOpen.NXObject.AttributeType.String, -1):
        return False

    description_value = part.GetUserAttributeAsString("DESCRIPTION", NXOpen.NXObject.AttributeType.String, -1)
    return description_value is not None and re.search("SEE(-|_| )3D(-|_| )DATA",
                                                       description_value.upper()) is not None


def _is_999(part: NXOpen.BasePart) -> bool:
    """BasePart.__Is999 - detail number 990..1000."""
    match = re.search(_RegexDetail, part.Leaf)
    if not match:
        return False
    detail_number = int(match.group(3))
    return 990 <= detail_number <= 1000


def _ucf_static_read(file_path: str, start_delimeter: str, end_delimeter: str) -> List[str]:
    """Ucf.StaticRead(..., StringComparison.OrdinalIgnoreCase) - the lines between the two delimiter lines."""
    if not os.path.isfile(file_path):
        raise FileNotFoundError("Could not find file \"{}\".".format(file_path))

    # File.ReadAllLines: \r\n, \n and \r all end a line; a trailing newline does not add an empty line.
    with open(file_path, "r", encoding="utf-8-sig", errors="replace") as reader:
        file_path_lines = reader.read().split("\n")
    if file_path_lines and file_path_lines[-1] == "":
        file_path_lines.pop()

    if len(file_path_lines) == 0:
        raise ValueError("Supplied file path doesn't contain any readable lines.\r\nParameter name: filePath")

    def index_of(delimeter: str) -> int:
        return next((i for i, line in enumerate(file_path_lines) if line.lower() == delimeter.lower()), -1)

    start_delimeter_index = index_of(start_delimeter)
    end_delimeter_index = index_of(end_delimeter)

    if start_delimeter_index >= end_delimeter_index:
        raise Exception("Start delimeter was greater than end delimeter.")

    if start_delimeter_index < 0:
        raise Exception("Did not find start delimeter.")

    if end_delimeter_index < 0:
        raise Exception("Did not find end delimeter.")

    return file_path_lines[start_delimeter_index + 1:end_delimeter_index]


# ---------------------------------------------------------------------------------------------------
# Printing and exporters
# ---------------------------------------------------------------------------------------------------

def _print_pdfs(parts_with_4_views: Iterable[NXOpen.Part]) -> None:
    """AssemblyExportDesignDataExport1.PrintPdfs - Print4Views inside a suppressed display that it unsuppresses."""
    with nx.suppress_display():
        try:
            nx.ufsession_.Disp.SetDisplay(nx.UF_DISP_UNSUPPRESS_DISPLAY)
            nx.ufsession_.Disp.RegenerateDisplay()
            _print_4_views(parts_with_4_views)
        except Exception as ex:
            nx.print_exception(ex)


def _print_4_views(all_parts: Iterable[NXOpen.Part]) -> None:
    """AssemblyExportDesignDataExport1.Print4Views - one letter-landscape B/W print of each detail's 4-VIEW sheet
    to the office MFC, in leaf order."""
    try:
        def is_not_assembly(part: NXOpen.Part) -> bool:
            name = ntpath.splitext(ntpath.basename(part.FullPath))[0]

            name = name.lower()

            if name.endswith("000") or name.endswith("lsh") or name.endswith("ush") or name.endswith("lwr") \
                    or name.endswith("upr"):
                return False

            return "lsp" not in name and "usp" not in name

        parts = [part for part in all_parts
                 if re.search(_RegexDetail, part.Leaf, re.IGNORECASE)
                 and is_not_assembly(part)
                 and any(d.Name.upper() == "4-VIEW" for d in part.DraftingDrawingSheets)]

        # Ordinal compare of the leaves.
        parts.sort(key=lambda p: p.Leaf)

        for i, part in enumerate(parts):
            nx.prompt("{} of {}. Printing 4-VIEW of {}.".format(i + 1, len(parts), part.Leaf))

            nx.set_display_part(part)

            nx.set_work_part(nx.display_part())

            work = nx.work_part()

            print_builder = work.PlotManager.CreatePrintBuilder()

            try:
                # sql
                print_builder.Copies = 1

                print_builder.ThinWidth = 1.0

                print_builder.NormalWidth = 2.0

                print_builder.ThickWidth = 3.0

                print_builder.Output = NXOpen.PrintBuilder.OutputOption.WireframeBlackWhite

                print_builder.ShadedGeometry = True

                drawing_sheet = work.DraftingDrawingSheets.FindObject("4-VIEW")

                drawing_sheet.Open()

                print_builder.SourceBuilder.SetSheets([drawing_sheet])

                print_builder.PrinterText = _Printer

                print_builder.Orientation = NXOpen.PrintBuilder.OrientationOption.Landscape

                print_builder.Paper = NXOpen.PrintBuilder.PaperSize.Letter

                print_builder.Commit()
            finally:
                print_builder.Destroy()
    except Exception as ex:
        nx.print_exception(ex)


_stp = design_exports.stp
_pdf = design_exports.pdf
_dwg = design_exports.dwg


# ---------------------------------------------------------------------------------------------------
# Zipping, reports, stocklist, error check
# ---------------------------------------------------------------------------------------------------

class _Process7Zip(object):
    """The unstarted System.Diagnostics.Process Create7ZipProcess returns: start() / has_exited / wait_for_exit()
    stand for Start() / HasExited / WaitForExit()."""

    def __init__(self, arguments: str, files_to_zip: List[str]) -> None:
        self._arguments = arguments
        self._files_to_zip = files_to_zip  # kept alive so id() in the list-file name stays unique
        self._process: Optional[subprocess.Popen] = None

    def start(self) -> None:
        # UseShellExecute, normal window. CreateProcess appends ".exe" to the extension-less 7z.
        self._process = subprocess.Popen('"{}" {}'.format(_SevenZip, self._arguments))

    @property
    def has_exited(self) -> bool:
        if self._process is None:
            raise RuntimeError("No process is associated with this object.")
        return self._process.poll() is not None

    def wait_for_exit(self) -> None:
        if self._process is None:
            raise RuntimeError("No process is associated with this object.")
        self._process.wait()


def _create_7zip_process(zip_path: str, *files_to_zip: str) -> _Process7Zip:
    """AssemblyExportDesignDataExport1.Create7ZipProcess - writes the list file now, returns the unstarted
    "7z a -t7z <zip> @<list> -mx9". Like the C#, the list file is never deleted."""
    files = list(files_to_zip)

    # Path.GetTempPath() ends with a backslash.
    temp_file = "{}zipData{}.txt".format(os.path.join(tempfile.gettempdir(), ""), id(files))

    # StreamWriter: UTF-8 without a BOM, WriteLine = CRLF.
    with open(temp_file, "w", encoding="utf-8", newline="\r\n") as writer:
        for f in files:
            writer.write(f + "\n")

    return _Process7Zip("a -t7z \"{}\" \"@{}\" -mx9".format(zip_path, temp_file), files)


def _assembly(snap_part: NXOpen.Part, wait_for_process: bool, zip_path: str) -> _Process7Zip:
    """AssemblyExportDesignDataExport1.Assembly - the unstarted 7-Zip of every part file in the loaded,
    unsuppressed, non-simulation tree. wait_for_process is unused, as in the C#."""
    file_paths: Dict[str, None] = {}

    for component in _get_assembly(_root(snap_part)):
        file_paths[component.Prototype.FullPath] = None

    return _create_7zip_process(zip_path, *file_paths)


def _get_assembly(snap_component: NXOpen.Assemblies.Component) -> Iterator[NXOpen.Assemblies.Component]:
    """AssemblyExportDesignDataExport1.GetAssembly - stops at unloaded, suppressed and "-simulation" components."""
    if not nx.is_loaded(snap_component):
        return

    if snap_component.DisplayName.lower().endswith("-simulation"):
        return

    if snap_component.IsSuppressed:
        return

    yield snap_component

    for child in snap_component.GetChildren():
        for comp in _get_assembly(child):
            yield comp


def _launch_processes(number_of_processes: int, *processes: _Process7Zip) -> None:
    """AssemblyExportDesignDataExport1.LaunchProcesses - runs at most number_of_processes at a time (busy-waiting,
    as the C# does)."""
    processes_completed = 0

    try:
        length = len(processes) if number_of_processes > len(processes) else number_of_processes
        hash_processes: List[_Process7Zip] = []
        for i in range(length):
            processes[i].start()
            hash_processes.append(processes[i])
            nx.prompt("{} of {}".format(processes_completed, len(processes)))

        i = length
        while processes_completed < len(processes):
            first = next((p for p in hash_processes if p is not None and p.has_exited), None)
            if first is None:
                # C#: i--; continue; - the for loop's i++ puts it back.
                continue

            hash_processes.remove(first)
            processes_completed += 1
            if i < len(processes):
                next_process = processes[i]
                next_process.start()
                hash_processes.append(next_process)

            nx.prompt("{} of {}".format(processes_completed, len(processes)))
            i += 1

        for proc in processes:
            proc.wait_for_exit()
    except Exception as ex:
        nx.print_exception(ex)

    nx.prompt("All processes have finished.")


def _zip_up_data_folders(directories_to_export: Iterable[str], export_directory: Optional[str]) -> None:
    """AssemblyExportDesignDataExport1.ZipUpDataFolders - one .7z per data folder, ten at a time. Always runs over
    no folders (the empty dict) - preserved from the C#."""
    _launch_processes(10, *[
        _create_7zip_process("{}\\{}.7z".format(export_directory or "", ntpath.basename(directory)), directory)
        for directory in directories_to_export])


def _zipup_directories(seven_zip: str, directories_to_export: Iterable[str], zip_path: str) -> None:
    """AssemblyExportDesignDataExport1.ZipupDirectories - deletes the data folders from the assembly zip. With no
    folders (the empty dict) it still runs "7z d <zip> -r " - preserved from the C#."""
    try:
        # Constructs the arguments that deletes the sub data folders in the newly created assembly zip.
        names = "".join(" \"{}\"".format(ntpath.basename(d)) for d in directories_to_export)
        arguments = "d \"{}\" -r {}".format(zip_path, names)

        # Starts the actual delete process, and waits for it to finish.
        delete_process = subprocess.Popen("\"{}\" {}".format(seven_zip, arguments))
        delete_process.wait()
    except Exception as ex:
        nx.print_exception(ex)


def _zipup_data_directories(export_directory: str, assembly_process: Optional[_Process7Zip]) -> None:
    """AssemblyExportDesignDataExport1.ZipupDataDirectories - zips the export folder's top-level .stp files into
    {first stp name}_STP.7z, deletes them, then waits for the assembly zip."""
    try:
        stp_files_in_out_going_folder = [f for f in exportstrip._get_files(export_directory)
                                         if f.lower().endswith(".stp")]

        if len(stp_files_in_out_going_folder) != 0:
            display_name = ntpath.splitext(ntpath.basename(stp_files_in_out_going_folder[0]))[0]

            stp_zip_process = _create_7zip_process("{}\\{}_STP.7z".format(export_directory, display_name),
                                                   *stp_files_in_out_going_folder)

            stp_zip_process.start()

            stp_zip_process.wait_for_exit()

            for file in stp_files_in_out_going_folder:
                try:
                    if os.path.isfile(file):
                        os.remove(file)
                except Exception as ex:
                    nx.print_exception(ex)

        if assembly_process is not None:
            assembly_process.wait_for_exit()
    except Exception as ex:
        nx.print_exception(ex)


def _get_reports(cts_job_number: str) -> List[str]:
    """AssemblyExportDesignDataExport1.GetReports - the X:\\Reports-{start}-{end} sim report .7z files whose name
    starts with the job number, from the folders whose range holds it."""
    result: List[str] = []
    for directory in _get_directories("X:\\"):
        directory_name = ntpath.basename(directory)
        # sql
        match = re.search(r"^Reports-([0-9]{4})-([0-9]{4})$", directory_name)
        if not match:
            continue
        start_range = int(match.group(1))
        end_range = int(match.group(2))
        job_number = int(cts_job_number)
        if not (start_range <= job_number <= end_range):
            continue
        for report in exportstrip._get_files(directory):
            if not report.lower().endswith(".7z"):
                continue
            file_name = ntpath.splitext(ntpath.basename(report))[0]
            if file_name.startswith(cts_job_number):
                result.append(report)
    return result


def _move_sim_report(folder: _GFolder, export_directory: str) -> None:
    """AssemblyExportDesignDataExport1.MoveSimReport - copies the job's sim reports (CTS jobs only)."""
    try:
        if not folder.is_cts_job():
            return

        reports = _get_reports(folder.CtsNumber)
        if len(reports) != 0:
            for report in reports:
                report_name = ntpath.basename(report)

                exported_report_path = "{}\\{}".format(export_directory, report_name)

                if os.path.isfile(exported_report_path):
                    nx.print_("Sim report \"{}\" already exists.".format(exported_report_path))
                    continue

                _file_copy(report, exported_report_path)
        else:
            nx.print_("Unable to find a sim report to transfer.")
    except Exception as ex:
        nx.print_exception(ex)


def _move_stocklist(folder: _GFolder, top_display_name: str, export_directory: str) -> None:
    """AssemblyExportDesignDataExport1.MoveStocklist - copies the one {top}-stocklist from NX Stocklist."""
    try:
        matches = [file for file in exportstrip._get_files(folder.DirStocklist)
                   if ntpath.splitext(ntpath.basename(file))[0].endswith("{}-stocklist".format(top_display_name))]

        if len(matches) > 1:
            raise RuntimeError("Sequence contains more than one matching element")

        stocklist = matches[0] if matches else None

        if stocklist is None:
            nx.print_("Could not find a stocklist named: {}-stocklist".format(top_display_name))
            return

        _file_copy(stocklist, "{}\\{}".format(export_directory, ntpath.basename(stocklist)))
    except Exception as ex:
        nx.print_exception(ex)


def _error_check(is_rto: bool, zip_assembly: bool, expected_files: Iterable[str]) -> None:
    """AssemblyExportDesignDataExport1.ErrorCheck - prints how many of expected_files exist and lists the missing ones
    with the first line of a .err beside them, if any (C# never reached it: the empty dict)."""
    enumerable = list(expected_files)

    file_created_count = len([f for f in enumerable if os.path.isfile(f)])

    nx.print_("Created {} file(s).".format(file_created_count))

    if not is_rto and not zip_assembly:
        nx.print_("Created files will have to be manually moved to outgoingData folderWithCtsNumber if that is "
                  "desired. (Example: RTO)")

    files_that_were_not_created = [s for s in enumerable if not os.path.isfile(s)]

    error_list: List[Tuple[str, str]] = []

    for file in files_that_were_not_created:
        extension = ntpath.splitext(file)[1]

        # Path.GetExtension is "" (never null) without an extension, and string.Replace("", ...) throws.
        if not extension:
            raise ValueError("String cannot be of zero length.\r\nParameter name: oldValue")

        error_file_path = file.replace(extension, ".err")

        if os.path.isfile(error_file_path):
            with open(error_file_path, "r", encoding="utf-8-sig", errors="replace") as reader:
                file_contents = reader.read().splitlines()

            error_list.append((file, file_contents[0]))

            os.remove(error_file_path)
        else:
            error_list.append((file, "Unknown error."))

    if len(error_list) <= 0:
        return

    nx.print_("Files that were not created.")

    for item in error_list:
        # Tuple<string, string>.ToString()
        nx.print_("({}, {})".format(item[0], item[1]))


# ---------------------------------------------------------------------------------------------------
# Small .NET stand-ins
# ---------------------------------------------------------------------------------------------------

def _get_directories(directory: str) -> List[str]:
    """Directory.GetDirectories(directory) - full paths of the folders directly in it."""
    return [ntpath.join(directory, entry.name) for entry in os.scandir(directory) if entry.is_dir()]


def _file_delete(path: str) -> None:
    """File.Delete - no error when the file is missing, but its folder must exist."""
    if os.path.isfile(path):
        os.remove(path)
    elif not os.path.isdir(ntpath.dirname(path) or "."):
        raise FileNotFoundError("Could not find a part of the path '{}'.".format(path))


def _file_copy(source: str, destination: str) -> None:
    """File.Copy(source, destination) - refuses to overwrite."""
    if os.path.exists(destination):
        raise FileExistsError("The file '{}' already exists.".format(destination))
    shutil.copy2(source, destination)


def _cs_timespan(delta: datetime.timedelta) -> str:
    """TimeSpan.ToString() - [-][d.]hh:mm:ss[.fffffff]."""
    ticks = ((delta.days * 86400 + delta.seconds) * 1000000 + delta.microseconds) * 10
    sign = "-" if ticks < 0 else ""
    ticks = abs(ticks)
    days, ticks = divmod(ticks, 864000000000)
    hours, ticks = divmod(ticks, 36000000000)
    minutes, ticks = divmod(ticks, 600000000)
    seconds, fraction = divmod(ticks, 10000000)
    text = "{}{}{:02d}:{:02d}:{:02d}".format(sign, "{}.".format(days) if days else "", hours, minutes, seconds)
    return text + (".{:07d}".format(fraction) if fraction else "")


def main() -> None:
    """Standalone entry (File -> Execute -> NX Open): the Design tab's defaults - 50% Review, the form's default
    folder name, no printing."""
    AssemblyExportDesignData.export_design(False, False, True, False, False, False,
                                           AssemblyExportDesignData.default_folder_name(), False, "")


if __name__ == "__main__":
    main()

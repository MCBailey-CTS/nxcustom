"""
Python port of the export-strip UFunc (src\\UFuncs\\ExportStrip.cs): STP / PDF / zipped strip assembly / printed
copies of the displayed strip into the job's outgoing (or, for 6-digit jobs, Layout) folder, zipped, and optionally
copied to "Process and Sim Data for Design".

ALL PYTHON since 2026-10-23: the export-strip menu button runs this file. main() records the run
(usage_db.run("export-strip")) and shows a Block UI Styler dialog (ExportStrip.dlx, built by tools\\make-dlx.py) with
the old form's inputs, then calls ExportStrip.export(stp, copies, part, pdf, name, copy). It replaced the C#
ExportStrip _UFunc and its SNAP ExportStripDialog (src\\UFuncs\\ExportStrip.cs, src\\Ui\\Dialogs\\ExportStripDialog.cs),
which in turn had replaced the WinForms form and the src\\Static\\ExportStrip.cs statics - all of it, the commented-out
C# included, is in git at f3ec98e. AssemblyExportDesignData.py still imports this module for _GFolder, _add_dummy and
friends. The dialog has NEVER BEEN RUN IN NX, nor has the export itself.

Ported from:
  - ExportStrip.BtnAccept_Click                  -> ExportStrip.export (try / print exception / "Complete")
  - Static.ExportStripExport                     -> _export
  - Static.ExportStripPrintDrawing               -> ExportStrip.print_drawing
  - Static.ExportStripCheckAssemblyDummyFiles    -> _check_assembly_dummy_files
  - Static.ExportStripSetLayersInBlanksAndLayoutsAndAddDummies -> _set_layers_in_blanks_and_layouts_and_add_dummies
  - Static.ExportStripAddDummy                   -> _add_dummy
  - Static.ExportStripDescendants                -> _descendants
  - Static.ExportStripUpdateForStp               -> _update_for_stp
  - Static.ExportStripUpdateForPdf               -> _update_for_pdf
  - Static.ExportStripExportPDF                  -> _export_pdf
  - Static.ExportStripPdf                        -> _export_strip_pdf
  - Static.ExportStripStp                        -> _export_strip_stp
  - Static.ExportStripPart                       -> _export_strip_part
  - ExportStrip.Zip7                             -> _Zip7
  - Static.ExportStripPrompt                     -> tsg_nx.prompt (same UF_UI_set_prompt call)

  - ExportStrip() constructor's folder-name default -> default_name

Not ported: Static.ExportStripNewMethod - nothing calls it (a dead copy of the UpdateForStp loop body).

Differences from the C#:
  - export() itself catches, prints (print_exception) and prints "Complete" in a finally, as the form's Accept
    button did around Static.ExportStripExport - so the listing window reads exception-then-Complete as before.
    The C# wrapper's own catch now only sees failures to start the script.
  - The form hid itself for the run (UsingFormShowHide) and stayed open afterwards; the dialog is modal and
    closes on OK, so one run per launch. The form's window-location setting is no longer used.
  - The form greyed out Accept when nothing was ticked and copies was 0; the Block Styler dialog greys out OK the
    same way (enable_ok). The SNAP dialog in between had left OK live and printed a message instead.
  - The dialog's OK closes it before the export starts; the export's prompts and "Complete" follow in NX.
  - The two WinForms Yes/No MessageBoxes (overwrite the outgoing folder, delete each old .7z) are NX Question
    boxes. Anything but Yes counts as No; the C# "default: throw new ArgumentException()" for the delete prompt
    was unreachable with YesNo and is gone.
  - Directory.GetFiles(dir, "*.7z") is a case-insensitive ".7z" suffix match, without the Win32 8.3 short-name
    quirk.
  - Zip7's temp list file is named with id() of the file list where the C# uses the array's GetHashCode().
  - One save (2026-10-23): the C# saved the blank, the layout, the strip with its components, the sheet's part with
    its components, then each STP child with its components - 13 saves on 006969-010, 12 s. The preparation now
    only changes parts, and _save_strip saves the strip and its components once, after the overwrite question
    (a No leaves the parts unsaved) and before any export reads the .prt files. The strip's own layer settings
    for the PDF stay unsaved, as before. The print now comes after that save (it came first, before any
    preparation); printing alone updates the sheet's views and saves once, then prints.

Progress window (2026-10-23): once the dialog is accepted, progress_window.ProgressWindow (ProgressWindow.ps1, Auto
Design's window) opens in the bottom-right corner - out of the way of the overwrite / delete-old-.7z questions - and
shows every _log line plus the current step (_step) in its title, then Complete or the failure. It stays open until
closed.

2026-10-23, after the first runs in NX:
  - The Folder Name came through empty (the string block keeps its text in WideValue - tsg_dialog.string_value), so
    the outgoing folder was the job's Layout folder itself and the overwrite question deleted it whole.
    _outgoing_folder now refuses an empty / non-plain name, OK stays grey without one, and rmtree refuses the parent.
  - Prints on the MFC's 12x18 paper (Custom + the printer's paper id, _printer_paper_id), 11x17 if it has none.
  - Export DWG: the sheet as an AutoCAD 2004 DWG (_export_strip_dwg). The STP translator now starts without
    waiting (ProcessHoldFlag False) after every save, the DWG, PDF and part zip run while it works, and
    _wait_for_translator waits for the .stp before zipping.
"""

from __future__ import annotations

import datetime
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Iterable, List, Optional, Set, Tuple, cast

# Session.Execute does not put the script's folder on sys.path, so the shared module would not import.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)
# From the source tree (src\UFuncs) the shared modules are in src\python; deployed, they are beside this file.
_shared_python = os.path.join(os.path.dirname(_here), "python")
if os.path.isdir(_shared_python) and _shared_python not in sys.path:
    sys.path.insert(1, _shared_python)

import NXOpen  # noqa: E402
import NXOpen.Assemblies  # noqa: E402
import NXOpen.Layer  # noqa: E402

import tsg_nx as nx  # noqa: E402
import progress_window  # noqa: E402
from tsg_dialog import Dialog, title_with_version  # noqa: E402

# Static.ExportStripRegex_* / ExportStripDummyPath (.NET named groups (?<x>) are (?P<x>) in Python).
_Regex_Strip = r"^(?P<customerNum>\d+)-(?P<opNum>\d+)-strip$"
_DummyPath = "G:\\0Library\\SeedFiles\\Components\\Dummy.prt"
_Regex_PressAssembly = r"^(?P<customerNum>\d+)-Press-(?P<opNum>\d+)-Assembly$"
_Regex_Layout = r"^(?P<customerNum>\d+)-(?P<opNum>\d+)-layout$"
_Regex_Blank = r"^(?P<customerNum>\d+)-(?P<opNum>\d+)-blank$"

# NXMessageBox.Show return value for "Yes" on a Question dialog.
_MessageBoxYes = 1

_StepSettingsFile = "U:\\nxFiles\\Step Translator\\ExternalStep_AllLayers.def"
_Printer = "\\\\ctsfps1.cts.toolingsystemsgroup.com\\CTS Office MFC"
# The paper the strip drawing prints on, in inches. The MFC has no 12x17, so its 12x18.
_PaperInches = (12.0, 18.0)
_SevenZip = "C:\\Program Files\\7-Zip\\7z"

# 7-Zip's exit codes: 0 no error, 1 warning (some files skipped - locked, say - the archive is still written),
# 2 fatal error, 7 command line error, 8 not enough memory, 255 stopped by the user.
_SevenZipWarning = 1


class ExportStrip(object):

    @staticmethod
    def export(stp: bool, copies: int, part: bool, pdf: bool, name: str, copy: bool, dwg: bool = False) -> None:
        """ExportStrip.BtnAccept_Click - runs the export, prints any exception, then always prints "Complete".

        stp / part / pdf / copy / dwg are the Export STP / Export NX Part / Export PDF / Copy to / Export DWG check
        boxes, copies the Print Copies count and name the Folder Name text."""
        try:
            _export(stp, copies, part, pdf, name, copy, dwg)
        except Exception as ex:
            _step("failed")
            _log("FAILED: {}: {}".format(type(ex).__name__, ex))
            nx.print_exception(ex)
        else:
            if _progress_step != "stopped":
                _step("complete")
        finally:
            nx.print_("Complete")

    @staticmethod
    def default_name() -> str:
        """The ExportStrip form constructor's Folder Name default: "{today}-" with no displayed part,
        "{today}-Strip" on an op 010, "{today}-FlowChart" on an op 900, otherwise empty."""
        display = nx.display_part()

        if display is None:
            return "{}-".format(_todays_date())

        match = re.match(r"^[0-9]{4,}-([0-9]{3,})", display.Leaf)
        op = match.group(1) if match else None

        if op == "010":
            return "{}-Strip".format(_todays_date())

        if op == "900":
            return "{}-FlowChart".format(_todays_date())

        return ""

    @staticmethod
    def print_drawing(copies: int) -> None:
        """Static.ExportStripPrintDrawing"""
        _print_drawing(copies)


def _export(chk_stp: bool, num_up_down_copies: int, chk_part: bool, chk_pdf: bool, txt_input: str,
            chk_copy: bool, chk_dwg: bool = False) -> None:
    """Static.ExportStripExport - everything the Accept button did after the form hid itself."""
    folder = _GFolder.create(nx.display_part().FullPath)
    txt_input = (txt_input or "").strip()

    _log("setting DATE = {} on {}".format(_todays_date(), nx.display_part().Leaf))
    nx.display_part().SetUserAttribute("DATE", -1, _todays_date(), NXOpen.Update.Option.Now)

    if folder is None:
        raise Exception("The current displayed part is not in a GFolder.")

    _log("job folder {}  customer {}  CTS job {}".format(folder.DirJob, folder.CustomerNumber, folder.is_cts_job()))

    if chk_stp:
        _step("checking presses")
        _log("STP pre-check: presses")
        _check_assembly_dummy_files()

    exporting = chk_part or chk_pdf or chk_stp or chk_dwg
    if not exporting:
        _log("only printing was asked for - nothing to export")
        _prepare_save_and_print(False, False, num_up_down_copies)
        return

    parent_folder = folder.DirLayout if len(folder.CustomerNumber) == 6 else folder.DirOutgoing
    outgoing_folder_name = _outgoing_folder(parent_folder, txt_input)
    _log("outgoing folder {} ({})".format(
        outgoing_folder_name, "Layout: 6-digit customer number" if len(folder.CustomerNumber) == 6
        else "Outgoing: customer number is not 6 digits"))

    if os.path.isdir(outgoing_folder_name):
        if not _yes_no(
                "Warning",
                "Folder {} already exists, is it okay to overwrite the files in the folder?".format(
                    outgoing_folder_name)):
            _log("outgoing folder already exists - user said No, stopping")
            nx.mark_cancelled("the overwrite-folder question")
            _step("stopped")
            return

        removed = sum(len(files) for _, _, files in os.walk(outgoing_folder_name))
        _log("outgoing folder already exists - user said Yes, removing it ({} files)".format(removed))
        # _outgoing_folder already refused a name that would make this the Layout / Outgoing folder itself.
        if os.path.normcase(outgoing_folder_name) == os.path.normcase(os.path.normpath(parent_folder)):
            raise RuntimeError("Refusing to delete \"{}\".".format(outgoing_folder_name))
        shutil.rmtree(outgoing_folder_name)

    os.makedirs(outgoing_folder_name, exist_ok=True)

    _prepare_save_and_print(chk_stp, chk_pdf or chk_dwg, num_up_down_copies)

    # Not saved: the strip's layers only for the PDF (made from the session) - as the C# left them.
    _step("setting layers")

    nx.prompt("Export Strip: Setting layers in {}.".format(nx.display_part().Leaf))

    nx.work_part().Layers.SetState(1, NXOpen.Layer.State.WorkLayer)

    # sql
    for i in range(2, 257):
        nx.work_part().Layers.SetState(i, NXOpen.Layer.State.Hidden)

    for i in [6, 10, 200, 201, 202, 254]:
        nx.work_part().Layers.SetState(i, NXOpen.Layer.State.Selectable)

    regex = r"^\d+-(?P<op>\d+)-.+$"

    op_match = re.match(regex, nx.work_part().Leaf, re.IGNORECASE)
    # Regex.Match(...).Groups["op"].Value is "" when there is no match.
    op = op_match.group("op") if op_match else ""
    common_string = "{}-{}-strip {}".format(folder.CustomerNumber, op, _todays_date())
    _log("op {}  file name stem '{}'".format(op or "(none)", common_string))

    nx.prompt("Exporting \".prt\" file." if chk_part else "Finding objects to export.")

    # The STP translator reads the saved .prt from disk while the DWG, PDF and part zip are made, so nothing may be
    # saved under it once it has started.
    stp_path = None
    stp_started = time.monotonic()
    if chk_stp:
        _step("starting the STP")
        stp_path = _export_strip_stp(outgoing_folder_name, wait=False)

    running = " (STP running)" if chk_stp else ""

    if chk_dwg:
        nx.prompt("Exporting DWG......")
        _step("exporting the DWG" + running)
        started = time.monotonic()
        output_path = _export_strip_dwg(outgoing_folder_name, common_string)
        _log_file("DWG", output_path, started)
        _print_created(output_path)

    if chk_pdf:
        nx.prompt("Exporting PDF......")
        _step("exporting the PDF" + running)

        started = time.monotonic()
        output_path = _export_pdf(outgoing_folder_name, common_string)
        _log_file("PDF", output_path, started)
        _print_created(output_path)

    if chk_part:
        _step("exporting the part (7-Zip)" + running)
        started = time.monotonic()
        output_path = _export_strip_part(outgoing_folder_name)
        _log_file("Part", output_path, started)
        _print_created(output_path)

    if stp_path is not None:
        _step("waiting for the STP")
        nx.prompt("Waiting for the STP translator......")
        _wait_for_translator(stp_path, "STP")
        _log_file("STP", stp_path, stp_started)
        _print_created(stp_path)

    nx.prompt("Zipping up {}.".format(outgoing_folder_name))

    files_to_zip = _get_files(outgoing_folder_name)

    zip_file_name = "{}-{}.7z".format(folder.CustomerNumber, txt_input)

    zip_file = "{}\\{}".format(outgoing_folder_name, zip_file_name)

    if len(files_to_zip) != 0:
        _step("zipping")
        started = time.monotonic()
        zip_ = _Zip7(zip_file, files_to_zip)

        zip_.start()

        zip_.wait_for_exit()
        _log_file("zip", zip_file, started)
    else:
        _log("outgoing folder is empty - no {} made".format(zip_file_name))

    if chk_copy:
        # Nothing was zipped when the outgoing folder came out empty: there is no archive to copy.
        if not os.path.isfile(zip_file):
            nx.print_("Nothing was zipped, so nothing was copied to \"{}\".".format(folder.DirProcessSimDataDesign))
            _log("copy skipped - {} was not made".format(zip_file))
        else:
            _step("copying to Process and Sim Data for Design")
            if not os.path.isdir(folder.DirProcessSimDataDesign):
                os.makedirs(folder.DirProcessSimDataDesign, exist_ok=True)

            zip_files = [f for f in _get_files(folder.DirProcessSimDataDesign) if f.lower().endswith(".7z")]

            for zip_file1 in zip_files:
                if _yes_no("Warning", "Delete file \"{}\"".format(zip_file1)):
                    os.remove(zip_file1)
                    _log("deleted old {}".format(zip_file1))
                else:
                    _log("kept old {}".format(zip_file1))

            destination = "{}\\{}".format(folder.DirProcessSimDataDesign, zip_file_name)
            shutil.copyfile(zip_file, destination)
            _log("copied {} -> {} ({})".format(zip_file, destination, _size(destination)))

    _log("back to Modeling, leaving Drafting")
    nx.session_.ApplicationSwitchImmediate("UG_APP_MODELING")

    nx.work_part().Drafting.ExitDraftingApplication()


def _prepare_save_and_print(stp: bool, drawing: bool, copies: int) -> None:
    """The strip's preparation, its one save, then the print. The preparation changes parts without saving them;
    _save_strip then saves the strip and its components once (it used to be 13 saves, the strip's assembly several
    times over). The STP translator, the DWG and the part zip read the saved .prt files, so this runs before any of
    them, and nothing is saved after it. The print comes last, off the updated and saved strip."""
    if stp:
        current_d = nx.display_part()
        current_w = nx.work_part()
        try:
            _step("setting up blanks and layouts")
            _set_layers_in_blanks_and_layouts_and_add_dummies(nx.display_part())
        finally:
            nx.set_display_part(current_d)
            nx.set_work_part(current_w)

        _step("preparing for STP")
        _update_for_stp()

    if drawing or copies > 0:
        _step("preparing the drawing sheet")
        # A PDF / DWG needs the one sheet; the print alone skips with a message, as it always has.
        _update_for_pdf(required=drawing)

    _step("saving")
    _save_strip()

    if copies > 0:
        _step("printing")
        _print_drawing(copies, save=False)


def _outgoing_folder(parent_folder: str, name: str) -> str:
    """{parent}\\{name}, refusing a name that is empty or not one plain folder name. An empty Folder Name made the
    outgoing folder the Layout (or Outgoing) folder itself, which the overwrite question then deleted whole."""
    if not name or name in (".", "..") or any(c in name for c in '\\/:*?"<>|'):
        raise ValueError("Folder Name \"{}\" is not a folder name - type one, e.g. {}-Strip.".format(
            name, _todays_date()))
    outgoing = os.path.normpath(os.path.join(parent_folder, name))
    if os.path.normcase(os.path.dirname(outgoing)) != os.path.normcase(os.path.normpath(parent_folder)):
        raise ValueError("\"{}\" is not directly inside \"{}\".".format(outgoing, parent_folder))
    return outgoing


def _print_created(output_path: str) -> None:
    nx.print_("Successfully created \"{}\".".format(output_path) if os.path.isfile(output_path)
              else "Did not successfully create \"{}\".".format(output_path))


def _print_drawing(copies: int, save: bool = True) -> bool:
    """Static.ExportStripPrintDrawing - prints the work part's single sheet to the office MFC, 12x18 landscape
    (11x17 when the printer has no 12x18 paper). Out-of-date views are updated first, and saved unless save is
    False (Export Strip saves once, later). Returns whether views were updated."""
    if copies == 0:
        return False

    work_part = nx.session_.Parts.Work

    print_builder1 = work_part.PlotManager.CreatePrintBuilder()

    try:
        # sql
        print_builder1.ThinWidth = 1.0
        print_builder1.NormalWidth = 2.0
        print_builder1.ThickWidth = 3.0
        print_builder1.Copies = copies
        print_builder1.RasterImages = True
        print_builder1.Output = NXOpen.PrintBuilder.OutputOption.WireframeBlackWhite
        sheets = list(work_part.DrawingSheets)

        if len(sheets) == 0:
            nx.print_("Current work part doesn't not have a sheet to print.")
            _log("print skipped - {} has no drawing sheet".format(work_part.Leaf))
            return False

        if len(sheets) != 1:
            nx.print_("Current work part contains more than 1 sheet.")
            _log("print skipped - {} has {} drawing sheets".format(work_part.Leaf, len(sheets)))
            return False

        nx.session_.ApplicationSwitchImmediate("UG_APP_DRAFTING")
        sheets[0].Open()
        # Python UF: the C# out bool is the return value (not confirmed against the pyd).
        out_of_date = nx.ufsession_.Draw.IsObjectOutOfDate(sheets[0].Tag)
        if out_of_date:
            try:
                nx.ufsession_.Draw.UpdOutOfDateViews(sheets[0].Tag)
                if save:
                    _save(sheets[0].OwningPart, True)
            except Exception as ex:
                nx.print_exception(ex)

        print_builder1.SourceBuilder.SetSheets([sheets[0]])

        print_builder1.PrinterText = _Printer
        print_builder1.Orientation = NXOpen.PrintBuilder.OrientationOption.Landscape
        # NX has no 12x18 PaperSize; a printer's own paper is Custom plus that paper's Windows id (512 on the MFC).
        paper_id = _printer_paper_id(_Printer, _PaperInches)
        if paper_id is not None:
            print_builder1.Paper = NXOpen.PrintBuilder.PaperSize.Custom
            print_builder1.CustomPaper = paper_id
            paper = "{:g}x{:g} (paper id {})".format(_PaperInches[0], _PaperInches[1], paper_id)
        else:
            print_builder1.Paper = NXOpen.PrintBuilder.PaperSize.Inch11x17
            paper = "11x17 (the printer has no {:g}x{:g} paper)".format(_PaperInches[0], _PaperInches[1])
        print_builder1.Commit()
        _log("printed sheet {} of {}: {} copies, {} landscape, to {}{}".format(
            sheets[0].Name, work_part.Leaf, copies, paper, _Printer,
            " (views were out of date, updated)" if out_of_date else ""))
    finally:
        print_builder1.Destroy()
    return bool(out_of_date)


def _printer_paper_id(printer: str, inches: Tuple[float, float]) -> Optional[int]:
    """The Windows paper id (DMPAPER_*; a driver's own papers are 256 and up) of the printer's paper that is inches
    in size either way round, from DeviceCapabilities; None when it has none or the printer cannot be asked."""
    try:
        import ctypes
        winspool = ctypes.WinDLL("winspool.drv")
        device_capabilities = winspool.DeviceCapabilitiesW
        device_capabilities.restype = ctypes.c_int
        device_capabilities.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_ushort, ctypes.c_void_p,
                                        ctypes.c_void_p]
        dc_papers, dc_papersize = 2, 3
        count = device_capabilities(printer, None, dc_papers, None, None)
        if count <= 0:
            return None
        ids = (ctypes.c_ushort * count)()
        sizes = (ctypes.c_long * (2 * count))()  # POINTs, tenths of a millimetre
        device_capabilities(printer, None, dc_papers, ids, None)
        device_capabilities(printer, None, dc_papersize, sizes, None)
        want = sorted(round(i * 254) for i in inches)
        for index in range(count):
            size = sorted((sizes[2 * index], sizes[2 * index + 1]))
            if abs(size[0] - want[0]) <= 5 and abs(size[1] - want[1]) <= 5:
                return int(ids[index])
    except Exception as ex:
        _log("could not read the papers of {}: {}".format(printer, ex))
    return None


# ---------------------------------------------------------------------------------------------------
# Strip preparation
# ---------------------------------------------------------------------------------------------------

def _assembly_path_string(component: NXOpen.Assemblies.Component) -> str:
    """Component.__AssemblyPathString - "{ child, parent, ..., root, }"."""
    result = "{ "
    current: Optional[NXOpen.Assemblies.Component] = component
    while current is not None:
        result += "{}, ".format(current.DisplayName)
        current = current.Parent
    return result + "}"


def _check_assembly_dummy_files() -> None:
    """Static.ExportStripCheckAssemblyDummyFiles"""
    root = nx.display_part().ComponentAssembly.RootComponent

    if root is None:
        return

    for child_of_strip in root.GetChildren():
        if child_of_strip.IsSuppressed:
            continue

        if not isinstance(child_of_strip.Prototype, NXOpen.Part):
            continue

        if not re.search(_Regex_PressAssembly, child_of_strip.DisplayName, re.IGNORECASE):
            continue

        _log("press {}: {} children".format(child_of_strip.DisplayName, len(child_of_strip.GetChildren())))

        if len(child_of_strip.GetChildren()) == 0:
            raise Exception("A press exists in your assembly without any children. {}".format(
                _assembly_path_string(child_of_strip)))

        if len(child_of_strip.GetChildren()) == 1:
            raise Exception(
                "A press exists in your assembly with only one child. Expecting a ram and a bolster. {}".format(
                    _assembly_path_string(child_of_strip)))

        if len(child_of_strip.GetChildren()) != 2:
            continue

        for child_of_press in child_of_strip.GetChildren():
            if not isinstance(child_of_press.Prototype, NXOpen.Part):
                raise Exception("The child of a press must be loaded. {}".format(
                    _assembly_path_string(child_of_press)))

            if child_of_press.IsSuppressed:
                raise Exception("The child of a press cannot be suppressed. {}".format(
                    _assembly_path_string(child_of_press)))

            grand_children = child_of_press.GetChildren()
            if len(grand_children) != 0 and any(
                    not c.IsSuppressed and isinstance(c.Prototype, NXOpen.Part) for c in grand_children):
                continue

            raise Exception("The child of a bolster or ram under a press must be the Dummy file: {}{}".format(
                _DummyPath, _assembly_path_string(child_of_press)))

        break


def _descendants(parent: NXOpen.Assemblies.Component) -> List[NXOpen.Assemblies.Component]:
    """Static.ExportStripDescendants - parent and every component under it, suppressed and unloaded included."""
    _list = [parent]

    for _child in parent.GetChildren():
        _list.extend(_descendants(_child))

    return _list


def _set_layers_in_blanks_and_layouts_and_add_dummies(snap_strip010: NXOpen.Part) -> None:
    """Static.ExportStripSetLayersInBlanksAndLayoutsAndAddDummies - without its saves (the blank, the layout, then
    the strip with its components): _export saves the strip and its components once, afterwards."""
    if not re.search(_Regex_Strip, snap_strip010.Leaf, re.IGNORECASE):
        # ArgumentException(message, paramName).Message
        raise ValueError("Must be an op 010 strip.\r\nParameter name: snapStrip010")

    current_d = nx.display_part()
    current_w = nx.work_part()

    try:
        blank_name_regex = re.compile(r"^BLANK-([0-9]{1,})$")

        layout_name_regex = re.compile(r"^LAYOUT-([0-9]{1,})$")

        layout_part = next(
            (proto for proto in (c.Prototype for c in _descendants(_root(nx.display_part())))
             if isinstance(proto, NXOpen.Part) and re.search(_Regex_Layout, proto.Leaf, re.IGNORECASE)),
            None)

        blank_part = next(
            (proto for proto in (c.Prototype for c in _descendants(_root(nx.display_part())))
             if isinstance(proto, NXOpen.Part) and re.search(_Regex_Blank, proto.Leaf, re.IGNORECASE)),
            None)

        layout_layers: Set[int] = set()

        blank_layers: Set[int] = set()

        for child in _descendants(_root(nx.display_part())):
            if not isinstance(child.Prototype, NXOpen.Part):
                continue

            if child.IsSuppressed:
                continue

            blank_match = blank_name_regex.search(child.Name)

            layout_match = layout_name_regex.search(child.Name)

            if blank_match:
                blank_layers.add(int(blank_match.group(1)) + 10)

            if not layout_match:
                continue

            layer = int(layout_match.group(1)) * 10

            layout_layers.add(layer)

            layout_layers.add(layer + 1)

        _log("blank part {}  layers {}".format(blank_part.Leaf if blank_part else "(none)", sorted(blank_layers)))
        _log("layout part {}  layers {}".format(layout_part.Leaf if layout_part else "(none)", sorted(layout_layers)))

        if len(blank_layers) != 0 and blank_part is not None:
            nx.set_display_part(blank_part)

            nx.set_work_part(nx.display_part())

            _add_dummy(blank_part, blank_layers)

        if len(layout_layers) != 0 and layout_part is not None:
            nx.set_display_part(layout_part)

            nx.set_work_part(nx.display_part())

            _add_dummy(layout_part, layout_layers)
    finally:
        nx.set_display_part(current_d)
        nx.set_work_part(current_w)


def _add_dummy(part: NXOpen.Part, layers: Iterable[int]) -> None:
    """Static.ExportStripAddDummy - shows only the given layers (work layer = the lowest), and adds the Dummy part
    to the work part when the part has no loaded, unsuppressed child."""
    nx.prompt("Setting layers in {}.".format(nx.display_part().Leaf))

    layer_array = list(layers)

    nx.display_part().Layers.WorkLayer = 1

    for i in range(2, 256):
        if i in layer_array:
            nx.display_part().Layers.SetState(i, NXOpen.Layer.State.Selectable)
        else:
            nx.display_part().Layers.SetState(i, NXOpen.Layer.State.Hidden)

    nx.display_part().Layers.SetState(min(layer_array), NXOpen.Layer.State.WorkLayer)

    nx.display_part().Layers.SetState(1, NXOpen.Layer.State.Hidden)

    root = part.ComponentAssembly.RootComponent
    if root is not None:
        valid_child = next(
            (c for c in root.GetChildren() if isinstance(c.Prototype, NXOpen.Part) and not c.IsSuppressed), None)

        if valid_child is not None:
            _log("{}: layers {} shown, work layer {}; has a loaded child, no dummy added".format(
                part.Leaf, sorted(layer_array), min(layer_array)))
            return

    _log("{}: layers {} shown, work layer {}; adding {}".format(part.Leaf, sorted(layer_array), min(layer_array),
                                                                 _DummyPath))
    dummy_part = nx.find_or_open(_DummyPath)

    nx.prompt("Adding dummy file to {}.".format(part.Leaf))

    nx.add_component(nx.work_part(), dummy_part, "Entire Part", "DUMMY", NXOpen.Point3d(0.0, 0.0, 0.0),
                     nx.identity_matrix(), 1)


def _update_for_stp() -> None:
    """Static.ExportStripUpdateForStp - in each child's prototype, makes the layers of its reference set's members
    selectable and unblanks them. Not saved here (the C# saved each prototype): _export saves the strip and its
    components once, afterwards."""
    current_d = nx.display_part()
    current_w = nx.work_part()

    try:
        for child in _root(nx.work_part()).GetChildren():
            if child.IsSuppressed:
                continue

            if not isinstance(child.Prototype, NXOpen.Part):
                continue

            nx.set_display_part(child.Prototype)

            if child.ReferenceSet == "Empty":
                continue

            proto = child.Prototype

            reference_set = next((r for r in proto.GetAllReferenceSets() if r.Name == child.ReferenceSet), None)

            if reference_set is None:
                continue

            objects_in_reference_set = reference_set.AskMembersInReferenceSet()

            for obj in objects_in_reference_set:
                if not isinstance(obj, NXOpen.DisplayableObject):
                    continue

                if obj.Layer <= 1 or obj.Layer >= 256:
                    continue

                if proto.Layers.GetState(obj.Layer) == NXOpen.Layer.State.WorkLayer:
                    continue

                proto.Layers.SetState(obj.Layer, NXOpen.Layer.State.Selectable)

            displayable = [obj for obj in objects_in_reference_set if isinstance(obj, NXOpen.DisplayableObject)]
            nx.session_.DisplayManager.UnblankObjects(displayable)
            _log("STP prep {} ({}): layers {} selectable, {} objects unblanked".format(
                proto.Leaf, child.ReferenceSet, sorted({o.Layer for o in displayable if 1 < o.Layer < 256}),
                len(displayable)))
    finally:
        nx.set_display_part(current_d)
        nx.set_work_part(current_w)


# ---------------------------------------------------------------------------------------------------
# Exporters
# ---------------------------------------------------------------------------------------------------

def _update_for_pdf(required: bool = True) -> None:
    """Static.ExportStripUpdateForPdf - opens the work part's one sheet and updates out-of-date views. Not saved
    here: _export saves the strip and its components once, afterwards. Without exactly one sheet it raises, or, not
    required (only printing), returns and leaves _print_drawing to say why it skips."""
    sheets = list(nx.work_part().DrawingSheets)

    if not required and len(sheets) != 1:
        return

    if len(sheets) == 0:
        raise RuntimeError("Current work part doesn't not have a sheet to print.")

    if len(sheets) != 1:
        raise RuntimeError("Current work part contains more than 1 sheet.")

    nx.session_.ApplicationSwitchImmediate("UG_APP_DRAFTING")
    sheets[0].Open()
    # Python UF: the C# out bool is the return value (not confirmed against the pyd).
    out_of_date = nx.ufsession_.Draw.IsObjectOutOfDate(sheets[0].Tag)
    if out_of_date:
        nx.ufsession_.Draw.UpdOutOfDateViews(sheets[0].Tag)
    _log("PDF prep: sheet {} of {}{}".format(sheets[0].Name, sheets[0].OwningPart.Leaf,
                                                     " (views were out of date, updated)" if out_of_date else ""))


def _export_pdf(out_put_path: str, file_name: str) -> str:
    """Static.ExportStripExportPDF"""
    sheets = list(nx.work_part().DrawingSheets)

    _export_strip_pdf(nx.work_part().FullPath, sheets[0].Name, "{}\\{}.pdf".format(out_put_path, file_name))

    return "{}\\{}.pdf".format(out_put_path, file_name)


def _export_strip_pdf(part_path: str, drawing_sheet_name: str, file_path: str) -> None:
    """Static.ExportStripPdf"""
    if not file_path.endswith(".pdf"):
        raise Exception("File path for PDF must end with \".pdf\".")

    if os.path.isfile(file_path):
        raise Exception("PDF '{}' already exists.".format(file_path))

    part = nx.find_or_open(part_path)

    # We can use SingleOrDefault here because NX will prevent the naming of two drawing sheets the exact same string.
    matches = [s for s in part.DrawingSheets if s.Name == drawing_sheet_name]
    if len(matches) > 1:
        raise RuntimeError("Sequence contains more than one matching element")
    if len(matches) == 0:
        raise Exception("Part '{}' does not have a sheet named '{}'.".format(part_path, drawing_sheet_name))
    sheet = matches[0]

    nx.set_display_part(part)
    nx.set_work_part(nx.display_part())

    pdf_builder = part.PlotManager.CreatePrintPdfbuilder()

    try:
        # sql
        pdf_builder.Scale = 1.0
        pdf_builder.Size = NXOpen.PrintPDFBuilder.SizeOption.ScaleFactor
        pdf_builder.OutputText = NXOpen.PrintPDFBuilder.OutputTextOption.Polylines
        pdf_builder.Units = NXOpen.PrintPDFBuilder.UnitsOption.English
        pdf_builder.XDimension = 8.5
        pdf_builder.YDimension = 11.0
        pdf_builder.RasterImages = True
        pdf_builder.Colors = NXOpen.PrintPDFBuilder.Color.AsDisplayed
        pdf_builder.Watermark = ""
        # Python UF: the C# out bool is the return value (not confirmed against the pyd).
        flag = nx.ufsession_.Draw.IsObjectOutOfDate(sheet.Tag)
        if flag:
            # Not saved: the PDF comes from the session, and the STP translator may be reading the saved parts.
            nx.ufsession_.Draw.UpdOutOfDateViews(sheet.Tag)

        sheet.Open()
        pdf_builder.SourceBuilder.SetSheets([sheet])
        pdf_builder.Filename = file_path
        _log("PDF: sheet {} of {} -> {}{}".format(sheet.Name, part.Leaf, file_path,
                                                 " (views were out of date, updated)" if flag else ""))
        pdf_builder.Commit()
    finally:
        pdf_builder.Destroy()


def _export_strip_stp(outgoing_folder_name: str, wait: bool = True) -> str:
    """Static.ExportStripStp - AP214 STEP of the work part with the all-layers settings file. Returns the path.
    wait=False starts the translator and returns at once (_wait_for_translator waits for the file)."""
    output_path = "{}\\{}-{}.stp".format(outgoing_folder_name, nx.work_part().Leaf, _todays_date())
    _log("STP: {} -> {} with {}".format(nx.work_part().FullPath, output_path, _StepSettingsFile))

    step = nx.session_.DexManager.CreateStepCreator()

    try:
        step.ExportDestination = NXOpen.BaseCreator.ExportDestinationOption.NativeFileSystem

        # sql convert
        # in theory you should just be able to load the settingfile
        # and not set any other step.properties
        step.SettingsFile = _StepSettingsFile

        # Enum member name assumed to match .NET (Ap214); not confirmed in NX Python.
        step.ExportAs = NXOpen.StepCreator.ExportAsOption.Ap214

        step.InputFile = nx.work_part().FullPath

        step.OutputFile = output_path

        step.ProcessHoldFlag = wait

        step.Commit()
    finally:
        step.Destroy()

    if wait:
        _print_created(output_path)
    return output_path


def _export_strip_dwg(outgoing_folder_name: str, file_name: str) -> str:
    """The work part's one drawing sheet as an AutoCAD 2004 DWG (AssemblyExportDesignData's Dwg settings), waiting
    for the translator. _update_for_pdf has already updated and saved the sheet. Returns the path."""
    part = nx.work_part()
    sheets = list(part.DrawingSheets)
    if len(sheets) != 1:
        raise RuntimeError("{} has {} drawing sheets - the DWG needs exactly one.".format(part.Leaf, len(sheets)))

    output_path = "{}\\{}.dwg".format(outgoing_folder_name, file_name)
    if os.path.isfile(output_path):
        os.remove(output_path)

    settings = _dxfdwg_settings_file()
    _log("DWG: sheet {} of {} -> {} with {}".format(sheets[0].Name, part.FullPath, output_path,
                                                   settings or "the translator's default settings"))

    dwg = nx.session_.DexManager.CreateDxfdwgCreator()
    try:
        dwg.AutoCADRevision = NXOpen.DxfdwgCreator.AutoCADRevisionOptions.R2004
        dwg.ViewEditMode = True
        if settings:
            dwg.SettingsFile = settings
        dwg.ExportFrom = NXOpen.DxfdwgCreator.ExportFromOption.ExistingPart
        dwg.OutputFileType = NXOpen.DxfdwgCreator.OutputFileTypeOption.Dwg
        dwg.ObjectTypes.Curves = True
        dwg.ObjectTypes.Annotations = True
        dwg.ObjectTypes.Structures = True
        dwg.FlattenAssembly = False
        dwg.ExportData = NXOpen.DxfdwgCreator.ExportDataOption.Drawing
        dwg.InputFile = part.FullPath
        dwg.ProcessHoldFlag = True
        dwg.OutputFile = output_path
        dwg.WidthFactorMode = NXOpen.DxfdwgCreator.WidthfactorMethodOptions.AutomaticCalculation
        dwg.LayerMask = "1-256"
        dwg.DrawingList = sheets[0].Name
        dwg.Commit()
    finally:
        dwg.Destroy()

    return output_path


def _dxfdwg_settings_file() -> Optional[str]:
    """This NX's dxfdwg\\dxfdwg.def, or None (the translator's defaults) - not the NX 11.0 path
    AssemblyExportDesignData still names."""
    try:
        base = nx.session_.GetEnvironmentVariableValue("UGII_BASE_DIR")
    except Exception:
        base = ""
    for root in (base, "C:\\Program Files\\Siemens\\NX2306.6001"):
        if root and os.path.isfile(os.path.join(root, "dxfdwg", "dxfdwg.def")):
            return os.path.join(root, "dxfdwg", "dxfdwg.def")
    return None


def _wait_for_translator(output_path: str, what: str, timeout: float = 1800.0) -> bool:
    """Waits for a translator started with ProcessHoldFlag False to finish output_path: the file exists, its size
    has not changed for 5 s, and it can be renamed (the translator holds it open while writing). False on timeout."""
    started = time.monotonic()
    last_size = -1
    stable_since = time.monotonic()
    while time.monotonic() - started < timeout:
        time.sleep(1.0)
        try:
            size = os.path.getsize(output_path)
        except OSError:
            continue
        if size != last_size:
            last_size, stable_since = size, time.monotonic()
            continue
        if size == 0 or time.monotonic() - stable_since < 5.0:
            continue
        probe = output_path + ".wait"
        try:
            os.rename(output_path, probe)
            os.rename(probe, output_path)
            return True
        except OSError:
            continue
    _log("{} still not finished after {:.0f}s: {}".format(what, timeout, output_path))
    nx.print_("The {} translator had not finished \"{}\" after {:.0f} minutes.".format(
        what, output_path, timeout / 60))
    return False


def _export_strip_part(outgoing_folder_path: str) -> str:
    """Static.ExportStripPart - 7-zips every loaded, unsuppressed part of the display assembly."""
    assembly_part_paths: List[str] = []
    seen: Set[object] = set()
    for component in nx.descendants(_root(nx.display_part())):
        if component.IsSuppressed:
            continue
        proto = component.Prototype
        if not isinstance(proto, NXOpen.Part) or proto.Tag in seen:
            continue
        seen.add(proto.Tag)
        assembly_part_paths.append(proto.FullPath)

    _log("Part: {} prototype files into NX StripAssembly.7z".format(len(assembly_part_paths)))

    zip_ = _Zip7("{}\\NX StripAssembly.7z".format(outgoing_folder_path), assembly_part_paths)
    zip_.start()
    zip_.wait_for_exit()
    return "{}\\NX StripAssembly.7z".format(outgoing_folder_path)


class _Zip7(object):
    """ExportStrip.Zip7 - "7z a -t7z <archive> @<list> -mx9" in a visible console."""

    def __init__(self, zip_archive: str, files_to_zip: List[str]) -> None:
        self._zip_archive = zip_archive
        self._files_to_zip = files_to_zip
        self._process: Optional[subprocess.Popen] = None
        self._started = False

    def wait_for_exit(self) -> None:
        """Waits for 7-Zip and raises when it failed; a warning (some files skipped) is printed and logged."""
        if self._process is None:
            raise ValueError("Value cannot be null.\r\nParameter name: _process")

        if not self._started:
            raise RuntimeError("Zip process hasn't been started yet.")

        code = self._process.wait()
        _log("7-Zip exit code {} for {}".format(code, self._zip_archive))

        if code == _SevenZipWarning:
            nx.print_("7-Zip finished with warnings for \"{}\" - some files may not be in it.".format(
                self._zip_archive))
        elif code != 0:
            raise RuntimeError("7-Zip failed (exit code {}) making \"{}\".".format(code, self._zip_archive))

    def start(self) -> None:
        # Path.GetTempPath() ends with a backslash. Like the C#, the list file is never deleted.
        temp_file = "{}zipData{}.txt".format(os.path.join(tempfile.gettempdir(), ""), id(self._files_to_zip))

        # StreamWriter: UTF-8 without a BOM, WriteLine = CRLF.
        with open(temp_file, "w", encoding="utf-8", newline="\r\n") as writer:
            for f in self._files_to_zip:
                writer.write(f + "\n")

        # select
        command = '"{}" a -t7z "{}" "@{}" -mx9'.format(_SevenZip, self._zip_archive, temp_file)
        _log("7-Zip: {} ({} files listed)".format(command, len(self._files_to_zip)))
        self._process = subprocess.Popen(command)

        self._started = True


# ---------------------------------------------------------------------------------------------------
# Small helpers (no tsg_nx equivalent yet)
# ---------------------------------------------------------------------------------------------------

# The progress window while an export runs (_run), else None.
_progress: Optional[progress_window.ProgressWindow] = None
_progress_title = ""
_progress_step = ""


def _log(message: str) -> None:
    """A line in the NX syslog (not the listing window), under the run's START / END banners - and in the progress
    window."""
    nx.syslog("ExportStrip: {}".format(message))
    if _progress is not None:
        _progress.write_line(message)


def _step(step: str) -> None:
    """The progress window's title: Export Strip - {step}."""
    global _progress_step
    _progress_step = step
    if _progress is not None:
        _progress.set_title("{} - {}".format(_progress_title, step))


def _size(path: str) -> str:
    try:
        return "{:,} bytes".format(os.path.getsize(path))
    except OSError:
        return "missing"


def _log_file(what: str, path: str, started: float) -> None:
    """One export step's result: the file, its size (or missing) and how long it took."""
    _log("{} done in {:.1f}s: {} ({})".format(what, time.monotonic() - started, path, _size(path)))


def _root(part: NXOpen.BasePart) -> NXOpen.Assemblies.Component:
    """part.ComponentAssembly.RootComponent where the C# assumes an assembly (an NRE there, AttributeError here)."""
    return cast(NXOpen.Assemblies.Component, part.ComponentAssembly.RootComponent)


def _save_strip() -> None:
    """Export Strip's one save: the display part (the strip) with its components - every part the preparation
    changed (the blank and layout, the STP children, the drawing sheet's part) is in its assembly. Logs which parts
    were modified."""
    strip = nx.display_part()
    modified = [p.Leaf for p in nx.session_.Parts if getattr(p, "IsModified", False)]
    nx.prompt("Saving: {} and its components.".format(strip.Leaf))
    started = time.monotonic()
    _save(strip, True)
    _log("saved {} and its components in {:.1f}s - {} modified part(s): {}".format(
        strip.Leaf, time.monotonic() - started, len(modified), ", ".join(modified) or "(none)"))


def _save(part: NXOpen.BasePart, save_components: bool) -> None:
    """BasePart.Save(SaveComponents, CloseAfterSave.False). Python enum members are TrueValue/FalseValue."""
    part.Save(NXOpen.BasePart.SaveComponents.TrueValue if save_components
              else NXOpen.BasePart.SaveComponents.FalseValue,
              NXOpen.BasePart.CloseAfterSave.FalseValue)


def _yes_no(title: str, message: str) -> bool:
    """MessageBox.Show(message, title, YesNo) == Yes, as an NX Question box."""
    return nx.message_box(title, NXOpen.NXMessageBox.DialogType.Question, message) \
        == _MessageBoxYes


def _get_files(directory: str) -> List[str]:
    """Directory.GetFiles(directory) - full paths of the files directly in the folder."""
    return [os.path.join(directory, entry.name) for entry in os.scandir(directory) if entry.is_file()]


def _todays_date() -> str:
    """Extensions.TodaysDate - yyyy-MM-dd."""
    today = datetime.date.today()
    return "{}-{:02d}-{:02d}".format(today.year, today.month, today.day)


class _GFolder(object):
    """GFolder (src\\Utilities\\GFolder.cs) - the members ExportStrip reads, plus the ones AssemblyExportDesignData.py
    imports it for (DirDesignInformation, DirStocklist, CtsNumber, is_cts_job, dir_op, file_strip)."""

    def __init__(self, dir_job: str, customer_number: str) -> None:
        self.DirJob = dir_job
        self.CustomerNumber = customer_number

    @property
    def DirLayout(self) -> str:
        """GFolder.DirLayout"""
        return "{}\\Layout".format(self.DirJob)

    @property
    def DirOutgoing(self) -> str:
        """GFolder.DirOutgoing"""
        return "{}\\Outgoing".format(self.DirJob)

    @property
    def DirProcessSimDataDesign(self) -> str:
        """GFolder.DirProcessSimDataDesign"""
        return "{}\\Process and Sim Data for Design".format(self.DirJob)

    @property
    def DirSimulation(self) -> str:
        """GFolder.DirSimulation (ExportSimPackage.py)"""
        return "{}\\Simulation".format(self.DirJob)

    @property
    def DirDesignInformation(self) -> str:
        """GFolder.DirDesignInformation"""
        return "{}\\Design Information".format(self.DirJob)

    @property
    def DirStocklist(self) -> str:
        """GFolder.DirStocklist"""
        return "{}\\NX Stocklist".format(self.DirDesignInformation)

    @property
    def CtsNumber(self) -> str:
        """GFolder.CtsNumber - raises where the C# throws FormatException."""
        # Path.GetFileNameWithoutExtension(DirJob)
        dir_leaf = os.path.splitext(self.DirJob.split("\\")[-1])[0]
        match = re.match(r"^\d+ \([a-zA-Z]+-(?P<cts>\d+)\)$", dir_leaf)
        if not match:
            raise ValueError("Could not find a cts number: {}".format(self.DirJob))
        return match.group("cts")

    def is_cts_job(self) -> bool:
        """GFolder.is_cts_job"""
        return "\\cts\\" in self.DirJob.lower()

    def dir_op(self, op: str) -> str:
        """GFolder.dir_op"""
        return "{}\\{}-{}".format(self.DirJob, self.CustomerNumber, op)

    def file_strip(self, op: str) -> str:
        """GFolder.file_strip"""
        return "{}\\{}-{}-Strip.prt".format(self.DirLayout, self.CustomerNumber, op)

    @staticmethod
    def create(job_folder: str) -> "_GFolder":
        """GFolder.Create(string)"""
        split = job_folder.split("\\")

        if len(split) < 3:
            # C#: IndexOutOfRangeException(jobFolder)
            raise IndexError(job_folder)

        directory = "{}\\{}\\{}".format(split[0], split[1], split[2])
        number = _GFolder._job_number(directory, split[2])
        if number:
            return _GFolder(directory, number)

        # Not the C#: a job copied below the usual depth (G:\CTS\junk\Mark B\006073\006073-010\...) has no job
        # number in the third piece, so the job folder is the first deeper folder whose name starts with one.
        for i in range(3, len(split) - 1):
            deeper = "\\".join(split[:i + 1])
            number = _GFolder._job_number(deeper, split[i])
            if number:
                return _GFolder(deeper, number)

        if "\\cts\\" not in directory.lower():
            return _GFolder(directory, "")

        raise ValueError("Could not make GFolder from '{}'".format(job_folder))

    @staticmethod
    def _job_number(directory: str, leaf: str) -> Optional[str]:
        """GFolder.Create's rules for the job folder `directory` named `leaf`: its customer number, or None."""
        if "\\cts\\" not in directory.lower():
            match0 = re.match(r"^(?P<num_0>\d{2,})", leaf)
            return match0.group("num_0") if match0 else None

        if _int_try_parse(leaf):
            return leaf

        match = re.match(r"^(?P<cts_number>\d{2,}) \([A-Z]+-[xX]+\)", leaf)
        if match:
            return match.group("cts_number")

        match = re.match(r"^(?P<cts_number>\d{2,}) \([A-Za-z]+-(?P<customer_number>\d+)\)", leaf)
        if match:
            return match.group("customer_number")

        match = re.match(r"^(?P<customer_number>\d{2,})", leaf)
        if match:
            return match.group("customer_number")

        return None


def _int_try_parse(text: str) -> bool:
    """int.TryParse(string, out _) with the default NumberStyles.Integer."""
    match = re.match(r"^\s*([+-]?\d+)\s*$", text)
    if match is None:
        return False
    try:
        value = int(match.group(1))
    except ValueError:
        return False
    return -2147483648 <= value <= 2147483647


# ---------------------------------------------------------------------------------------------------
# The export-strip UFunc: a modal dialog (ExportStrip.dlx) in place of the SNAP ExportStripDialog
# ---------------------------------------------------------------------------------------------------

# _UFunc.ufunc_export_strip
ufunc_export_strip = "export-strip"

# NX will not build a Block Styler dialog from inside some callbacks (a menu or toolbar launch, it seems).
_ErrorCannotLaunchDialog = 3520048


class _ExportStripDialog(Dialog):
    """
    The old form's inputs: Export NX Part / STP / PDF (ticked), Print Copies, Folder Name (the form's default) and
    Copy to \\Process and Sim Data for Design. OK is greyed out, as the form's Accept was, until Part, STP or PDF is
    ticked or a copy count is set - Copy alone does not count, since the export returns before the zip without one.
    """

    dlx_name = "ExportStrip.dlx"

    def __init__(self, title: str, default_folder_name: str) -> None:
        self.title = title
        super().__init__()
        self._default_folder_name = default_folder_name
        # Captured in ok(): the blocks are gone once Launch returns.
        self.part = self.stp = self.pdf = self.copy = self.dwg = False
        self.copies = 0
        self.folder_name = ""

    def initialize(self) -> None:
        # Also in the .dlx, but NX keeps the first copy of a .dlx it loads for the rest of the session, so a label
        # changed there only shows after a restart. Set here, it shows on the next run.
        self.block("copies").Label = "Print:"

    def shown(self) -> None:
        # Every run opens on the form's defaults, not the last run's values.
        self.block("part").Value = True
        self.block("stp").Value = True
        self.block("pdf").Value = True
        self.block("dwg").Value = False
        self.block("copies").Value = 0
        self.set_string_value(self.block("folder_name"), self._default_folder_name)
        self.block("copy").Value = False

    def enable_ok(self) -> bool:
        exporting = (bool(self.block("part").Value) or bool(self.block("stp").Value)
                     or bool(self.block("pdf").Value) or bool(self.block("dwg").Value))
        # An export needs a folder name: an empty one used to make the Layout folder itself the outgoing folder.
        if exporting and not self.string_value(self.block("folder_name")):
            return False
        return exporting or int(self.block("copies").Value) > 0

    def ok(self) -> bool:
        self.part = bool(self.block("part").Value)
        self.stp = bool(self.block("stp").Value)
        self.pdf = bool(self.block("pdf").Value)
        self.dwg = bool(self.block("dwg").Value)
        self.copies = int(self.block("copies").Value)
        self.folder_name = self.string_value(self.block("folder_name"))
        self.copy = bool(self.block("copy").Value)
        return True


def _run() -> None:
    """ExportStrip.execute (the C# _UFunc, deleted): the dialog, then export with what it captured. The progress
    window opens once the dialog is accepted, so it does not sit on top of it."""
    global _progress, _progress_title
    title = "Export Strip"

    try:
        default_name = ExportStrip.default_name()
        dialog = _ExportStripDialog(title_with_version(title), default_name)
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

    # enable_ok greys OK out in this case; a backstop.
    if not dialog.part and not dialog.stp and not dialog.pdf and not dialog.dwg and dialog.copies == 0:
        nx.print_("{}: nothing to do - tick Part, STP, PDF or DWG, or set a number of print copies.".format(title))
        return

    _progress_title = title_with_version(title)
    _progress = progress_window.ProgressWindow(_progress_title, "ExportStrip", progress_window.BottomRight)
    try:
        _step("starting")
        _log("dialog: part {}  stp {}  pdf {}  dwg {}  print copies {}  copy to sim data {}  folder name '{}' ({})".format(
            dialog.part, dialog.stp, dialog.pdf, dialog.dwg, dialog.copies, dialog.copy, dialog.folder_name,
            "the default" if dialog.folder_name == default_name else "typed"))

        ExportStrip.export(dialog.stp, dialog.copies, dialog.part, dialog.pdf, dialog.folder_name, dialog.copy,
                           dialog.dwg)
    finally:
        _progress.stop_following()
        _progress = None


def main() -> None:
    """The export-strip UFunc - its menu button runs this file. An escaping exception is printed."""
    import usage_db

    with usage_db.run(ufunc_export_strip):
        try:
            _run()
        except Exception as ex:
            nx.print_exception(ex)


if __name__ == "__main__":
    main()

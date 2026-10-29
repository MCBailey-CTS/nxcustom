"""
The per-file exports of Assembly Export Design Data (AssemblyExportDesignDataExport1.Stp / Pdf / Dwg / SetLayers),
moved out of AssemblyExportDesignData.py (2026-10-23) so the headless export workers (export_worker.py, run by
export_pool.py) can run them too. Imports only NXOpen and tsg_nx: nothing here may need the NX UI, which a
run_journal session does not have.

A job is a plain dict, so it can be pickled to a worker:
    {"id": int, "kind": "stp" | "pdf" | "dwg", "part": full path, "output": path, "settings": .def (stp),
     "sheet": drawing sheet name (pdf / dwg), "label": what the listing window calls it}
run_job runs one in this session and returns None, or the error text.
"""

from __future__ import annotations

import os
import time
import traceback
from typing import Any, Dict, List, Optional, Sequence, cast

import NXOpen
import NXOpen.Layer

import tsg_nx as nx

# The layers SetLayers leaves selectable (everything else from 2 to 256 is hidden; 1 is the work layer).
Layers = (1, 94, 100, 111, 200, 230)

# The C# pointed at "C:\Program Files\Siemens\NX 11.0\dxfdwg\dxfdwg.def", which is not on these machines; the
# running NX's own copy, as ExportStrip._dxfdwg_settings_file does.
_DxfDwgFallback = "C:\\Program Files\\Siemens\\NX2306.6001\\DXFDWG\\dxfdwg.def"

Job = Dict[str, Any]


def dxfdwg_settings_file() -> str:
    base = os.environ.get("UGII_BASE_DIR", "")
    candidate = os.path.join(base, "DXFDWG", "dxfdwg.def") if base else ""
    return candidate if candidate and os.path.isfile(candidate) else _DxfDwgFallback


def set_layers() -> None:
    """AssemblyExportDesignDataExport1.SetLayers - the display part: 1 work, Layers selectable, the rest hidden."""
    disp = nx.display_part()
    disp.Layers.SetState(1, NXOpen.Layer.State.WorkLayer)

    for i in range(2, 257):
        if i in Layers:
            disp.Layers.SetState(i, NXOpen.Layer.State.Selectable)
        else:
            disp.Layers.SetState(i, NXOpen.Layer.State.Hidden)


def _save(part: NXOpen.BasePart) -> None:
    part.Save(NXOpen.BasePart.SaveComponents.TrueValue, NXOpen.BasePart.CloseAfterSave.FalseValue)


def _sheet(part: NXOpen.Part, drawing_sheet_name: str) -> NXOpen.Drawings.DrawingSheet:
    # NX will not let two drawing sheets share a name.
    matches = [s for s in part.DrawingSheets if s.Name == drawing_sheet_name]
    if len(matches) > 1:
        raise RuntimeError("Sequence contains more than one matching element")
    if len(matches) == 0:
        raise ValueError("Part \"{}\" does not have a sheet named \"{}\".\r\nParameter name: drawingSheetName".format(
            part.Leaf, drawing_sheet_name))
    return matches[0]


def stp(part_path: str, output_path: str, settings_file: str, open_part: bool = True) -> None:
    """
    AssemblyExportDesignDataExport1.Stp - AP214 STEP of layers 1 and 96 of the saved part file; prints any
    exception instead of raising. The translator reads the file from disk, so a worker passes open_part=False
    rather than load the part (and, for the -000, the whole assembly) for nothing.
    """
    try:
        _stp(part_path, output_path, settings_file, open_part)
    except Exception as ex:
        nx.print_exception(ex)


def _stp(part_path: str, output_path: str, settings_file: str, open_part: bool) -> None:
    if not output_path.endswith(".stp"):
        raise RuntimeError("File path for STP must end with \".stp\".")

    if os.path.isfile(output_path):
        raise ValueError("STP \"{}\" already exists.\r\nParameter name: output_path".format(output_path))

    if not os.path.isfile(part_path):
        raise FileNotFoundError("Could not find file location \"{}\".".format(part_path))

    if open_part:
        nx.find_or_open(part_path)

    step_creator = nx.session_.DexManager.CreateStepCreator()

    try:
        step_creator.ExportAs = NXOpen.StepCreator.ExportAsOption.Ap214
        step_creator.SettingsFile = settings_file
        step_creator.ObjectTypes.Solids = True
        step_creator.OutputFile = output_path
        step_creator.BsplineTol = 0.0254
        step_creator.ObjectTypes.Annotations = True
        step_creator.ExportFrom = NXOpen.StepCreator.ExportFromOption.ExistingPart
        step_creator.InputFile = part_path
        step_creator.FileSaveFlag = False
        step_creator.LayerMask = "1, 96"
        step_creator.ProcessHoldFlag = True
        step_creator.Commit()
    finally:
        step_creator.Destroy()

    switch_file_path = output_path.replace(".stp", ".log")

    if os.path.isfile(switch_file_path):
        os.remove(switch_file_path)


# ----- STEP batches: one translator run for several parts -----
#
# NX's StepCreator writes a temporary copy of the .def and runs `step214ug.exe d="<that copy>"` with no input
# argument: the part goes in PROCESS_PART_LIST and the output in INDIVIDUAL_LIST. Both take comma-separated lists,
# so one run (whose ~5-6 s start-up is most of a small part's export time) can translate several parts. The
# overrides below are the ones StepCreator made to ExternalStep_Detail.def for _stp's settings (captured from a
# run on 2026-10-23); its output was identical to StepCreator's apart from the file name and time stamp.
_StepOverrides = (
    ("APPLICATION_PROTOCOL", "AP214"),
    ("AP203_COLLAY_EXT", "Off"),
    ("AP242_VERSION", "EDITION2"),
    ("UGI_LAYER_MASK", "1, 96"),                                 # LayerMask = "1, 96"
    ("PA_EDGE_FACE_BSPLINE_APPROX_TOL", "0.64516000000"),        # BsplineTol = 0.0254, as StepCreator writes it
)

_StepTranslatorFallback = "C:\\Program Files\\Siemens\\NX2306.6001\\STEP214UG\\step214ug.exe"


def step_translator() -> str:
    base = os.environ.get("UGII_BASE_DIR", "")
    candidate = os.path.join(base, "STEP214UG", "step214ug.exe") if base else ""
    return candidate if candidate and os.path.isfile(candidate) else _StepTranslatorFallback


def write_step_batch_def(settings_file: str, parts: Sequence[str], outputs: Sequence[str], log_file: str,
                         def_path: str) -> None:
    """
    The .def for one batch translator run: settings_file with StepCreator's overrides and the lists. FILE_FILTER is
    the parts' folder, as StepCreator sets it: left at the .def's H:\\*.prt the translator finds "No parts in current
    input file". So the parts of one run must share a folder (export_pool groups them that way).
    """
    with open(settings_file, "r", encoding="utf-8-sig") as f:
        lines = [line.rstrip("\r\n") for line in f]

    values: Dict[str, str] = dict(_StepOverrides)
    values["FILE_FILTER"] = os.path.join(os.path.dirname(parts[0]), "*.prt")
    values["LOG_FILE"] = log_file
    values["PROCESS_PART_LIST"] = ",".join(parts)
    values["INDIVIDUAL_LIST"] = ",".join(outputs)

    written = set()
    out = []
    for line in lines:
        key = line.split("=", 1)[0].strip()
        if "=" in line and key in values:
            out.append("{}={}".format(key, values[key]))
            written.add(key)
        else:
            out.append(line)
    out.extend("{}={}".format(k, v) for k, v in values.items() if k not in written)

    with open(def_path, "w", encoding="ascii", errors="replace") as f:
        f.write("\n".join(out) + "\n")


def pdf(part: NXOpen.Part, drawing_sheet_name: str, file_path: str, save_updated: bool = True) -> None:
    """
    AssemblyExportDesignDataExport1.Pdf - the sheet as a black-on-white PDF, after updating out-of-date views.
    The part becomes the display and work part. save_updated=False (a worker) prints the updated views without
    saving them: the main session owns the parts and saved them before the exports started.
    """
    if not file_path.endswith(".pdf"):
        raise RuntimeError("File path for PDF must end with \".pdf\".")

    if os.path.isfile(file_path):
        raise ValueError("PDF \"{}\" already exists.\r\nParameter name: output_path".format(file_path))

    sheet = _sheet(part, drawing_sheet_name)

    nx.set_display_part(part)
    nx.set_work_part(nx.display_part())  # Session.__SetDisplayToWork
    set_layers()

    pdf_builder = part.PlotManager.CreatePrintPdfbuilder()

    try:
        pdf_builder.Scale = 1.0
        pdf_builder.Size = NXOpen.PrintPDFBuilder.SizeOption.ScaleFactor
        pdf_builder.OutputText = NXOpen.PrintPDFBuilder.OutputTextOption.Polylines
        pdf_builder.Units = NXOpen.PrintPDFBuilder.UnitsOption.English
        pdf_builder.XDimension = 8.5
        pdf_builder.YDimension = 11.0
        pdf_builder.RasterImages = True
        pdf_builder.Colors = NXOpen.PrintPDFBuilder.Color.BlackOnWhite
        pdf_builder.Watermark = ""
        # Python UF: the C# out bool is the return value.
        flag = nx.ufsession_.Draw.IsObjectOutOfDate(sheet.Tag)

        if flag:
            nx.ufsession_.Draw.UpdOutOfDateViews(sheet.Tag)
            if save_updated:
                _save(part)

        sheet.Open()
        pdf_builder.SourceBuilder.SetSheets([sheet])
        pdf_builder.Filename = file_path
        pdf_builder.Commit()
    finally:
        pdf_builder.Destroy()


def dwg(part_path: str, drawing_sheet_name: str, file_path: str, save_updated: bool = True) -> None:
    """AssemblyExportDesignDataExport1.Dwg - an AutoCAD 2004 DWG of the named sheet. The log clean-up is
    file_path.replace(".dwg", ".log"): on the 4-View export's ".pdf" path that is the output file itself, so the
    finished file is deleted again - preserved from the C#. save_updated as in pdf."""
    if os.path.isfile(file_path):
        os.remove(file_path)

    part = nx.find_or_open(part_path)
    sheet = _sheet(part, drawing_sheet_name)

    flag = nx.ufsession_.Draw.IsObjectOutOfDate(sheet.Tag)

    if flag:
        set_layers()
        nx.ufsession_.Draw.UpdOutOfDateViews(sheet.Tag)
        if save_updated:
            _save(part)

    dxfdwg_creator1 = nx.session_.DexManager.CreateDxfdwgCreator()
    try:
        dxfdwg_creator1.AutoCADRevision = NXOpen.DxfdwgCreator.AutoCADRevisionOptions.R2004
        dxfdwg_creator1.ViewEditMode = True
        dxfdwg_creator1.SettingsFile = dxfdwg_settings_file()
        dxfdwg_creator1.ExportFrom = NXOpen.DxfdwgCreator.ExportFromOption.ExistingPart
        dxfdwg_creator1.OutputFileType = NXOpen.DxfdwgCreator.OutputFileTypeOption.Dwg
        dxfdwg_creator1.ObjectTypes.Curves = True
        dxfdwg_creator1.ObjectTypes.Annotations = True
        dxfdwg_creator1.ObjectTypes.Structures = True
        dxfdwg_creator1.FlattenAssembly = False
        dxfdwg_creator1.ExportData = NXOpen.DxfdwgCreator.ExportDataOption.Drawing
        dxfdwg_creator1.InputFile = part.FullPath
        dxfdwg_creator1.ProcessHoldFlag = True
        dxfdwg_creator1.OutputFile = file_path
        dxfdwg_creator1.WidthFactorMode = NXOpen.DxfdwgCreator.WidthfactorMethodOptions.AutomaticCalculation
        dxfdwg_creator1.LayerMask = "1-256"
        dxfdwg_creator1.DrawingList = drawing_sheet_name
        dxfdwg_creator1.Commit()
    finally:
        dxfdwg_creator1.Destroy()

    switch_file_path = file_path.replace(".dwg", ".log")

    if os.path.isfile(switch_file_path):
        os.remove(switch_file_path)


def update_part(part: NXOpen.Part, casting: bool, save_components: bool,
                timings: Optional[Dict[str, float]] = None) -> List[str]:
    """
    One part of AssemblyExportDesignDataExport1.UpdateParts: display it, set the export layers, unblank what is
    on them, update the drafting views, back to modeling, save. Returns the warnings it would have printed. No cue
    line: a run_journal worker has no UI. Layers can only be read or set on the DISPLAYED part ("This operation
    can only be performed on a displayed part"), which is why each part is displayed in turn - and why the export
    workers, each displaying its own part, can do this several parts at a time. timings, when given, gets each
    step's seconds (display, layers, unblank, views, modeling, save) and the view and object counts.
    """
    messages: List[str] = []
    lap = _Laps(timings)
    nx.set_display_part(part)
    nx.set_work_part(nx.display_part())
    lap("display")

    if casting and part.ComponentAssembly.RootComponent is not None:
        # If it is a casting then it cannot contain a child that is a lift lug and set to entire part.
        lift_lugs = [child for child in nx.children(part)
                     if isinstance(child.Prototype, NXOpen.Part)
                     and "LiftLugs" in child.Prototype.FullPath
                     and child.ReferenceSet != nx.RefsetEmpty]
        if any(child.ReferenceSet == nx.RefsetEntirePart for child in lift_lugs):
            messages.append("Casting part {} contains a Lift Lug that is set to Entire Part. "
                            "Casting Part cannot be made.".format(part.Leaf))

    set_layers()
    lap("layers")
    objects: List[NXOpen.DisplayableObject] = []

    for layer in Layers:
        objects.extend(o for o in nx.display_part().Layers.GetAllObjectsOnLayer(layer)
                       if isinstance(o, NXOpen.DisplayableObject))

    nx.session_.DisplayManager.UnblankObjects(objects)
    lap("unblank", objects=len(objects))

    views = list(nx.display_part().DraftingViews)
    for view in views:
        view.Update()
    lap("views", views=len(views))

    try:
        nx.session_.ApplicationSwitchImmediate("UG_APP_MODELING")
        nx.work_part().Drafting.ExitDraftingApplication()
    except NXOpen.NXException as ex:
        # A run_journal session has no applications to switch between; the save does not need it.
        messages.append("{}: could not switch back to modeling ({})".format(part.Leaf, ex))
    lap("modeling")

    part.Save(NXOpen.BasePart.SaveComponents.TrueValue if save_components
              else NXOpen.BasePart.SaveComponents.FalseValue,
              NXOpen.BasePart.CloseAfterSave.FalseValue)
    lap("save")
    return messages


class _Laps(object):
    """Adds the seconds since the last call to timings[name] (and any counts given); does nothing without one."""

    def __init__(self, timings: Optional[Dict[str, float]]) -> None:
        self.timings = timings
        self.last = time.monotonic()

    def __call__(self, name: str, **counts: int) -> None:
        now = time.monotonic()
        if self.timings is not None:
            self.timings[name] = self.timings.get(name, 0.0) + now - self.last
            for key, value in counts.items():
                self.timings[key] = self.timings.get(key, 0) + value
        self.last = now


def run_detail(job: Job, worker: bool = False) -> Dict[str, Any]:
    """
    A "detail" job: open the part, update and save it (update_part), then its PDF / DWG exports while it is open
    and current. Returns {"error": the update's error or None, "messages": [...], "exports": {export job id:
    error or None}}. A worker saves the detail alone (not its components: two workers saving a shared library
    part at once is not a risk worth taking - the main session's save of the display part covers components) and
    closes everything afterwards.
    """
    timings: Dict[str, float] = {}
    result: Dict[str, Any] = {"error": None, "messages": [], "exports": {}, "timings": timings}
    lap = _Laps(timings)
    try:
        timings["mb"] = os.path.getsize(job["part"]) / 1e6
    except OSError:
        pass
    try:
        try:
            part = nx.find_or_open(job["part"])
            lap("open", loaded=sum(1 for _p in nx.session_.Parts))
            result["messages"] = update_part(part, bool(job.get("casting")), save_components=not worker,
                                             timings=timings)
            lap = _Laps(timings)
        except Exception as ex:
            result["error"] = "{}: {}\n{}".format(type(ex).__name__, ex, traceback.format_exc())

        for export in job.get("exports", []):
            try:
                if export["kind"] == "pdf":
                    pdf(nx.find_or_open(export["part"]), export["sheet"], export["output"], save_updated=False)
                elif export["kind"] == "dwg":
                    dwg(export["part"], export["sheet"], export["output"], save_updated=False)
                elif export["kind"] == "stp":
                    # Only with no translator runs (ExportPool translators=0): after the save, through StepCreator.
                    _stp(export["part"], export["output"], export["settings"], open_part=False)
                else:
                    raise ValueError("A detail job cannot run a '{}' export".format(export["kind"]))
                written = os.path.isfile(export["output"]) or export["output"].endswith(".pdf") and \
                    export["kind"] == "dwg"
                result["exports"][export["id"]] = None if written else "no file was written"
            except Exception as ex:
                result["exports"][export["id"]] = "{}: {}\n{}".format(type(ex).__name__, ex, traceback.format_exc())
            lap(export["kind"])
    finally:
        if worker:
            try:
                cast(Any, nx.session_.Parts).CloseAll(NXOpen.BasePart.CloseModified.CloseModified, None)
            except Exception:
                pass
            lap("close")
    return result


def run_job(job: Job, worker: bool = False) -> Optional[str]:
    """
    Runs one job in this session; None when it worked, else the error text. A worker does not open parts for a
    STEP, does not save updated drawing views, and closes every part afterwards; the main session keeps its parts
    loaded and its display part as the caller's display_part_reset leaves it.
    """
    kind = job["kind"]
    try:
        if kind == "stp":
            _stp(job["part"], job["output"], job["settings"], open_part=not worker)
        elif kind == "pdf":
            pdf(nx.find_or_open(job["part"]), job["sheet"], job["output"], save_updated=not worker)
        elif kind == "dwg":
            dwg(job["part"], job["sheet"], job["output"], save_updated=not worker)
        else:
            raise ValueError("Unknown export job kind '{}'".format(kind))
        if not os.path.isfile(job["output"]) and not (kind == "dwg" and job["output"].endswith(".pdf")):
            return "no file was written"
        return None
    except Exception as ex:
        return "{}: {}\n{}".format(type(ex).__name__, ex, traceback.format_exc())
    finally:
        if worker:
            try:
                cast(Any, nx.session_.Parts).CloseAll(NXOpen.BasePart.CloseModified.CloseModified, None)
            except Exception:
                pass

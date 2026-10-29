"""
The assembly-auto-detail UFunc as a Block UI Styler dialog: a port of the C# AutoDetail form
(src\\UFuncs\\AutoDetail.cs) and its Static methods (src\\Static\\AutoDetail.cs). Its menu button runs this file's
main(). NEVER RUN IN NX YET.

The dialog (AutoDetail.dlx, tools\\make-dlx.py) replaces the form:
  - Options      - the form's eight check boxes, same names. As on the form, Hole Charting and Drill Charting
                   exclude each other, and Delete All 4-Views unticks Hole Charting / Update All Views (and Create
                   Detail Sheet when ticked) and greys those three out. Hole Charting, Create Detail Sheet, Update All
                   Views and Delete All 4-Views open unticked every time (the form's SetFormDefaults); the other four
                   are left to dialog memory.
  - Components   - "Select all" is the form's Select All button: every loaded, unsuppressed {job}-{op}-{detail}
                   component under the display part whose MATERIAL is one of ConceptControlFile.ucf's
                   COMPONENT_MATERIALS, or whose DESCRIPTION is CHUTE TO SUIT / contains diemaker to alter. The C#
                   then let you deselect some in a preselected class-selection dialog (Preselect.GetUserSelections);
                   here the component picker opens holding that list instead, to deselect or add to.
                   "Select components" is the form's Select button: the picker starts empty, pick what to detail.
  - Border file  - the 4-VIEW border part imported into each sheet; starts as ConceptControlFile.ucf's
                   BORDER_FILE_LOCATION. Browse is the form's Select Border File button (a file box on
                   G:\\0Library\\Drafting); cancelling it puts the .ucf default back, as the form did.
OK is greyed out until one of Hole Charting / Drill Charting / Create Detail Sheet / Update All Views / Delete All
4-Views is ticked and at least one component is picked (the form's Select / Select All buttons were disabled until
one of those was ticked). The work runs after the dialog closes, with what ok() captured.

Then each component, sorted by name, distinct by display name, unsuppressed, gets AutoDetailDetailComponent: made
the display part, CleanBodyRefSet, WCS onto its DYNAMIC BLOCK, shading, BODY curves off layer 1, and then, as ticked,
the hole-chart notes, the 4-VIEW sheet (border import, plan / right / bottom views, the overall dimensions, the
GRUMBLEGRUMBLE drill chart note and DTS_FILE_PATH note, the STANDARD / WAITING FOR FINAL TRIM notes), the out-of-date
sheet updates and the 4-VIEW delete. Each component is caught on its own, like the C#; the display and work parts
are put back afterwards.

Kept from the C# (quirks included):
  - No undo mark of its own; the hole-chart notes and the borderScale expression are made under the C#'s invisible /
    DoUpdate marks.
  - Hole charting: the LAST hole-size key whose diameter matches wins (the C# breaks only the inner loop); a
    HOLECHART face with no match gets a note with no text, which raises and ends that part's hole charting.
  - The 4-VIEW sheet's size comes from the layer-1 body alone: the C# measures the layer-111 bodies and never uses
    the result, so this does not measure them.
  - The bottom view's min-Y / max-Y dimension points and the right view's are picked from the end points exactly as
    the C#'s nested ternaries do (they reduce to plain min / max picks, written that way here).
  - A part whose DESCRIPTION is NITROGEN PLATE SYSTEM gets its 4-VIEW without dimensions or the note clean-up.
  - The drill chart (Static.AutoDetailDrillChart, [Obsolete] in C# but called) is ported as is, from
    U:\\nxFiles\\UfuncFiles\\HoleChart.txt.

Not ported: AutoDetailMakePlanView / AutoDetailGetPlanView (their only caller is commented out) and the form's window
location (Properties.Settings). AutoDetailGetMinsMaxs's AskBoundingBoxAligned result was never read, so it is not
called. The C# AutoDetailCreateMaterialList stays in C# for Etching's Smart Selection; _material_list here is its
port.

Behaviour changes:
  - The Select All deselect step happens in the dialog's picker (above), not in a second selection dialog.
  - OK's enabling is "any of the five ticked" - the form's enabling had an order-dependent quirk (unticking Delete
    All 4-Views disabled Select even with Drill Charting ticked; ticking Dual Dimensions recomputed it without Delete
    All 4-Views).
  - A ConceptControlFile.ucf with no COMPONENT_MATERIALS section content gives an empty list (the C# null made every
    component print a NullReferenceException under Select All).
  - Python's sorts are stable; the C#'s Array.Sort / List.Sort are not, so ties (equal X / Y in the dimension pick,
    equal component names) may come out in a different order.
"""

from __future__ import annotations

import os
import re
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple, cast

# Session.Execute does not put the script's folder on sys.path, so the shared modules would not import.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)
# From the source tree (src\UFuncs) the shared modules are in src\python; deployed, they are beside this file.
_shared_python = os.path.join(os.path.dirname(_here), "python")
if os.path.isdir(_shared_python) and _shared_python not in sys.path:
    sys.path.insert(1, _shared_python)

import NXOpen  # noqa: E402
import NXOpen.Annotations  # noqa: E402
import NXOpen.Assemblies  # noqa: E402
import NXOpen.BlockStyler  # noqa: E402
import NXOpen.Drawings  # noqa: E402
import NXOpen.Layer  # noqa: E402
import NXOpen.Preferences  # noqa: E402
import NXOpen.UF  # noqa: E402

import tsg_nx as nx  # noqa: E402
from CleanBodyRefSet import CleanBodyRefSet  # noqa: E402
from tsg_dialog import Dialog, components_of, title_with_version  # noqa: E402

# [UFunc(ufunc_assembly_auto_detail)]
ufunc_name = "assembly-auto-detail"

# The stubs cover little of the drafting API used here, so these modules are reached untyped.
_NX: Any = NXOpen
_Ann: Any = NXOpen.Annotations
_Pref: Any = NXOpen.Preferences
_UF: Any = NXOpen.UF
_ufs: Any = nx.ufsession_

# Extensions.FilePathUcf.
ConceptControlFile = "U:\\nxFiles\\UfuncFiles\\ConceptControlFile.ucf"

# Static.AutoDetailDrillChart.HoleChartText.
HoleChartText = "U:\\nxFiles\\UfuncFiles\\HoleChart.txt"

# ButtonSelectBorderFile_Click's initial directory.
BorderFolder = "G:\\0Library\\Drafting"

# Extensions.RegexDetail.
RegexDetail = r"^(?P<customerNum>\d+)-(?P<opNum>\d+)-(?P<detailNum>\d+)$"

# NX will not build a Block Styler dialog from inside some callbacks (a menu or toolbar launch, it seems).
_ErrorCannotLaunchDialog = 3520048

# Layout.ReplaceView's "could not replace view" (AutoDetailSetCsysToPlanView catches it).
_ErrorCannotReplaceView = 925019

# The dialog's Components items (tools\make-dlx.py).
ScopeSelectAll = "Select all"
ScopeSelectComponents = "Select components"

# CtsDimensionData.ExtremePointId - the C# hands these to UF_DRF as assoc modifiers where it does not overwrite them.
_ExtremeMinX, _ExtremeMaxX, _ExtremeMinY, _ExtremeMaxY = 1, 2, 3, 4

# UF_DRAW_set_display_state: 1 = modeling view.
_DisplayStateModeling = 1


def _delete_objects(objects: Sequence[Any]) -> None:
    """Session.__DeleteObjects / TaggedObject.__Delete - the delete list inside a DoUpdate. Local because tsg_nx
    defines delete_objects twice with different signatures."""
    with nx.do_update():
        nx.session_.UpdateManager.AddObjectsToDeleteList(list(objects))


def _first_end_point() -> int:
    return int(_UF.UFConstants.UF_DRF_first_end_point)


def _last_end_point() -> int:
    return int(_UF.UFConstants.UF_DRF_last_end_point)


# ---------------------------------------------------------------------------------------------------
# Settings files
# ---------------------------------------------------------------------------------------------------

def _read_crlf(path: str) -> str:
    """StreamReader.ReadToEnd - the text with its \\r\\n line ends kept."""
    with open(path, "r", newline="") as f:
        return f.read()


def _ucf_section(path: str, start: str, end: str) -> str:
    """The text between start and end (Regex.Split, as PerformStreamReader* do)."""
    after_start = re.split(start, _read_crlf(path))[1]
    return re.split(end, after_start)[0]


def perform_stream_reader_string(path: str, start: str, end: str) -> Optional[str]:
    """string.PerformStreamReaderString - the section with every \\r\\n removed, None when that leaves nothing."""
    text = _ucf_section(path, start, end).replace("\r\n", "")
    return text if len(text) > 0 else None


def perform_stream_reader_list(path: str, start: str, end: str) -> Optional[List[str]]:
    """string.PerformStreamReaderList - the section's non-empty lines (CtsAttributes.AttrValue), None when none."""
    lines = [line for line in re.split("\r\n", _ucf_section(path, start, end)) if line != ""]
    return lines if lines else None


def default_border_file() -> Optional[str]:
    return perform_stream_reader_string(ConceptControlFile, ":BORDER_FILE_LOCATION:", ":END_BORDER_FILE_LOCATION:")


def read_hole_chart_sizes() -> Dict[str, List[str]]:
    """MainForm_Load - HOLESIZE_FILE_LOCATION's file: pairs of lines, the diameters (comma separated) then the note
    text, skipping -- comments and blank lines."""
    size_file = perform_stream_reader_string(ConceptControlFile, ":HOLESIZE_FILE_LOCATION:",
                                             ":END_HOLESIZE_FILE_LOCATION:")
    if size_file is None:
        raise ValueError("{} has no HOLESIZE_FILE_LOCATION.".format(ConceptControlFile))
    with open(size_file, "r") as f:
        lines = [s.rstrip("\r\n") for s in f]
    lines = [s for s in lines if not s.startswith("--") and s.strip() != ""]
    hole_chart: Dict[str, List[str]] = {}
    for i in range(0, len(lines) - 1, 2):
        hole_chart[lines[i + 1]] = lines[i].split(",")
    return hole_chart


def _material_list() -> List[str]:
    """Static.AutoDetailCreateMaterialList - the COMPONENT_MATERIALS values (the attribute name is not used)."""
    return perform_stream_reader_list(ConceptControlFile, ":COMPONENT_MATERIALS:", ":END_COMPONENT_MATERIALS:") or []


# ---------------------------------------------------------------------------------------------------
# Picking the components
# ---------------------------------------------------------------------------------------------------

def is_name_valid(component: NXOpen.Assemblies.Component) -> bool:
    """Static.AutoDetailIsNameValid"""
    return re.match(RegexDetail, component.DisplayName) is not None


def _ensure_loaded_quietly(component: NXOpen.Assemblies.Component) -> bool:
    """Component.__EnsureLoadedQuietly"""
    instance = _ufs.Assem.AskInstOfPartOcc(component.Tag)
    if not instance:
        return False
    result = _ufs.Assem.AskPartNameOfChild(instance)
    part_name = result if isinstance(result, str) else result[0]
    if _ufs.Part.IsLoaded(part_name) == 1:
        return True
    if _ufs.Cfi.AskFileExist(part_name) != 0:
        return False
    part_open, _status = _ufs.Part.OpenQuiet(part_name)
    return bool(part_open)


def get_child_components(assembly: NXOpen.Assemblies.Component,
                         into: List[NXOpen.Assemblies.Component]) -> None:
    """Static.AutoDetailGetChildComponents (Component.__LoadedDescendants with IsNameValid): every unsuppressed detail
    that is loaded or opens quietly; a suppressed detail is printed, and nothing under a suppressed component is
    walked."""
    for child in assembly.GetChildren():
        if child.IsSuppressed:
            if is_name_valid(child):
                nx.print_("{} is suppressed".format(child.DisplayName))
            continue
        if not is_name_valid(child):
            get_child_components(child, into)
            continue
        if not _ensure_loaded_quietly(child):
            continue
        into.append(child)
        get_child_components(child, into)


def _assembly_path_string(component: NXOpen.Assemblies.Component) -> str:
    """Component.__AssemblyPathString"""
    text = "{ "
    current: Optional[NXOpen.Assemblies.Component] = component
    while current is not None:
        text += "{}, ".format(current.DisplayName)
        current = current.Parent
    return text + "}"


def select_all_candidates(display: NXOpen.BasePart) -> List[NXOpen.Assemblies.Component]:
    """ButtonSelectAll_Click up to the Preselect step: the details with a listed MATERIAL, CHUTE TO SUIT or
    diemaker to alter. [] (after printing why) when there are none."""
    root = display.ComponentAssembly.RootComponent
    if root is None:
        return []

    all_components: List[NXOpen.Assemblies.Component] = []
    get_child_components(root, all_components)

    if len(all_components) == 0:
        nx.print_("No valid components")
        return []

    materials = _material_list()
    passed: List[NXOpen.Assemblies.Component] = []

    for comp in all_components:
        try:
            for attr in comp.GetUserAttributes():
                if attr.Title.upper() == "MATERIAL":
                    value = comp.GetUserAttributeAsString("MATERIAL", NXOpen.NXObject.AttributeType.String, -1)
                    if value != "":
                        passed.extend(comp for m in materials if m == value)
                    else:
                        nx.print_("\n{} : MATERIAL attribute equals nothing".format(comp.DisplayName))

                # Rev1.1 Change - Added for Scrap Chutes
                if attr.Title.upper() != "DESCRIPTION":
                    continue

                d_value = comp.GetUserAttributeAsString("DESCRIPTION", NXOpen.NXObject.AttributeType.String, -1)

                if d_value is None:
                    nx.print_("////////////////////////////////////")
                    nx.print_("Component: {} has a null DESCRIPTION value.".format(comp.DisplayName))
                    nx.print_(_assembly_path_string(comp))
                    nx.print_("////////////////////////////////////")
                    continue

                if d_value.upper() == "CHUTE TO SUIT":
                    passed.append(comp)

                if "diemaker to alter" in d_value.lower():
                    passed.append(comp)
        except Exception as ex:
            nx.print_exception(ex, comp.DisplayName)

    if len(passed) == 0:
        nx.print_("No valid components")

    # The C# list repeats a component once per matching rule; the picker holds each once.
    return nx.distinct_by(passed, lambda c: c.Tag)


def trim_components(components: Sequence[NXOpen.Assemblies.Component]) -> List[NXOpen.Assemblies.Component]:
    """Both buttons' last step: unsuppressed, distinct by display name, sorted by name (ordinal)."""
    trimmed = nx.distinct_by([c for c in components if not c.IsSuppressed], lambda c: c.DisplayName)
    trimmed.sort(key=lambda c: c.Name)
    return trimmed


# ---------------------------------------------------------------------------------------------------
# Options
# ---------------------------------------------------------------------------------------------------

class Options(object):
    """The form's check boxes and its static _holeChart / _borderFile, as AutoDetailDetailComponent takes them."""

    def __init__(self) -> None:
        self.color_detail_sheet = False
        self.hole_chart = False
        self.detail_sheet = False
        self.drill_chart = False
        self.update_views = False
        self.delete_4_views = False
        self.dual_dimensions = False
        self.dts_path = False
        self.hole_chart_sizes: Dict[str, List[str]] = {}
        self.border_file = ""
        self.select_all = True
        self.components: List[NXOpen.Assemblies.Component] = []


# ---------------------------------------------------------------------------------------------------
# Detailing one component (Static.AutoDetailDetailComponent and its helpers)
# ---------------------------------------------------------------------------------------------------

def _disp() -> Any:
    return nx.display_part()


def _work() -> Any:
    return nx.work_part()


def _dynamic_block_or_none(part: Any) -> Optional[Any]:
    """BasePart.__DynamicBlockOrNull - SingleOrDefault, so two raise."""
    blocks = [f for f in part.Features.GetFeatures()
              if isinstance(f, NXOpen.Features.Block) and f.Name == "DYNAMIC BLOCK"]
    if len(blocks) > 1:
        raise RuntimeError("Sequence contains more than one matching element")
    return blocks[0] if blocks else None


def _block_origin_and_orientation(block: Any) -> Tuple[NXOpen.Point3d, NXOpen.Matrix3x3]:
    """Block.__Origin / Block.__Orientation - read off a BlockFeatureBuilder."""
    builder = block.OwningPart.Features.CreateBlockFeatureBuilder(block)
    try:
        x_axis, y_axis = builder.GetOrientation()
        return builder.Origin, nx.matrix_from_axes(x_axis, y_axis)
    finally:
        builder.Destroy()


def set_wcs_to_work_part() -> None:
    """Static.AutoDetailSetWcsToWorkPart. AutoDetail always calls it with the work part displayed, so only the
    first branch runs; the other is ported as written (absolute origin, the block's orientation mapped through the
    work component)."""
    work = _work()
    dynamic = _dynamic_block_or_none(work)
    if dynamic is None:
        raise Exception("Could not find ")
    origin, orientation = _block_origin_and_orientation(dynamic)

    if work.Tag == _disp().Tag:
        _disp().WCS.SetOriginAndMatrix(origin, orientation)
        return

    work_component: Any = nx.session_.Parts.WorkComponent
    original_refset = work_component.ReferenceSet
    try:
        nx.set_reference_set(work_component, "Entire Part")
        system = work.CoordinateSystems.CreateCoordinateSystem(NXOpen.Point3d(0.0, 0.0, 0.0), orientation, False)
        occurrence = work_component.FindOccurrence(system)
        if not isinstance(occurrence, NXOpen.CartesianCoordinateSystem):
            raise Exception()
        _disp().WCS.SetOriginAndMatrix(NXOpen.Point3d(0.0, 0.0, 0.0), cast(Any, occurrence).Orientation.Element)
        _ufs.Obj.DeleteObject(system.Tag)
    finally:
        nx.set_reference_set(work_component, original_refset)


def _set_layers(*layers: int) -> None:
    """Static.AutoDetailSetLayers - category ALL hidden, then the given layers selectable (unless the work layer)."""
    disp = _disp()
    layer_state = disp.Layers.GetStates()
    try:
        for category in disp.LayerCategories:
            if category.Name == "ALL":
                layer_state.SetStateOfCategory(category, NXOpen.Layer.State.Hidden)
        disp.Layers.SetStates(layer_state, True)
    finally:
        layer_state.Dispose()

    for layer in [layer for layer in layers if disp.Layers.GetState(layer) != NXOpen.Layer.State.WorkLayer]:
        disp.Layers.SetState(layer, NXOpen.Layer.State.Selectable)


def _set_hole_chart_layers() -> None:
    """Static.AutoDetailSetHoleChartLayers"""
    _disp().Layers.SetState(230, NXOpen.Layer.State.WorkLayer)
    _set_layers(1, 94, 96, 200, 231)


def _set_default_layers() -> None:
    """Static.AutoDetailSetDefaultLayers"""
    _disp().Layers.SetState(1, NXOpen.Layer.State.WorkLayer)
    _set_layers(94, 96, 99, 100, 111, 200, 230)


def _set_csys_to_plan_view() -> None:
    """Static.AutoDetailSetCsysToPlanView - L1 shows PLAN (else Top), by way of Back, and the WCS goes onto it."""
    work = _work()
    disp = _disp()
    try:
        layout = work.Layouts.FindObject("L1")
        back_view = work.ModelingViews.FindObject("Back")
        layout.ReplaceView(work.ModelingViews.WorkView, back_view, True)

        view_name = "PLAN" if any(v.Name == "PLAN" for v in disp.ModelingViews) else "Top"

        # BasePart.__FindModelingView - SingleOrDefault, then throws when absent.
        views = [v for v in disp.ModelingViews if v.Name == view_name]
        if len(views) > 1:
            raise RuntimeError("Sequence contains more than one matching element")
        if not views:
            raise RuntimeError('Could not find modeling view "{}" in {}'.format(view_name, disp.Leaf))
        view = views[0]

        layout.ReplaceView(back_view, view, True)
        disp.WCS.SetOriginAndMatrix(view.Origin, view.Matrix)
    except NXOpen.NXException as ex:
        if ex.ErrorCode == _ErrorCannotReplaceView:
            nx.print_("Could not replace view in {}".format(work.Leaf))
        else:
            nx.print_exception(ex, "Part: {}".format(work.Leaf))
    except Exception as ex:
        nx.print_exception(ex, "Part: {}".format(work.Leaf))
    finally:
        work.ModelingViews.WorkView.UpdateDisplay()


def _text_cfw(color: int) -> Any:
    """Static.AutoDetailCreateCfw - new TextCfw(color, 1, LineWidth.Normal)."""
    cfw = _Ann.TextCfw()
    cfw.Color = color
    cfw.Font = 1
    cfw.Width = _Ann.LineWidth.Normal
    return cfw


def _lettering(size: float, character_space_factor: float, color: int) -> Any:
    lettering = _Ann.Lettering()
    lettering.Size = size
    lettering.CharacterSpaceFactor = character_space_factor
    lettering.AspectRatio = 1.0
    lettering.LineSpaceFactor = 1.0
    lettering.Cfw = _text_cfw(color)
    lettering.Italic = False
    return lettering


def _set_lettering_preferences(units: Any) -> None:
    """Static.AutoDetailSetLetteringPreferences - general text .125" (3.175 mm), color 31."""
    disp = _disp()
    size = .125 if units == NXOpen.BasePart.Units.Inches else 3.175
    prefs = disp.Annotations.Preferences.GetLetteringPreferences()
    try:
        prefs.SetGeneralText(_lettering(size, 1.0, 31))
        disp.Annotations.Preferences.SetLetteringPreferences(prefs)
    finally:
        prefs.Dispose()


def _set_drafting_preferences(units: Any, scale: float, dual_dimensions: bool) -> None:
    """Static.AutoDetailSetDraftingPreferences"""
    work = _work()
    disp = _disp()
    inches = units == NXOpen.BasePart.Units.Inches
    unit_multiplier = 1.0 if inches else 25.4

    lettering_prefs = work.Annotations.Preferences.GetLetteringPreferences()
    try:
        lettering_prefs.SetDimensionText(_lettering(.125 * unit_multiplier * scale, 0.9, 7))
        lettering_prefs.SetAppendedText(_lettering(.0625 * unit_multiplier * scale, 0.9, 7))
        lettering_prefs.SetToleranceText(_lettering(.0625 * unit_multiplier * scale, 0.9, 7))
        lettering_prefs.SetGeneralText(_lettering(.125 * unit_multiplier * scale, 0.9, 7))
        work.Annotations.Preferences.SetLetteringPreferences(lettering_prefs)
    finally:
        lettering_prefs.Dispose()

    def line_cfw(color: int) -> Any:
        cfw = _Ann.LineCfw()
        cfw.Color = color
        cfw.Font = NXOpen.DisplayableObject.ObjectFont.Solid
        cfw.Width = _Ann.LineWidth.Thin
        return cfw

    arrows = work.Annotations.Preferences.GetLineAndArrowPreferences()
    try:
        arrows.SetFirstExtensionLineCfw(line_cfw(141))
        arrows.SetFirstArrowheadCfw(line_cfw(173))
        arrows.SetFirstArrowLineCfw(line_cfw(173))
        arrows.SetSecondExtensionLineCfw(line_cfw(173))
        arrows.SetSecondArrowheadCfw(line_cfw(173))
        arrows.SetSecondArrowLineCfw(line_cfw(173))
        arrows.ArrowheadLength = .125 * unit_multiplier
        arrows.ArrowheadIncludedAngle = 30.0
        arrows.StubLength = 0.25 * unit_multiplier
        arrows.TextToLineDistance = 0.0625 * unit_multiplier
        arrows.LinePastArrowDistance = 0.125 * unit_multiplier
        arrows.FirstPosToExtLineDist = 0.0625 * unit_multiplier
        arrows.SecondPosToExtLineDist = 0.0625 * unit_multiplier
        arrows.DatumLengthPastArrow = 0.0625 * unit_multiplier
        arrows.TextOverStubSpaceFactor = 0.1 * unit_multiplier
        disp.Annotations.Preferences.SetLineAndArrowPreferences(arrows)
    finally:
        arrows.Dispose()

    dimension_prefs = disp.Annotations.Preferences.GetDimensionPreferences()
    try:
        dimension_prefs.ExtensionLineDisplay = _Ann.ExtensionLineDisplay.Two
        dimension_prefs.ArrowDisplay = _Ann.ArrowDisplay.Two
        dimension_prefs.TextPlacement = _Ann.TextPlacement.Automatic
        dimension_prefs.TextOrientation = _Ann.TextOrientation.Horizontal
        linear_tolerance = disp.Annotations.Preferences.GetLinearTolerances()
        linear_tolerance.PrimaryDimensionDecimalPlaces = 3 if inches else 2
        disp.Annotations.Preferences.SetLinearTolerances(linear_tolerance)

        units_format = dimension_prefs.GetUnitsFormatPreferences()
        try:
            if dual_dimensions:
                units_format.DualDimensionPlacement = _Ann.DualDimensionPlacement.Below
            units_format.PrimaryDimensionUnit = _Ann.DimensionUnit.Inches if inches else _Ann.DimensionUnit.Millimeters
            units_format.PrimaryDimensionTextFormat = _Ann.DimensionTextFormat.Decimal
            units_format.DecimalPointCharacter = _Ann.DecimalPointCharacter.Period
            units_format.DisplayTrailingZeros = True
            units_format.TolerancePlacement = _Ann.TolerancePlacement.After
            dimension_prefs.SetUnitsFormatPreferences(units_format)
            work.Annotations.Preferences.SetDimensionPreferences(dimension_prefs)
        finally:
            units_format.Dispose()
    finally:
        dimension_prefs.Dispose()


def _set_view_preferences() -> None:
    """Static.AutoDetailSetViewPreferences"""
    work = _work()
    view_prefs = work.ViewPreferences
    view_prefs.HiddenLines.HiddenlineColor = 0
    view_prefs.HiddenLines.HiddenlineFont = NXOpen.Preferences.Font.Dashed
    view_prefs.VisibleLines.VisibleColor = 0
    view_prefs.VisibleLines.VisibleWidth = NXOpen.Preferences.Width.Original
    view_prefs.SmoothEdges.SmoothEdgeColor = 0
    view_prefs.SmoothEdges.SmoothEdgeFont = NXOpen.Preferences.Font.Invisible
    view_prefs.SmoothEdges.SmoothEdgeWidth = NXOpen.Preferences.Width.Original
    view_prefs.General.AutomaticAnchorPoint = False
    view_prefs.General.Centerlines = False
    work.Preferences.ColorSettingVisualization.MonochromeDisplay = False
    work.Preferences.Drafting.DisplayBorders = False


def _create_hole_chart_note(note_origin: NXOpen.Point3d, hole_dia: List[Optional[str]], view: Any) -> None:
    """Static.AutoDetailCreateHoleChartNote - a HOLECHARTNOTE note converted to model in the work view."""
    work = _work()
    mark = nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Invisible, "CreateOrNull Annotation")
    lettering_prefs = work.Annotations.Preferences.GetLetteringPreferences()
    user_symbol_prefs = work.Annotations.NewUserSymbolPreferences(
        NXOpen.Annotations.UserSymbolPreferences.SizeType.ScaleAspectRatio, 1.0, 1.0)
    try:
        # A None line (no hole-size match) raises here, as the C# null did.
        note = work.Annotations.CreateNote(cast(List[str], hole_dia), note_origin, NXOpen.AxisOrientation.Horizontal,
                                           lettering_prefs, user_symbol_prefs)
        note.SetName("HOLECHARTNOTE")
        _ufs.View.ConvertToModel(view, note.Tag)
    finally:
        lettering_prefs.Dispose()
        user_symbol_prefs.Dispose()
    nx.session_.UpdateManager.DoUpdate(mark)
    nx.session_.DeleteUndoMark(mark, "CreateOrNull Annotation")


def _hole_chart(hole_chart_sizes: Dict[str, List[str]]) -> None:
    """The isHoleChart block of AutoDetailDetailComponent."""
    disp = _disp()
    # set WCS to "PLAN" view and set "Top" as the work view
    _set_csys_to_plan_view()
    _set_hole_chart_layers()
    # get work view and part units and set lettering preferences
    work_view = disp.Views.WorkView
    _set_lettering_preferences(disp.PartUnits)

    delete_note = [n for n in disp.Notes if n.Layer == 230]
    if len(delete_note) > 0:
        _delete_objects(delete_note)

    for solid_body in disp.Bodies:
        solid_body.Unblank()

        if solid_body.Layer not in (1, 94, 96):
            continue

        for cyl_face in solid_body.GetFaces():
            _type, point, _direction, _box, radius, _rad_data, _norm_dir = _ufs.Modeling.AskFaceData(cyl_face.Tag)

            if cyl_face.SolidFaceType != NXOpen.Face.FaceType.Cylindrical:
                continue

            # Revision 1.45
            if "HOLECHART" not in cyl_face.Name.upper():
                continue

            cf_origin = NXOpen.Point3d(point[0], point[1], point[2])
            cf_note: List[Optional[str]] = [None]
            multiplier = 1.0 if disp.PartUnits == NXOpen.BasePart.Units.Inches else 25.4

            for key in hole_chart_sizes:
                # The C# breaks only this inner loop, so the last matching key wins.
                for value in hole_chart_sizes[key]:
                    hole_diameter = float(value)
                    face_diameter = radius * 2
                    difference = hole_diameter * .000000001
                    if abs(hole_diameter * multiplier - face_diameter) > difference * multiplier:
                        continue
                    cf_note[0] = key
                    break

            _create_hole_chart_note(cf_origin, cf_note, work_view.Tag)

    _set_default_layers()
    nx.print_("HoleCharted {}".format(disp.Leaf))


def _find_by_name(name: str) -> Any:
    """Session.__FindByName - the first object UF_OBJ_cycle_by_name finds; raises when there is none (First())."""
    tag = _ufs.Obj.CycleByName(name, 0)
    if not tag:
        raise RuntimeError("Sequence contains no elements (no object named {})".format(name))
    return nx.tagged_object(tag)


def drill_chart() -> List[str]:
    """Static.AutoDetailDrillChart.Main - lettered HOLECHARTNOTE notes on the layer-1 body's HOLECHART holes (layer
    230, after deleting that layer's notes) and the chart text for the border's GRUMBLEGRUMBLE note."""
    disp = _disp()
    work = _work()

    with open(HoleChartText, "r") as f:
        lines = [s.rstrip("\r\n") for s in f]
    lines = [s for s in lines if s.strip() != "" and not s.startswith("//")]

    hole_chart = [line.split("\t") for line in lines[1:]]

    solid_body = _solid_body_layer1_or_none(disp)
    if solid_body is None:
        raise ValueError("Display part does not have solid body on layer 1")

    # diameter -> [count, faces, chart line], in first-seen order like the C# Dictionary.
    found: Dict[float, Tuple[List[int], List[Any], List[str]]] = {}

    for face in solid_body.GetFaces():
        if face.SolidFaceType != NXOpen.Face.FaceType.Cylindrical:
            continue
        if "HOLECHART" not in face.Name.upper():
            continue

        radius = _ufs.Modeling.AskFaceData(face.Tag)[4]
        diameter = radius * 2  # * 25.4;

        actual_line = next((line for line in hole_chart if abs(float(line[1]) - diameter) < .000000001), None)

        if actual_line is None:
            nx.print_("Couldn't find hole chart: {}".format(nx.cs_double_str(diameter)))
            continue

        if diameter not in found:
            found[diameter] = ([0], [], actual_line)

        found[diameter][0][0] += 1
        found[diameter][1].append(face)

    on_230 = [o for o in disp.Layers.GetAllObjectsOnLayer(230) if isinstance(o, NXOpen.Annotations.Note)]
    _delete_objects(on_230)

    letter = "A"
    actual_lines: List[List[str]] = []

    for diameter in found:
        counts, faces, message = found[diameter]
        temp = "{} ".format(message[2]) if len(message) == 3 else "{} ".format(message[0])
        split = re.split("FOR\\s", temp)
        actual_lines.append(["{} ".format(letter), "{}FOR".format(split[0]), split[1], "QTY {}".format(counts[0])])

        for face in faces:
            point = _ufs.Modeling.AskFaceData(face.Tag)[1]

            with nx.do_update():
                lettering_prefs = work.Annotations.Preferences.GetLetteringPreferences()
                user_symbol_prefs = work.Annotations.NewUserSymbolPreferences(
                    NXOpen.Annotations.UserSymbolPreferences.SizeType.ScaleAspectRatio, 1.0, 1.0)
                try:
                    user_symbol_prefs.SetLengthAndHeight(.125, .125)
                    note = work.Annotations.CreateNote([letter], NXOpen.Point3d(point[0], point[1], point[2]),
                                                       NXOpen.AxisOrientation.Horizontal, lettering_prefs,
                                                       user_symbol_prefs)
                    note.Layer = 230
                    note.RedisplayObject()
                    note.SetName("HOLECHARTNOTE")
                    _ufs.View.ConvertToModel(disp.ModelingViews.WorkView.Tag, note.Tag)

                    note_builder = work.Annotations.CreateDraftingNoteBuilder(note)
                    try:
                        note_builder.Style.LetteringStyle.GeneralTextSize = .125
                        note_builder.Commit()
                    finally:
                        note_builder.Destroy()
                finally:
                    lettering_prefs.Dispose()
                    user_symbol_prefs.Dispose()

        letter = chr(ord(letter) + 1)

    note_text: List[str] = []
    for t in actual_lines:
        note_text.append("{}{}".format(t[0], t[1]))
        note_text.append("{}{}".format(t[2], t[3]).upper())
        note_text.append("")
        note_text.append("".join(t))
    return note_text


def _solid_body_layer1_or_none(part: Any) -> Optional[Any]:
    """BasePart.__SolidBodyLayer1OrNull - the only prototype solid body on layer 1."""
    bodies = [b for b in part.Bodies if not b.IsOccurrence and b.IsSolidBody and b.Layer == 1]
    return bodies[0] if len(bodies) == 1 else None


def _import_plan_view(x_placement: float, y_placement: float) -> Any:
    """Static.AutoDetailImportPlanView - a base view of PLAN (else Top) at the given sheet point."""
    work = _work()
    builder = work.DraftingViews.CreateBaseViewBuilder(None)
    try:
        plan_view = None
        top_view = None
        for m_view in work.ModelingViews:
            if m_view.Name == "PLAN":
                plan_view = m_view
            elif m_view.Name == "Top":
                top_view = m_view

        builder.SelectModelView.SelectedView = plan_view if plan_view is not None else top_view
        builder.Style.ViewStyleBase.Part = work
        builder.Style.ViewStyleBase.PartName = work.FullPath
        work.LoadFully().Dispose()
        builder.Style.ViewStyleGeneral.UVGrid = False
        builder.Style.ViewStyleGeneral.AutomaticAnchorPoint = False
        builder.Style.ViewStyleGeneral.Centerlines = False
        builder.Placement.Placement.SetValue(None, work.Views.WorkView, NXOpen.Point3d(x_placement, y_placement, 0.0))
        return builder.Commit()
    finally:
        builder.Destroy()


def _set_layer_visibility(view: Any) -> None:
    """Static.AutoDetailSetLayerVisibility - only layers 1, 96 and 111 visible in the view. As in the C# (and
    CreateBurnout.py) the 256th entry is left at its default."""
    states: List[Any] = [NXOpen.Layer.StateInfo() for _ in range(256)]
    for i in range(len(states) - 1):
        states[i].Layer = i + 1
        states[i].State = NXOpen.Layer.State.Hidden
    for index, layer in ((0, 1), (95, 96), (110, 111)):
        states[index].Layer = layer
        states[index].State = NXOpen.Layer.State.Visible
    _disp().Layers.SetObjectsVisibilityOnLayer(view, states, True)


class DimensionData(object):
    """Static.AutoDetailCtsDimensionData"""

    def __init__(self, dim_entity: Any, x: float, y: float, type_name: str, ext_point_id: int = 0) -> None:
        self.DimEntity = dim_entity
        self.DimXvalue = x
        self.DimYvalue = y
        self.Type = type_name
        self.ExtPointId = ext_point_id

    def copy_with(self, ext_point_id: int) -> "DimensionData":
        return DimensionData(self.DimEntity, self.DimXvalue, self.DimYvalue, self.Type, ext_point_id)


def _end_points(data: DimensionData) -> Tuple[NXOpen.Point3d, NXOpen.Point3d]:
    """Static.AutoDetailFindEndPoints - a line's start / end, else the edge's two vertices."""
    obj = nx.tagged_object(data.DimEntity)
    if isinstance(obj, NXOpen.Line):
        return obj.StartPoint, obj.EndPoint
    vertex1, vertex2 = cast(Any, obj).GetVertices()
    return vertex1, vertex2


def _to_drawing(view: Any, point: NXOpen.Point3d) -> List[float]:
    return list(_ufs.View.MapModelToDrawing(view.Tag, [point.X, point.Y, point.Z]))


def _drf_object(view: Any, data: DimensionData) -> Any:
    """InitObjectStructure + Static.AutoDetailAssignDraftObject."""
    obj = _ufs.Drf.InitObjectStructure(_UF.Drf.Object())
    obj.ObjectTag = data.DimEntity
    obj.ObjectViewTag = view.Tag
    obj.ObjectAssocModifier = data.ExtPointId
    return obj


def _dimension_view(drf_view: Any, drf_view_position: Sequence[float], view_scale: float,
                    size: Sequence[float], part_units: Any) -> None:
    """Static.AutoDetailDimensionView - an overall horizontal + vertical dimension on 4-VIEW-BOTTOM and a vertical one
    on 4-VIEW-RIGHT, between the extreme visible edges / lines."""
    drf_view.Update()
    view_matrix = drf_view.Matrix
    obj_in_view: List[Any] = []
    vis_obj: Any = 0

    while True:
        vis_obj = _ufs.View.CycleObjects(drf_view.Tag, _UF.View.CycleObjects.VISIBLE_OBJECTS, vis_obj)
        if not vis_obj:
            break
        obj_in_view.append(nx.tagged_object(vis_obj))

    dim_data: List[DimensionData] = []
    for disp_obj in obj_in_view:
        if isinstance(disp_obj, NXOpen.Edge):
            x_dir = nx.axis_x(view_matrix)
            y_dir = nx.axis_y(view_matrix)
            z_dir = nx.axis_z(view_matrix)
            _subent, extreme = _ufs.Modeling.AskExtreme(
                disp_obj.Tag, [x_dir.X, x_dir.Y, x_dir.Z], [y_dir.X, y_dir.Y, y_dir.Z], [z_dir.X, z_dir.Y, z_dir.Z])
            extreme_point = NXOpen.Point3d(extreme[0], extreme[1], extreme[2])
        elif isinstance(disp_obj, NXOpen.Line):
            extreme_point = disp_obj.StartPoint
        else:
            continue

        drf_location = _to_drawing(drf_view, extreme_point)
        dim_data.append(DimensionData(disp_obj.Tag, drf_location[0], drf_location[1], type(disp_obj).__name__))

    if len(dim_data) <= 0:
        return

    by_x = sorted(dim_data, key=lambda d: d.DimXvalue, reverse=True)
    min_x = by_x[-1].copy_with(_ExtremeMinX)
    max_x = by_x[0].copy_with(_ExtremeMaxX)
    by_y = sorted(dim_data, key=lambda d: d.DimYvalue, reverse=True)
    min_y = by_y[-1].copy_with(_ExtremeMinY)
    max_y = by_y[0].copy_with(_ExtremeMaxY)
    # Sic: the C# then gives min-Y max-Y's id.
    min_y.ExtPointId = _ExtremeMaxY

    first, last = _first_end_point(), _last_end_point()

    if drf_view.Name == "4-VIEW-BOTTOM":
        # min X: the left-most end point, its higher Y
        d1, d2 = (_to_drawing(drf_view, p) for p in _end_points(min_x))
        min_x.DimXvalue = d1[0] if d1[0] <= d2[0] else d2[0]
        min_x.ExtPointId = first if d1[0] <= d2[0] else last
        min_x.DimYvalue = d1[1] if d1[1] >= d2[1] else d2[1]

        # max X: the right-most end point, its higher Y
        d3, d4 = (_to_drawing(drf_view, p) for p in _end_points(max_x))
        max_x.DimXvalue = d3[0] if d3[0] >= d4[0] else d4[0]
        max_x.ExtPointId = first if d3[0] >= d4[0] else last
        max_x.DimYvalue = d3[1] if d3[1] >= d4[1] else d4[1]

        # min Y: the C#'s nested ternaries reduce to the lower end point
        d5, d6 = (_to_drawing(drf_view, p) for p in _end_points(min_y))
        min_y.DimXvalue = d5[0] if d5[0] >= d6[0] else d6[0]
        min_y.DimYvalue = d5[1] if d5[1] <= d6[1] else d6[1]
        min_y.ExtPointId = first if d5[1] <= d6[1] else last

        # max Y: likewise the higher end point
        d7, d8 = (_to_drawing(drf_view, p) for p in _end_points(max_y))
        max_y.DimXvalue = d7[0] if d7[0] >= d8[0] else d8[0]
        max_y.DimYvalue = d7[1] if d7[1] >= d8[1] else d8[1]
        max_y.ExtPointId = first if d7[1] >= d8[1] else last

    elif drf_view.Name == "4-VIEW-RIGHT":
        d1, d2 = (_to_drawing(drf_view, p) for p in _end_points(min_y))
        min_y.DimXvalue = d1[0] if d1[0] <= d2[0] else d2[0]
        min_y.DimYvalue = d1[1] if d1[1] <= d2[1] else d2[1]
        min_y.ExtPointId = first if d1[1] <= d2[1] else last

        d3, d4 = (_to_drawing(drf_view, p) for p in _end_points(max_y))
        max_y.DimXvalue = d3[0] if d3[0] <= d4[0] else d4[0]
        max_y.DimYvalue = d3[1] if d3[1] >= d4[1] else d4[1]
        max_y.ExtPointId = first if d3[1] >= d4[1] else last

    dim_space = .75 if part_units == NXOpen.BasePart.Units.Inches else 20
    x_distance = size[0]
    z_distance = size[2]

    ortho_right_dim_origin = [drf_view_position[0] - z_distance / 2 - dim_space * view_scale,
                              drf_view_position[1], 0.0]
    ortho_btm_horiz_dim_origin = [drf_view_position[0],
                                  drf_view_position[1] + z_distance / 2 + dim_space * view_scale, 0.0]
    ortho_btm_vert_dim_origin = [drf_view_position[0] + x_distance / 2 + dim_space * view_scale,
                                 drf_view_position[1], 0.0]

    if drf_view.Name == "4-VIEW-BOTTOM":
        _ufs.Drf.CreateVerticalDim(_drf_object(drf_view, min_y), _drf_object(drf_view, max_y), _UF.Drf.Text(),
                                   ortho_btm_vert_dim_origin)
        _ufs.Drf.CreateHorizontalDim(_drf_object(drf_view, min_x), _drf_object(drf_view, max_x), _UF.Drf.Text(),
                                     ortho_btm_horiz_dim_origin)

    if drf_view.Name != "4-VIEW-RIGHT":
        return

    _ufs.Drf.CreateVerticalDim(_drf_object(drf_view, min_y), _drf_object(drf_view, max_y), _UF.Drf.Text(),
                               ortho_right_dim_origin)


def _create_detail_sheet(drill_chart_text: Optional[List[str]], is_drill_chart: bool, is_dts_path: bool,
                         border_file: str, is_dual_dimensions: bool) -> None:
    """Static.AutoDetailCreateDetailSheet - the 4-VIEW sheet, border, three views and dimensions."""
    work = _work()
    disp = _disp()

    pref_builder = work.SettingsManager.CreatePreferencesBuilder()
    try:
        pref_builder.ViewStyle.ViewStyleGeneral.ViewRepresentation = _Pref.GeneralViewRepresentationOption.PreNx85Exact
        pref_builder.ViewStyle.ViewStyleGeneral.ExtractedEdges = _Pref.GeneralExtractedEdgesOption.NotSet
        pref_builder.Commit()
    finally:
        pref_builder.Destroy()

    try:
        base_width_x_dir = 11.0
        fit_sheet_x_dir = .7
        base_height_y_dir = 8.5
        fit_sheet_y_dir = .7
        border_space = 1.0
        view_space = 2.0
        view_min_from_btm = 1.0
        scale = 1.0
        increment = .125

        body_count = len([b for b in disp.Bodies if b.Layer == 1])

        if body_count != 1:
            nx.print_("DetailPart Sheet will not be created.  {} : Solid bodies on layer one = {}".format(
                disp.FullPath, body_count))
            return

        s_body = _solid_body_layer1_or_none(disp)

        if s_body is None:
            nx.print_("Could not find solid body on layer 1 :' {}'".format(disp.Leaf))
            return

        units = disp.PartUnits

        # OrientedBox(body): the body's exact box in the WCS.
        _min_corner, _directions, box_distances = _ufs.ModlGeneral.AskBoundingBoxExact(
            s_body.Tag, _ufs.Csys.AskWcs())
        distances = [float(box_distances[0]), float(box_distances[1]), float(box_distances[2])]

        unit_multiplier = 1.0 if units == NXOpen.BasePart.Units.Inches else 25.4

        measure_width = (distances[0] + distances[2] + border_space * unit_multiplier * 2
                         + view_space * unit_multiplier) / unit_multiplier
        measure_height = (distances[1] + distances[2] + border_space * unit_multiplier
                          + view_space * unit_multiplier + view_min_from_btm * unit_multiplier) / unit_multiplier

        if measure_width > base_width_x_dir * fit_sheet_x_dir or measure_height > base_height_y_dir * fit_sheet_y_dir:
            while True:
                scale += increment
                scaled_width = base_width_x_dir * fit_sheet_x_dir * scale
                scaled_height = base_height_y_dir * fit_sheet_y_dir * scale
                if not (scaled_width < measure_width or scaled_height < measure_height):
                    break

        if all(e.Name != "borderScale" for e in disp.Expressions):
            with nx.do_update("Expression"):
                work.Expressions.CreateWithUnits("borderScale={}".format(nx.cs_double_str(scale)), None)

        sheet_width = base_width_x_dir * unit_multiplier * scale
        sheet_height = base_height_y_dir * unit_multiplier * scale

        sheet_units = (NXOpen.Drawings.DrawingSheet.Unit.Inches if units == NXOpen.BasePart.Units.Inches
                       else NXOpen.Drawings.DrawingSheet.Unit.Millimeters)

        # (height, width) in the C#'s order.
        four_view_sheet = disp.DraftingDrawingSheets.InsertSheet(
            "4-VIEW", sheet_units, sheet_height, sheet_width, 1, 1,
            NXOpen.Drawings.DrawingSheet.ProjectionAngleType.ThirdAngle)

        _set_drafting_preferences(units, scale, is_dual_dimensions)
        _set_view_preferences()

        # import 4-VIEW border part
        modes = _UF.Part.ImportPartModes()
        modes.LayerMode = 1
        modes.GroupMode = 1
        modes.CsysMode = 0
        modes.PlistMode = 0
        if hasattr(modes, "ViewMode"):
            modes.ViewMode = 0
        modes.CamMode = False
        modes.UseSearchDirs = False
        _ufs.Part.Import(border_file, modes, [1.0, 0.0, 0.0, 0.0, 1.0, 0.0], [0.0, 0.0, 0.0], scale)

        try:
            if is_drill_chart and drill_chart_text is not None and len(drill_chart_text) > 0:
                cast(Any, _find_by_name("GRUMBLEGRUMBLE")).SetText(drill_chart_text)
            else:
                _delete_objects([_find_by_name("GRUMBLEGRUMBLE")])
        except Exception as ex:
            nx.print_exception(ex)

        try:
            if is_dts_path:
                cast(Any, _find_by_name("DTS_FILE_PATH")).SetText([disp.FullPath])
            else:
                _delete_objects([_find_by_name("DTS_FILE_PATH")])
        except Exception as ex:
            nx.print_exception(ex)

        x_distance, y_distance, z_distance = distances

        pv_ref_point = [
            sheet_width * .333 if sheet_width * .333 > x_distance
            else border_space * unit_multiplier * scale + x_distance / 2,
            sheet_height * .667 if sheet_height * .667 > y_distance
            else (view_min_from_btm * unit_multiplier + view_space * unit_multiplier) * scale + z_distance
            + y_distance / 2,
        ]

        plan_drf_view = _import_plan_view(pv_ref_point[0], pv_ref_point[1])
        plan_drf_view.Update()

        orthogonal_right = [pv_ref_point[0] + x_distance / 2 + view_space * unit_multiplier * scale + z_distance / 2,
                            pv_ref_point[1]]
        r_ortho_tag = _ufs.Draw.AddOrthographicView(four_view_sheet.Tag, plan_drf_view.Tag,
                                                    _UF.Draw.ProjDir.PROJECT_RIGHT, orthogonal_right)
        right_drf_view: Any = nx.tagged_object(r_ortho_tag)
        right_drf_view.SetName("4-VIEW-RIGHT")
        _set_layer_visibility(right_drf_view)
        state_111: Any = NXOpen.Layer.StateInfo()
        state_111.Layer = 111
        state_111.State = NXOpen.Layer.State.Visible
        disp.Layers.SetObjectsVisibilityOnLayer(right_drf_view, [state_111], True)

        orthogonal_btm = [pv_ref_point[0],
                          pv_ref_point[1] - y_distance / 2 - view_space * unit_multiplier * .667 * scale
                          - z_distance / 2]
        b_ortho_tag = _ufs.Draw.AddOrthographicView(four_view_sheet.Tag, plan_drf_view.Tag,
                                                    _UF.Draw.ProjDir.PROJECT_BELOW, orthogonal_btm)
        btm_drf_view: Any = nx.tagged_object(b_ortho_tag)
        btm_drf_view.SetName("4-VIEW-BOTTOM")
        _set_layer_visibility(btm_drf_view)
        disp.Layers.SetObjectsVisibilityOnLayer(btm_drf_view, [state_111], True)

        if not nx.has_attribute(disp, "DESCRIPTION"):
            nx.print_("Does not have DESCRIPTION att")
        elif nx.get_attribute(disp, "DESCRIPTION").upper() == "NITROGEN PLATE SYSTEM":
            return

        _dimension_view(btm_drf_view, orthogonal_btm, scale, distances, units)
        _dimension_view(right_drf_view, orthogonal_right, scale, distances, units)

        is_wire_taper = False
        is_wait_for_dev = False

        for attr_note in disp.GetUserAttributes():
            if attr_note.Title.upper() == "WTN":
                if nx.get_attribute(disp, attr_note.Title).upper() == "YES":
                    is_wire_taper = True

            if attr_note.Title.upper() != "WFTD":
                continue

            if nx.get_attribute(disp, attr_note.Title).upper() == "YES":
                is_wait_for_dev = True

        add_to_delete: List[Any] = []

        for drf_note in disp.Notes:
            if drf_note.Layer != 200:
                continue

            note_text = drf_note.GetText()

            # Changed from "TSG STANDARD" to "STANDARD" - to work with the GE Border file. 2016-11-16 Duane VW
            if "STANDARD" in note_text[0] and not is_wire_taper:
                add_to_delete.append(drf_note)

            if "WAITING FOR FINAL TRIM" in note_text[0] and not is_wait_for_dev:
                add_to_delete.append(drf_note)

        if len(add_to_delete) != 0:
            _delete_objects(add_to_delete)
    except Exception as ex:
        nx.print_exception(ex, disp.Leaf)


def detail_component(detail_comp: NXOpen.Assemblies.Component, options: Options) -> None:
    """Static.AutoDetailDetailComponent"""
    nx.print_("////////////////////////")

    if not nx.is_loaded(detail_comp):
        nx.print_("Component {} is not loaded".format(detail_comp.DisplayName))
        nx.print_("4-VIEW will not be created for this component")
        return

    with nx.suppress_display():
        nx.set_display_part(nx.prototype(detail_comp))
        disp = _disp()

        CleanBodyRefSet.execute_part(disp)

        try:
            if _dynamic_block_or_none(_work()) is not None:
                set_wcs_to_work_part()
        except Exception as ex:
            nx.print_exception(ex)

        if disp.Layers.GetState(111) != NXOpen.Layer.State.WorkLayer:
            disp.Layers.SetState(111, NXOpen.Layer.State.Selectable)

        # ResetShadeRendering: the work part's shading rendering style, put back on the way out.
        reader = _work().SettingsManager.CreatePreferencesBuilder()
        try:
            original_rendering = reader.ViewStyle.ViewStyleShading.RenderingStyle
        finally:
            reader.Destroy()

        try:
            _detail_display_part(options)
        finally:
            restorer = _work().SettingsManager.CreatePreferencesBuilder()
            try:
                restorer.ViewStyle.ViewStyleShading.RenderingStyle = original_rendering
                restorer.Commit()
            finally:
                restorer.Destroy()


def _detail_display_part(options: Options) -> None:
    """The ResetShadeRendering block of AutoDetailDetailComponent."""
    disp = _disp()

    pref_builder = _work().SettingsManager.CreatePreferencesBuilder()
    try:
        if options.color_detail_sheet:
            pref_builder.ViewStyle.ViewStyleShading.RenderingStyle = _Pref.ShadingRenderingStyleOption.FullyShaded
            pref_builder.Commit()
    finally:
        pref_builder.Destroy()

    _ufs.Draw.SetDisplayState(_DisplayStateModeling)
    disp.ModelingViews.WorkView.RenderingStyle = _NX.View.RenderingStyleType.ShadedWithEdges

    body_refset = nx.try_get_refset(disp, "BODY")
    if body_refset is not None:
        for ref_member in cast(Any, body_refset).AskMembersInReferenceSet():
            if not isinstance(ref_member, NXOpen.Curve):
                continue
            if ref_member.Layer != 1:
                continue
            body_refset.RemoveObjectsFromReferenceSet([ref_member])
            ref_member.Layer = 10

    if options.hole_chart:
        try:
            _hole_chart(options.hole_chart_sizes)
        except Exception as ex:
            nx.print_exception(ex)

    if options.detail_sheet:
        try:
            _set_hole_chart_layers()
            _set_csys_to_plan_view()

            # delete existing 4-VIEW
            delete_view = [s for s in disp.DrawingSheets if s.Name == "4-VIEW"]
            if len(delete_view) > 0:
                _delete_objects(delete_view)

            chart: Optional[List[str]] = None

            if options.drill_chart:
                chart = drill_chart()
                nx.print_("Drill Charted in {}".format(disp.Leaf))

            _create_detail_sheet(chart, options.drill_chart, options.dts_path, options.border_file,
                                 options.dual_dimensions)
            _set_default_layers()
            nx.print_("Created 4-View in {}".format(disp.Leaf))
        except Exception as ex:
            nx.print_exception(ex)

    if options.update_views:
        try:
            # update all views
            _set_default_layers()

            for dwg in disp.DrawingSheets:
                # Revision 1.7 - 2018 / 02 / 09
                if not _ufs.Draw.IsObjectOutOfDate(dwg.Tag):
                    continue

                dwg.Open()

                for drf_view in dwg.GetDraftingViews():
                    drf_view.Update()
                    nx.print_("Updated view {} in {}".format(drf_view.Name, disp.Leaf))
        except Exception as ex:
            nx.print_exception(ex)

    if not options.delete_4_views:
        return

    # Revision 1.62 - 2017 / 12 / 13
    try:
        for note in [n for n in disp.Notes if n.Layer == 230]:
            _ufs.Obj.DeleteObject(note.Tag)
    except Exception as ex:
        nx.print_exception(ex)

    # delete existing 4-VIEW
    delete_view1 = [s for s in disp.DrawingSheets if s.Name == "4-VIEW"]
    if len(delete_view1) > 0:
        _delete_objects(delete_view1)


def detail_components(components: Sequence[NXOpen.Assemblies.Component], options: Options) -> None:
    """AutoDetail.DetailComponents - each component on its own, display and work parts restored afterwards."""
    with nx.display_part_reset():
        for index, detail_comp in enumerate(components):
            try:
                nx.prompt("({} of {})".format(index + 1, len(components)))
                detail_component(detail_comp, options)
            except Exception as ex:
                nx.print_exception(ex, detail_comp.DisplayName)


# ---------------------------------------------------------------------------------------------------
# Dialog
# ---------------------------------------------------------------------------------------------------

# The toggles' block ids (tools\make-dlx.py), in the form's order.
_Toggles = ("hole_chart", "drill_chart", "detail_sheet", "update_views", "shaded_views", "dual_dimensions",
            "delete_4_views", "dts_path")

# The toggles that make OK mean something (the form's Select / Select All enabling).
_ActionToggles = ("hole_chart", "drill_chart", "detail_sheet", "update_views", "delete_4_views")


class _AutoDetailDialog(Dialog):
    dlx_name = "AutoDetail.dlx"

    def __init__(self, title: str, default_border: str) -> None:
        self.title = title
        self.default_border = default_border
        super().__init__()
        # Select all's candidates, scanned once (the scan loads parts and prints what it skips).
        self._candidates: Optional[List[NXOpen.Assemblies.Component]] = None
        # Captured in ok(): the blocks are gone once Launch returns.
        self.options: Optional[Options] = None

    def initialize(self) -> None:
        self.component_filter(self.block("components"))
        self.assembly_scope(self.block("components"))

    def shown(self) -> None:
        # SetFormDefaults (on load and after every run).
        for block_id in ("hole_chart", "detail_sheet", "update_views", "delete_4_views"):
            self.block(block_id).Value = False
        self._apply_delete_4_views()
        self.set_string_value(self.block("border_file"), self.default_border)
        self._refresh_components()

    def update(self, block: NXOpen.BlockStyler.UIBlock) -> None:
        if block == self.block("scope"):
            self._refresh_components()
        elif block == self.block("drill_chart"):
            # ChkChart_CheckedChanged
            if self.block("drill_chart").Value:
                self.block("hole_chart").Value = False
        elif block == self.block("hole_chart"):
            if self.block("hole_chart").Value:
                self.block("drill_chart").Value = False
        elif block == self.block("delete_4_views"):
            # CheckBoxDelete4Views_CheckedChanged
            self.block("hole_chart").Value = False
            self.block("update_views").Value = False
            if self.block("delete_4_views").Value:
                self.block("detail_sheet").Value = False
            self._apply_delete_4_views()
        elif block == self.block("browse_border"):
            # ButtonSelectBorderFile_Click - a cancelled pick puts the .ucf default back.
            path = nx.select_file_or_none("Select Border File", "Select Border File",
                                          os.path.join(BorderFolder, "*.prt"))
            self.set_string_value(self.block("border_file"), path if path else self.default_border)

    def enable_ok(self) -> bool:
        return (any(self.block(b).Value for b in _ActionToggles)
                and len(self.selected(self.block("components"))) > 0
                and (not self.block("detail_sheet").Value or self.string_value(self.block("border_file")) != ""))

    def ok(self) -> bool:
        components = components_of(self.selected(self.block("components")))
        if not components:
            self.message("Select at least one component.", error=True)
            return False
        if not any(self.block(b).Value for b in _ActionToggles):
            self.message("Tick Hole Charting, Drill Charting, Create Detail Sheet, Update All Views or "
                         "Delete All 4-Views.", error=True)
            return False

        options = Options()
        options.hole_chart = bool(self.block("hole_chart").Value)
        options.drill_chart = bool(self.block("drill_chart").Value)
        options.detail_sheet = bool(self.block("detail_sheet").Value)
        options.update_views = bool(self.block("update_views").Value)
        options.color_detail_sheet = bool(self.block("shaded_views").Value)
        options.dual_dimensions = bool(self.block("dual_dimensions").Value)
        options.delete_4_views = bool(self.block("delete_4_views").Value)
        options.dts_path = bool(self.block("dts_path").Value)
        options.border_file = self.string_value(self.block("border_file"))
        options.select_all = self._select_all()
        options.components = components
        self.options = options
        return True

    def _select_all(self) -> bool:
        return str(self.block("scope").ValueAsString) != ScopeSelectComponents

    def _apply_delete_4_views(self) -> None:
        enabled = not self.block("delete_4_views").Value
        for block_id in ("detail_sheet", "hole_chart", "update_views"):
            self.block(block_id).Enable = enabled

    def _refresh_components(self) -> None:
        """Select all fills the picker with the candidates to deselect from; Select components empties it."""
        picker = self.block("components")
        if self._select_all():
            if self._candidates is None:
                self._candidates = select_all_candidates(nx.display_part())
            picker.Label = "Details found (deselect to skip)"
            picker.SetSelectedObjects(self._candidates)
        else:
            picker.Label = "Select Components"
            picker.SetSelectedObjects([])


def execute() -> None:
    """The assembly-auto-detail UFunc: the dialog, then the detailing with what it captured."""
    title = "Auto Detail"

    if nx.display_part() is None:
        nx.show_error("{} needs a displayed part.".format(title))
        return

    # MainForm_Load: the border default and the hole sizes, read once per run.
    default_border = default_border_file() or ""
    hole_chart_sizes = read_hole_chart_sizes()

    full_title = title_with_version(title)
    try:
        dialog = _AutoDetailDialog(full_title, default_border)
        accepted = dialog.run()
    except NXOpen.NXException as ex:
        if ex.ErrorCode != _ErrorCannotLaunchDialog:
            raise
        nx.print_exception(ex)
        nx.show_error("NX would not open the {} dialog (error {} - it will not create a dialog from inside a "
                      "callback).\n\nTry running it from File -> Execute -> NX Open rather than from a menu or "
                      "toolbar button.".format(full_title, _ErrorCannotLaunchDialog))
        return

    if not accepted or dialog.options is None:
        return

    options = dialog.options
    options.hole_chart_sizes = hole_chart_sizes

    components = trim_components(options.components)
    if len(components) == 0:
        nx.print_("No valid components")
        return

    detail_components(components, options)


def main() -> None:
    """The assembly-auto-detail UFunc - its menu button runs this file. An escaping exception is printed."""
    import usage_db

    with usage_db.run(ufunc_name):
        try:
            execute()
        except Exception as ex:
            nx.print_exception(ex)


if __name__ == "__main__":
    main()

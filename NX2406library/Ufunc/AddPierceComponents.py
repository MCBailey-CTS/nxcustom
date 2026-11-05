"""
Python port of the add-pierce-components UFunc (src\\UFuncs\\AddPierceComponents.cs and
src\\Static\\AddPierceComponents.cs). The C# form and Static were deleted 2026-10-30 (in git at 97eb2a6): the UFunc's
menu button runs this file's main().

Needs exactly one strip-control loaded and an `e` expression in the display part (a {job}-{op}-lsp/usp station).
The dialog (AddPierceComponents.dlx) is the form: Units (Metric / English), Button / Punch / Retainer each with an
optional detail to use in place of the library seed, Same assembly, and the slug faces (named PIERCED_n, carrying
PIERCED_TYPE / PIERCED_P / PIERCED_W) picked in the dialog in place of the Select Slug button's face pick.

After OK the faces are grouped by PIERCED_TYPE, then P, then W (rounded to 4 places). Each group gets its own copy
of each library seed, saved as the next free {job}-{op}-NNN.prt in the op folder, counting up from the station's
start number (lsp1 100, usp1 600, ...; lspNNN / uspNNN for a non-CTS job). At each face the button and punch go at
the slug's PIERCED_AXIS_X_n origin raised by `e`, the retainer at the origin, oriented by the slug's X / Y axes; each
is aligned to the slug's Z axis (the constraint then deleted), gets the face's PIERCED_* attributes and joins the
station's BODY reference set. A punch and retainer are then constrained together (punch fixed, Z axes aligned, the
retainer's ALIGNPUNCH face touching the punch's PUNCHTOPFACE, its XZPLANE parallel to the punch's BALL_SEAT_ANGLE;
the constraints on layer 254) and all three end on BODY.

Same assembly: everything goes into the display part (layer 1 in an lsp, 101 in a usp). Otherwise (the form's
default) the button goes into the matching lspN (layer 1) and the punch and retainer into the uspN (layer 101), both
of which must be loaded.

Differences from the C#:
  - A detail box takes the detail's number, its leaf or its full path. The C# compared it with the full path only.
  - A seed is only copied to a new detail when its box is checked. The C# copied all three for every group.
  - `e` is always the original display part's. The C# Different-assemblies path read it from whatever was displayed
    by then (the lsp or usp after the first face).
  - Faces not named PIERCED_n or without a PIERCED_TYPE are dropped from the pick. The C# threw on them mid-run.
  - Dropped: GetCurrentDetailNumberOfChildren (its `Length >= 0` test always gave -1, so the start number was always
    the table's), PrintResults (all commented out), and the unused AddButton / AddPunch / AddRetainer /
    GetNextDetailNumber.

Never run in NX.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
from typing import Any, Dict, List, Optional, Tuple, cast

# Session.Execute does not put the script's folder on sys.path, so the shared module would not import.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)
# The shared modules are in the python folder beside this file (src\UFuncs\python; deployed, Ufunc\python).
_shared_python = os.path.join(_here, "python")
if os.path.isdir(_shared_python) and _shared_python not in sys.path:
    sys.path.insert(1, _shared_python)

import NXOpen  # noqa: E402
import NXOpen.Assemblies  # noqa: E402
import NXOpen.BlockStyler  # noqa: E402
import NXOpen.UF  # noqa: E402

import tsg_nx as nx  # noqa: E402
from tsg_dialog import Dialog, title_with_version  # noqa: E402

ufunc_name = "add-pierce-components"

SmartButtonMetric = "G:\\0Library\\Button\\Smart Button Metric.prt"
SmartButtonEnglish = "G:\\0Library\\Button\\Smart Button English.prt"
SmartPunchMetric = "G:\\0Library\\PunchPilot\\Metric\\Smart Punch Metric.prt"
SmartPunchEnglish = "G:\\0Library\\PunchPilot\\English\\Smart Punch English.prt"
SmartBallLockRetainerMetric = "G:\\0Library\\Retainers\\Metric\\Smart Ball Lock Retainer Metric.prt"
SmartBallLockRetainerEnglish = "G:\\0Library\\Retainers\\English\\Smart Ball Lock Retainer English.prt"

SlugRefsetName = "SLUG BUTTON ALIGN"
RetainerAlignPunchFaceName = "ALIGNPUNCH"
PunchTopFaceName = "PUNCHTOPFACE"
PiercedP = "PIERCED_P"
PiercedW = "PIERCED_W"
PiercedType = "PIERCED_TYPE"
PiercedFaceRegex = re.compile(r"^PIERCED_([0-9]{1,})$")
ConstraintLayer = 254

# The same-assembly path's display part name, and RegexLspUsp for the other one.
_SameAssemblyRegex = re.compile(r"^[0-9]{4,5}-([0-9]{3})-[l|u]sp([0-9]{1,})$")
_LspUspRegex = re.compile(r"^(?P<customerNum>\d+)-(?P<opNum>\d+)-(?P<subPlate>lsp|usp)(?P<extraOpNum>\d+)?$")
_DetailRegex = re.compile(r"^\d+-\d+-(\d+)$")

# The first detail number of each station: GetUsp/LspDetailNumberShort (CTS jobs, lsp1..15) and ...Long (lsp010..150).
_UspShort = [600, 700, 800, 900, 650, 750, 850, 950, 675, 775, 875, 975, 680, 780, 880]
_LspShort = [100, 200, 300, 400, 150, 250, 350, 450, 175, 275, 375, 475, 180, 280, 380]

MetricUnits = "Metric"
EnglishUnits = "English"

_ErrorCannotLaunchDialog = 3520048

# The positioning API is not in the hand-written NXOpen stubs.
_NX: Any = NXOpen


def _start_number(is_upper: bool, station_number: int, is_cts_job: bool) -> int:
    """AddPierceComponentsGet{Usp,Lsp}DetailNumber{Short,Long}"""
    table = _UspShort if is_upper else _LspShort
    index = station_number if is_cts_job else station_number // 10 if station_number % 10 == 0 else 0
    if 1 <= index <= len(table):
        return table[index - 1]
    return 881 if is_upper else 381


def face_name_integer(face: NXOpen.Face) -> int:
    """AddPierceComponentsGetFaceNameInteger"""
    match = PiercedFaceRegex.match(face.Name or "")
    if not match:
        raise ValueError('"{}" is invalid.'.format(face.Name))
    return int(match.group(1))


def is_slug_face(face: NXOpen.Face) -> bool:
    """A face this UFunc can use: named PIERCED_n, with a PIERCED_TYPE."""
    return (PiercedFaceRegex.match(face.Name or "") is not None
            and face.HasUserAttribute(PiercedType, NXOpen.NXObject.AttributeType.Any, -1))


def _attribute_text(obj: NXOpen.NXObject, title: str) -> str:
    return obj.GetUserAttributeAsString(title, NXOpen.NXObject.AttributeType.Any, -1)


def _real_attribute(obj: NXOpen.NXObject, title: str) -> float:
    return round(float(_attribute_text(obj, title)), 4)


def check_strip_control() -> bool:
    """btnSelect_Click's check: exactly one loaded strip control. Prints and returns False otherwise."""
    controls = [p.FullPath for p in nx.session_.Parts if "strip-control" in p.FullPath]
    if not controls:
        nx.print_("There is no strip control loaded. Please load one before continuing.")
        return False
    if len(controls) > 1:
        nx.print_("More than one strip control is loaded:")
        for control in controls:
            nx.print_(control)
        return False
    return True


def _e_expression() -> NXOpen.Expression:
    """AddPierceComponentsConfirmStripControlAndEExpression's `e` check, and the expression itself."""
    matches = [e for e in nx.display_part().Expressions if e.Name == "e"]
    if not matches:
        raise RuntimeError("Unable to find an expression with the name of 'e'.")
    return matches[0]


def _seed(kind: str, is_metric: bool) -> str:
    return {
        "button": SmartButtonMetric if is_metric else SmartButtonEnglish,
        "punch": SmartPunchMetric if is_metric else SmartPunchEnglish,
        "retainer": SmartBallLockRetainerMetric if is_metric else SmartBallLockRetainerEnglish,
    }[kind]


def part_path(kind: str, is_metric: bool, detail: str) -> str:
    """AddPierceComponentsGetPartPaths for one kind: the library seed, or the typed detail in the display part's
    folder after checking its LIBRARY attribute names that seed."""
    seed = _seed(kind, is_metric)
    detail = detail.strip()
    if not detail:
        return seed
    directory = os.path.dirname(nx.display_part().FullPath)
    found = None
    for name in os.listdir(directory):
        leaf, extension = os.path.splitext(name)
        match = _DetailRegex.match(leaf)
        if extension.lower() != ".prt" or not match:
            continue
        path = os.path.join(directory, name)
        if detail.lower() in (path.lower(), leaf.lower(), match.group(1)):
            found = path
            break
    if found is None:
        raise RuntimeError("Could not find a detail with # '{}' in folder '{}'.".format(detail, directory))
    part = nx.find_or_open(found)
    if not part.HasUserAttribute("LIBRARY", NXOpen.NXObject.AttributeType.String, -1):
        raise RuntimeError("The selected part {} does not have a 'LIBRARY' attribute.".format(part.Leaf))
    expected = os.path.splitext(os.path.basename(seed))[0]
    value = part.GetUserAttributeAsString("LIBRARY", NXOpen.NXObject.AttributeType.String, -1)
    if value != expected:
        raise RuntimeError("{}'s LIBRARY attribute {} does not equal {}.".format(part.Leaf, value, expected))
    return part.FullPath


def new_part_path(start_of_path: str, original_path: str, number: int) -> str:
    """AddPierceComponentsGetNewPartPath - a library seed is copied to the first free {start}{number + i}.prt; a
    detail is used as it is."""
    if not original_path.lower().startswith("g:\\0library"):
        return original_path
    for i in range(1000):
        path = "{}{}.prt".format(start_of_path, number + i)
        if os.path.exists(path):
            continue
        shutil.copyfile(original_path, path)
        return path
    raise RuntimeError("No free detail number from {}{}.".format(start_of_path, number))


def _group_faces(faces: List[NXOpen.Face]) -> List[List[NXOpen.Face]]:
    """The faces by PIERCED_TYPE, then PIERCED_P, then PIERCED_W (rounded to 4 places), in pick order."""
    groups: Dict[Tuple[str, float, float], List[NXOpen.Face]] = {}
    for face in faces:
        key = (_attribute_text(face, PiercedType), _real_attribute(face, PiercedP), _real_attribute(face, PiercedW))
        groups.setdefault(key, []).append(face)
    return list(groups.values())


def _show(part: NXOpen.BasePart) -> None:
    nx.set_display_part(part)
    nx.set_work_part(part)


# ----- constraints (AddPierceComponentsConstraints) -----

def _begin(part: NXOpen.BasePart) -> Any:
    positioner = cast(Any, part).ComponentAssembly.Positioner
    positioner.ClearNetwork()
    positioner.PrimaryArrangement = cast(Any, part).ComponentAssembly.Arrangements.FindObject("Arrangement 1")
    positioner.BeginAssemblyConstraints()
    return positioner


def _touch_align(part: NXOpen.BasePart, alignment: Any, movable: NXOpen.NXObject, fixed: NXOpen.NXObject) -> Any:
    """CreateTouchAlignImpl"""
    positioner = _begin(part)
    network = positioner.EstablishNetwork()
    network.MoveObjectsState = True
    network.NetworkArrangementsMode = _NX.Positioning.ComponentNetwork.ArrangementsMode.Existing
    constraint = positioner.CreateConstraint(True)
    constraint.ConstraintAlignment = alignment
    constraint.ConstraintType = _NX.Positioning.Constraint.Type.Touch
    constraint.CreateConstraintReference(cast(Any, movable).OwningComponent, movable, False, False, False)
    constraint.CreateConstraintReference(cast(Any, fixed).OwningComponent, fixed, False, False, False)
    network.Solve()
    positioner.ClearNetwork()
    nx.delete_objects([network])
    positioner.EndAssemblyConstraints()
    return constraint.GetDisplayedConstraint()


def create_align(part: NXOpen.BasePart, movable: NXOpen.NXObject, fixed: NXOpen.NXObject) -> Any:
    """CreateAlign"""
    return _touch_align(part, _NX.Positioning.Constraint.Alignment.CoAlign, movable, fixed)


def create_touch(part: NXOpen.BasePart, movable: NXOpen.NXObject, fixed: NXOpen.NXObject) -> Any:
    """CreateTouch"""
    return _touch_align(part, _NX.Positioning.Constraint.Alignment.ContraAlign, movable, fixed)


def create_parallel(part: NXOpen.BasePart, movable: NXOpen.NXObject, geometry: NXOpen.NXObject) -> Any:
    """CreateParallelConstraint"""
    positioner = _begin(part)
    network = positioner.EstablishNetwork()
    network.MoveObjectsState = True
    network.NetworkArrangementsMode = _NX.Positioning.ComponentNetwork.ArrangementsMode.Existing
    constraint = positioner.CreateConstraint(True)
    constraint.ConstraintType = _NX.Positioning.Constraint.Type.Parallel
    constraint.CreateConstraintReference(cast(Any, movable).OwningComponent, movable, False, False, False)
    constraint.CreateConstraintReference(cast(Any, geometry).OwningComponent, geometry, False, False, False)
    network.Solve()
    positioner.ClearNetwork()
    nx.delete_objects([network])
    positioner.DeleteNonPersistentConstraints()
    positioner.EndAssemblyConstraints()
    return constraint.GetDisplayedConstraint()


def create_fixed(part: NXOpen.BasePart, component: NXOpen.Assemblies.Component) -> Any:
    """CreateFixedConstraint"""
    positioner = _begin(part)
    constraint = positioner.CreateConstraint(True)
    constraint.ConstraintType = _NX.Positioning.Constraint.Type.Fix
    constraint.CreateConstraintReference(component, component, False, False, False)
    positioner.EndAssemblyConstraints()
    return constraint.GetDisplayedConstraint()


def _to_constraint_layer(displayed: Any) -> None:
    displayed.Layer = ConstraintLayer
    displayed.RedisplayObject()


def _single_member(component: NXOpen.Assemblies.Component, kind: type, name: str) -> Any:
    found = [m for m in nx.members(component) if isinstance(m, kind) and m.Name == name]
    if len(found) != 1:
        raise RuntimeError("{} has {} {} named {}.".format(component.DisplayName, len(found), kind.__name__, name))
    return found[0]


def constrain_punch_and_retainer(punch: NXOpen.Assemblies.Component,
                                 retainer: NXOpen.Assemblies.Component) -> None:
    """AddPierceComponentsConstrainPunchAndRetainer: in the punch's parent - fix the punch, align the Z axes, touch
    the faces, the ball seat plane parallel to the retainer's XZ plane."""
    part = nx.prototype(cast(Any, punch).OwningComponent)
    _show(part)
    _to_constraint_layer(create_fixed(part, punch))

    # ConstrainZAxes
    nx.set_reference_set(punch, "ALIGN")
    nx.set_reference_set(retainer, "MATE")
    retainer_z = _single_member(retainer, NXOpen.DatumAxis, "ZAXIS")
    csyses = [m for m in nx.members(punch) if isinstance(m, NXOpen.CartesianCoordinateSystem)]
    if len(csyses) != 1:
        raise RuntimeError("{} has {} coordinate systems in ALIGN.".format(punch.DisplayName, len(csyses)))
    punch_z_direction = nx.axis_z(cast(Any, csyses[0]).Orientation.Element)
    punch_zs = [m for m in nx.members(punch) if isinstance(m, NXOpen.DatumAxis)
                and nx.vectors_equal(cast(Any, m).Direction, punch_z_direction)]
    if len(punch_zs) != 1:
        raise RuntimeError("{} has {} datum axes along its Z.".format(punch.DisplayName, len(punch_zs)))
    _to_constraint_layer(create_align(part, retainer_z, punch_zs[0]))

    # ConstrainFaces
    punch_face = _single_member(punch, NXOpen.Face, PunchTopFaceName)
    retainer_face = _single_member(retainer, NXOpen.Face, RetainerAlignPunchFaceName)
    _to_constraint_layer(create_touch(part, retainer_face, punch_face))

    # ConstrainAlignBallSetAndPlane
    nx.set_reference_set(punch, "MATE")
    nx.set_reference_set(retainer, "MATE")
    retainer_plane = _single_member(retainer, NXOpen.DatumPlane, "XZPLANE")
    ball_seat = _single_member(punch, NXOpen.DatumPlane, "BALL_SEAT_ANGLE")
    _to_constraint_layer(create_parallel(part, retainer_plane, ball_seat))


# ----- adding -----

def add_component_and_constrain(face: NXOpen.Face, path: str, part: NXOpen.Part, reference_set: str, layer: int,
                                z_offset: Optional[float] = None) -> NXOpen.Assemblies.Component:
    """AddPierceComponentsAddComponentAndConstrain: adds `path` to `part` at the slug's axes (raised by z_offset in
    absolute Z), copies the face's PIERCED_* attributes onto it, puts it in the part's BODY reference set and
    aligns its absolute-Z datum axis to the slug's Z axis (the constraint is deleted again)."""
    _show(part)
    face.Unhighlight()
    number = face_name_integer(face)
    layout = cast(Any, face).OwningComponent
    x_axis = _single_member(layout, NXOpen.DatumAxis, "PIERCED_AXIS_X_{}".format(number))
    y_axis = _single_member(layout, NXOpen.DatumAxis, "PIERCED_AXIS_Y_{}".format(number))
    z_axis = _single_member(layout, NXOpen.DatumAxis, "PIERCED_AXIS_Z_{}".format(number))
    orientation = nx.matrix_from_axes(x_axis.Direction, y_axis.Direction)
    origin = x_axis.Origin
    if z_offset is not None:
        origin = nx.add_z(origin, z_offset)

    name = os.path.splitext(os.path.basename(path))[0]
    component = nx.add_component(part, path, reference_set, name, origin, orientation, layer)

    for title in (PiercedP, PiercedW, PiercedType):
        component.SetUserAttribute(title, -1, _attribute_text(face, title), NXOpen.Update.Option.Now)

    nx.set_reference_set(component, reference_set)

    # ReferenceSetReset: BODY while the component joins the part's BODY reference set, then back.
    nx.set_reference_set(component, "BODY")
    try:
        body = nx.find_reference_set_or_null(nx.prototype(cast(Any, component).OwningComponent), "BODY")
        if body is not None:
            body.AddObjectsToReferenceSet([component])
    finally:
        nx.set_reference_set(component, reference_set)

    z_absolute = NXOpen.Vector3d(0.0, 0.0, 1.0)
    component_zs = [m for m in nx.members(component) if isinstance(m, NXOpen.DatumAxis)
                    and nx.vectors_equal(cast(Any, m).Direction, z_absolute)]
    if len(component_zs) != 1:
        raise RuntimeError("{} has {} datum axes along absolute Z.".format(component.DisplayName, len(component_zs)))
    nx.delete_objects([create_align(part, component_zs[0], z_axis)])
    return component


class _Settings(object):
    """The dialog's values, captured in ok()."""

    def __init__(self, is_metric: bool, add: Dict[str, bool], details: Dict[str, str], same_assembly: bool,
                 faces: List[NXOpen.Face]) -> None:
        self.is_metric = is_metric
        self.add = add
        self.details = details
        self.same_assembly = same_assembly
        self.faces = faces


def _place(settings: _Settings, face: NXOpen.Face, paths: Dict[str, str], parts: Dict[str, NXOpen.Part],
           layers: Dict[str, int], e_value: float) -> None:
    """One face: the punch, retainer and button (each when checked), the punch and retainer constrained together,
    all three on BODY - with the slug's layout component on SLUG BUTTON ALIGN meanwhile."""
    layout = cast(Any, face).OwningComponent
    original = layout.ReferenceSet
    nx.set_reference_set(layout, SlugRefsetName)
    try:
        punch = retainer = button = None
        if settings.add["punch"]:
            punch = add_component_and_constrain(face, paths["punch"], parts["punch"], "ALIGN", layers["punch"],
                                                e_value)
        if settings.add["retainer"]:
            retainer = add_component_and_constrain(face, paths["retainer"], parts["retainer"], "MATE",
                                                   layers["retainer"])
        if settings.add["button"]:
            button = add_component_and_constrain(face, paths["button"], parts["button"], "ALIGN", layers["button"],
                                                 e_value)
        if punch is not None and retainer is not None:
            constrain_punch_and_retainer(punch, retainer)
        for component in (button, retainer, punch):
            if component is not None:
                nx.set_reference_set(component, "BODY")
    finally:
        nx.set_reference_set(layout, original)


def _folder() -> Any:
    from ExportStrip import _GFolder

    path = nx.work_part().FullPath
    try:
        return _GFolder.create(path)
    except Exception as ex:
        raise RuntimeError("The work part {} does not reside within a job folder.".format(path)) from ex


def same_assembly(settings: _Settings) -> None:
    """AddPierceComponentsSameAssembly: everything into the displayed lsp / usp."""
    e_value = _e_expression().Value
    display = nx.display_part()
    leaf = os.path.splitext(os.path.basename(display.FullPath))[0]
    match = _SameAssemblyRegex.match(leaf)
    if not match:
        raise RuntimeError("{} is not a valid usp or lsp.".format(leaf))
    folder = _folder()
    op, station_number = match.group(1), int(match.group(2))
    is_upper = "usp" in display.Leaf
    layer = 1 if "lsp" in display.Leaf else 101
    seeds = {kind: part_path(kind, settings.is_metric, settings.details[kind])
             for kind in settings.add if settings.add[kind]}
    start_of_path = "{}\\{}-{}-".format(folder.dir_op(op), folder.CustomerNumber, op)

    nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, "Add Pierce Components")
    for faces in _group_faces(settings.faces):
        number = _start_number(is_upper, station_number, folder.is_cts_job())
        paths = {kind: new_part_path(start_of_path, seeds[kind], number)
                 for kind in ("button", "retainer", "punch") if settings.add[kind]}
        for face in faces:
            _place(settings, face, paths, {kind: display for kind in settings.add},
                   {kind: layer for kind in settings.add}, e_value)


def different_assemblies(settings: _Settings) -> None:
    """AddPierceComponentsDifferentAssemblies (the form's default, marked [Obsolete] in the C#): the button into
    the lspN, the punch and retainer into the uspN."""
    folder = _folder()
    e_value = _e_expression().Value
    leaf = os.path.splitext(os.path.basename(nx.display_part().FullPath))[0]
    match = _LspUspRegex.match(leaf)
    if not match:
        raise RuntimeError("{} is not a valid usp or lsp.".format(leaf))
    op = match.group("opNum")
    station_text = match.group("extraOpNum") or ""
    station_number = int(station_text) if station_text else 0
    lsp_name = "{}-{}-lsp{}".format(folder.CustomerNumber, op, station_text)
    usp_name = "{}-{}-usp{}".format(folder.CustomerNumber, op, station_text)

    def loaded(name: str) -> Optional[NXOpen.Part]:
        found = [p for p in nx.session_.Parts if name in p.FullPath]
        if len(found) > 1:
            raise RuntimeError("More than one loaded part holds {}.".format(name))
        return cast(NXOpen.Part, found[0]) if found else None

    lsp, usp = loaded(lsp_name), loaded(usp_name)
    if settings.add["button"] and lsp is None:
        raise RuntimeError('Could not find part "{}" loaded in your session.'.format(lsp_name))
    if (settings.add["punch"] or settings.add["retainer"]) and usp is None:
        raise RuntimeError('Could not find part "{}" loaded in your session.'.format(usp_name))
    seeds = {kind: part_path(kind, settings.is_metric, settings.details[kind])
             for kind in settings.add if settings.add[kind]}
    start_of_path = "{}\\{}-{}-".format(folder.dir_op(op), folder.CustomerNumber, op)
    parts = cast(Dict[str, NXOpen.Part], {"button": lsp, "punch": usp, "retainer": usp})

    nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, "Add Pierce Components")
    for faces in _group_faces(settings.faces):
        paths: Dict[str, str] = {}
        if settings.add["button"]:
            paths["button"] = new_part_path(start_of_path, seeds["button"],
                                            _start_number(False, station_number, folder.is_cts_job()))
        for kind in ("retainer", "punch"):
            if settings.add[kind]:
                paths[kind] = new_part_path(start_of_path, seeds[kind],
                                            _start_number(True, station_number, folder.is_cts_job()))
        for face in faces:
            _place(settings, face, paths, parts, {"button": 1, "punch": 101, "retainer": 101}, e_value)


# ----- the dialog -----

_Kinds = ("button", "punch", "retainer")


class _PierceDialog(Dialog):
    """The form: Units, the three Add boxes with their detail boxes, Same assembly, and the slug faces."""

    dlx_name = "AddPierceComponents.dlx"

    def __init__(self, title: str) -> None:
        self.title = title
        super().__init__()
        self.settings: Optional[_Settings] = None

    def initialize(self) -> None:
        mask = NXOpen.Selection.MaskTriple(NXOpen.UF.UFConstants.UF_solid_type, 0,
                                           NXOpen.UF.UFConstants.UF_UI_SEL_FEATURE_ANY_FACE)
        self.block("faces").SetSelectionFilter(NXOpen.Selection.SelectionAction.ClearAndEnableSpecific, [mask])
        self.assembly_scope(self.block("faces"))

    def shown(self) -> None:
        # The form opened with all three checked.
        for kind in _Kinds:
            self.block(kind).Value = True
        self._refresh()

    def update(self, block: NXOpen.BlockStyler.UIBlock) -> None:
        if block == self.block("faces"):
            picked = self._faces()
            kept = [f for f in picked if is_slug_face(f)]
            if len(kept) != len(picked):
                self.block("faces").SetSelectedObjects(kept)
                self.message("{} picked face(s) are not slug faces (PIERCED_n with a PIERCED_TYPE) and were "
                             "dropped.".format(len(picked) - len(kept)))
        self._refresh()

    def enable_ok(self) -> bool:
        return bool(self._faces()) and any(bool(self.block(kind).Value) for kind in _Kinds)

    def ok(self) -> bool:
        faces = self._faces()
        if not faces:
            self.message("Select the slug faces.")
            return False
        self.settings = _Settings(
            str(self.block("units").ValueAsString) == MetricUnits,
            {kind: bool(self.block(kind).Value) for kind in _Kinds},
            {kind: self.string_value(self.block(kind + "_detail")) for kind in _Kinds},
            bool(self.block("same_assembly").Value),
            faces)
        return True

    def _faces(self) -> List[NXOpen.Face]:
        return [cast(NXOpen.Face, o) for o in self.selected(self.block("faces")) if isinstance(o, NXOpen.Face)]

    def _refresh(self) -> None:
        for kind in _Kinds:
            self.block(kind + "_detail").Enable = bool(self.block(kind).Value)


def execute() -> None:
    """The form's checks, its dialog, then Select Slug's run with the display and work parts put back."""
    if not check_strip_control():
        return
    _e_expression()
    dialog = _PierceDialog(title_with_version("Add Pierce Components"))
    try:
        if not dialog.run() or dialog.settings is None:
            return
    except NXOpen.NXException as ex:
        if ex.ErrorCode != _ErrorCannotLaunchDialog:
            raise
        nx.print_exception(ex)
        return
    settings = dialog.settings
    with nx.display_part_reset():
        if settings.same_assembly:
            same_assembly(settings)
        else:
            different_assemblies(settings)


def main() -> None:
    """The add-pierce-components UFunc - its menu button runs this file. An escaping exception is printed."""
    import usage_db

    with usage_db.run(ufunc_name):
        try:
            execute()
        except Exception as ex:
            nx.print_exception(ex)


if __name__ == "__main__":
    main()

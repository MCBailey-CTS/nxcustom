"""
Shared helpers for the TSG Python UFunc library.

The Python counterpart of the bits of src\\Globals.cs the migrated methods need. Each helper names the
C# member it ports so the two can be kept in step while both exist. Only port what a migrated method
actually calls - this module should grow one method at a time, not mirror Globals.cs wholesale.
"""

from __future__ import annotations

import contextlib
import math
import os
import traceback
from typing import Any, Union
from typing import Iterable, Iterator, List, NamedTuple, Optional, Sequence, cast

import NXOpen
import NXOpen.Assemblies
import NXOpen.Features
import NXOpen.GeometricUtilities
import NXOpen.Layer
import NXOpen.UF
import NXOpen.UserDefinedObjects

session_ = NXOpen.Session.GetSession()
ufsession_ = NXOpen.UF.UFSession.GetUFSession()

# Globals.cs constants.
LayerFastener = 99
RefsetEntirePart = "Entire Part"
RefsetEmpty = "Empty"

# NXOpen.UF.UFConstants - values read from NXOpen.UF.dll (NX 2306). Note suppress is 0, not 1.
UF_DISP_SUPPRESS_DISPLAY = 0
UF_DISP_UNSUPPRESS_DISPLAY = 1

# NXException.ErrorCode for a boolean whose tool does not touch the target.
ErrorNoInterference = 670030


# ---------------------------------------------------------------------------------------------------
# Listing window
# ---------------------------------------------------------------------------------------------------

def print_(message: object) -> None:
    """Extensions.print - writes a line to the NX listing window."""
    lw = session_.ListingWindow
    lw.Open()
    lw.WriteLine(str(message))


def library_file(name: str, near: str = "") -> str:
    """
    The path of a file the UFuncs ship beside their scripts (a .dlx, a .ps1). Deployed, bin\\<config>\\python holds
    them all; in the source tree they are split between src\\UFuncs and src\\python, so this looks beside near (a
    module's __file__) first, then beside this module, then in the sibling UFuncs folder. A missing file comes back
    as the first place looked, so the caller's error names a sensible path.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    folders = [os.path.dirname(os.path.abspath(near))] if near else []
    folders += [here, os.path.join(os.path.dirname(here), "UFuncs")]
    for folder in folders:
        path = os.path.join(folder, name)
        if os.path.isfile(path):
            return path
    return os.path.join(folders[0], name)


def syslog(message: object) -> None:
    """Writes to the NX syslog only (not the listing window), one WriteLine per line. Never raises."""
    try:
        for line in str(message).splitlines() or [""]:
            session_.LogFile.WriteLine(line)
    except Exception:
        pass  # Nowhere left to report it.


def print_exception(ex: BaseException, user_message: Optional[str] = None) -> None:
    """Exception.__PrintException - same layout as the C# version so the listing window reads alike."""
    print_("///////////////////////////////////////////")
    if user_message:
        print_("UserMessage: {}".format(user_message))
    print_("Message: {}".format(ex))
    print_("Exception: {}".format(type(ex).__name__))
    if isinstance(ex, NXOpen.NXException):
        print_("Error Code: {}".format(ex.ErrorCode))
    for line in traceback.format_exc().splitlines():
        print_(line)
    print_("///////////////////////////////////////////")
    progress("FAILED: {}".format(ex))

    # tblExceptions, as __PrintException writes it. usage_db never raises, but a missing pyodbc must not either.
    try:
        import usage_db
        usage_db.log_exception(ex, user_message)
    except Exception:
        pass


# The file Auto Design's progress window follows (AutoDesign.py sets it for the length of a run and clears it after),
# so a builder launched on its own writes nothing.
progress_path: Optional[str] = None


def progress(message: str) -> None:
    """Appends a line to Auto Design's progress window; a no-op unless an Auto Design run is following the file."""
    if not progress_path:
        return
    try:
        with open(progress_path, "a", encoding="utf-8") as f:
            f.write(str(message).replace("\n", " ") + "\n")
    except OSError:
        pass


# ---------------------------------------------------------------------------------------------------
# Session pseudo-properties (__display_part_, __work_part_, __work_component_)
# ---------------------------------------------------------------------------------------------------

def display_part() -> NXOpen.Part:
    return session_.Parts.Display


def set_display_part(part: NXOpen.BasePart) -> None:
    session_.Parts.SetDisplay(part, False, False)


def work_part() -> NXOpen.Part:
    return session_.Parts.Work


def set_work_part(part: NXOpen.BasePart) -> None:
    session_.Parts.SetWork(part)


def set_work_component(component: Optional[NXOpen.Assemblies.Component]) -> None:
    session_.Parts.SetWorkComponent(
        component,
        NXOpen.PartCollection.RefsetOption.Current,
        NXOpen.PartCollection.WorkComponentOption.Given)


def tagged_object(tag: NXOpen.Tag) -> NXOpen.TaggedObject:
    return NXOpen.TaggedObjectManager.GetTaggedObject(tag)


# ---------------------------------------------------------------------------------------------------
# Disposable wrappers -> context managers
# ---------------------------------------------------------------------------------------------------

@contextlib.contextmanager
def display_part_reset() -> Iterator[None]:
    """DisplayPartReset - restores the display and work parts on exit."""
    original_display = display_part()
    if original_display is None:
        raise RuntimeError("No display part.")
    original_work = work_part()
    try:
        yield
    finally:
        set_display_part(original_display)
        set_work_part(original_work)


@contextlib.contextmanager
def suppress_display() -> Iterator[None]:
    """SuppressDisplayReset - suppresses display updates, regenerates on exit."""
    ufsession_.Disp.SetDisplay(UF_DISP_SUPPRESS_DISPLAY)
    try:
        yield
    finally:
        ufsession_.Disp.SetDisplay(UF_DISP_UNSUPPRESS_DISPLAY)
        ufsession_.Disp.RegenerateDisplay()


@contextlib.contextmanager
def reset_work_layer() -> Iterator[None]:
    """ResetWorkLayer - restores the display part's work layer on exit."""
    layer = display_part().Layers.WorkLayer
    try:
        yield
    finally:
        display_part().Layers.SetState(layer, NXOpen.Layer.State.WorkLayer)


# ---------------------------------------------------------------------------------------------------
# Name predicates (Globals.cs Component/string region)
# ---------------------------------------------------------------------------------------------------

def is_shcs(name: str) -> bool:
    """string._IsShcs_ (substring test, not the regex)"""
    return "-shcs-" in name.lower()


def is_dwl(name: str) -> bool:
    """string._IsDwl_"""
    return "-dwl-" in name.lower()


def is_jck_screw_tsg(name: str) -> bool:
    """string._IsJckScrewTsg_"""
    return "-jck-screw-tsg" in name.lower()


def is_jck_screw(name: str) -> bool:
    """string._IsJckScrew_"""
    return not is_jck_screw_tsg(name) and "-jck-screw-" in name.lower()


# ---------------------------------------------------------------------------------------------------
# Component / body helpers
# ---------------------------------------------------------------------------------------------------

def is_loaded(component: NXOpen.Assemblies.Component) -> bool:
    """Component.__IsLoaded"""
    return isinstance(component.Prototype, NXOpen.Part)


def prototype(component: NXOpen.Assemblies.Component) -> NXOpen.BasePart:
    """Component.__Prototype"""
    return component.Prototype


def proto_child_comp(component: NXOpen.Assemblies.Component) -> NXOpen.Assemblies.Component:
    """Component.__ProtoChildComp - the same child as seen inside its owning component's prototype."""
    instance = ufsession_.Assem.AskInstOfPartOcc(component.Tag)
    root = root_component(component.OwningComponent.Prototype)
    if root is None:
        raise ValueError('The owning component of "{}" has no root component.'.format(component.DisplayName))
    return cast(NXOpen.Assemblies.Component,
                tagged_object(ufsession_.Assem.AskPartOccOfInst(root.Tag, instance)))


def members(component: NXOpen.Assemblies.Component) -> List[NXOpen.NXObject]:
    """Component.__Members"""
    result: List[NXOpen.NXObject] = []
    tag = 0
    while True:
        tag = ufsession_.Assem.CycleEntsInPartOcc(component.Tag, tag)
        if tag == 0:
            break
        try:
            obj = tagged_object(tag)
            if isinstance(obj, NXOpen.NXObject):
                result.append(obj)
        except Exception as ex:
            print_exception(ex)
    return result


def solid_body_members(component: NXOpen.Assemblies.Component) -> List[NXOpen.Body]:
    """Component.__SolidBodyMembers"""
    return [m for m in members(component) if isinstance(m, NXOpen.Body) and m.IsSolidBody]


def reference_set_names(part: NXOpen.BasePart) -> List[str]:
    return [refset.Name for refset in part.GetAllReferenceSets()]


def set_reference_set(component: NXOpen.Assemblies.Component, name: str) -> None:
    """Component.__ReferenceSet(string)"""
    part = component.Prototype
    if not isinstance(part, NXOpen.Part):
        raise ValueError('The given component "{}" is not loaded.'.format(component.DisplayName))
    if name not in (RefsetEntirePart, RefsetEmpty) and name not in reference_set_names(part):
        raise RuntimeError('Cannot set component "{}" to the reference set "{}".'.format(
            component.DisplayName, name))
    component.DirectOwner.ReplaceReferenceSet(component, name)


def interferes_with(target: NXOpen.Body, component: NXOpen.Assemblies.Component) -> bool:
    """Body.__InterferesWith(Component)"""
    if target.OwningPart.Tag != component.OwningPart.Tag:
        raise ValueError("Body and component are not in the same assembly.")
    tools = [b.Tag for b in solid_body_members(component)]
    if not tools:
        return False
    results = ufsession_.Modeling.CheckInterference(target.Tag, len(tools), tools)
    return any(r == 1 for r in results)


def create_linked_body(child: NXOpen.Assemblies.Component) -> NXOpen.Features.Feature:
    """Component.__CreateLinkedBody - wave links the child's solid bodies into the work part."""
    part = work_part()
    builder = part.BaseFeatures.CreateWaveLinkBuilder(None)
    try:
        extract = builder.ExtractFaceBuilder
        extract.ParentPart = NXOpen.Features.ExtractFaceBuilder.ParentPartType.OtherPart
        builder.Type = NXOpen.Features.WaveLinkBuilder.Types.BodyLink
        extract.Associative = True
        extract.FeatureOption = NXOpen.Features.ExtractFaceBuilder.FeatureOptionType.OneFeatureForAllBodies
        rule = part.ScRuleFactory.CreateRuleBodyDumb(solid_body_members(child), False)
        extract.ExtractBodyCollector.ReplaceRules([rule], False)
        extract.FixAtCurrentTimestamp = False
        return cast(NXOpen.Features.Feature, builder.Commit())
    finally:
        builder.Destroy()


def create_linked_bodies(child: NXOpen.Assemblies.Component) -> List[NXOpen.Features.ExtractFace]:
    """Component.__CreateLinkedBodies - like create_linked_body, but one LINKED_BODY feature per solid body."""
    part = work_part()
    builder = part.BaseFeatures.CreateWaveLinkBuilder(None)
    try:
        extract = builder.ExtractFaceBuilder
        extract.ParentPart = NXOpen.Features.ExtractFaceBuilder.ParentPartType.OtherPart
        builder.Type = NXOpen.Features.WaveLinkBuilder.Types.BodyLink
        extract.Associative = True
        extract.FeatureOption = NXOpen.Features.ExtractFaceBuilder.FeatureOptionType.SeparateFeatureForEachBody
        rule = part.ScRuleFactory.CreateRuleBodyDumb(solid_body_members(child), False)
        extract.ExtractBodyCollector.ReplaceRules([rule], False)
        extract.FixAtCurrentTimestamp = False
        builder.Commit()
        return [o for o in builder.GetCommittedObjects() if isinstance(o, NXOpen.Features.ExtractFace)]
    finally:
        builder.Destroy()


def create_boolean(target: NXOpen.Body, tool_bodies: Iterable[NXOpen.Body],
                   boolean_type: NXOpen.Features.Feature.BooleanType) -> NXOpen.Features.BooleanFeature:
    """BasePart.__CreateBoolean - built in the work part, like the C# version.

    The C# version feeds BooleanBuilder.Tools, which is obsolete; this uses the tool-body collector instead.
    """
    part = work_part()
    builder = part.Features.CreateBooleanBuilderUsingCollector(None)
    try:
        builder.Operation = boolean_type
        builder.Target = target
        collector = part.ScCollectors.CreateCollector()
        rule = part.ScRuleFactory.CreateRuleBodyDumb(list(tool_bodies))
        collector.ReplaceRules([rule], False)
        builder.ToolBodyCollector = collector
        return cast(NXOpen.Features.BooleanFeature, builder.Commit())
    finally:
        builder.Destroy()


def subtract(target: NXOpen.Body, tool_bodies: Iterable[NXOpen.Body]) -> NXOpen.Features.BooleanFeature:
    """Body.__Subtract"""
    return create_boolean(target, tool_bodies, NXOpen.Features.Feature.BooleanType.Subtract)


def root_component(part: NXOpen.BasePart) -> Optional[NXOpen.Assemblies.Component]:
    """BasePart.__RootComponent"""
    return part.ComponentAssembly.RootComponent


def descendants(component: NXOpen.Assemblies.Component, include_root: bool = True, include_suppressed: bool = False,
                include_unloaded: bool = False) -> Iterator[NXOpen.Assemblies.Component]:
    """Component.__Descendants"""
    if include_root:
        yield component
    for child in component.GetChildren():
        if child.IsSuppressed and not include_suppressed:
            continue
        if not is_loaded(child) and not include_unloaded:
            continue
        for descendant in descendants(child, True, include_suppressed, include_unloaded):
            yield descendant


def is_link_broken(extract_face: NXOpen.Features.Feature) -> bool:
    """ExtractFace.__IsBroken"""
    return ufsession_.Wave.IsLinkBroken(extract_face.Tag)


# ---------------------------------------------------------------------------------------------------
# Selection (TSG_Library.Ui.Selection)
# ---------------------------------------------------------------------------------------------------

def select_many_components(message: str) -> List[NXOpen.Assemblies.Component]:
    """Selection.SelectManyComponents(message) - returns [] on cancel."""
    mask = NXOpen.Selection.MaskTriple(NXOpen.UF.UFConstants.UF_component_type, 0, 0)
    response, objects = NXOpen.UI.GetUI().SelectionManager.SelectTaggedObjects(
        message,
        message,
        NXOpen.Selection.SelectionScope.AnyInAssembly,
        NXOpen.Selection.SelectionAction.ClearAndEnableSpecific,
        False,
        False,
        [mask])
    if response not in (NXOpen.Selection.Response.Ok, NXOpen.Selection.Response.ObjectSelected):
        return []
    return [obj for obj in objects if isinstance(obj, NXOpen.Assemblies.Component)]


# ---------------------------------------------------------------------------------------------------
# Geometry (Box3d, __RoundTo_125, __CreateBlock)
# ---------------------------------------------------------------------------------------------------

class Box3d(NamedTuple):
    MinX: float
    MinY: float
    MinZ: float
    MaxX: float
    MaxY: float
    MaxZ: float


def body_box(body: NXOpen.Body) -> Box3d:
    """Body.__Box3d - exact bounding box in absolute coordinates (OrientedBox against Tag.Null)."""
    min_corner, directions, distances = ufsession_.ModlGeneral.AskBoundingBoxExact(body.Tag, 0)
    # directions arrives as 3x3 or as 9 flat values depending on the binding; normalise to rows.
    flat = [value for row in directions for value in (row if hasattr(row, "__len__") else [row])]
    axes = [flat[0:3], flat[3:6], flat[6:9]]
    max_corner = [min_corner[i] + sum(axes[a][i] * distances[a] for a in range(3)) for i in range(3)]
    return Box3d(min(min_corner[0], max_corner[0]), min(min_corner[1], max_corner[1]),
                 min(min_corner[2], max_corner[2]), max(min_corner[0], max_corner[0]),
                 max(min_corner[1], max_corner[1]), max(min_corner[2], max_corner[2]))


def combine_boxes(boxes: Iterable[Optional[Box3d]]) -> Box3d:
    """Box3d.Combine"""
    present = [b for b in boxes if b is not None]
    return Box3d(min(b.MinX for b in present), min(b.MinY for b in present), min(b.MinZ for b in present),
                 max(b.MaxX for b in present), max(b.MaxY for b in present), max(b.MaxZ for b in present))


def round_to_125(distance: float) -> float:
    """double.__RoundTo_125 - rounds up to the next .125. Python's round() is banker's, like Math.Round."""
    round_value = round(distance, 3)
    truncate_value = float(math.trunc(round_value))
    fraction_value = round_value - truncate_value

    if fraction_value == 0:
        return round_value

    ii = .125
    while ii <= 1:
        if fraction_value <= ii:
            return truncate_value + ii
        ii += .125
    return distance


def create_block(min_point: NXOpen.Point3d, max_point: NXOpen.Point3d,
                 x_direction: NXOpen.Vector3d = NXOpen.Vector3d(1.0, 0.0, 0.0),
                 y_direction: NXOpen.Vector3d = NXOpen.Vector3d(0.0, 1.0, 0.0)) -> NXOpen.Features.Block:
    """BasePart.__CreateBlock(Matrix3x3, Point3d, Point3d) - diagonal-points block in the work part.

    The block takes its orientation from the WCS, so the WCS is turned to the given directions for the
    commit and put back afterwards.
    """
    csys = display_part().WCS.CoordinateSystem
    original = csys.Orientation.Element
    csys.SetDirections(x_direction, y_direction)
    builder = work_part().Features.CreateBlockFeatureBuilder(None)
    try:
        builder.Type = NXOpen.Features.BlockFeatureBuilder.Types.DiagonalPoints
        builder.BooleanOption.Type = NXOpen.GeometricUtilities.BooleanOperation.BooleanType.Create
        builder.SetTwoDiagonalPoints(min_point, max_point)
        return cast(NXOpen.Features.Block, builder.Commit())
    finally:
        builder.Destroy()
        csys.SetDirections(NXOpen.Vector3d(original.Xx, original.Xy, original.Xz),
                           NXOpen.Vector3d(original.Yx, original.Yy, original.Yz))


def create_block_two_points_and_height(orientation: NXOpen.Matrix3x3, origin_point: NXOpen.Point3d,
                                       corner_point: NXOpen.Point3d, height: float) -> NXOpen.Features.Block:
    """BasePart.__CreateBlock(Matrix3x3, Point3d, Point3d, double) - two-points-and-height block in the work part.

    Like create_block, the WCS is turned to orientation for the commit and put back afterwards.
    """
    csys = display_part().WCS.CoordinateSystem
    original = csys.Orientation.Element
    csys.SetDirections(axis_x(orientation), axis_y(orientation))
    builder = work_part().Features.CreateBlockFeatureBuilder(None)
    try:
        builder.Type = NXOpen.Features.BlockFeatureBuilder.Types.TwoPointsAndHeight
        builder.BooleanOption.Type = NXOpen.GeometricUtilities.BooleanOperation.BooleanType.Create
        builder.SetTwoPointsAndHeight(origin_point, corner_point, str(height))
        csys.SetDirections(axis_x(original), axis_y(original))
        return cast(NXOpen.Features.Block, builder.Commit())
    finally:
        builder.Destroy()


# ---------------------------------------------------------------------------------------------------
# Vectors / matrices (Point3d.__Add, Matrix3x3.__AxisX, Vector3d.__Equals, ...)
# ---------------------------------------------------------------------------------------------------

def axis_x(matrix: NXOpen.Matrix3x3) -> NXOpen.Vector3d:
    """Matrix3x3.__AxisX"""
    return NXOpen.Vector3d(matrix.Xx, matrix.Xy, matrix.Xz)


def axis_y(matrix: NXOpen.Matrix3x3) -> NXOpen.Vector3d:
    """Matrix3x3.__AxisY"""
    return NXOpen.Vector3d(matrix.Yx, matrix.Yy, matrix.Yz)


def axis_z(matrix: NXOpen.Matrix3x3) -> NXOpen.Vector3d:
    """Matrix3x3.__AxisZ"""
    return NXOpen.Vector3d(matrix.Zx, matrix.Zy, matrix.Zz)


def negate(vector: NXOpen.Vector3d) -> NXOpen.Vector3d:
    """Vector3d.__Negate"""
    return NXOpen.Vector3d(-vector.X, -vector.Y, -vector.Z)


def unit(vector: NXOpen.Vector3d) -> NXOpen.Vector3d:
    """Vector3d.__Unit"""
    length = math.sqrt(vector.X * vector.X + vector.Y * vector.Y + vector.Z * vector.Z)
    return NXOpen.Vector3d(vector.X / length, vector.Y / length, vector.Z / length)


def vectors_equal(vector0: NXOpen.Vector3d, vector1: NXOpen.Vector3d, tolerance: float = .001) -> bool:
    """Vector3d.__Equals - compares the unit vectors component by component."""
    a = unit(vector0)
    b = unit(vector1)
    return abs(a.X - b.X) <= tolerance and abs(a.Y - b.Y) <= tolerance and abs(a.Z - b.Z) <= tolerance


def add_along(point: NXOpen.Point3d, vector: NXOpen.Vector3d, length: float) -> NXOpen.Point3d:
    """Point3d.__Add(Vector3d, double)"""
    return NXOpen.Point3d(point.X + vector.X * length, point.Y + vector.Y * length, point.Z + vector.Z * length)


def distance(point0: NXOpen.Point3d, point1: NXOpen.Point3d) -> float:
    """Point3d.__Distance"""
    return math.sqrt((point1.X - point0.X) ** 2 + (point1.Y - point0.Y) ** 2 + (point1.Z - point0.Z) ** 2)


def matrix_from_axes(x_axis: NXOpen.Vector3d, y_axis: NXOpen.Vector3d) -> NXOpen.Matrix3x3:
    """Vector3d.__ToMatrix3x3(Vector3d) - rows X, Y and Z = X x Y."""
    matrix = NXOpen.Matrix3x3()
    matrix.Xx, matrix.Xy, matrix.Xz = x_axis.X, x_axis.Y, x_axis.Z
    matrix.Yx, matrix.Yy, matrix.Yz = y_axis.X, y_axis.Y, y_axis.Z
    matrix.Zx = x_axis.Y * y_axis.Z - x_axis.Z * y_axis.Y
    matrix.Zy = x_axis.Z * y_axis.X - x_axis.X * y_axis.Z
    matrix.Zz = x_axis.X * y_axis.Y - x_axis.Y * y_axis.X
    return matrix


def identity_matrix() -> NXOpen.Matrix3x3:
    """_Matrix3x3Identity"""
    return matrix_from_axes(NXOpen.Vector3d(1.0, 0.0, 0.0), NXOpen.Vector3d(0.0, 1.0, 0.0))


def distance_tolerance() -> float:
    """Extensions.DistanceTolerance - the work part's modeling distance tolerance."""
    return work_part().Preferences.Modeling.DistanceToleranceData


# ---------------------------------------------------------------------------------------------------
# Display / attributes / faces
# ---------------------------------------------------------------------------------------------------

def show_error(message: str) -> None:
    """Merlin.ShowError - the standard NX "Error" message box."""
    message_box("Error", NXOpen.NXMessageBox.DialogType.Error, message)


# NXMessageBox.Show returns 1 for Yes and 2 for No on a Question box.
MessageBoxYes = 1
MessageBoxNo = 2


def message_box(title: str, dialog_type: Any, message: str) -> int:
    """
    UFuncUsage.MessageBox - shows an NXMessageBox and writes its tblDialogs row. Use it for every message box, in
    place of UI.NXMessageBox.Show. Returns what Show returns (MessageBoxYes on a Question box's Yes).
    """
    response = NXOpen.UI.GetUI().NXMessageBox.Show(title, dialog_type, message)
    type_name = next((name for name in ("Error", "Warning", "Information", "Question")
                      if getattr(NXOpen.NXMessageBox.DialogType, name, None) == dialog_type), str(dialog_type))
    if type_name == "Question":
        answer = "yes" if response == MessageBoxYes else "no" if response == MessageBoxNo else str(response)
    else:
        answer = str(response)
    log_dialog("message-box", title, type_name, message, answer)
    return response


def confirm_execute(ufunc_name: str) -> bool:
    """
    UFuncUsage.ConfirmExecute - the "Are you sure you want to execute" Question box a UFunc with no dialog of its
    own shows before it does anything. True on Yes.
    """
    if message_box(ufunc_rev_name(ufunc_name), NXOpen.NXMessageBox.DialogType.Question,
                   "Are you sure you want to execute {}?".format(ufunc_name)) == MessageBoxYes:
        return True
    mark_cancelled("the confirm")
    return False


def mark_cancelled(where: str) -> None:
    """usage_db.mark_cancelled - the run's END syslog banner says CANCELLED at where. Never raises."""
    try:
        import usage_db
        usage_db.mark_cancelled(where)
    except Exception:
        pass


def log_dialog(kind: str, title: Optional[str], dialog_type: Optional[str], message: Optional[str],
               response: Optional[str]) -> None:
    """usage_db.log_dialog. usage_db never raises, but a missing pyodbc must not either."""
    try:
        import usage_db
        usage_db.log_dialog(kind, title, dialog_type, message, response)
    except Exception:
        pass


def set_color(obj: NXOpen.DisplayableObject, color: int) -> None:
    """DisplayableObject.__Color(int)"""
    obj.Color = color
    obj.RedisplayObject()


def set_attribute(obj: NXOpen.NXObject, title: str, value: str) -> None:
    """NXObject.__SetAttribute(string, string)"""
    obj.SetUserAttribute(title, -1, value, NXOpen.Update.Option.Now)


# UF_MODL_ask_face_data's type for a planar face.
UF_MODL_PLANAR_FACE = 22


def face_normal(face: NXOpen.Face) -> NXOpen.Vector3d:
    """Face.__Normal - the unit surface normal of a planar face (the face sense is not applied)."""
    face_type, _point, direction, _box, _radius, _rad_data, _norm_dir = ufsession_.Modeling.AskFaceData(face.Tag)
    if face_type != UF_MODL_PLANAR_FACE:
        raise RuntimeError("Cannot ask for the normal of a non planar face")
    return unit(NXOpen.Vector3d(direction[0], direction[1], direction[2]))


def planar_face_with_normal_or_null(body: NXOpen.Body, normal: NXOpen.Vector3d) -> Optional[NXOpen.Face]:
    """Body.__PlanarFaceWithNormalOrNull"""
    for face in body.GetFaces():
        if face.SolidFaceType == NXOpen.Face.FaceType.Planar and vectors_equal(face_normal(face), normal):
            return face
    return None


# ---------------------------------------------------------------------------------------------------
# Reference sets / occurrences / part setup
# ---------------------------------------------------------------------------------------------------

def find_reference_set_or_null(part: NXOpen.BasePart, name: str) -> Optional[NXOpen.ReferenceSet]:
    """BasePart.__FindReferenceSetOrNull"""
    for refset in part.GetAllReferenceSets():
        if refset.Name == name:
            return refset
    return None


def has_reference_set(part: NXOpen.BasePart, name: str) -> bool:
    """BasePart.__HasReferenceSet"""
    return find_reference_set_or_null(part, name) is not None


# True inside quiet_listing() - Auto Design's builders leave out their elapsed times and "Created reference set"
# lines, so the listing window carries only what needs reading.
quiet = False


@contextlib.contextmanager
def quiet_listing(on: bool = True) -> Iterator[None]:
    """Sets quiet for the block when on (never clears an outer one); restores it on exit."""
    global quiet
    previous = quiet
    quiet = previous or bool(on)
    try:
        yield
    finally:
        quiet = previous


def info(message: object) -> None:
    """
    A progress line, not an error: the syslog always, the listing window only outside quiet_listing() (so Auto
    Design's listing window shows just its errors). Errors and warnings stay on print_.
    """
    syslog(message)
    if not quiet:
        print_(message)


def reference_set_box(component: NXOpen.Assemblies.Component, refset: str, label: str) -> Optional[Box3d]:
    """
    The combined absolute box of component's solid bodies under refset, measured by switching component to it and
    putting it back on the reference set it had. None when the part has no such reference set or it shows no solid
    body (printed, prefixed with label). Switching kills the component's body occurrences - capture anything read
    off them first.
    """
    if not has_reference_set(component.Prototype, refset):
        return None

    original_refset = component.ReferenceSet
    try:
        set_reference_set(component, refset)
        bodies = solid_body_members(component)
        if not bodies:
            print_("{}: {} {} has no solid body - using the picked body.".format(label, component.DisplayName, refset))
            return None
        return combine_boxes([body_box(b) for b in bodies])
    finally:
        if original_refset != refset:
            set_reference_set(component, original_refset)


def confirm_missing_reference_sets(label: str, purpose: str, components: Iterable[NXOpen.Assemblies.Component],
                                   refsets: Sequence[str]) -> bool:
    """
    Checks every component for refsets. When any are missing, one Question box (title label) lists each component,
    its current reference set and what it lacks, after purpose ("The window height is taken from ...").
    True to proceed with the current reference set for those (printed per component), False when the user declines.
    """
    missing = []
    for component in components:
        absent = [name for name in refsets if not has_reference_set(component.Prototype, name)]
        if absent:
            missing.append("{} (current: {}) has no {}".format(component.DisplayName, component.ReferenceSet,
                                                               " or ".join(absent)))
    if not missing:
        return True

    message = "{}, but:\r\n{}\r\n\r\nProceed using the current reference set for those?".format(
        purpose, "\r\n".join(missing))
    # 1 is Yes on a Question box.
    if message_box(label, NXOpen.NXMessageBox.DialogType.Question, message) != MessageBoxYes:
        print_("{} cancelled: {}".format(label, "; ".join(missing)))
        return False

    for line in missing:
        info("{}: {} - using the current reference set.".format(label, line))
    return True


def find_or_create_reference_set(part: NXOpen.BasePart, name: str) -> NXOpen.ReferenceSet:
    """Merlin.FindOrCreateReferenceSet - the part's reference set, created and named when absent."""
    existing = find_reference_set_or_null(part, name)
    if existing is not None:
        return existing
    created = part.CreateReferenceSet()
    created.SetName(name)
    info('Created reference set "{}" in {}'.format(name, part.Leaf))
    return created


def occurrences_of_part_in(assembly: NXOpen.BasePart, proto: NXOpen.BasePart) -> List[NXOpen.Assemblies.Component]:
    """Merlin.OccurrencesOfPartIn - every occurrence of proto anywhere inside assembly."""
    # The Python binding returns (partOccs, count), unlike the C# out-parameter form.
    occurrence_tags, _count = ufsession_.Assem.AskOccsOfPart(assembly.Tag, proto.Tag)
    return [cast(NXOpen.Assemblies.Component, tagged_object(tag)) for tag in occurrence_tags]


def first_occurrence_in(proto: NXOpen.BasePart, assembly: NXOpen.BasePart) -> NXOpen.Assemblies.Component:
    """Part.__FirstOccurrenceIn"""
    return occurrences_of_part_in(assembly, proto)[0]


def first_block_feature(part: NXOpen.BasePart) -> Optional[NXOpen.Features.Block]:
    """part.Features.OfType<Block>().FirstOrDefault()"""
    for feature in part.Features.GetFeatures():
        if isinstance(feature, NXOpen.Features.Block):
            return feature
    return None


def dynamic_block(part: NXOpen.BasePart) -> NXOpen.Features.Block:
    """BasePart.__DynamicBlock"""
    for feature in part.Features.GetFeatures():
        if isinstance(feature, NXOpen.Features.Block) and feature.Name == "DYNAMIC BLOCK":
            return feature
    raise RuntimeError("Could not find ")


def setup_station_expressions(part: NXOpen.BasePart) -> None:
    """Part.__SetupStationExpressions"""
    unit_type = part.UnitCollection.FindObject("Inch" if part.PartUnits == NXOpen.BasePart.Units.Inches
                                               else "MilliMeter")
    part.Expressions.CreateWithUnits("AddX=.000", unit_type)
    part.Expressions.CreateWithUnits("AddY=.000", unit_type)
    part.Expressions.CreateWithUnits("AddZ=.000", unit_type)
    part.Expressions.CreateExpression("String", 'Burnout="no"')
    part.Expressions.CreateExpression("String", 'Grind="no"')
    part.Expressions.CreateExpression("String", 'GrindTolerance="none"')
    part.Expressions.CreateExpression("String", 'BurnDir="none"')


# NXException.ErrorCode when a user-defined class is not registered in the session.
ErrorUdoClassNotRegistered = 1535022


def create_auto_size_udo(part: NXOpen.BasePart) -> None:
    """BasePart.__CreateAutoSizeUdo - tags the part's single layer-1 body for AutoSize.

    The UdoAutoSizeComponent class (and its update callback) can only be registered from C#
    (AutoSizeComponent.initializeUDO). A caller in TSG_Library makes sure it is registered before handing over;
    run without that, the UDO is skipped with a print.
    """
    try:
        udo_class = session_.UserDefinedClassManager.GetUserDefinedClassFromClassName("UdoAutoSizeComponent")
    except NXOpen.NXException as ex:
        if ex.ErrorCode != ErrorUdoClassNotRegistered:
            raise
        print_("UdoAutoSizeComponent is not registered in this session - {} has no AutoSize UDO.".format(part.Leaf))
        return

    if udo_class is None or len(part.UserDefinedObjectManager.GetUdosOfClass(udo_class)) != 0:
        return

    udo = part.UserDefinedObjectManager.CreateUserDefinedObject(udo_class)
    layer1 = [body for body in part.Bodies if body.Layer == 1]
    if len(layer1) != 1:
        return

    link = NXOpen.UserDefinedObjects.UserDefinedObject.LinkDefinition()
    link.AssociatedObject = layer1[0]
    link.Status = NXOpen.UserDefinedObjects.UserDefinedObject.LinkStatus.UpToDate
    udo.SetLinks(NXOpen.UserDefinedObjects.UserDefinedObject.LinkType.Type1, [link])
    udo.SetIntegers([1])


# ---------------------------------------------------------------------------------------------------
# Added for PunchButtonRetainer: formatting, selection, parts/components, update wrappers, edges/curves
# ---------------------------------------------------------------------------------------------------

def cs_double_str(value: float) -> str:
    """double.ToString() as C# string interpolation prints it ("G", 15 significant digits on .NET Framework):
    10.0 -> "10", 12.7 -> "12.7". Python's str() would give "10.0"."""
    text = format(value, ".15G")
    return "0" if text == "-0" else text


def doubles_equal(num0: float, num1: float, tolerance: float = .001) -> bool:
    """double.__Equals(double, tolerance = .001)"""
    return abs(num0 - num1) <= tolerance


def select_many_solid_bodies(message: str = "Select Many Solid Bodies") -> List[NXOpen.Body]:
    """Selection.SelectManySolidBodies - returns [] on cancel.

    The C# version rejects non-bodies with a UF filter proc inside the dialog; here the mask does the
    filtering and anything that is not a solid Body is dropped afterwards.
    """
    mask = NXOpen.Selection.MaskTriple(NXOpen.UF.UFConstants.UF_solid_type, 0,
                                       NXOpen.UF.UFConstants.UF_UI_SEL_FEATURE_BODY)
    response, objects = NXOpen.UI.GetUI().SelectionManager.SelectTaggedObjects(
        message,
        message,
        NXOpen.Selection.SelectionScope.AnyInAssembly,
        NXOpen.Selection.SelectionAction.ClearAndEnableSpecific,
        False,
        False,
        [mask])
    if response not in (NXOpen.Selection.Response.Ok, NXOpen.Selection.Response.ObjectSelected):
        return []
    bodies = [obj for obj in objects if isinstance(obj, NXOpen.Body) and obj.IsSolidBody]
    for body in bodies:
        body.Unhighlight()
    return bodies


def find_or_open(path_or_leaf: str) -> NXOpen.Part:
    """Session.__FindOrOpen - the loaded part, or opens it.

    C# rethrows NXException.Create with a friendlier message; Python cannot construct an NXException, so the
    same message is raised as a RuntimeError chained to the original.
    """
    try:
        if ufsession_.Part.IsLoaded(path_or_leaf) == 0:
            opened, load_status = session_.Parts.Open(path_or_leaf)
            load_status.Dispose()
            return cast(NXOpen.Part, opened)
        return cast(NXOpen.Part, session_.Parts.FindObject(path_or_leaf))
    except NXOpen.NXException as ex:
        if ex.ErrorCode == 1020038:
            raise RuntimeError("Invalid file format: '{}'".format(path_or_leaf)) from ex
        if ex.ErrorCode == 1020001:
            raise RuntimeError("File not found: '{}'".format(path_or_leaf)) from ex
        raise


def part_dir(part: NXOpen.BasePart) -> str:
    """BasePart.__Dir - NB the C# ignores its argument and returns the DISPLAY part's folder; kept."""
    return os.path.dirname(display_part().FullPath)


def add_component(part: NXOpen.BasePart, path_or_prototype: Union[str, NXOpen.BasePart],
                  reference_set: str = "Entire Part", component_name: Optional[str] = None,
                  origin: Optional[NXOpen.Point3d] = None, orientation: Optional[NXOpen.Matrix3x3] = None,
                  layer: int = 1) -> NXOpen.Assemblies.Component:
    """BasePart.__AddComponent(string path | BasePart prototype, ...) - origin defaults to (0,0,0), orientation to
    identity. A path goes through find_or_open."""
    proto = find_or_open(path_or_prototype) if isinstance(path_or_prototype, str) else path_or_prototype
    component, load_status = part.ComponentAssembly.AddComponent(
        proto,
        reference_set,
        component_name,
        origin if origin is not None else NXOpen.Point3d(0.0, 0.0, 0.0),
        orientation if orientation is not None else identity_matrix(),
        layer)
    if load_status is not None:
        load_status.Dispose()
    return component


def component_origin(component: NXOpen.Assemblies.Component) -> NXOpen.Point3d:
    """Component.__Origin"""
    origin, _orientation = component.GetPosition()
    return origin


def component_orientation(component: NXOpen.Assemblies.Component) -> NXOpen.Matrix3x3:
    """Component.__Orientation"""
    _origin, orientation = component.GetPosition()
    return orientation


@contextlib.contextmanager
def do_update(undo_text: str = "Do Update") -> Iterator[None]:
    """DoUpdate / Session.__UsingDoUpdate([undo_text]) - sets a visible undo mark, then on exit DoUpdate()s to it
    and deletes the mark."""
    mark = session_.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, undo_text)
    try:
        yield
    finally:
        session_.UpdateManager.DoUpdate(mark)
        session_.DeleteUndoMark(mark, "")


@contextlib.contextmanager
def lock_updates() -> Iterator[None]:
    """LockUpdates / Session.__UsingLockUgUpdates - update lock on; on exit off + UF_MODL_update."""
    session_.UpdateManager.SetUpdateLock(True)
    try:
        yield
    finally:
        session_.UpdateManager.SetUpdateLock(False)
        ufsession_.Modeling.Update()


def add_z(point: NXOpen.Point3d, z: float) -> NXOpen.Point3d:
    """Point3d.__AddZ"""
    return NXOpen.Point3d(point.X, point.Y, point.Z + z)


def mid_point(p: NXOpen.Point3d, q: NXOpen.Point3d) -> NXOpen.Point3d:
    """Point3d.__MidPoint(Point3d)"""
    return NXOpen.Point3d((p.X + q.X) / 2, (p.Y + q.Y) / 2, (p.Z + q.Z) / 2)


def faces_with_vector(body: NXOpen.Body, vector: NXOpen.Vector3d) -> List[NXOpen.Face]:
    """Body.__FacesWithVector - planar faces whose normal equals vector."""
    return [face for face in body.GetFaces()
            if face.SolidFaceType == NXOpen.Face.FaceType.Planar and vectors_equal(face_normal(face), vector)]


def _single(items: List[Any], what: str) -> Any:
    """Enumerable.Single - exactly one item, else an error (InvalidOperationException in C#)."""
    if len(items) != 1:
        raise RuntimeError("Sequence contains {} {}".format(
            "no" if not items else "more than one", what if not items else "matching element"))
    return items[0]


def single_pos_z_face(body: NXOpen.Body) -> NXOpen.Face:
    """Body.__SinglePosZFace"""
    return cast(NXOpen.Face, _single(faces_with_vector(body, NXOpen.Vector3d(0.0, 0.0, 1.0)), "elements"))


def single_neg_z_face(body: NXOpen.Body) -> NXOpen.Face:
    """Body.__SingleNegZFace"""
    return cast(NXOpen.Face, _single(faces_with_vector(body, NXOpen.Vector3d(0.0, 0.0, -1.0)), "elements"))


def edge_start_point(edge: NXOpen.Edge) -> NXOpen.Point3d:
    """Edge.__StartPoint - the edge's first vertex."""
    vertex1, _vertex2 = edge.GetVertices()
    return vertex1


def edge_to_curve(edge: NXOpen.Edge) -> NXOpen.Curve:
    """Edge.__ToCurve - UF_MODL_create_curve_from_edge; the new curve lands in the work part."""
    return cast(NXOpen.Curve, tagged_object(ufsession_.ModlGeneral.CreateCurveFromEdge(edge.Tag)))


def curve_mid_point(curve: NXOpen.Curve) -> NXOpen.Point3d:
    """Curve.__MidPoint - the point at the middle of the parameter range (__MinU/__MaxU/__Position, Factor 1).

    The Python UFEval has no Evaluate and no Free (checked against NXOpen_UF.pyd): EvaluateUnitVectors gives the
    position at the same unnormalized parameter, and the binding releases the evaluator itself."""
    evaluator = ufsession_.Eval.Initialize2(curve.Tag)
    limits = ufsession_.Eval.AskLimits(evaluator)
    middle = limits[1] - (limits[1] - limits[0]) / 2
    point = ufsession_.Eval.EvaluateUnitVectors(evaluator, middle)[0]
    return NXOpen.Point3d(point[0], point[1], point[2])


# ---------------------------------------------------------------------------------------------------
# UFunc naming / cue line / extra Disposable wrappers (ref-set UFunc ports)
# ---------------------------------------------------------------------------------------------------

@contextlib.contextmanager
def regenerate_display() -> Iterator[None]:
    """RegenerateDisplay (session_.__UsingRegenerateDisplay) - regenerates the display on exit."""
    try:
        yield
    finally:
        ufsession_.Disp.RegenerateDisplay()


def set_layer(obj: NXOpen.DisplayableObject, layer: int, redisplay_obj: bool = True) -> None:
    """DisplayableObject.__Layer(int, bool)"""
    obj.Layer = layer
    if redisplay_obj:
        obj.RedisplayObject()


def try_get_refset(part: NXOpen.BasePart, name: str) -> Optional[NXOpen.ReferenceSet]:
    """BasePart.__TryGetRefset - SingleOrDefault by name: None when absent, raises when there are two."""
    matches = [refset for refset in part.GetAllReferenceSets() if refset.Name == name]
    if len(matches) > 1:
        raise RuntimeError('Sequence contains more than one matching element (reference set "{}").'.format(name))
    return matches[0] if matches else None


def reference_set_single(part: NXOpen.BasePart, name: str) -> NXOpen.ReferenceSet:
    """Part.__ReferenceSets(string) - Single by name: raises when absent or duplicated."""
    matches = [refset for refset in part.GetAllReferenceSets() if refset.Name == name]
    if len(matches) != 1:
        raise RuntimeError('Expected exactly one reference set "{}" in {}, found {}.'.format(
            name, part.Leaf, len(matches)))
    return matches[0]


def replace_ref_sets(part: NXOpen.BasePart, components: Iterable[NXOpen.Assemblies.Component],
                     refset_name: str) -> None:
    """BasePart.__ReplaceRefSets"""
    part.ComponentAssembly.ReplaceReferenceSetInOwners(refset_name, list(components))


def select_components(cue: str = "Components",
                      title: str = "Please select components...") -> Optional[List[NXOpen.Assemblies.Component]]:
    """Selection.select_components - multi-select components (any in assembly). None on cancel or empty.

    The C# version is a SNAP SelectObject dialog; this uses SelectionManager with a component mask.
    """
    mask = NXOpen.Selection.MaskTriple(NXOpen.UF.UFConstants.UF_component_type, 0, 0)
    response, objects = NXOpen.UI.GetUI().SelectionManager.SelectTaggedObjects(
        cue,
        title,
        NXOpen.Selection.SelectionScope.AnyInAssembly,
        NXOpen.Selection.SelectionAction.ClearAndEnableSpecific,
        False,
        False,
        [mask])
    if response not in (NXOpen.Selection.Response.Ok, NXOpen.Selection.Response.ObjectSelected):
        return None
    components = [obj for obj in objects if isinstance(obj, NXOpen.Assemblies.Component)]
    return components if components else None


def cycle_objs_in_part(part_tag: NXOpen.Tag, object_type: int) -> List[NXOpen.Tag]:
    """The UF_OBJ_cycle_objs_in_part do/while loop (ufsession_.Obj.CycleObjsInPart until Tag.Null)."""
    result: List[NXOpen.Tag] = []
    tag = 0
    while True:
        tag = ufsession_.Obj.CycleObjsInPart(part_tag, object_type, tag)
        if tag == 0:
            break
        result.append(tag)
    return result


def ask_ref_set_members(refset_tag: NXOpen.Tag) -> List[NXOpen.Tag]:
    """ufsession_.Assem.AskRefSetMembers - the member tags (C#: out count, out members).

    The order of the out values in the Python tuple is not confirmed against the pyd, so the list is picked
    out by type rather than by position.
    """
    result = ufsession_.Assem.AskRefSetMembers(refset_tag)
    if isinstance(result, (tuple, list)):
        for value in result:
            if isinstance(value, (tuple, list)):
                return list(value)
        return []
    return []


def wcs_origin_and_matrix_values() -> tuple[List[float], List[float]]:
    """The AskWcs / AskCsysInfo / AskMatrixValues triplet the UF ref-set code feeds to Assem.CreateRefSet.

    C# AskCsysInfo fills a caller-supplied origin array; the Python binding returns it with the matrix tag.
    Like ask_ref_set_members, the two are told apart by type.
    """
    wcs = ufsession_.Csys.AskWcs()
    info = ufsession_.Csys.AskCsysInfo(wcs)
    matrix_tag: NXOpen.Tag = 0
    origin: List[float] = [0.0, 0.0, 0.0]
    for value in info:
        if isinstance(value, (tuple, list)):
            origin = [float(v) for v in value]
        else:
            matrix_tag = value
    matrix_values = [float(v) for v in ufsession_.Csys.AskMatrixValues(matrix_tag)]
    return origin, matrix_values


# ---------------------------------------------------------------------------------------------------
# Delete / update, attributes, expressions, prompt, version (CleanBrokenLinks, DeleteComponent, ...)
# ---------------------------------------------------------------------------------------------------

from typing import Any as _Any, Callable as _Callable, Dict as _Dict, Sequence as _Sequence, TypeVar as _TypeVar  # noqa: E402

_T = _TypeVar("_T")
_K = _TypeVar("_K")


def delete_objects(objects: _Sequence[NXOpen.TaggedObject]) -> None:
    """Session.__DeleteObjects - adds the objects to the delete list inside a DoUpdate."""
    with do_update():
        session_.UpdateManager.AddObjectsToDeleteList(list(objects))


def is_linked_body(extract_face: NXOpen.Features.Feature) -> bool:
    """ExtractFace.__IsLinkedBody"""
    return extract_face.FeatureType == "LINKED_BODY"


def xform_tag(extract_face: NXOpen.Features.Feature) -> NXOpen.Tag:
    """ExtractFace.__XFormTag"""
    return ufsession_.Wave.AskLinkXform(extract_face.Tag)


def children(part: NXOpen.BasePart) -> List[NXOpen.Assemblies.Component]:
    """BasePart.__Children - the root component's children, [] when the part has no root component."""
    root = part.ComponentAssembly.RootComponent
    return list(root.GetChildren()) if root is not None else []


def distinct_by(source: Iterable[_T], key: _Callable[[_T], _K]) -> List[_T]:
    """IEnumerable.__DistinctBy - keeps the first item for each key, in order."""
    seen: _Dict[_K, bool] = {}
    result: List[_T] = []
    for item in source:
        k = key(item)
        if k in seen:
            continue
        seen[k] = True
        result.append(item)
    return result


def get_attribute(obj: NXOpen.NXObject, title: str) -> str:
    """NXObject.__GetAttribute - string user attribute (throws when absent, like the C#)."""
    return obj.GetUserAttributeAsString(title, NXOpen.NXObject.AttributeType.String, -1)


def has_attribute(obj: NXOpen.NXObject, title: str) -> bool:
    """NXObject.__HasAttribute - string user attribute."""
    return obj.HasUserAttribute(title, NXOpen.NXObject.AttributeType.String, -1)


def find_expression_or_null(part: NXOpen.BasePart, name: str) -> Optional[NXOpen.Expression]:
    """BasePart.__FindExpressionOrNull - case-insensitive; raises when more than one matches (SingleOrDefault)."""
    matches = [e for e in part.Expressions if e.Name.lower() == name.lower()]
    if len(matches) > 1:
        raise ValueError("Sequence contains more than one matching element")
    return matches[0] if matches else None


def reference_sets(part: NXOpen.BasePart, name: str) -> NXOpen.ReferenceSet:
    """Part.__ReferenceSets(string) - the one reference set with that exact name; raises otherwise (Single)."""
    matches = [r for r in part.GetAllReferenceSets() if r.Name == name]
    if len(matches) != 1:
        raise ValueError("Sequence contains no matching element" if not matches
                         else "Sequence contains more than one matching element")
    return matches[0]


def prompt(message: str) -> None:
    """Extensions.prompt - writes the cue line, and the same line to Auto Design's progress window (progress)."""
    ufsession_.Ui.SetPrompt(message)
    progress(message)


_assembly_file_version: Optional[str] = None


def assembly_file_version() -> str:
    """
    Extensions.AssemblyFileVersion - the FileVersion string of the TSG_Library.dll this python folder is
    deployed beside (python\\ sits next to the DLL), or "" when it cannot be read.
    """
    global _assembly_file_version
    if _assembly_file_version is not None:
        return _assembly_file_version
    _assembly_file_version = ""
    try:
        import ctypes
        import os
        dll = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "TSG_Library.dll")
        version_dll: _Any = getattr(ctypes, "windll").version
        size = version_dll.GetFileVersionInfoSizeW(dll, None)
        if not size:
            return _assembly_file_version
        data = ctypes.create_string_buffer(size)
        if not version_dll.GetFileVersionInfoW(dll, 0, size, data):
            return _assembly_file_version
        pointer = ctypes.c_void_p()
        length = ctypes.c_uint()
        if not version_dll.VerQueryValueW(data, "\\VarFileInfo\\Translation",
                                          ctypes.byref(pointer), ctypes.byref(length)) or length.value < 4:
            return _assembly_file_version
        words = ctypes.cast(pointer, ctypes.POINTER(ctypes.c_ushort))
        key = "\\StringFileInfo\\{:04x}{:04x}\\FileVersion".format(words[0], words[1])
        if version_dll.VerQueryValueW(data, key, ctypes.byref(pointer), ctypes.byref(length)) and length.value \
                and pointer.value is not None:
            _assembly_file_version = ctypes.wstring_at(pointer.value, length.value).rstrip("\0")
    except Exception:
        _assembly_file_version = ""
    return _assembly_file_version


def ufunc_rev_name(ufunc_name: str) -> str:
    """_UFunc.ufunc_rev_name - "{AssemblyFileVersion} - {ufunc_name}"."""
    return "{} - {}".format(assembly_file_version(), ufunc_name)


# UF_UI response codes (uf_ui.h).
UF_UI_BACK = 1
UF_UI_CANCEL = 2
UF_UI_OK = 3


def select_file_or_none(prompt_string: str, title: str, filter_string: str, default_name: str = "") -> Optional[str]:
    """
    Nearest equivalent of a WinForms OpenFileDialog: UF_UI_create_filebox. filter_string is a path pattern
    such as U:\\nxFiles\\UfuncFiles\\*.cdf (the folder sets the initial directory). Returns None unless OK.
    The C# out/ref parameters come back as a tuple; the filename is its last string and the response its int.
    """
    result: _Any = ufsession_.Ui.CreateFilebox(prompt_string, title, filter_string, default_name)
    values = list(result) if isinstance(result, (tuple, list)) else [result]
    responses = [v for v in values if isinstance(v, int) and not isinstance(v, bool)]
    names = [v for v in values if isinstance(v, str)]
    if not responses or responses[-1] != UF_UI_OK or not names or not names[-1]:
        return None
    return str(names[-1])

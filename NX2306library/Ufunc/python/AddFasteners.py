"""
Python ports of the AddFasteners form's buttons (src\\UFuncs\\AddFasteners.cs; the C# bodies they replace are
commented out in src\\Static\\AddFasteners.cs). The form is the UFunc holder: each button that does one
self-contained job calls a method here through
    PythonLibrary.Execute("AddFasteners.py", "AddFasteners", "<method>", args...)
and keeps only its own control enabling / disabling in C#.

Button -> method:
    Select Component     select_target()             returns 1 picked, 0 cancelled
    Block Origin         block_origin()
    View WCS             orient_work_view_to_wcs()
    Grid spacing combo   apply_grid_spacing(spacing)
    Wire Taps            insert_wire_taps(fastener_dir)
    Plan View            make_plan_view()            (the Yes/No stays in C#)
    OK                   finish()                    wave_in + plan view + child reference sets
    Strip Wave Out       strip_wave_out()
    Close All Fasteners  close_all_fasteners()

Still C#: the placement loops behind the fastener list (the mouse drag needs a native motion callback, which Python
cannot hand NX), substitute and cycle-add (driven by the list and checkboxes), the fastener listings (they fill the
form's list box), Reset and the settings toggles.

Every method works on the session's display part / work part / work component, as the C# does.
"""

from __future__ import annotations

import os
import sys
from typing import Optional, Sequence, cast

# Session.Execute does not put the script's folder on sys.path, so the shared module would not import.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

import NXOpen  # noqa: E402
import NXOpen.Assemblies  # noqa: E402
import NXOpen.Features  # noqa: E402
import NXOpen.Layer  # noqa: E402
import NXOpen.Preferences  # noqa: E402
import NXOpen.UF  # noqa: E402

import tsg_nx as nx  # noqa: E402

# The layers WaveIn treats as fastener layers (Globals.cs LayerDwlTooling = 97, LayerShcsHandlingWireTap = 98,
# LayerFastener = 99).
_FastenerLayers = (97, 98, 99)

# Layer the linked bodies are parked on.
_LinkedBodyLayer = 96


class AddFasteners(object):

    @staticmethod
    def strip_wave_out() -> None:
        """
        Static.AddFastenersStripWaveOut (was the body of AddFasteners.StripWaveOut_Click). Deletes every live LINKED_BODY in the work
        part whose wave-link transform sits exactly on the origin of the component it links from - the links
        WaveIn made.
        """
        try:
            part = nx.work_part()

            for feat in part.Features.GetFeatures():
                try:
                    if not isinstance(feat, NXOpen.Features.ExtractFace):
                        continue

                    if not nx.is_linked_body(feat):
                        continue

                    if nx.is_link_broken(feat):
                        continue

                    xform = nx.xform_tag(feat)

                    # The C# dereferences __RootComponent() here, so a part with no components fails once per
                    # link, inside this try.
                    root = nx.root_component(part)
                    if root is None:
                        raise RuntimeError("{} has no root component.".format(part.Leaf))

                    from_part_occ = nx.ufsession_.So.AskAssyCtxtPartOcc(xform, root.Tag)

                    if from_part_occ == 0:
                        continue

                    point = nx.ufsession_.So.AskPointOfXform(xform)
                    from_comp = cast(NXOpen.Assemblies.Component, nx.tagged_object(from_part_occ))

                    if not _is_equal_to(nx.component_origin(from_comp), point):
                        continue

                    # Session.__DeleteObjects, inline: tsg_nx defines delete_objects twice with different
                    # signatures, and which one wins depends on definition order.
                    with nx.do_update():
                        nx.session_.UpdateManager.AddObjectsToDeleteList([feat])
                except Exception as ex:
                    nx.print_exception(ex)
        except Exception as ex:
            nx.print_exception(ex)

    @staticmethod
    def wave_in() -> None:
        """
        Static.AddFastenersWaveIn() - links and subtracts every fastener child of the work part from its layer-1
        solid: the dynamic block's body when the part has one, otherwise the single solid body on layer 1.
        """
        try:
            part = nx.work_part()
            block = _dynamic_block_or_none(part)
            solid_body_layer_1 = block.GetBodies()[0] if block is not None else _single_solid_body_on_layer_1(part)

            for child in nx.children(part):
                try:
                    wave_in_child(child, solid_body_layer_1)
                except Exception as ex:
                    nx.print_exception(ex)
        except Exception as ex:
            nx.print_exception(ex)


    @staticmethod
    def select_target() -> int:
        """
        Static.AddFastenersSelectTarget - pick the target body, make it 75% translucent and put the WCS on its
        dynamic block; a pick in a component makes that component the work component. Returns 1 when something
        was picked, 0 on cancel / back (the C# threw NothingSelectedException for that).
        """
        mask = NXOpen.Selection.MaskTriple(NXOpen.UF.UFConstants.UF_solid_type, 0,
                                           NXOpen.UF.UFConstants.UF_UI_SEL_FEATURE_BODY)
        response, obj, _cursor = NXOpen.UI.GetUI().SelectionManager.SelectTaggedObject(
            "Select A Target Body",
            "Select A Target Body",
            NXOpen.Selection.SelectionScope.AnyInAssembly,
            NXOpen.Selection.SelectionAction.ClearAndEnableSpecific,
            False,
            False,
            [mask])

        r = NXOpen.Selection.Response
        disp = nx.display_part()
        work = nx.work_part()

        if response in (r.Back, r.Cancel):
            return 0

        if response == r.ObjectSelectedByName:
            raise RuntimeError("Cannot select an object by name")

        if response == r.Ok:
            block = _dynamic_block_or_none(work)
            if block is None:
                disp.WCS.SetOriginAndMatrix(NXOpen.Point3d(0.0, 0.0, 0.0), nx.identity_matrix())
                _translucency(_single_solid_body_on_layer_1(work), 75)
                nx.print_("Part does not have a dynamic block. You will need to move the csys manually.")
                return 1

            _translucency(block.GetBodies()[0], 75)
            disp.WCS.SetOriginAndMatrix(_block_origin(block), _block_orientation(block))
            return 1

        if response != r.ObjectSelected:
            return 0

        selected = cast(NXOpen.Body, obj)

        if selected.IsOccurrence:
            component = selected.OwningComponent
            part = cast(NXOpen.Part, nx.prototype(component))
            block = _dynamic_block_or_none(part)

            if block is None:
                nx.set_work_component(component)
                component.SetTranslucency(75)
                disp.WCS.SetOriginAndMatrix(nx.component_origin(component), nx.component_orientation(component))
                nx.print_("Part does not have a dynamic block. You will need to move the csys manually.")
                return 1

            # A csys in the prototype, seen through the occurrence, gives the block's frame in display coordinates.
            csys = part.CoordinateSystems.CreateCoordinateSystem(_block_origin(block), _block_orientation(block),
                                                                 False)
            _body_reference_set(part).AddObjectsToReferenceSet([csys])
            occ_csys = cast(NXOpen.CartesianCoordinateSystem, component.FindOccurrence(csys))
            disp.WCS.SetCoordinateSystemCartesianAtCsys(occ_csys)
            nx.set_work_component(component)
            component.SetTranslucency(75)
            _delete([occ_csys, csys])
            return 1

        block = _dynamic_block_or_none(work)

        if block is not None:
            block_body = block.GetBodies()[0]
            if block_body.Tag != selected.Tag:
                raise RuntimeError("Selected body that wasn't the dynamic block")

            _translucency(block_body, 75)
            disp.WCS.SetOriginAndMatrix(_block_origin(block), _block_orientation(block))
            return 1

        bodies = [b for b in work.Bodies if b.IsSolidBody and b.Layer == 1]

        if len(bodies) == 1:
            _translucency(bodies[0], 75)
            disp.WCS.SetOriginAndMatrix(NXOpen.Point3d(0.0, 0.0, 0.0), nx.identity_matrix())
            nx.print_("Part does not have a dynamic block. You will need to move the csys manually.")

        return 1

    @staticmethod
    def block_origin() -> None:
        """Static.AddFastenersBlockOrigin - set_wcs_to_work_part, printing any failure."""
        try:
            set_wcs_to_work_part()
        except Exception as ex:
            nx.print_exception(ex)

    @staticmethod
    def orient_work_view_to_wcs() -> None:
        """Static.AddFastenersOrientWorkViewToWcs (View WCS button)."""
        disp = nx.display_part()
        disp.Views.WorkView.Orient(disp.WCS.CoordinateSystem.Orientation.Element)

    @staticmethod
    def apply_grid_spacing(grid_spacing: float) -> None:
        """
        Static.AddFastenersApplyGridSpacing - a uniform work-plane grid at grid_spacing with snap on, or grid
        and snap off for (about) zero.
        """
        disp = nx.display_part()
        if disp is None:
            return

        workplane = disp.Preferences.Workplane

        if abs(grid_spacing) < .001:
            workplane.ShowGrid = False
            workplane.SnapToGrid = False
            return

        workplane.SnapToGrid = True
        grid = NXOpen.Preferences.WorkPlane.GridSize()
        grid.MajorGridSpacing = float(grid_spacing)
        grid.MinorLinesPerMajor = 1
        grid.SnapPointsPerMinor = 1
        workplane.SetRectangularUniformGridSize(grid)

    @staticmethod
    def insert_wire_taps(fastener_dir: str) -> None:
        """
        Static.AddFastenersInsertWireTaps - two 8mm-shcs-020 on SHORT-TAP, layer 98, at WCS (1, .875) and
        (3, .875) with the WCS turned 90 deg about X, stamped subtract = WIRE_TAP. fastener_dir is the form's
        AddFasteners.fastener_dir.
        """
        nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, "WIRE_TAP")
        disp = nx.display_part()
        work = nx.work_part()

        if disp.Tag == work.Tag:
            for layer in (99, 98, 97):
                disp.Layers.SetState(layer, NXOpen.Layer.State.Selectable)

        wire_tap_screw = nx.find_or_open(
            os.path.join(fastener_dir, "Metric", "SocketHeadCapScrews", "008", "8mm-shcs-020.prt"))

        disp.WCS.Rotate(NXOpen.WCS.Axis.XAxis, 90.0)
        saved_csys = disp.WCS.Save()
        components = []
        try:
            rotate_orientation = saved_csys.Orientation.Element
            x = 1.0 if disp.PartUnits == NXOpen.BasePart.Units.Inches else 25.4

            for offset in ([1.00 * x, .875 * x, 0.0], [3.00 * x, .875 * x, 0.0]):
                absolute = nx.ufsession_.Csys.MapPoint(_UF_CSYS_ROOT_WCS_COORDS, offset, _UF_CSYS_ROOT_COORDS)
                in_work = nx.ufsession_.Csys.MapPoint(_UF_CSYS_ROOT_COORDS, list(absolute), _UF_CSYS_WORK_COORDS)
                components.append(nx.add_component(
                    work, wire_tap_screw, "SHORT-TAP", "8mm-shcs-020",
                    NXOpen.Point3d(in_work[0], in_work[1], in_work[2]), rotate_orientation, 98))
        finally:
            disp.WCS.Rotate(NXOpen.WCS.Axis.XAxis, -90.0)

        for component in components:
            component.SetInstanceUserAttribute("subtract", -1, "WIRE_TAP", NXOpen.Update.Option.Now)

        _delete([saved_csys])

    @staticmethod
    def make_plan_view() -> None:
        """Plan View button: make_plan_view on a saved copy of the display part's WCS."""
        make_plan_view(nx.display_part().WCS.Save())

    @staticmethod
    def finish() -> None:
        """
        Static.AddFastenersFinish (OK button) - wave_in and the plan view in the work part (displaying it while
        working at assembly level), then each child of the work component gets its prototype occurrence's
        reference set unless it is on the tooling (97) or handling (98) layer.
        """
        nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, "AddFasteners")
        work_component = nx.session_.Parts.WorkComponent

        if work_component is None:
            AddFasteners.wave_in()
            make_plan_view(nx.display_part().WCS.Save())
            return

        with nx.display_part_reset():
            nx.set_display_part(nx.work_part())
            AddFasteners.wave_in()
            make_plan_view(nx.display_part().WCS.Save())

        proto = nx.prototype(work_component)

        for child in work_component.GetChildren():
            if not nx.is_loaded(child):
                nx.print_("Child {} is not loaded".format(child.Name))
                continue

            proto_part_occ = _proto_part_occ(proto, child)

            if proto_part_occ.Layer in (97, 98):
                continue

            nx.set_reference_set(child, proto_part_occ.ReferenceSet)

    @staticmethod
    def close_all_fasteners() -> None:
        """
        Static.AddFastenersCloseAllFasteners - closes every loaded part under G:\\0Library\\Fasteners (whole tree,
        modified or not), unless the display part is one.
        """
        root = "G:\\0Library\\Fasteners"

        if nx.display_part().FullPath.startswith(root):
            nx.print_("You cannot run this command with a fastener as your display part.")
            return

        parts = [p for p in nx.session_.Parts if p.FullPath.startswith(root)]

        for part in parts:
            part.Close(NXOpen.BasePart.CloseWholeTree.TrueValue, NXOpen.BasePart.CloseModified.CloseModified, None)

        nx.print_("Closed {} fastener files.".format(len(parts)))


def wave_in_child(child: NXOpen.Assemblies.Component, solid_body_layer_1: NXOpen.Body) -> None:
    """
    Static.AddFastenersWaveIn(Component, Body) - one child. Skips it unless it is loaded, unsuppressed, on layer
    97/98/99, not already linked, and carries a "subtract" instance attribute. That attribute picks the
    reference set to subtract with (HANDLING/WIRE_TAP -> SHORT-TAP, BLIND_OPP -> CBORE_BLIND_OPP,
    CLR_DRILL -> CLR_HOLE, anything else as written). Afterwards HANDLING/WIRE_TAP go to layer 98 and TOOLING to
    97; anything off layer 99, or HANDLING/WIRE_TAP, ends up on the Empty reference set and out of the part's
    BODY reference set, everything else on BODY and in it.

    Quirks kept from the C#:
    - The already-linked check walks the *display* part's features, but the link is made in the *work* part.
      They are the same part whenever the form runs at the displayed part.
    - The child's reference set before the switch is read but never put back.
    """
    if not nx.is_loaded(child):
        return

    if child.IsSuppressed:
        return

    if child.Layer not in _FastenerLayers:
        return

    if _is_already_linked(child):
        return

    if not child.HasInstanceUserAttribute("subtract", NXOpen.NXObject.AttributeType.String, -1):
        return

    subtract_att = nx.get_attribute(child, "subtract")
    subtract_ref_set = _subtract_reference_set(subtract_att)

    nx.set_reference_set(child, subtract_ref_set)

    linked_body = nx.create_linked_body(child)
    linked_body.SetName("{}, {}".format(child.Name, subtract_att))
    linked_body.OwningPart.Layers.MoveDisplayableObjects(_LinkedBodyLayer, linked_body.GetBodies())
    # State.Visible means displayed but *not* pickable, so a linked body parked on 96 could not be selected
    # afterwards. Set here rather than in wave_in so every path that puts a body on 96 leaves it selectable.
    linked_body.OwningPart.Layers.SetState(_LinkedBodyLayer, NXOpen.Layer.State.Selectable)
    linked_body.SetName("{}, {}".format(child.DisplayName, subtract_att))

    try:
        nx.subtract(solid_body_layer_1, linked_body.GetBodies())
    except NXOpen.NXException as ex:
        if ex.ErrorCode != nx.ErrorNoInterference:
            raise
        nx.print_("Could not subtract {} with reference set {}".format(child.DisplayName, subtract_ref_set))

    if subtract_att in ("HANDLING", "WIRE_TAP"):
        nx.set_layer(child, 98)
    elif subtract_att == "TOOLING":
        nx.set_layer(child, 97)

    work = nx.work_part()

    if child.Layer != 99 or subtract_att in ("HANDLING", "WIRE_TAP"):
        nx.set_reference_set(child, nx.RefsetEmpty)
        _body_reference_set(work).RemoveObjectsFromReferenceSet([child])
        return

    nx.set_reference_set(child, "BODY")
    _body_reference_set(work).AddObjectsToReferenceSet([child])


def _subtract_reference_set(subtract_att: str) -> str:
    """The switch at the top of WaveIn(Component, Body)."""
    if subtract_att in ("HANDLING", "WIRE_TAP"):
        return "SHORT-TAP"
    if subtract_att == "BLIND_OPP":
        return "CBORE_BLIND_OPP"
    if subtract_att == "CLR_DRILL":
        return "CLR_HOLE"
    return subtract_att


def _is_already_linked(child: NXOpen.Assemblies.Component) -> bool:
    """
    The is_subtracted loop in WaveIn(Component, Body): true when a live LINKED_BODY in the display part has its
    wave-link transform on the child's origin. A broken link prints its source and is skipped.
    """
    origin = nx.component_origin(child)

    for feature in nx.display_part().Features.GetFeatures():
        if not isinstance(feature, NXOpen.Features.ExtractFace):
            continue

        if not nx.is_linked_body(feature):
            continue

        if nx.is_link_broken(feature):
            part_name, source = nx.ufsession_.Wave.AskBrokenLinkSourcePart(feature.Tag)
            nx.print_(part_name)
            nx.print_(source)
            continue

        point = nx.ufsession_.So.AskPointOfXform(nx.xform_tag(feature))

        if _is_equal_to(origin, point):
            return True

    return False


def _is_equal_to(point: NXOpen.Point3d, array: Sequence[float]) -> bool:
    """Point3d.__IsEqualTo(double[]) - each coordinate within .001."""
    return (abs(point.X - array[0]) < .001
            and abs(point.Y - array[1]) < .001
            and abs(point.Z - array[2]) < .001)


def _dynamic_block_or_none(part: NXOpen.BasePart) -> Optional[NXOpen.Features.Block]:
    """BasePart.__DynamicBlockOrNull - the Block feature named DYNAMIC BLOCK. SingleOrDefault, so two throw."""
    blocks = [f for f in part.Features.GetFeatures()
              if isinstance(f, NXOpen.Features.Block) and f.Name == "DYNAMIC BLOCK"]

    if len(blocks) > 1:
        raise RuntimeError("{} has more than one DYNAMIC BLOCK.".format(part.Leaf))

    return blocks[0] if blocks else None


def _single_solid_body_on_layer_1(part: NXOpen.BasePart) -> NXOpen.Body:
    """BasePart.__SingleSolidBodyOnLayer1 - throws on none or several, like the C#."""
    bodies = [b for b in part.Bodies if b.IsSolidBody and b.Layer == 1]

    if not bodies:
        raise RuntimeError("{} has no solid body on layer 1.".format(part.Leaf))

    if len(bodies) > 1:
        raise RuntimeError("{} has more than one solid body on layer 1.".format(part.Leaf))

    return bodies[0]


def _body_reference_set(part: NXOpen.BasePart) -> NXOpen.ReferenceSet:
    """The part's BODY reference set. The C# throws when there is none (__FindReferenceSet / Single)."""
    refset = nx.find_reference_set_or_null(part, "BODY")

    if refset is None:
        raise RuntimeError("{} has no BODY reference set.".format(part.Leaf))

    return refset


# UF_CSYS_ROOT_COORDS / UF_CSYS_WORK_COORDS / UF_CSYS_ROOT_WCS_COORDS
_UF_CSYS_ROOT_COORDS = 1
_UF_CSYS_WORK_COORDS = 2
_UF_CSYS_ROOT_WCS_COORDS = 3


def set_wcs_to_work_part() -> None:
    """Static.AddFastenersSetWcsToWorkPart - the display part's WCS onto the work part's dynamic block."""
    disp = nx.display_part()
    work = nx.work_part()
    block = _dynamic_block_or_none(work)

    if block is None:
        raise RuntimeError("{} has no DYNAMIC BLOCK.".format(work.Leaf))

    origin = _block_origin(block)
    orientation = _block_orientation(block)

    if work.Tag == disp.Tag:
        disp.WCS.SetOriginAndMatrix(origin, orientation)
        return

    work_component = nx.session_.Parts.WorkComponent
    comp_origin = nx.component_origin(work_component)
    comp_orientation = nx.component_orientation(work_component)

    # The C# maps from a csys at the work component to the absolute one, so this is "component frame -> display
    # coordinates". As in the C#, the new X / Y are the work component's own axes mapped, not the block's - kept.
    new_origin = _component_to_absolute(origin, comp_origin, comp_orientation)
    new_x = _rotate_to_absolute(nx.axis_x(comp_orientation), comp_orientation)
    new_y = _rotate_to_absolute(nx.axis_y(comp_orientation), comp_orientation)
    disp.WCS.SetOriginAndMatrix(new_origin, nx.matrix_from_axes(new_x, new_y))


def make_plan_view(csys: NXOpen.CartesianCoordinateSystem) -> None:
    """
    Static.AddFastenersMakePlanView - makes the work part the display part, rebuilds its saved PLAN view from csys
    in layout L1 in place of Top, and deletes csys. The C# orients the work view with UF_VIEW_set_view_matrix from
    the csys; this orients it to the csys's matrix, which is the same thing.
    """
    nx.set_display_part(nx.work_part())
    disp = nx.display_part()

    if _modeling_view_or_none(disp, "PLAN") is not None:
        layout = disp.Layouts.FindObject("L1")
        layout.ReplaceView(disp.ModelingViews.WorkView, disp.ModelingViews.FindObject("Top"), True)
        _delete([disp.ModelingViews.FindObject("PLAN")])

    disp.Views.WorkView.Orient(csys.Orientation.Element)
    view = cast(NXOpen.ModelingView, disp.Views.SaveAs(disp.ModelingViews.WorkView, "PLAN", False, False))
    disp.Layouts.FindObject("L1").ReplaceView(view, disp.ModelingViews.FindObject("Top"), True)
    _delete([csys])


def _modeling_view_or_none(part: NXOpen.BasePart, name: str) -> Optional[NXOpen.ModelingView]:
    """Part.ModelingView(name) - None when the part has no view by that name."""
    for view in part.ModelingViews:
        if view.Name == name:
            return view
    return None


def _proto_part_occ(owning_part: NXOpen.BasePart,
                    part_occ: NXOpen.Assemblies.Component) -> NXOpen.Assemblies.Component:
    """Static.AddFastenersGetProtoPartOcc - part_occ's instance as an occurrence under owning_part's root."""
    instance = nx.ufsession_.Assem.AskInstOfPartOcc(part_occ.Tag)
    root = owning_part.ComponentAssembly.RootComponent
    return cast(NXOpen.Assemblies.Component,
                nx.tagged_object(nx.ufsession_.Assem.AskPartOccOfInst(root.Tag, instance)))


def _component_to_absolute(point: NXOpen.Point3d, origin: NXOpen.Point3d,
                           orientation: NXOpen.Matrix3x3) -> NXOpen.Point3d:
    """Point3d.__MapCsysToCsys(component csys, absolute csys)"""
    x, y, z = nx.axis_x(orientation), nx.axis_y(orientation), nx.axis_z(orientation)
    return NXOpen.Point3d(origin.X + point.X * x.X + point.Y * y.X + point.Z * z.X,
                          origin.Y + point.X * x.Y + point.Y * y.Y + point.Z * z.Y,
                          origin.Z + point.X * x.Z + point.Y * y.Z + point.Z * z.Z)


def _rotate_to_absolute(vector: NXOpen.Vector3d, orientation: NXOpen.Matrix3x3) -> NXOpen.Vector3d:
    """Vector3d.__MapCsysToCsys(component csys, absolute csys)"""
    x, y, z = nx.axis_x(orientation), nx.axis_y(orientation), nx.axis_z(orientation)
    return NXOpen.Vector3d(vector.X * x.X + vector.Y * y.X + vector.Z * z.X,
                           vector.X * x.Y + vector.Y * y.Y + vector.Z * z.Y,
                           vector.X * x.Z + vector.Y * y.Z + vector.Z * z.Z)


def _block_origin(block: NXOpen.Features.Block) -> NXOpen.Point3d:
    """Block.__Origin - read off a BlockFeatureBuilder."""
    builder = block.OwningPart.Features.CreateBlockFeatureBuilder(block)
    try:
        return builder.Origin
    finally:
        builder.Destroy()


def _block_orientation(block: NXOpen.Features.Block) -> NXOpen.Matrix3x3:
    """Block.__Orientation - read off a BlockFeatureBuilder."""
    builder = block.OwningPart.Features.CreateBlockFeatureBuilder(block)
    try:
        x_axis, y_axis = builder.GetOrientation()
        return nx.matrix_from_axes(x_axis, y_axis)
    finally:
        builder.Destroy()


def _translucency(obj: NXOpen.DisplayableObject, translucency: int) -> None:
    """DisplayableObject.__Translucency"""
    nx.ufsession_.Obj.SetTranslucency(obj.Tag, translucency)
    obj.RedisplayObject()


def _delete(objects: Sequence[NXOpen.TaggedObject]) -> None:
    """Session.DeleteObjects - inline, for the same reason strip_wave_out does it inline."""
    with nx.do_update():
        nx.session_.UpdateManager.AddObjectsToDeleteList(list(objects))

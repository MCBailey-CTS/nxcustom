"""
Python port of Merlin.BuildPointComponent (src\\UFuncs\\Merlin.cs) - the builder behind
Merlin.StaticPointComponent.

The picks stay in C#: StaticPointComponent runs the units gate, the rubber-band rectangle picker (UF motion
callbacks) and the SNAP RectangleSizeDialog, none of which Python can host, and hands the result here through
PythonLibrary.Execute. Everything after the dialog runs in this module:

  - divide the picked rectangle into component_count blocks along the WCS split axis, .004" apart
  - color each block (168 single, or a random draw from the split palette) and the gap/bottom faces 42
  - promote each block to its own point-component-{token}.prt and re-base the part onto the block
  - BODY / SUBTOOL reference sets, DYNAMIC BLOCK, station expressions, attributes, AutoSize UDO
  - BODY as the used reference set (and a BODY member) in every loaded ancestor assembly
  - optionally link and subtract a component's reference set from every block

Session.Execute cannot pass null or a Point3d, so the corners arrive as six doubles, the optional component
as its tag (0 = none) and the optional reference set as a string ("" = none).
"""

from __future__ import annotations

import os
import random
import re
import sys
from typing import Callable, Iterable, List, Optional, Sequence, cast

# Session.Execute does not put the script's folder on sys.path, so the shared module would not import.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

import NXOpen  # noqa: E402
import NXOpen.Assemblies  # noqa: E402
import NXOpen.Features  # noqa: E402
import NXOpen.Layer  # noqa: E402
import NXOpen.UF  # noqa: E402

import tsg_nx as nx  # noqa: E402

# Merlin constants.
SplitGap = 0.004
BlockAtWcsColor = 168
SplitComponentColors = [8, 11, 50, 78, 93, 98, 102, 126, 134, 138, 161, 198, 209]
PointComponentName = "point-component"

# NXException.ErrorCode for a boolean that failed outright (SubtractComponents prints and carries on).
ErrorBooleanFailed = 3520001

# Merlin.RegexStationLeaf / LowerHolders / UpperHolders.
RegexStationLeaf = r"^(?P<job>\d+)-(?P<op>\d+)-(?P<detail>[A-Za-z]+)\d*$"
LowerHolders = ["lwr", "las"]
UpperHolders = ["upr", "uas"]


class PointComponent(object):

    @staticmethod
    def build(first_x: float, first_y: float, first_z: float,
              second_x: float, second_y: float, second_z: float,
              height: float, component_count: int,
              subtract_component_tag: int, subtract_refset: str, split_axis: str) -> None:
        """
        Session.Execute entry for Merlin.StaticPointComponent. split_axis is "X" or "Y" (Merlin.SplitAxis); the
        other arguments are BuildPointComponent's, flattened so they can cross Session.Execute.
        """
        try:
            subtract_component = None
            if subtract_component_tag:
                subtract_component = cast(NXOpen.Assemblies.Component, nx.tagged_object(subtract_component_tag))

            build_point_component(
                NXOpen.Point3d(first_x, first_y, first_z),
                NXOpen.Point3d(second_x, second_y, second_z),
                height,
                int(component_count),
                subtract_component,
                subtract_refset or None,
                "X" if str(split_axis).upper() == "X" else "Y")
        except Exception as ex:
            nx.print_exception(ex)


def build_point_component(first_corner: NXOpen.Point3d, second_corner: NXOpen.Point3d, height: float,
                          component_count: int = 1,
                          subtract_component: Optional[NXOpen.Assemblies.Component] = None,
                          subtract_refset: Optional[str] = None,
                          split_axis: str = "Y") -> None:
    """Merlin.BuildPointComponent - see the C# doc comment for the parameters."""
    if nx.distance(first_corner, second_corner) <= nx.distance_tolerance():
        nx.show_error("The two picked points are the same - the block needs a length and a width.")
        return

    if height <= nx.distance_tolerance():
        nx.show_error("Block height must be greater than zero (got {}).".format(height))
        return

    if component_count < 1:
        nx.show_error("Number of components must be at least 1 (got {}).".format(component_count))
        return

    nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, "Start UFunc")
    starting_display = nx.display_part()
    starting_work = nx.work_part()

    # The WCS is read for the rectangle's orientation and restored in the finally - __CreateBlock swaps the
    # display part's WCS orientation internally.
    saved_wcs_origin = starting_display.WCS.CoordinateSystem.Origin
    saved_wcs_matrix = starting_display.WCS.CoordinateSystem.Orientation.Element

    try:
        # (The C# calls GFolder.create_or_null here and discards the result - it only prints when the display
        # part is not in a job folder. Not ported.)

        wcs_matrix = nx.display_part().WCS.CoordinateSystem.Orientation.Element
        x_axis = nx.axis_x(wcs_matrix)
        y_axis = nx.axis_y(wcs_matrix)

        # The picked span is measured along the WCS axes, signed so the low corner can be found: the user can
        # drag in any direction, but the components stack from the low edge upward.
        delta = NXOpen.Vector3d(second_corner.X - first_corner.X,
                                second_corner.Y - first_corner.Y,
                                second_corner.Z - first_corner.Z)

        def along(axis: NXOpen.Vector3d) -> float:
            return delta.X * axis.X + delta.Y * axis.Y + delta.Z * axis.Z

        dx = along(x_axis)
        dy = along(y_axis)
        xlength = abs(dx)
        ywidth = abs(dy)

        low_corner = nx.add_along(nx.add_along(first_corner, x_axis, min(dx, 0.0)), y_axis, min(dy, 0.0))

        # The blocks are laid out along split_axis and keep the full span along the other one.
        stacks_along_x = split_axis == "X"
        stack_axis = x_axis if stacks_along_x else y_axis
        keep_axis = y_axis if stacks_along_x else x_axis
        stack_span = xlength if stacks_along_x else ywidth
        keep_span = ywidth if stacks_along_x else xlength

        # Same arithmetic as CreateSplitForm: the gaps come out of the picked span.
        component_width = (stack_span - (component_count - 1) * SplitGap) / component_count

        if component_width <= nx.distance_tolerance():
            nx.show_error("{} components do not fit in a {} span with {} gaps.".format(
                component_count, _format_0_000(stack_span), SplitGap))
            return

        block_xlength = component_width if stacks_along_x else xlength
        block_ywidth = ywidth if stacks_along_x else component_width

        # A split run colors each block differently: a random draw without replacement.
        split_colors = random.sample(SplitComponentColors, len(SplitComponentColors)) if component_count > 1 else None

        nx.work_part().Layers.WorkLayer = 1
        blocks = []
        for index in range(component_count):
            block_origin = nx.add_along(low_corner, stack_axis, index * (component_width + SplitGap))
            block_corner = nx.add_along(nx.add_along(block_origin, keep_axis, keep_span), stack_axis, component_width)
            blocks.append(nx.create_block_two_points_and_height(wcs_matrix, block_origin, block_corner, height))

        for index, block in enumerate(blocks):
            try:
                # CreateCtsComponent leaves the new detail as the display/work part, so every iteration after
                # the first has to come back to the starting parts before promoting.
                nx.set_display_part(starting_display)
                nx.set_work_part(starting_work)

                _build_one_block(block, index, len(blocks), split_colors, wcs_matrix, stack_axis,
                                 block_xlength, block_ywidth, height, starting_display,
                                 subtract_component, subtract_refset)
            # Per-block catch so one bad component does not drop the rest of the batch.
            except Exception as ex:
                nx.print_exception(ex)
    except Exception as ex:
        nx.print_exception(ex)
    finally:
        nx.set_display_part(starting_display)
        nx.set_work_part(starting_work)
        # Put the WCS back on the part whose WCS __CreateBlock actually touched.
        starting_display.WCS.SetOriginAndMatrix(saved_wcs_origin, saved_wcs_matrix)


def _build_one_block(block: NXOpen.Features.Block, index: int, block_count: int,
                     split_colors: Optional[Sequence[int]], wcs_matrix: NXOpen.Matrix3x3,
                     stack_axis: NXOpen.Vector3d, block_xlength: float, block_ywidth: float, height: float,
                     starting_display: NXOpen.Part,
                     subtract_component: Optional[NXOpen.Assemblies.Component],
                     subtract_refset: Optional[str]) -> None:
    """The body of BuildPointComponent's per-block loop."""
    block_body = block.GetBodies()[0]

    # Color the whole body first - it colors every face, so the yellow faces below have to come after.
    nx.set_color(block_body, BlockAtWcsColor if split_colors is None else split_colors[index % len(split_colors)])

    bottom_face = nx.planar_face_with_normal_or_null(block_body, nx.negate(nx.axis_z(wcs_matrix)))
    if bottom_face is None:
        nx.print_("Could not find the block's -Z face to color yellow")
    else:
        nx.set_color(bottom_face, 42)

    # Yellow the faces that bound a gap - +stack on every block but the last, -stack on every block but the first.
    if index < block_count - 1:
        face = nx.planar_face_with_normal_or_null(block_body, stack_axis)
        if face is not None:
            nx.set_color(face, 42)
    if index > 0:
        face = nx.planar_face_with_normal_or_null(block_body, nx.negate(stack_axis))
        if face is not None:
            nx.set_color(face, 42)

    new_component = _create_cts_component(block, PointComponentName)

    # Re-base onto the block's own corner and orientation before anything else is built against the geometry.
    # The parent is the component's owning part - the block was built in the work part.
    _rebase_block_to_part_origin(new_component, cast(NXOpen.Part, new_component.OwningPart))
    nx.find_or_create_reference_set(new_component.OwningPart, "BODY").AddObjectsToReferenceSet([new_component])
    new_part = nx.work_part()
    nx.setup_station_expressions(new_part)
    refset = new_part.CreateReferenceSet()
    refset.SetName("BODY")
    refset.AddObjectsToReferenceSet(list(new_part.Bodies))
    first_block = nx.first_block_feature(new_part)
    if first_block is None:
        raise RuntimeError("{} has no block feature to name DYNAMIC BLOCK.".format(new_part.Leaf))
    first_block.SetName("DYNAMIC BLOCK")
    nx.set_attribute(new_part, "DESCRIPTION", "{} X {} X {}".format(
        _format_0_000(block_xlength), _format_0_000(block_ywidth), _format_0_000(height)))
    nx.set_attribute(new_part, "MATERIAL", "FILL IN")
    nx.set_attribute(new_part, "DETAIL NAME", "FILL IN")
    # Extract the subtool onto layer 15 (after BODY is populated so it is not added to BODY).
    new_part.Layers.WorkLayer = 15
    _create_subtool(new_part)
    new_part.Layers.WorkLayer = 1
    new_part.Layers.SetState(15, NXOpen.Layer.State.Hidden)
    nx.create_auto_size_udo(new_part)

    nx.set_display_part(starting_display)
    new_comp = nx.first_occurrence_in(new_part, nx.display_part())
    new_comp.Unblank()
    # The new component defaults to ENTIRE PART; force BODY here and in every ancestor assembly.
    nx.set_reference_set(new_comp, "BODY")

    # Before the subtract, so a subtract that throws does not leave ENTIRE PART showing above the block.
    _set_reference_set_in_ancestor_assemblies(new_comp, "BODY", add_to_reference_set=True)

    if subtract_component is not None and subtract_refset:
        nx.set_work_part(new_part)
        nx.work_part().Layers.WorkLayer = 1
        _subtract_components(lambda: nx.dynamic_block(nx.work_part()).GetBodies()[0],
                             [subtract_component], subtract_refset)


# ---------------------------------------------------------------------------------------------------
# Merlin component scaffolding
# ---------------------------------------------------------------------------------------------------

def _random_file_token() -> str:
    """Merlin.RandomFileToken - Random.NextDouble().ToString() (15 significant digits) minus the "0."."""
    return "{:.15g}".format(random.random()).replace("0.", "")


def _create_cts_component(block: NXOpen.Features.Block, name: str) -> NXOpen.Assemblies.Component:
    """
    Merlin.CreateCtsComponent with its defaults (WCS origin, work layer 1, originals deleted, AutoSize UDO)
    over Merlin.CreateNewComponentCore.
    """
    work = nx.work_part()
    builder = work.AssemblyManager.CreateNewComponentBuilder()
    try:
        file_new = nx.session_.Parts.FileNew()
        file_new.Units = (NXOpen.Part.Units.Millimeters if work.PartUnits == NXOpen.BasePart.Units.Millimeters
                          else NXOpen.Part.Units.Inches)
        file_new.NewFileName = "{}\\{}-{}.prt".format(
            os.path.dirname(nx.display_part().FullPath), name, _random_file_token())
        file_new.UseBlankTemplate = True
        builder.ReferenceSet = NXOpen.Assemblies.CreateNewComponentBuilder.ComponentReferenceSetType.Other
        builder.LayerOption = NXOpen.Assemblies.CreateNewComponentBuilder.ComponentLayerOptionType.Work
        builder.NewComponentName = os.path.splitext(os.path.basename(file_new.NewFileName))[0]
        builder.LayerNumber = 1
        builder.ComponentOrigin = NXOpen.Assemblies.CreateNewComponentBuilder.ComponentOriginType.Wcs
        builder.OriginalObjectsDeleted = True
        builder.ObjectForNewComponent.Add(block.GetBodies()[0])
        builder.NewFile = file_new
        builder.Commit()
        new_component = cast(NXOpen.Assemblies.Component, builder.GetObject())
        # Every component Merlin makes gets these placeholder GM job attributes on its prototype part.
        new_prototype = nx.prototype(new_component)
        nx.set_attribute(new_prototype, "CSPC", "X")
        nx.set_attribute(new_prototype, "GM Tool Number", "X")
        nx.create_auto_size_udo(nx.work_part())
        return new_component
    finally:
        builder.Destroy()


def _rebase_block_to_part_origin(component: NXOpen.Assemblies.Component, parent: NXOpen.Part) -> None:
    """
    Merlin.RebaseBlockToPartOrigin(component, parent) with applyOrientation = true, oppositeCorner = false -
    the block's corner becomes the part's (0,0,0) and its orientation the part's absolute orientation, edited
    parametrically on the block feature; the component is then moved by the inverse, rotate first and
    translate second. Leaves the new detail as the display and work part.
    """
    new_part = nx.prototype(component)
    block = nx.first_block_feature(new_part)

    if block is None:
        nx.print_("{} has no block feature - leaving its origin alone".format(new_part.Leaf))
        return

    nx.set_display_part(new_part)
    nx.set_work_part(new_part)

    # The builder's Length/Width/Height come back None in Python, so the size expressions come from
    # UF_MODL_ask_block_parms ("name=value" strings, length / width / height) - as DrawDie's re-base does.
    length_exp, width_exp, height_exp = (new_part.Expressions.FindObject(parm.split("=", 1)[0].strip())
                                         for parm in nx.ufsession_.ModlFeatures.AskBlockParms(block.Tag, 0))

    # The block's own origin and orientation, read in assembly coordinates - they become the component's
    # position after the reset below.
    builder = new_part.Features.CreateBlockFeatureBuilder(block)
    try:
        block_origin = builder.Origin
        x_axis, y_axis = builder.GetOrientation()
        block_orientation = nx.matrix_from_axes(x_axis, y_axis)

        # Orientation before origin, so the origin is written against the axes the block keeps.
        builder.SetOrientation(NXOpen.Vector3d(1.0, 0.0, 0.0), NXOpen.Vector3d(0.0, 1.0, 0.0))
        builder.SetOriginAndLengths(
            NXOpen.Point3d(0.0, 0.0, 0.0),
            length_exp.RightHandSide,
            width_exp.RightHandSide,
            height_exp.RightHandSide)
        builder.Commit()
    finally:
        builder.Destroy()

    # The component move needs its owning assembly as the work part...
    nx.set_display_part(parent)
    nx.set_work_part(parent)

    # Rotate first, while the geometry is still on the origin and therefore spins in place...
    parent.ComponentAssembly.MoveComponent(component, NXOpen.Vector3d(0.0, 0.0, 0.0), block_orientation)
    # ...then carry it out to where the block was.
    parent.ComponentAssembly.MoveComponent(
        component, NXOpen.Vector3d(block_origin.X, block_origin.Y, block_origin.Z), nx.identity_matrix())

    # ...but the caller picks up with the new detail as the display and work part.
    nx.set_display_part(new_part)
    nx.set_work_part(new_part)


def _create_subtool(new_part: NXOpen.BasePart, name: str = "SUBTOOL") -> NXOpen.Features.Feature:
    """Merlin.CreateSubtool - extracts the layer-1 body (onto the current work layer) plus a SUBTOOL refset."""
    builder = new_part.Features.CreateExtractFaceBuilder(None)
    try:
        builder.FaceOption = NXOpen.Features.ExtractFaceBuilder.FaceOptionType.FaceChain
        builder.Type = NXOpen.Features.ExtractFaceBuilder.ExtractType.Body
        builder.FixAtCurrentTimestamp = True
        layer1_body = None
        for body in new_part.Bodies:
            if body.Layer == 1:
                layer1_body = body
        if layer1_body is None:
            raise RuntimeError("{} has no body on layer 1 to extract a subtool from.".format(new_part.Leaf))
        builder.BodyToExtract.Add(layer1_body)
        extract = builder.CommitFeature()
    finally:
        builder.Destroy()

    extract.SetName(name)
    subtool_body = extract.GetBodies()[0]
    nx.set_color(subtool_body, 42)
    subtool_refset = new_part.CreateReferenceSet()
    subtool_refset.SetName(name)
    subtool_refset.AddObjectsToReferenceSet([subtool_body])
    return extract


def _subtract_components(get_target: Callable[[], NXOpen.Body],
                         components: Iterable[NXOpen.Assemblies.Component], refset: str) -> None:
    """Merlin.SubtractComponents - link each component's refset into the work part and subtract it."""
    for comp in components:
        if not nx.has_reference_set(nx.prototype(comp), refset):
            nx.print_("Component {} does not have reference set {}, skipping boolean".format(comp.DisplayName, refset))
            continue

        try:
            nx.set_reference_set(comp, refset)
            linked = nx.create_linked_body(comp)
            # Re-fetched every time - a boolean can replace the target body.
            nx.subtract(get_target(), linked.GetBodies())
        except NXOpen.NXException as ex:
            if ex.ErrorCode == ErrorBooleanFailed:
                nx.print_("Failed to boolean {} with reference set {}".format(comp.DisplayName, refset))
            nx.print_exception(ex)
        except Exception as ex:
            nx.print_exception(ex)
        finally:
            nx.set_reference_set(comp, "BODY")


# ---------------------------------------------------------------------------------------------------
# Reference sets in ancestor assemblies
# ---------------------------------------------------------------------------------------------------

def _set_reference_set_in_ancestor_assemblies(occurrence: NXOpen.Assemblies.Component, refset: str = "BODY",
                                              add_to_reference_set: bool = False) -> None:
    """
    Merlin.SetReferenceSetInAncestorAssemblies - the used reference set in every loaded assembly that contains
    the detail (its own ancestors first, then a sweep over the session), and with add_to_reference_set the
    direct child on the path added to each assembly's own refset.
    """
    proto = nx.prototype(occurrence)

    assemblies: List[NXOpen.Part] = []
    ancestor = occurrence.Parent
    while ancestor is not None:
        if isinstance(ancestor.Prototype, NXOpen.Part):
            assemblies.append(ancestor.Prototype)
        ancestor = ancestor.Parent

    for loaded in nx.session_.Parts:
        try:
            if (not isinstance(loaded, NXOpen.Part)
                    or loaded.PartLoadState != NXOpen.PartLoadState.FullyLoaded
                    or loaded.Tag == proto.Tag
                    or any(already.Tag == loaded.Tag for already in assemblies)
                    or loaded.ComponentAssembly.RootComponent is None
                    or len(nx.occurrences_of_part_in(loaded, proto)) == 0):
                continue
            assemblies.append(loaded)
        except Exception as ex:
            nx.print_exception(ex, loaded.Leaf)

    for owner_part in assemblies:
        try:
            occurrences = nx.occurrences_of_part_in(owner_part, proto)

            if not occurrences:
                nx.print_('Found no occurrence of {} in {} - reference set "{}" not set there'.format(
                    proto.Leaf, owner_part.Leaf, refset))
                continue

            for occ in occurrences:
                nx.set_reference_set(occ, refset)

            if add_to_reference_set:
                # Only what this assembly directly owns is a legal member - see the C# comment.
                members: List[NXOpen.Assemblies.Component] = []
                for occ in occurrences:
                    member = _direct_child_on_path_in(owner_part, occ)
                    if member is not None and all(m.Tag != member.Tag for m in members):
                        members.append(member)

                if not members:
                    nx.print_('No component of {} carries {} - reference set "{}" contents unchanged there'.format(
                        owner_part.Leaf, proto.Leaf, refset))
                else:
                    nx.find_or_create_reference_set(owner_part, refset).AddObjectsToReferenceSet(members)
        except Exception as ex:
            nx.print_exception(ex)

    _warn_about_unreached_station_assemblies(nx.display_part(), proto, refset, assemblies)


def _direct_child_on_path_in(assembly: NXOpen.BasePart,
                             occurrence: NXOpen.Assemblies.Component) -> Optional[NXOpen.Assemblies.Component]:
    """Merlin.DirectChildOnPathIn - the component on occurrence's path that assembly's root directly owns."""
    root = assembly.ComponentAssembly.RootComponent

    if root is None:
        return None

    current: Optional[NXOpen.Assemblies.Component] = occurrence
    while current is not None:
        if current.Parent is not None and current.Parent.Tag == root.Tag:
            return current
        current = current.Parent

    return None


def _warn_about_unreached_station_assemblies(station: NXOpen.BasePart, proto: NXOpen.BasePart, refset: str,
                                             handled: Sequence[NXOpen.BasePart]) -> None:
    """Merlin.WarnAboutUnreachedStationAssemblies - name each expected holder/-000 the refset pass missed."""
    try:
        match = re.match(RegexStationLeaf, station.Leaf)

        if not match:
            return

        detail = match.group("detail").lower()

        if detail.startswith("l"):
            holders = LowerHolders
        elif detail.startswith("u"):
            holders = UpperHolders
        else:
            return

        prefix = "{}-{}-".format(match.group("job"), match.group("op"))
        # Each group is one level, spelled every way a job might name it.
        expected: List[List[str]] = []

        if detail not in holders:
            expected.append([prefix + holder for holder in holders])

        expected.append([prefix + "000"])

        handled_leaves = [part.Leaf.lower() for part in handled]

        for candidates in expected:
            if any(leaf.lower() in handled_leaves for leaf in candidates):
                continue

            loaded = [leaf for leaf in candidates if nx.ufsession_.Part.IsLoaded(leaf) != 0]

            if not loaded:
                nx.print_('{}: reference set "{}" NOT set in {} - not loaded in this session. Open the assembly and '
                          'set it there, or re-run from the assembly.'.format(proto.Leaf, refset, " or ".join(candidates)))
            else:
                nx.print_('{}: reference set "{}" NOT set in {} - loaded but contains no occurrence of the detail.'
                          .format(proto.Leaf, refset, " or ".join(loaded)))
    except Exception as ex:
        nx.print_exception(ex)


def _format_0_000(value: float) -> str:
    """C#'s value.ToString("0.###") - at most three decimals, trailing zeros dropped."""
    text = "{:.3f}".format(value).rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text

"""
Python port of the nine-99-block UFunc (Nine99Block.Block999, src\\UFuncs\\Nine99Block.cs), as of 2026-10-20
(9771eec "Nine99Block set up like a Merlin block" + d3fc8bb).
The C# wrapper was deleted 2026-10-22 (in git at 1cb53d8): the UFunc's menu button runs this file's main().

First (2026-10-29), a Warning box when the display assembly holds any component that is still the library
G:\\0Library\\Unikix\\Smart Unikix Pins.prt (never saved as its own pin part), listed by parent; the run then goes on.

Select components, take the solid body on layer 1 of each one's part, find that body's occurrence under the
picked component, and build one block over the bounding box of all of them in the display part (grown .75" on
the four sides, each length rounded up to .125", the -Z face colored 42). Then:
  - the block is promoted to the next free {job}-{op}-NNN.prt (counting down from 998; job/op from the op folder);
  - SetUpAsMerlinBlock: CSPC / GM Tool Number "X", the part re-based onto its block (RebaseBlockToPartOrigin),
    the new component in its owning part's BODY, station expressions, BODY, DYNAMIC BLOCK, DESCRIPTION
    "{L} X {W} X {H}", MATERIAL copied from the first picked component (else FILL IN), DETAIL NAME
    "Make from Det NNN" (the block's own detail number), SUBTOOL on hidden layer 15, AutoSize UDO, then BODY used -
    and added to BODY - in every loaded assembly above it;
  - the picked components are restructured under the block, and each live assembly-context LINKED_BODY in their
    prototypes is traced back to its source body, which is wave-linked into the block and subtracted from its
    DYNAMIC BLOCK body (one link at a time, printed);
  - FinishBlock999, in the block's own part: 2x 12mm-jck-screw-tsg on the top face pointing -Z (puck flush with
    it) at diagonal corners on the block's 1" grid (CBORE_BLIND, layer 99), each subtracted; the DYNAMIC BLOCK's
    top face colored 42 like its bottom (after the subtracts); every child into BODY; "XX" appended to the component
    name of each trim steel and each detail child of a trim steel - in its own part and on its occurrences in the
    block and the display assembly; each trim steel's AutoSize switched off and its DESCRIPTION set to
    "MAKE FROM DET# NNN" (the block's number). (The two 8mm-shcs-020-2x wire taps on the +X face were dropped
    2026-10-26.)

Three ways in:
  - File -> Execute -> NX Open on this file runs main(), which does the component pick itself (the C# UFunc
    picks inside execute(), so this is the like-for-like entry).
  - Session.Execute("Nine99.py", "Nine99Block", "execute") from C#, which also picks here.
  - Session.Execute("Nine99.py", "Nine99Block", "run", components) from C#, with the picks passed in as
    TaggedObject[] (see README.md).

The Merlin helpers already ported are imported, not copied: RebaseBlockToPartOrigin, CreateSubtool,
SetReferenceSetInAncestorAssemblies and the "0.###" format from PointComponent.py; Vector3d.__ToMatrix3x3() from
DrawDie.py; Part_.FindOrCreateReferenceSet (quiet) and Part.__SubtractLinkedBody from GmSplitForm.py.

Differences from the C#:
  - create_block restores both WCS axes, where __CreateBlock(Matrix3x3, Point3d, Point3d) puts the new Y back
    instead of the original.
  - No {job}-{op} op folder raises RuntimeError (C#: InvalidOperationException) - same message, printed by the
    outer except. A punch prototype with no root component raises RuntimeError where the C# would NRE on
    __RootComponent().Tag; both abort the run the same way (caught by the outer except).
  - The AutoSize UDO class can only be registered from C# (tsg_nx.create_auto_size_udo). It is registered at NX
    startup (AutoSizeComponent.Startup); in a session where TSG_Library never registered it, the block gets no
    UDO - that prints and carries on.
  - The re-base reads the block's size through UF_MODL_ask_block_parms, since BlockFeatureBuilder.Length/Width/
    Height come back None in Python.
"""

from __future__ import annotations

import math
import os
import re
import sys
from typing import List, Optional, Sequence, Set, cast

# Session.Execute does not put the script's folder on sys.path, so the shared modules would not import.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)
# From the source tree (src\UFuncs) the shared modules are in src\python; deployed, they are beside this file.
_shared_python = os.path.join(os.path.dirname(_here), "python")
if os.path.isdir(_shared_python) and _shared_python not in sys.path:
    sys.path.insert(1, _shared_python)

import NXOpen  # noqa: E402
import NXOpen.Assemblies  # noqa: E402
import NXOpen.Features  # noqa: E402
import NXOpen.Layer  # noqa: E402

import tsg_nx as nx  # noqa: E402
import PointComponent as merlin  # noqa: E402
import DrawDie as drawdie  # noqa: E402
import GmSplitForm as splitform  # noqa: E402

Block999SideGrowth = .75

Block999FirstNumber = 998

Block999JackPath = "G:\\0Library\\Fasteners\\Metric\\JackScrews\\12mm-jck-screw-tsg.prt"

# The jig jacks sit this far in from their X faces (the trim details' jack inset).
Block999JackInsetX = .625

# The jig jacks sit this far in from their Y faces (the trim details' TSG jack inset).
Block999JackInsetY = 1.75

# The library smart part's leaf (G:\0Library\Unikix\Smart Unikix Pins.prt), lower case; a component still on it was
# never saved as its own pin part. The warning box lists at most this many parents.
UnikixPinsLeaf = "smart unikix pins"
UnikixWarningMaxLines = 20


class Nine99Block(object):

    @staticmethod
    def execute() -> None:
        """Nine99Block.execute - the unsaved Unikix pin warning, pick, then build."""
        _warn_unsaved_unikix_pins()
        Nine99Block.run(nx.select_many_components("Select components for Block999"))

    @staticmethod
    def run(picked: Optional[Sequence[NXOpen.TaggedObject]]) -> None:
        """Nine99Block.Block999 after the pick. picked: the picked Components (TaggedObject[] from C#)."""
        try:
            components = [c for c in (picked or []) if isinstance(c, NXOpen.Assemblies.Component)]

            if not components:
                nx.mark_cancelled("the component pick")
                return

            occurrence_bodies: List[NXOpen.Body] = []

            for component in components:
                try:
                    if not nx.is_loaded(component):
                        nx.print_("{}: not loaded, skipped.".format(component.DisplayName))
                        continue

                    # The layer is read off the prototype body - that is the layer it was modelled on.
                    layer1 = [body for body in nx.prototype(component).Bodies
                              if body.IsSolidBody and body.Layer == 1]

                    if not layer1:
                        nx.print_("{}: no solid body on layer 1, skipped.".format(component.DisplayName))
                        continue

                    for body in layer1:
                        occurrence = component.FindOccurrence(body)

                        if occurrence is None:
                            nx.print_("{}: no occurrence of {}, skipped.".format(
                                component.DisplayName, body.JournalIdentifier))
                        else:
                            occurrence_bodies.append(cast(NXOpen.Body, occurrence))
                except Exception as ex:
                    nx.print_exception(ex)

            if not occurrence_bodies:
                nx.print_("Block999: no layer-1 solid bodies found, nothing to build.")
                return

            box = nx.combine_boxes([nx.body_box(body) for body in occurrence_bodies])

            # Grow .75" on all four sides (not top or bottom), then round each length up to .125". X and Y stay
            # centred on the bodies; the height is rounded up from the bottom.
            x_length = nx.round_to_125(box.MaxX - box.MinX + 2 * Block999SideGrowth)
            y_length = nx.round_to_125(box.MaxY - box.MinY + 2 * Block999SideGrowth)
            height = nx.round_to_125(box.MaxZ - box.MinZ)
            center_x = (box.MinX + box.MaxX) / 2
            center_y = (box.MinY + box.MaxY) / 2
            min_point = NXOpen.Point3d(center_x - x_length / 2, center_y - y_length / 2, box.MinZ)
            max_point = NXOpen.Point3d(center_x + x_length / 2, center_y + y_length / 2, box.MinZ + height)

            path = _try_next_block999_path()

            if path is None:
                nx.print_("Block999: every detail number from {} down to 1 is already taken next to {}.".format(
                    Block999FirstNumber, nx.display_part().Leaf))
                return

            # Read now: the restructure below deletes the picked components.
            material = _block999_material(components[0])

            nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, "Block999")

            # The box is in display-part coordinates, so the block is built in the display part.
            starting_display = nx.display_part()
            nx.set_work_part(starting_display)
            nx.work_part().Layers.WorkLayer = 1
            block = nx.create_block(min_point, max_point)
            bottom_face = nx.planar_face_with_normal_or_null(block.GetBodies()[0], NXOpen.Vector3d(0.0, 0.0, -1.0))
            if bottom_face is not None:
                nx.set_color(bottom_face, 42)

            new_component = _promote_to_named_component(block, path)
            nx.print_("Block999: {} - {} x {} x {} over {} bodies".format(
                new_component.DisplayName, nx.cs_double_str(x_length), nx.cs_double_str(y_length),
                nx.cs_double_str(height), len(occurrence_bodies)))

            _set_up_as_merlin_block(new_component, starting_display, "{} X {} X {}".format(
                merlin._format_0_000(x_length), merlin._format_0_000(y_length), merlin._format_0_000(height)),
                material)
            nx.set_display_part(starting_display)
            nx.set_work_part(starting_display)

            # Make the picked components children of the new one. The originals are deleted.
            moved, errors = nx.display_part().ComponentAssembly.RestructureComponents(
                components, new_component, True)

            try:
                for i in range(errors.Length):
                    nx.print_("Block999: restructure error - {}".format(errors.GetErrorInfo(i).Description))
            finally:
                errors.Dispose()

            nx.print_("Block999: moved {} of {} components under {}".format(
                len(moved) if moved is not None else 0, len(components), new_component.DisplayName))

            # The links and the subtracts go into the new block's part - against the DYNAMIC BLOCK body,
            # not just the first solid one, since the part now carries a SUBTOOL body as well.
            nx.set_work_component(new_component)
            block_target = nx.dynamic_block(nx.work_part()).GetBodies()[0]

            # The picked components as they are now - children of the new block, which is where the
            # restructure put them. (Walking the display root's children never reached them.)
            restructured = list(moved) if moved is not None and len(moved) > 0 else list(new_component.GetChildren())

            for punch in restructured:
                _subtract_punch_links(punch, block_target)

            # Re-based, so in the block's own part it fills (0,0,0)..(L,W,H).
            trim_steels = _finish_block999(new_component, block_target, NXOpen.Point3d(0.0, 0.0, 0.0),
                                           NXOpen.Point3d(x_length, y_length, height))
            _add_xx_to_occurrences(starting_display, trim_steels)
        except Exception as ex:
            nx.print_exception(ex)

        nx.ufsession_.Disp.RegenerateDisplay()
        nx.display_part().ModelingViews.WorkView.Fit()


def _unsaved_unikix_pins(top_level: NXOpen.BasePart) -> List[NXOpen.Assemblies.Component]:
    """
    Every component under top_level that is still the library smart part (UnikixPinsLeaf), not a pin saved as its
    own job part: the Blank Station drops G:\\0Library\\Unikix\\Smart Unikix Pins.prt into each punch as is. Matched
    on the part name, so a copy that kept it counts too; an unloaded one by its display name.
    """
    root = nx.root_component(top_level)
    if root is None:
        return []
    found: List[NXOpen.Assemblies.Component] = []
    for component in nx.descendants(root):
        try:
            prototype = component.Prototype
            leaf = prototype.Leaf if prototype is not None else component.DisplayName
        except Exception:
            leaf = component.DisplayName
        if (leaf or "").strip().lower() == UnikixPinsLeaf:
            found.append(component)
    return found


def _warn_unsaved_unikix_pins() -> None:
    """A Warning box listing where each unsaved Smart Unikix Pins sits (by parent), when the assembly has any."""
    pins = _unsaved_unikix_pins(nx.display_part())
    if not pins:
        return

    by_parent: dict = {}
    for pin in pins:
        parent = pin.Parent
        name = parent.DisplayName if parent is not None else nx.display_part().Leaf
        by_parent[name] = by_parent.get(name, 0) + 1

    lines = ["{} x{}".format(name, count) for name, count in sorted(by_parent.items())]
    shown = lines[:UnikixWarningMaxLines]
    if len(lines) > len(shown):
        shown.append("... and {} more (all of them in the syslog)".format(len(lines) - len(shown)))
    for line in lines:
        nx.syslog("Block999: unsaved Smart Unikix Pins in {}".format(line))

    nx.message_box(
        "Block999",
        NXOpen.NXMessageBox.DialogType.Warning,
        "{} Smart Unikix Pins in this assembly are not saved as their own part (still the library smart part):\n\n"
        "{}".format(len(pins), "\n".join(shown)))


def _subtract_punch_links(punch: NXOpen.Assemblies.Component, block_target: NXOpen.Body) -> None:
    """
    The LINKED_BODY loop inside Block999, one punch at a time. Only each link's own link/subtract is guarded;
    anything else that throws ends the run, as in the C# (which has no per-punch try).
    """
    refset = punch.ReferenceSet

    nx.set_reference_set(punch, nx.RefsetEntirePart)
    try:
        punch_proto = nx.prototype(punch)

        for feat in punch_proto.Features.GetFeatures():
            if feat.FeatureType != "LINKED_BODY":
                continue

            if nx.is_link_broken(feat):
                continue

            xform = nx.ufsession_.Wave.AskLinkXform(feat.Tag)
            if xform == 0:
                continue  # not linked in assembly context (or broken)

            punch_root = nx.root_component(punch_proto)
            if punch_root is None:
                # The C# reads punch.__Prototype().__RootComponent().Tag here, which would NRE.
                raise RuntimeError("Object reference not set to an instance of an object.")

            proto_child_shcs_tag = nx.ufsession_.So.AskAssyCtxtPartOcc(xform, punch_root.Tag)
            if proto_child_shcs_tag == 0:
                continue

            # The link's source is a child as seen inside the punch's own part; map it to the same child as an
            # occurrence under the punch in the display part.
            proto_child_shcs = nx.tagged_object(proto_child_shcs_tag)
            shcs_inst = nx.ufsession_.Assem.AskInstOfPartOcc(proto_child_shcs.Tag)
            actual_shcs = cast(NXOpen.Assemblies.Component,
                               nx.tagged_object(nx.ufsession_.Assem.AskPartOccOfInst(punch.Tag, shcs_inst)))

            other_ref = actual_shcs.ReferenceSet

            # One link at a time, so a fastener that can't be reached doesn't cost the rest
            # (or FinishBlock999, which runs after this loop).
            try:
                nx.set_reference_set(actual_shcs, nx.RefsetEntirePart)

                source_feat = nx.tagged_object(nx.ufsession_.Wave.AskLinkSource(feat.Tag, True))
                occ_body = actual_shcs.FindOccurrence(source_feat)

                if not isinstance(occ_body, NXOpen.Body):
                    nx.print_("Block999: {} - no occurrence of {}'s source body under {}, not subtracted.".format(
                        punch.DisplayName, feat.GetFeatureName(), actual_shcs.DisplayName))
                    continue

                block_link = _link_body_into_work_part(occ_body)
                splitform._subtract_linked_body(nx.work_part(), block_target, block_link)
                nx.print_("Block999: subtracted {} ({} in {})".format(
                    actual_shcs.DisplayName, feat.GetFeatureName(), punch.DisplayName))
            except Exception as ex:
                nx.print_("Block999: {} - could not link {} ({})".format(
                    punch.DisplayName, actual_shcs.DisplayName, feat.GetFeatureName()))
                nx.print_exception(ex)
            finally:
                nx.set_reference_set(actual_shcs, other_ref)
    finally:
        nx.set_reference_set(punch, refset)


def _link_body_into_work_part(body: NXOpen.Body) -> NXOpen.Features.Feature:
    """Nine99Block.LinkBodyIntoWorkPart - wave-links exactly body (an occurrence in the display part) into the work part."""
    part = nx.work_part()
    builder = part.BaseFeatures.CreateWaveLinkBuilder(None)
    try:
        builder.Type = NXOpen.Features.WaveLinkBuilder.Types.BodyLink
        extract = builder.ExtractFaceBuilder
        extract.ParentPart = NXOpen.Features.ExtractFaceBuilder.ParentPartType.OtherPart
        extract.Associative = True
        extract.FeatureOption = NXOpen.Features.ExtractFaceBuilder.FeatureOptionType.OneFeatureForAllBodies
        extract.FixAtCurrentTimestamp = False
        extract.ExtractBodyCollector.ReplaceRules(
            [part.ScRuleFactory.CreateRuleBodyDumb([body], False)], False)
        return cast(NXOpen.Features.Feature, builder.Commit())
    finally:
        builder.Destroy()


def _finish_block999(new_component: NXOpen.Assemblies.Component, block_body: NXOpen.Body,
                     min_point: NXOpen.Point3d, max_point: NXOpen.Point3d) -> Set[int]:
    """
    Nine99Block.FinishBlock999 - the last stage, run in the block's own part: two 12mm TSG jig jacks on the
    top face pointing -Z on the block's 1" grid, CBORE_BLIND subtracted from block_body, the top face colored 42,
    then "XX" appended to the component name of every trim steel and every detail child of a trim steel, so they
    aren't ordered twice (returns those instances' tags, for _add_xx_to_occurrences). The part was re-based onto
    its block, so min_point/max_point are (0,0,0) and the block's size. Every child joins the part's BODY reference
    set, which is what the block now shows in its assemblies.
    """
    with nx.display_part_reset():
        nx.set_display_part(nx.prototype(new_component))
        nx.set_work_part(nx.display_part())

        # Taken before any fastener is added, so this is exactly the restructured trim steel.
        trim_steels = nx.children(nx.display_part())

        # Diagonal corners on the block's 1" grid (the part origin is the block's min corner): each inset corner
        # rounded inward to whole inches, so neither jack ends up closer to an edge than its inset. On the top
        # (yellow) face pointing -Z: the jack's origin is its puck face and CBORE_BLIND runs down its +Z from
        # there, so the puck sits flush with the top and the counterbore goes down into the block.
        def on_grid(x: float, y: float, x_up: bool, y_up: bool) -> NXOpen.Point3d:
            def snap(value: float, up: bool) -> float:
                value = round(value, 6)
                return float(math.ceil(value) if up else math.floor(value))
            return NXOpen.Point3d(min_point.X + snap(x - min_point.X, x_up), min_point.Y + snap(y - min_point.Y, y_up),
                                  max_point.Z)

        jack_first = on_grid(max_point.X - Block999JackInsetX, min_point.Y + Block999JackInsetY, False, True)
        jack_second = on_grid(min_point.X + Block999JackInsetX, max_point.Y - Block999JackInsetY, True, False)
        jack_orientation = drawdie._z_matrix(NXOpen.Vector3d(0.0, 0.0, -1.0))

        # One at a time, so a jack that fails to subtract doesn't cost the other.
        for origin in (jack_first, jack_second):
            try:
                component = nx.add_component(nx.display_part(), Block999JackPath, reference_set="BODY",
                                             origin=origin, orientation=jack_orientation, layer=99)
                _subtract_from_block999(component, block_body, "CBORE_BLIND")
            except Exception as ex:
                nx.print_("Block999: could not place {} (CBORE_BLIND)".format(
                    os.path.splitext(os.path.basename(Block999JackPath))[0]))
                nx.print_exception(ex)

        # The bottom was colored 42 when the block was built; the top (opposite it) gets 42 too. After the jack
        # subtracts, which cut into the top face - colored before them, it came out 129.
        top_face = nx.planar_face_with_normal_or_null(block_body, NXOpen.Vector3d(0.0, 0.0, 1.0))
        if top_face is not None:
            nx.set_color(top_face, 42)
        else:
            nx.print_("Block999: no +Z planar face on the DYNAMIC BLOCK body, top not colored.")

        # The trim steel and the jacks show in BODY.
        try:
            splitform._find_or_create_reference_set_quiet(nx.work_part(), "BODY").AddObjectsToReferenceSet(
                nx.children(nx.display_part()))
        except Exception as ex:
            nx.print_exception(ex)

        # The trim steels are now made from this block: no AutoSize, and DESCRIPTION says which detail.
        block_leaf = nx.display_part().Leaf
        description = "MAKE FROM DET# {}".format(block_leaf[block_leaf.rfind("-") + 1:])

        # The instances that get XX: each trim steel here, and each detail child of a trim steel (in its own part).
        renamed: Set[int] = set()

        for trim_steel in trim_steels:
            try:
                trim_part = nx.prototype(trim_steel)
                drawdie._switch_auto_size_off(trim_part)
                nx.set_attribute(trim_part, "DESCRIPTION", description)
                renamed.add(_add_xx(trim_steel))

                for child in trim_steel.GetChildren():
                    if nx.is_loaded(child) and _DetailLeaf.match(nx.prototype(child).Leaf):
                        renamed.add(_add_xx(nx.proto_child_comp(child)))
            except Exception as ex:
                nx.print_exception(ex)

        # Their occurrences here (the trim steels' detail children, as seen from the block) keep their own names.
        _add_xx_to_occurrences(nx.display_part(), renamed)

        return renamed


# A {job}-{op}-{detail} leaf.
_DetailLeaf = re.compile(r"^\d+-\d+-\d+$")


def _add_xx(component: NXOpen.Assemblies.Component) -> int:
    """Appends "XX" to component's name unless it already ends in XX; returns its tag."""
    if not component.Name.upper().endswith("XX"):
        name = component.Name + "XX"
        component.SetName(name)
        nx.print_("Block999: renamed {} to {}".format(component.DisplayName, name))

    return component.Tag


def _add_xx_to_occurrences(assembly: NXOpen.BasePart, renamed: Set[int]) -> None:
    """
    The instances in renamed got their XX in their own parts (_finish_block999), but each occurrence of them in
    assembly keeps its own name (the assembly navigator shows that one), so it gets the XX too.
    """
    root = nx.root_component(assembly)
    if root is None:
        return

    owners = set()
    for tag in renamed:
        owners.add(cast(NXOpen.Assemblies.Component, nx.tagged_object(tag)).OwningPart.Tag)

    for component in nx.descendants(root, include_root=False):
        try:
            # Only occurrences under a part that owns one of the instances, so most of the assembly costs no lookup.
            parent = component.Parent
            if parent is None or parent.Prototype is None or parent.Prototype.Tag not in owners:
                continue
            if component.Name.upper().endswith("XX") or nx.proto_child_comp(component).Tag not in renamed:
                continue

            component.SetName(component.Name + "XX")
        except Exception as ex:
            nx.print_exception(ex)


def _subtract_from_block999(component: NXOpen.Assemblies.Component, block_body: NXOpen.Body, refset: str) -> None:
    """
    Nine99Block.SubtractFromBlock999 - switches component to refset, links it into the work part and subtracts it
    from block_body, then puts it back on BODY.
    """
    if not nx.has_reference_set(nx.prototype(component), refset):
        nx.print_("Block999: {} has no {} reference set, not subtracted.".format(component.DisplayName, refset))
        return

    nx.set_reference_set(component, refset)

    try:
        splitform._subtract_linked_body(nx.work_part(), block_body, nx.create_linked_body(component))
    finally:
        nx.set_reference_set(component, "BODY")


def _try_next_block999_path() -> Optional[str]:
    """
    Nine99Block.TryNextBlock999Path - the first free {job}-{op}-NNN.prt in the display part's op folder,
    counting down from 998, or None when every number is taken. The job and op come from that folder's name,
    not from the display part's own name. A number is taken when the file exists in that folder or a part
    with that leaf is already loaded.
    """
    folder = os.path.dirname(nx.display_part().FullPath)
    match = None

    # The display part may sit below the op folder, so walk up until a {job}-{op} folder turns up.
    directory = folder
    while directory:
        match = re.match(r"^(?P<job>\d+)-(?P<op>\d+)$", os.path.basename(directory))
        if match:
            folder = directory
            break
        parent = os.path.dirname(directory)
        if parent == directory:
            break
        directory = parent

    if match is None:
        raise RuntimeError("No {{job}}-{{op}} op folder above {}, so there is no op number to name the block from."
                           .format(nx.display_part().FullPath))

    prefix = "{}-{}-".format(match.group("job"), match.group("op"))
    loaded = [part.Leaf.lower() for part in nx.session_.Parts]

    for number in range(Block999FirstNumber, 0, -1):
        leaf = "{}{:03d}".format(prefix, number)
        candidate = os.path.join(folder, leaf + ".prt")

        if os.path.exists(candidate) or leaf.lower() in loaded:
            continue

        return candidate

    return None


def _block999_material(first: NXOpen.Assemblies.Component) -> str:
    """
    Nine99Block.Block999Material - MATERIAL for the block: the first picked component's part's MATERIAL attribute,
    else the component's own, else "FILL IN" (printed), as the Merlin blocks are stamped when there is nothing to copy.
    """
    proto = nx.prototype(first)

    if nx.has_attribute(proto, "MATERIAL") and nx.get_attribute(proto, "MATERIAL").strip():
        return nx.get_attribute(proto, "MATERIAL")

    if nx.has_attribute(first, "MATERIAL") and nx.get_attribute(first, "MATERIAL").strip():
        return nx.get_attribute(first, "MATERIAL")

    nx.print_("Block999: {} has no MATERIAL, so the block's MATERIAL is FILL IN.".format(first.DisplayName))
    return "FILL IN"


def _set_up_as_merlin_block(new_component: NXOpen.Assemblies.Component, starting_display: NXOpen.Part,
                            description: str, material: str) -> None:
    """
    Nine99Block.SetUpAsMerlinBlock - sets the freshly promoted block up the way Merlin sets up its blocks
    (BuildPointComponent): CSPC / GM Tool Number placeholders, the part re-based onto its block, station
    expressions, BODY, the DYNAMIC BLOCK name, DESCRIPTION / MATERIAL / DETAIL NAME (Make from Det NNN, the block's
    own detail number), a SUBTOOL on hidden layer 15, the AutoSize UDO, then BODY used - and added to BODY - in
    every assembly above it. Leaves starting_display displayed.
    """
    proto = nx.prototype(new_component)
    nx.set_attribute(proto, "CSPC", "X")
    nx.set_attribute(proto, "GM Tool Number", "X")

    # Leaves the new part displayed and as the work part.
    merlin._rebase_block_to_part_origin(new_component, cast(NXOpen.Part, new_component.OwningPart))
    nx.find_or_create_reference_set(new_component.OwningPart, "BODY").AddObjectsToReferenceSet([new_component])

    new_part = nx.work_part()
    nx.setup_station_expressions(new_part)
    splitform._find_or_create_reference_set_quiet(new_part, "BODY").AddObjectsToReferenceSet(list(new_part.Bodies))
    first_block = nx.first_block_feature(new_part)
    if first_block is None:
        raise RuntimeError("Sequence contains no elements")
    first_block.SetName("DYNAMIC BLOCK")
    nx.set_attribute(new_part, "DESCRIPTION", description)
    nx.set_attribute(new_part, "MATERIAL", material)
    # The block's own detail number: the NNN of its {job}-{op}-NNN leaf (998, 997, ...).
    detail_number = proto.Leaf[proto.Leaf.rfind("-") + 1:]
    nx.set_attribute(new_part, "DETAIL NAME", "Make from Det {}".format(detail_number))

    # After BODY is filled, so the subtool stays out of it.
    new_part.Layers.WorkLayer = 15
    merlin._create_subtool(new_part)
    new_part.Layers.WorkLayer = 1
    new_part.Layers.SetState(15, NXOpen.Layer.State.Hidden)
    nx.create_auto_size_udo(new_part)

    nx.set_display_part(starting_display)
    occurrence = nx.first_occurrence_in(new_part, nx.display_part())
    nx.set_reference_set(occurrence, "BODY")
    merlin._set_reference_set_in_ancestor_assemblies(occurrence, add_to_reference_set=True)


def _promote_to_named_component(block: NXOpen.Features.Block, path: str) -> NXOpen.Assemblies.Component:
    """Nine99Block.PromoteToNamedComponent - promotes block's body into a new part saved at path, deleting the original."""
    nx.print_(path)
    part = nx.work_part()
    builder = part.AssemblyManager.CreateNewComponentBuilder()
    try:
        file_new = nx.session_.Parts.FileNew()
        file_new.Units = (NXOpen.Part.Units.Millimeters if part.PartUnits == NXOpen.BasePart.Units.Millimeters
                          else NXOpen.Part.Units.Inches)
        file_new.NewFileName = path
        file_new.UseBlankTemplate = True
        builder.NewComponentName = os.path.splitext(os.path.basename(path))[0]
        builder.ReferenceSet = NXOpen.Assemblies.CreateNewComponentBuilder.ComponentReferenceSetType.EntirePartOnly
        builder.ComponentOrigin = NXOpen.Assemblies.CreateNewComponentBuilder.ComponentOriginType.Absolute
        builder.LayerOption = NXOpen.Assemblies.CreateNewComponentBuilder.ComponentLayerOptionType.Original
        builder.OriginalObjectsDeleted = True
        for body in block.GetBodies():
            builder.ObjectForNewComponent.Add(body)
        builder.NewFile = file_new

        try:
            builder.Commit()
        except NXOpen.NXException as ex:
            _print_block999_commit_diagnostics(path, ex)
            raise

        return cast(NXOpen.Assemblies.Component, builder.GetObject())
    finally:
        builder.Destroy()


def _print_block999_commit_diagnostics(path: str, ex: NXOpen.NXException) -> None:
    """
    Nine99Block.PrintBlock999CommitDiagnostics - everything that could make NX think path is taken: the file
    on disk, a loaded part by full path or leaf, and a component already carrying that name in the display part.
    """
    leaf = os.path.splitext(os.path.basename(path))[0]
    nx.print_("Block999: CreateNewComponentBuilder.Commit failed - NX {}: {}".format(ex.ErrorCode, ex))
    nx.print_("  path            : {}".format(path))
    nx.print_("  File.Exists     : {}".format(os.path.exists(path)))
    nx.print_("  folder exists   : {}".format(os.path.isdir(os.path.dirname(path))))
    nx.print_("  display part    : {}".format(nx.display_part().FullPath))
    nx.print_("  work part       : {}".format(nx.work_part().FullPath))

    for part in nx.session_.Parts:
        if part.Leaf.lower() == leaf.lower() or part.FullPath.lower() == path.lower():
            nx.print_("  loaded part     : {} (leaf {})".format(part.FullPath, part.Leaf))

    root = nx.display_part().ComponentAssembly.RootComponent
    for component in (nx.descendants(root) if root is not None else []):
        if component.Name.lower() == leaf.lower() or component.DisplayName.lower() == leaf.lower():
            nx.print_("  component       : name {}, display {}".format(component.Name, component.DisplayName))


def main() -> None:
    """The nine-99-block UFunc - its menu button runs this file. An escaping exception is printed."""
    import usage_db

    with usage_db.run("nine-99-block"):
        try:
            # No confirm: it starts with the component pick, which the user can cancel.
            Nine99Block.execute()
        except Exception as ex:
            nx.print_exception(ex)


if __name__ == "__main__":
    main()

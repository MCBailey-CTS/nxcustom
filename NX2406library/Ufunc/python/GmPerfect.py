"""
Python port of the gm-perfect UFunc (Merlin.StaticPerfect / Merlin.BuildPerfect, src\\UFuncs\\Merlin.cs, region
"Standalone Builders - Boss, Perfect & Backing Plate").
The C# wrapper was deleted 2026-10-22 (in git at 1cb53d8): the UFunc's menu button runs this file's main().

Select solid bodies (any in assembly). Each one, in its own try/except (printed, so one bad body does not drop the
rest), is wrapped in a block the size of its exact absolute bounding box, built in the work part at the absolute
orientation, and the block is promoted to {gm|cts}-perfect-{token}.prt in the work part's folder (Absolute origin,
AsSpecified layer 60, originals deleted, no AutoSize UDO at promotion). Then:
  - the part is re-based onto the block (RebaseBlockToPartOrigin, parent = the display part);
  - the new component joins its owning part's BODY reference set; the part's bodies go in its own BODY;
  - its first block is named DYNAMIC BLOCK and it gets an AutoSize UDO after all (as the C# does);
  - MATERIAL / DETAIL NAME = FILL IN, a SUBTOOL on layer 15 (hidden);
  - back on the display part, the occurrence is unblanked, set to BODY, and BODY is set as its used reference set in
    every loaded ancestor assembly.
The starting display and work parts are restored after every body.

Two ways in:
  - File -> Execute -> NX Open on this file runs main() with is_gm = True, as the gm-perfect UFunc does.
  - Session.Execute("GmPerfect.py", "GmPerfect", "execute", is_gm) from C#, or build_perfect(is_gm, bodies) with the
    picked bodies (the caller brings the units gate, as BuildPerfect's does).

Differences from the C#:
  - The bounding box is nx.body_box. The C# makes five NXOpen.Points in the display part off an OrientedBox in the
    absolute csys, takes their min/max and deletes them - the same box (offset is 0), without the temporary points.
  - The pick is the NXOpen SelectionManager with SNAP's solid-body mask (70, 0, 36) instead of Snap.UI.Selection;
    an OK with nothing picked counts as a cancel, as in the C#.
  - GFolder.create_or_null (print-only, result unused) is not ported.
  - The AutoSize UDO class can only be registered from C# (see tsg_nx.create_auto_size_udo). Run standalone in a
    session where TSG_Library never registered it, the part gets no UDO - that prints and carries on.
  - The re-base is DrawDie._rebase_block_to_part_origin (block size read through UF_MODL_ask_block_parms, since
    BlockFeatureBuilder.Length/Width/Height come back None in Python).

The Merlin helpers DrawDie.py and PointComponent.py already port are imported rather than copied.
"""

from __future__ import annotations

import os
import sys
from typing import List, Optional, Sequence, cast

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
import NXOpen.GeometricUtilities  # noqa: E402
import NXOpen.Layer  # noqa: E402
import NXOpen.UF  # noqa: E402

import tsg_nx as nx  # noqa: E402
import PointComponent as merlin  # noqa: E402
import DrawDie as drawdie  # noqa: E402

# The layer the promoted block lands on.
PerfectLayer = 60

# Snap MaskTriple.BuildFromTypeCombo(Body, BodySolid) - SolidBodySubtype 36 (UF_UI_SEL_FEATURE_SOLID_BODY).
_UF_UI_SEL_FEATURE_SOLID_BODY = 36


class GmPerfect(object):

    @staticmethod
    def execute(is_gm: bool = True) -> None:
        """Merlin.StaticPerfect(is_gm) - the gm-perfect UFunc passes is_gm = True."""
        static_perfect(is_gm)


def static_perfect(is_gm: bool) -> None:
    """Merlin.StaticPerfect - units gate, undo mark, solid-body pick, then build_perfect."""
    ok, message = drawdie._check_info_units()
    if not ok:
        nx.show_error(message)
        return

    nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, "Start UFunc")
    version = nx.assembly_file_version()
    bodies = _select_solid_bodies("Select solid bodies for Perfect: {}".format(version),
                                  "Perfect: {}".format(version))
    if bodies is None:
        return

    build_perfect(is_gm, bodies)


def build_perfect(is_gm: bool, bodies: Sequence[NXOpen.Body]) -> None:
    """
    Merlin.BuildPerfect - a bounding-box block component per body, on bodies the caller already has. The caller
    brings the units gate.
    """
    offset = 0.0
    # (GFolder.create_or_null(disp) - print-only, result unused. Not ported.)
    starting_display = nx.display_part()
    starting_work = nx.work_part()

    for body in bodies:
        try:
            _build_one_perfect(is_gm, body, offset)
        except Exception as ex:
            nx.print_exception(ex)
        finally:
            # CreateCtsComponent leaves the new detail as the display/work part. Restore the parts we started on so
            # every body builds from the same state.
            nx.set_display_part(starting_display)
            nx.set_work_part(starting_work)


def _build_one_perfect(is_gm: bool, body: NXOpen.Body, offset: float) -> None:
    """The body of BuildPerfect's per-body loop."""
    box = nx.body_box(body)
    origin = NXOpen.Point3d(box.MinX - offset, box.MinY - offset, box.MinZ)
    opposite_corner = NXOpen.Point3d(box.MaxX + offset, box.MaxY + offset, box.MaxZ)

    length = opposite_corner.X - origin.X
    width = opposite_corner.Y - origin.Y
    height = opposite_corner.Z - origin.Z
    block = _create_block(origin, nx.identity_matrix(),
                          "{}in".format(nx.cs_double_str(length)),
                          "{}in".format(nx.cs_double_str(width)),
                          "{}in".format(nx.cs_double_str(height)))
    current_display = nx.display_part()
    base_new = _create_new_component_core(
        "gm-perfect" if is_gm else "cts-perfect",
        [block.GetBodies()[0]],
        NXOpen.Assemblies.CreateNewComponentBuilder.ComponentOriginType.Absolute,
        NXOpen.Assemblies.CreateNewComponentBuilder.ComponentLayerOptionType.AsSpecified,
        layer_number=PerfectLayer,
        original_objects_deleted=True,
        auto_size_udo=False,
        directory=os.path.dirname(nx.work_part().FullPath))
    # Origin on the block rather than the assembly's. Nothing below places geometry from assembly coordinates.
    drawdie._rebase_block_to_part_origin(base_new, current_display)
    nx.setup_station_expressions(nx.prototype(base_new))
    nx.find_or_create_reference_set(base_new.OwningPart, "BODY").AddObjectsToReferenceSet([base_new])
    refset = nx.find_or_create_reference_set(nx.work_part(), "BODY")
    refset.AddObjectsToReferenceSet(list(nx.work_part().Bodies))
    new_part = nx.work_part()
    first_block = nx.first_block_feature(new_part)
    if first_block is None:
        raise RuntimeError("Sequence contains no elements")
    first_block.SetName("DYNAMIC BLOCK")
    nx.create_auto_size_udo(nx.work_part())
    # Stamp the detail attributes as "FILL IN" for the designer to complete.
    nx.set_attribute(new_part, "MATERIAL", "FILL IN")
    nx.set_attribute(new_part, "DETAIL NAME", "FILL IN")
    # Extract a subtool onto layer 15 (after BODY is populated so it is not added to BODY).
    new_part.Layers.WorkLayer = 15
    merlin._create_subtool(new_part)
    new_part.Layers.WorkLayer = 1
    new_part.Layers.SetState(15, NXOpen.Layer.State.Hidden)
    nx.set_display_part(current_display)
    new_comp = nx.first_occurrence_in(new_part, nx.display_part())
    new_comp.Unblank()
    # The new component defaults to the ENTIRE PART reference set; force BODY in this context and in every ancestor
    # assembly (station .. -000) so it shows the body everywhere.
    nx.set_reference_set(new_comp, "BODY")
    merlin._set_reference_set_in_ancestor_assemblies(new_comp)


# ---------------------------------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------------------------------

def _select_solid_bodies(cue: str, title: str) -> Optional[List[NXOpen.Body]]:
    """
    Selection.select_solid_bodies(cue, title) - many solid bodies, any in assembly, not kept highlighted. None on
    anything but an OK with at least one body.
    """
    mask = NXOpen.Selection.MaskTriple(NXOpen.UF.UFConstants.UF_solid_type, 0, _UF_UI_SEL_FEATURE_SOLID_BODY)
    response, objects = NXOpen.UI.GetUI().SelectionManager.SelectTaggedObjects(
        cue,
        title,
        NXOpen.Selection.SelectionScope.AnyInAssembly,
        NXOpen.Selection.SelectionAction.ClearAndEnableSpecific,
        False,
        False,
        [mask])
    if response != NXOpen.Selection.Response.Ok:
        return None
    bodies = [obj for obj in objects if isinstance(obj, NXOpen.Body)]
    if len(bodies) == 0:
        return None
    return bodies


def _create_block(origin: NXOpen.Point3d, orientation: NXOpen.Matrix3x3, xlength: str, ylength: str,
                  zlength: str) -> NXOpen.Features.Block:
    """
    BasePart.__CreateBlock(Point3d, Matrix3x3, string, string, string) - an origin-and-edge-lengths block in the work
    part, lengths as expression strings. The block takes its orientation from the display part's WCS, so the WCS is
    turned to orientation (origin kept) for the build and put back before the commit, as the C# does.
    """
    wcs = nx.display_part().WCS
    original = wcs.CoordinateSystem.Orientation.Element
    wcs.SetOriginAndMatrix(wcs.Origin, orientation)
    builder = nx.work_part().Features.CreateBlockFeatureBuilder(None)
    try:
        builder.Type = NXOpen.Features.BlockFeatureBuilder.Types.OriginAndEdgeLengths
        builder.BooleanOption.Type = NXOpen.GeometricUtilities.BooleanOperation.BooleanType.Create
        builder.SetOriginAndLengths(origin, xlength, ylength, zlength)
        wcs.SetOriginAndMatrix(wcs.Origin, original)
        return cast(NXOpen.Features.Block, builder.Commit())
    finally:
        builder.Destroy()


def _create_new_component_core(name_prefix: str, objects: Sequence[NXOpen.DisplayableObject],
                               origin: NXOpen.Assemblies.CreateNewComponentBuilder.ComponentOriginType,
                               layer_option: NXOpen.Assemblies.CreateNewComponentBuilder.ComponentLayerOptionType,
                               layer_number: int, original_objects_deleted: bool, auto_size_udo: bool,
                               directory: str) -> NXOpen.Assemblies.Component:
    """
    Merlin.CreateNewComponentCore with its dir argument - DrawDie._create_new_component_core always writes next to
    the display part, and BuildPerfect passes the work part's folder.
    """
    work = nx.work_part()
    builder = work.AssemblyManager.CreateNewComponentBuilder()
    try:
        file_new = nx.session_.Parts.FileNew()
        file_new.Units = (NXOpen.Part.Units.Millimeters if work.PartUnits == NXOpen.BasePart.Units.Millimeters
                          else NXOpen.Part.Units.Inches)
        file_new.NewFileName = "{}\\{}-{}.prt".format(directory, name_prefix, merlin._random_file_token())
        file_new.UseBlankTemplate = True
        builder.ReferenceSet = NXOpen.Assemblies.CreateNewComponentBuilder.ComponentReferenceSetType.Other
        builder.LayerOption = layer_option
        builder.NewComponentName = os.path.splitext(os.path.basename(file_new.NewFileName))[0]
        builder.LayerNumber = layer_number
        builder.ComponentOrigin = origin
        builder.OriginalObjectsDeleted = original_objects_deleted
        for obj in objects:
            builder.ObjectForNewComponent.Add(obj)
        builder.NewFile = file_new
        builder.Commit()
        new_component = cast(NXOpen.Assemblies.Component, builder.GetObject())
        # Every component Merlin makes gets these placeholder GM job attributes on its prototype part.
        new_prototype = nx.prototype(new_component)
        nx.set_attribute(new_prototype, "CSPC", "X")
        nx.set_attribute(new_prototype, "GM Tool Number", "X")
        if auto_size_udo:
            nx.create_auto_size_udo(nx.work_part())
        return new_component
    finally:
        builder.Destroy()


def main() -> None:
    """The gm-perfect UFunc - its menu button runs this file. An escaping exception is printed."""
    import usage_db
    from tsg_dialog import ask_is_gm

    with usage_db.run("gm-perfect"):
        try:
            # The Customer dialog stands in for the "Are you sure" box: GM builds with the GM parts, TSG throws.
            is_gm = ask_is_gm("Perfect")
            if is_gm is not None:
                GmPerfect.execute(is_gm)
        except Exception as ex:
            nx.print_exception(ex)


if __name__ == "__main__":
    main()

"""
Python port of the gm-component UFunc (Merlin.StaticGmComponent / Merlin.BuildGmComponent -> Merlin.CreateComponent,
src\\UFuncs\\Merlin.cs, regions "Static Entry Points - GM Component / Split / Form Pad" and "Builders - Form Pad,
Component & Split").
The C# wrapper was deleted 2026-10-22 (in git at 1cb53d8): the UFunc's menu button runs this file's main().

Run from an upper or lower station (uad/upd/ush/usp or lad/lsh/lsp as the work part). Select solid bodies; their box,
+.375" on every side (each span rounded up to 1/8"), becomes one 8" block from Z -4 in the station, colored 107 with
its mounting face (+Z upper / -Z lower) colored 42. It is promoted to {gm|cts}-component, re-based onto the block (the
opposite corner for an upper), and gets:
  - station expressions, BODY, DYNAMIC BLOCK, DESCRIPTION (box X x Y x the bodies' height), MATERIAL / DETAIL NAME
    FILL IN, a SUBTOOL on layer 15 (hidden);
  - 4 12mm-shcs-050-2x .75" in from the corners (CBORE), linked and subtracted, the bottom face 42;
  - 2 12mm-dwl-050 .625" in from each X end on the Y centreline, CBORE subtracted from the dynamic block;
  - 4 keys around the edges (Merlin.PlaceEdgeItems, .0748 nudge on GM and CTS alike, as the C# passes), the first
    one's prototype Save As'd as {gm|cts}-component-key-{token}.prt;
  - the AutoSize UDO, BODY in the station, then the UPR-3D / LWR-3D reference set of each picked body's component
    linked and subtracted, and BODY in every loaded ancestor assembly.
The run is timed (the elapsed TimeSpan is printed) and the display part is regenerated on the new detail before the
session goes back to the starting display / work parts.

Merlin.CreateComponent itself stays in C#: PostTrimForm (src\\Static\\PostTrimForm.cs) calls it too.

Two ways in:
  - File -> Execute -> NX Open on this file runs main() with is_gm = True, as the gm-component UFunc does.
  - Session.Execute("GmComponent.py", "GmComponent", "execute", is_gm) from C#.

Differences from the C#: those listed in GmSplitForm.py (body pick, ComputeBlockDimensions without temporary points,
a body with no component, GFolder.create_or_null not ported, the AutoSize UDO class). The solid-only pick drops
sheet bodies after the pick rather than refusing them in the dialog.

The shared split / component helpers are imported from GmSplitForm.py, and the Merlin helpers DrawDie.py,
PointComponent.py and GmCastTrimPad.py already port from them.
"""

from __future__ import annotations

import datetime
import os
import sys
from typing import List, Sequence, cast

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
import NXOpen.Layer  # noqa: E402

import tsg_nx as nx  # noqa: E402
import PointComponent as merlin  # noqa: E402
import DrawDie as drawdie  # noqa: E402
import GmSplitForm as split  # noqa: E402

# ---------------------------------------------------------------------------------------------------
# Constants (Merlin's, inches unless the name says otherwise)
# ---------------------------------------------------------------------------------------------------

ComponentHeight = 8
ComponentColor = 107
ComponentShcsInset = .750
ComponentDowelInset = .625

_shcs12mm050Path = "G:\\0Library\\Fasteners\\Metric\\SocketHeadCapScrews-2X\\012-2x\\12mm-shcs-050-2x.prt"


class GmComponent(object):

    @staticmethod
    def execute(is_gm: bool = True) -> None:
        """Merlin.StaticGmComponent(is_gm) - the gm-component UFunc passes is_gm = True."""
        static_gm_component(is_gm)


def static_gm_component(is_gm: bool) -> None:
    """Merlin.StaticGmComponent - TryBeginGmEntry (solid bodies only), then the build."""
    entry = split._try_begin_gm_entry("Gm Component", solid_only=True)
    if entry is None:
        return
    is_upper, bodies, reference_set = entry

    build_gm_component(is_gm, is_upper, bodies, reference_set)


def build_gm_component(is_gm: bool, is_upper: bool, bodies: Sequence[NXOpen.Body], reference_set: str) -> None:
    """
    Merlin.BuildGmComponent - one GM component over bodies, subtracting reference_set. Builds into the work part's
    station, as the entry point does.
    """
    top_level = nx.display_part()
    starting_work = nx.work_part()
    nx.set_display_part(nx.work_part())

    with nx.suppress_display():
        start = datetime.datetime.now()
        try:
            _create_component(is_upper, top_level, starting_work, list(bodies), [reference_set], is_gm)
        finally:
            # Session.__UsingTimer prints the elapsed TimeSpan (disposed before the display is unsuppressed).
            nx.print_(drawdie._time_span(datetime.datetime.now() - start))


def _create_component(is_upper: bool, top_level: NXOpen.Part, start_work: NXOpen.Part,
                      selected_bodies: List[NXOpen.Body], reference_sets: Sequence[str], is_gm: bool) -> None:
    """Merlin.CreateComponent"""
    try:
        if len(selected_bodies) == 0:
            nx.print_("No bodies selected")
            return

        nx.display_part().Layers.WorkLayer = 1
        xlength, ywidth, height, block_origin = split._compute_block_dimensions(selected_bodies, split.SplitFormOffset)

        block = split._create_block(block_origin, nx.identity_matrix(), xlength, ywidth, ComponentHeight)

        face = split._first_planar_face(block.GetBodies()[0], split._VectorZ if is_upper else split._VectorZN)
        nx.set_color(block.GetBodies()[0], ComponentColor)
        nx.set_color(face, 42)
        new_component = merlin._create_cts_component(block, "gm-component" if is_gm else "cts-component")

        # Origin on the block's corner rather than the assembly's. Before the subtool below, so the extract is taken
        # at the final position. The block is built at the absolute orientation, so this is a pure translation.
        drawdie._rebase_block_to_part_origin(new_component, cast(NXOpen.Part, new_component.OwningPart),
                                             opposite_corner=is_upper)

        # Everything placed below sits inside the new part. The fasteners and dowels measure from `box`, re-read off
        # the body further down; the keys are the one thing that still measured from the assembly-space corner, so
        # point it at the part origin.
        block_origin = NXOpen.Point3d(0.0, 0.0, 0.0)

        new_part = cast(NXOpen.Part, nx.prototype(new_component))
        nx.setup_station_expressions(nx.work_part())
        refset = split._find_or_create_reference_set_quiet(nx.display_part(), "BODY")
        refset.AddObjectsToReferenceSet(list(nx.display_part().Bodies))
        new_part_display = nx.display_part()
        split._first_block_feature(new_part_display).SetName("DYNAMIC BLOCK")
        nx.set_attribute(new_part_display, "DESCRIPTION", split._description(xlength, ywidth, height))
        nx.set_attribute(new_part_display, "MATERIAL", "FILL IN")
        nx.set_attribute(new_part_display, "DETAIL NAME", "FILL IN")
        new_part_display.Layers.WorkLayer = 15
        merlin._create_subtool(new_part_display)
        new_part_display.Layers.WorkLayer = 1
        new_part_display.Layers.SetState(15, NXOpen.Layer.State.Hidden)

        bottom_face = split._find_bottom_face()

        box = nx.body_box(nx.dynamic_block(nx.display_part()).GetBodies()[0])
        body_reference_set = split._find_reference_set(nx.display_part(), "BODY")

        fastener_orientation = drawdie._z_matrix(split._VectorZN if is_upper else split._VectorZ)

        fastener_z = box.MaxZ if is_upper else box.MinZ
        inset = ComponentShcsInset
        fastener_origins = [
            split._add(NXOpen.Point3d(box.MinX, box.MinY, fastener_z), inset, inset, 0),
            split._add(NXOpen.Point3d(box.MaxX, box.MinY, fastener_z), -inset, inset, 0),
            split._add(NXOpen.Point3d(box.MaxX, box.MaxY, fastener_z), -inset, -inset, 0),
            split._add(NXOpen.Point3d(box.MinX, box.MaxY, fastener_z), inset, -inset, 0),
        ]

        fasteners = [nx.add_component(nx.display_part(), _shcs12mm050Path, reference_set="CBORE", origin=o,
                                      orientation=fastener_orientation, layer=99)
                     for o in fastener_origins]

        split._subtract_and_refset_fasteners(fasteners, bottom_face, body_reference_set)

        center_y = (box.MinY + box.MaxY) / 2
        dwl_orientation = fastener_orientation
        for dwl_origin in (NXOpen.Point3d(box.MinX + ComponentDowelInset, center_y, fastener_z),
                           NXOpen.Point3d(box.MaxX - ComponentDowelInset, center_y, fastener_z)):
            dwl = nx.add_component(nx.display_part(), split._dwl12mm050Path, reference_set="BODY", origin=dwl_origin,
                                   orientation=dwl_orientation, layer=99)
            drawdie._subtract_refset_from_dynamic_block(nx.display_part(), dwl, "CBORE")

            if nx.has_reference_set(nx.prototype(dwl), "CBORE"):
                drawdie._stamp_fastener_subtract(dwl, "CBORE")

            split._find_reference_set(dwl.OwningPart, "BODY").AddObjectsToReferenceSet([dwl])

        current_wcs = nx.display_part().WCS.CoordinateSystem.Orientation.Element
        path = split._gmKeyPath if is_gm else split._ctsSmartKeyMetric
        keys = drawdie._place_edge_items(path, block_origin, xlength, ywidth, is_upper,
                                         front_back_nudge=.0748, x_edge_inset=2.4498, layer=99)

        nx.prototype(keys[0]).SaveAs("{}\\{}-component-key-{}.prt".format(
            os.path.dirname(nx.display_part().FullPath), "gm" if is_gm else "cts", merlin._random_file_token()))
        nx.display_part().WCS.SetOriginAndMatrix(NXOpen.Point3d(0.0, 0.0, 0.0), current_wcs)
        body_reference_set.AddObjectsToReferenceSet(keys)
        nx.create_auto_size_udo(nx.work_part())
        nx.set_display_part(top_level)
        nx.set_reference_set(new_component, "BODY")
        nx.find_or_create_reference_set(new_component.OwningPart, "BODY").AddObjectsToReferenceSet([new_component])
        nx.set_work_part(new_part)
        nx.work_part().Layers.WorkLayer = 1
        selected_components = split._owning_components(selected_bodies)
        for item in reference_sets:
            try:
                reference_set, _ = split._parse_boolean_operation(item)
                split._subtract_components(lambda: nx.dynamic_block(nx.work_part()).GetBodies()[0],
                                           selected_components, reference_set)
            except Exception as ex:
                nx.print_exception(ex)
        nx.set_reference_set(new_component, "BODY")
        # Also set BODY as the used reference set in every ancestor assembly (start_work .. -000), not just the
        # start_work context, so each sub-assembly shows the detail when opened standalone.
        merlin._set_reference_set_in_ancestor_assemblies(nx.first_occurrence_in(new_part, top_level))
        new_component.Unblank()
        # Display the new detail only so RegenerateDisplay refreshes it; the finally puts the session back.
        nx.set_display_part(nx.prototype(new_component))
        nx.ufsession_.Disp.RegenerateDisplay()
    except Exception as ex:
        nx.print_exception(ex)
    finally:
        nx.set_display_part(top_level)
        nx.set_work_part(start_work)


def main() -> None:
    """The gm-component UFunc - its menu button runs this file. An escaping exception is printed."""
    import usage_db
    from tsg_dialog import ask_is_gm

    with usage_db.run("gm-component"):
        try:
            # The Customer dialog stands in for the "Are you sure" box: GM builds with the GM parts, TSG throws.
            is_gm = ask_is_gm("Component")
            if is_gm is not None:
                GmComponent.execute(is_gm)
        except Exception as ex:
            nx.print_exception(ex)


if __name__ == "__main__":
    main()

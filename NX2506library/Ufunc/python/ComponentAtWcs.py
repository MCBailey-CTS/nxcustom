"""
Python port of the component-at-wcs UFunc (Merlin.ComponentAtWcs, src\\UFuncs\\Merlin.cs, region
"Standalone Builders - Boss, Perfect & Backing Plate").
The C# wrapper was deleted 2026-10-22 (in git at 1cb53d8): the UFunc's menu button runs this file's main().

No picks. Writes "Component At Wcs -> {version}" to the NX log file, gates on english info units, sets an undo mark,
then builds a 4" x 4" x 1.5" block in the work part at the display part's WCS orientation, centred on the WCS origin in
X and Y (bottom face on the WCS XY plane). The body is colored 168 with its WCS -Z face 42 (a missing face prints and
carries on), and it is promoted to component-wcs-{token}.prt (CreateCtsComponent defaults: WCS origin, work layer 1,
originals deleted, AutoSize UDO). Then:
  - the part is re-based onto the block's corner (RebaseBlockToPartOrigin, parent = the starting display part);
  - the new component joins its owning part's BODY reference set; station expressions; the part's bodies in BODY;
  - first block DYNAMIC BLOCK; DESCRIPTION "4 X 4 X 1.5", MATERIAL / DETAIL NAME FILL IN;
  - SUBTOOL on layer 15 (hidden), AutoSize UDO;
  - back on the starting display part the occurrence is unblanked, set to BODY, and BODY is set as its used reference
    set in every loaded ancestor assembly.
Any failure prints; the starting display and work parts are restored in a finally.

Two ways in:
  - File -> Execute -> NX Open on this file runs main().
  - Session.Execute("ComponentAtWcs.py", "ComponentAtWcs", "execute") from C#. execute takes an optional is_gm and
    IGNORES it, so a wrapper can call it like the other Merlin ports (execute(true)) - the C# ComponentAtWcs() has no
    is_gm and the part name is always component-wcs.

Differences from the C#:
  - GFolder.create_or_null (print-only, result unused) is not ported.
  - Session.LogFile is not in python\\stubs; it is reached through Any.
  - The AutoSize UDO class can only be registered from C# (see tsg_nx.create_auto_size_udo). Run standalone in a
    session where TSG_Library never registered it, the part gets no UDO - that prints and carries on.
  - The re-base is DrawDie._rebase_block_to_part_origin (block size read through UF_MODL_ask_block_parms, since
    BlockFeatureBuilder.Length/Width/Height come back None in Python).

The Merlin helpers PointComponent.py, DrawDie.py and Perfect.py already port are imported rather than copied.
"""

from __future__ import annotations

import os
import sys
from typing import Any, cast

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
import Perfect as perfect  # noqa: E402

# Merlin.BlockAtWcsLength / Width / Height / Color.
BlockAtWcsLength = 4.0
BlockAtWcsWidth = 4.0
BlockAtWcsHeight = 1.5
BlockAtWcsColor = merlin.BlockAtWcsColor

ComponentAtWcsName = "component-wcs"


class ComponentAtWcs(object):

    @staticmethod
    def execute(is_gm: bool = True) -> None:
        """Merlin.ComponentAtWcs() - is_gm is accepted for a uniform Session.Execute call and ignored."""
        component_at_wcs()


def component_at_wcs() -> None:
    """Merlin.ComponentAtWcs - a 4 x 4 x 1.5 block centred on the WCS, promoted to component-wcs-{token}."""
    cast(Any, nx.session_).LogFile.WriteLine("Component At Wcs -> {}".format(nx.assembly_file_version()))

    ok, message = drawdie._check_info_units()
    if not ok:
        nx.show_error(message)
        return

    nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, "Start UFunc")
    starting_display = nx.display_part()
    starting_work = nx.work_part()

    try:
        # (GFolder.create_or_null(disp) - print-only, result unused. Not ported.)
        wcs = nx.display_part().WCS.CoordinateSystem
        wcs_matrix = wcs.Orientation.Element
        # __CreateBlock takes the block's corner and builds in +X/+Y/+Z, so back the corner off half the length in X
        # and half the width in Y (along the WCS axes) to leave the WCS at the centre of the block's bottom face.
        block_origin = nx.add_along(nx.add_along(wcs.Origin, nx.axis_x(wcs_matrix), -BlockAtWcsLength / 2),
                                    nx.axis_y(wcs_matrix), -BlockAtWcsWidth / 2)
        nx.work_part().Layers.WorkLayer = 1
        block = perfect._create_block(block_origin, wcs_matrix,
                                      "{}in".format(nx.cs_double_str(BlockAtWcsLength)),
                                      "{}in".format(nx.cs_double_str(BlockAtWcsWidth)),
                                      "{}in".format(nx.cs_double_str(BlockAtWcsHeight)))

        # Color the whole body first - it colors every face, so the yellow bottom face has to come after.
        block_body = block.GetBodies()[0]
        nx.set_color(block_body, BlockAtWcsColor)

        # The block is built at the WCS orientation, so its "negative Z" face is the one whose normal is WCS -Z.
        bottom_face = nx.planar_face_with_normal_or_null(block_body, nx.negate(nx.axis_z(wcs_matrix)))
        if bottom_face is None:
            nx.print_("Could not find the block's -Z face to color yellow")
        else:
            nx.set_color(bottom_face, 42)

        new_component = merlin._create_cts_component(block, ComponentAtWcsName)
        # Origin on the block's corner rather than the assembly's - the block itself stays centred on the WCS.
        drawdie._rebase_block_to_part_origin(new_component, starting_display)
        nx.find_or_create_reference_set(new_component.OwningPart, "BODY").AddObjectsToReferenceSet([new_component])
        new_part = nx.work_part()
        nx.setup_station_expressions(new_part)
        refset = nx.find_or_create_reference_set(new_part, "BODY")
        refset.AddObjectsToReferenceSet(list(new_part.Bodies))
        first_block = nx.first_block_feature(new_part)
        if first_block is None:
            raise RuntimeError("Sequence contains no elements")
        first_block.SetName("DYNAMIC BLOCK")
        nx.set_attribute(new_part, "DESCRIPTION", "{} X {} X {}".format(
            nx.cs_double_str(BlockAtWcsLength), nx.cs_double_str(BlockAtWcsWidth), nx.cs_double_str(BlockAtWcsHeight)))
        nx.set_attribute(new_part, "MATERIAL", "FILL IN")
        nx.set_attribute(new_part, "DETAIL NAME", "FILL IN")
        # Extract the subtool onto layer 15 (after BODY is populated so it is not added to BODY).
        new_part.Layers.WorkLayer = 15
        merlin._create_subtool(new_part)
        new_part.Layers.WorkLayer = 1
        new_part.Layers.SetState(15, NXOpen.Layer.State.Hidden)
        nx.create_auto_size_udo(new_part)

        nx.set_display_part(starting_display)
        new_comp = nx.first_occurrence_in(new_part, nx.display_part())
        new_comp.Unblank()
        # The new component defaults to the ENTIRE PART reference set; force BODY here and in every ancestor assembly.
        nx.set_reference_set(new_comp, "BODY")
        merlin._set_reference_set_in_ancestor_assemblies(new_comp)
    except Exception as ex:
        nx.print_exception(ex)
    finally:
        # CreateCtsComponent leaves the new detail as the display/work part - put the session back.
        nx.set_display_part(starting_display)
        nx.set_work_part(starting_work)


def main() -> None:
    """The component-at-wcs UFunc - its menu button runs this file. An escaping exception is printed."""
    import usage_db

    with usage_db.run("component-at-wcs"):
        try:
            # No dialog of its own: ask before doing anything (a logged Question box).
            if nx.confirm_execute("component-at-wcs"):
                ComponentAtWcs.execute()
        except Exception as ex:
            nx.print_exception(ex)


if __name__ == "__main__":
    main()

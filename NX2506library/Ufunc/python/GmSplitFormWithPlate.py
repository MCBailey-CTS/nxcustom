"""
Legacy entry for the gm-split-form-with-plate UFunc. Since 2026-10-22 the three GM split forms are one builder,
GmSplitForm._create_split_form, and one dialog, GmSplitFormDialog, with Backing Plate and SHCS From Backside boxes.
This module opens that dialog with Backing Plate pre-checked and hands everything to GmSplitForm.execute_with,
so the old UFunc name and its Session.Execute entry points keep working.
The C# wrapper was deleted 2026-10-22 (in git at 1cb53d8): the UFunc's menu button runs this file's main().

What changed from the separate gm-split-form-with-plate port (in git at 07dcca8):
  - Keys: the split keys (GmSplitForm._place_split_keys), not the GM-post keys (PlaceGmPostUpperKeys1 /
    PlaceGmPostLowerKeys1, 1.5748" X inset, the upper's Y-edge pair turned with the WCS).
  - The blocks are built at the display part's absolute datum CSYS orientation, not identity.
  - The corner SHCS are placed off the block's box re-read after the re-base rather than off its corner - the same
    points (16mm-shcs-050-2x, .75" in, CBORE, from the mounting face).
  - The blocks are named {gm|cts}-split-form, the plate {gm|cts}-split-form-backing-plate and the key copies
    {gm|cts}-split-form-key-{token}, as gm-split-form's are (they were {gm|cts}-split-form-with-plate-component / -backing-plate / -component-key).

    Session.Execute("GmSplitFormWithPlate.py", "GmSplitFormWithPlate", "execute_with", is_gm, is_upper, rows, cols, bodies)
    Session.Execute("GmSplitFormWithPlate.py", "GmSplitFormWithPlate", "execute", is_gm)   # the old menus
"""

from __future__ import annotations

import os
import sys
from typing import Sequence

# Session.Execute does not put the script's folder on sys.path, so the shared modules would not import.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)
# From the source tree (src\UFuncs) the shared modules are in src\python; deployed, they are beside this file.
_shared_python = os.path.join(os.path.dirname(_here), "python")
if os.path.isdir(_shared_python) and _shared_python not in sys.path:
    sys.path.insert(1, _shared_python)

import NXOpen  # noqa: E402

import GmSplitForm as split  # noqa: E402

_Backside = False


class GmSplitFormWithPlate(object):

    @staticmethod
    def execute(is_gm: bool = True) -> None:
        """The old menus - the station from the work part, the bodies, the split count - then the combined build."""
        entry = split._try_begin_gm_entry("Gm Split Post", solid_only=False)
        if entry is None:
            return
        is_upper, bodies, reference_set = entry

        splits = split._try_pick_split_count()
        if splits is None:
            return

        split.build_gm_split_form(is_gm, is_upper, bodies, splits, reference_set, plate=True, backside=_Backside)

    @staticmethod
    def execute_with(is_gm: bool, is_upper: bool, rows: int, cols: int, bodies: Sequence[NXOpen.TaggedObject],
                     plate: bool = True, backside: bool = _Backside) -> None:
        """GmSplitForm.execute_with, the plate on unless the caller says otherwise."""
        split.GmSplitForm.execute_with(is_gm, is_upper, rows, cols, bodies, plate, backside)


def main() -> None:
    """The gm-split-form-with-plate UFunc - its menu button runs this file. An escaping exception is printed."""
    import GmSplitFormDialog
    import tsg_nx as nx
    import usage_db

    with usage_db.run("gm-split-form-with-plate"):
        try:
            GmSplitFormDialog.GmSplitFormDialog.run("GM Split Form With Plate", "GmSplitForm", "GmSplitForm", True, True,
                                                    _Backside)
        except Exception as ex:
            nx.print_exception(ex)


if __name__ == "__main__":
    main()

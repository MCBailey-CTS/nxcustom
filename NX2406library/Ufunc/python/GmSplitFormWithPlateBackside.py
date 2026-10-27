"""
Legacy entry for the gm-split-form-with-plate-backside UFunc. Since 2026-10-22 the three GM split forms are one builder,
GmSplitForm._create_split_form, and one dialog, GmSplitFormDialog, with Backing Plate and SHCS From Backside boxes.
This module opens that dialog with Backing Plate and SHCS From Backside pre-checked and hands everything to GmSplitForm.execute_with,
so the old UFunc name and its Session.Execute entry points keep working.
The C# wrapper was deleted 2026-10-22 (in git at 1cb53d8): the UFunc's menu button runs this file's main().

What changed from the separate gm-split-form-with-plate-backside port (in git at 07dcca8):
  - execute()'s second menu (splits along X) is gone: the menus build one column, as gm-split-form's do. The
    dialog has Cols.
  - The work part is left on the station the run started from; the old port set it to the display part at the end.
  - The blocks are named {gm|cts}-split-form, the plate {gm|cts}-split-form-backing-plate and the key copies
    {gm|cts}-split-form-key-{token}, as gm-split-form's are (they were {gm|cts}-split-form-with-plate-backside-component / -backing-plate / -component-key).

    Session.Execute("GmSplitFormWithPlateBackside.py", "GmSplitFormWithPlateBackside", "execute_with", is_gm, is_upper, rows, cols, bodies)
    Session.Execute("GmSplitFormWithPlateBackside.py", "GmSplitFormWithPlateBackside", "execute", is_gm)   # the old menus
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

_Backside = True


class GmSplitFormWithPlateBackside(object):

    @staticmethod
    def execute(is_gm: bool = True) -> None:
        """The old menus - the station from the work part, the bodies, the split count - then the combined build."""
        entry = split._try_begin_gm_entry("Gm Split Component Backside", solid_only=False)
        if entry is None:
            return
        is_upper, bodies, reference_set = entry

        splits = split._try_pick_split_count()
        if splits is None:
            return

        split.build_gm_split_form(is_gm, is_upper, bodies, splits, reference_set, plate=True, backside=_Backside)

    @staticmethod
    def execute_with(is_gm: bool, is_upper: bool, rows: int, cols: int, bodies: Sequence[NXOpen.TaggedObject],
                     plate: bool = True, backside: bool = _Backside, size_off_bodies: bool = False) -> None:
        """GmSplitForm.execute_with, the plate and SHCS From Backside on unless the caller says otherwise."""
        split.GmSplitForm.execute_with(is_gm, is_upper, rows, cols, bodies, plate, backside, size_off_bodies)


def main() -> None:
    """The gm-split-form-with-plate-backside UFunc - its menu button runs this file. An escaping exception is printed."""
    import GmSplitFormDialog
    import tsg_nx as nx
    import usage_db

    with usage_db.run("gm-split-form-with-plate-backside"):
        try:
            GmSplitFormDialog.GmSplitFormDialog.run("GM Split Form Backside", "GmSplitForm", "GmSplitForm", True, True,
                                                    _Backside)
        except Exception as ex:
            nx.print_exception(ex)


if __name__ == "__main__":
    main()

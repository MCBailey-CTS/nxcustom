"""
Python port of the NX work in the ShowOnly form (src\\UFuncs\\ShowOnly.cs), whose static methods now live in
src\\Static\\ShowOnly.cs (partial class Static):

- ShowOnlyBlankOff(TaggedObject part, HashSet<Tag> blankedOffObjects) -> ShowOnly.blank_off(part)
- ShowOnlyUnblank(TaggedObject part, HashSet<Tag> blankedOffObjects)  -> ShowOnly.unblank(part)

The blanked-object set cannot cross Session.Execute (the C# passes the form's own HashSet so the Reset button
can unblank from it), so each method returns the occurrence tags it touched instead, as one comma-separated string
of ints ("" for none) - a plain string is the one return type sure to come back through Session.Execute. The C#
(Static.ShowOnlyPython) parses it into the set. The material combo box, its part loop and the Reset button stay C#.

WIRED (2026-10-21): ShowOnlyBlankOff / ShowOnlyUnblank call these once per loaded part; the replaced C# sits
commented out in src\\Static\\ShowOnly.cs. NEVER RUN IN NX - untested.
"""

from __future__ import annotations

import os
import sys

# Session.Execute does not put the script's folder on sys.path, so the shared module would not import.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

import NXOpen  # noqa: E402

import tsg_nx as nx  # noqa: E402

# NXOpen.UF.UFConstants.UF_OBJ_BLANKED / UF_OBJ_NOT_BLANKED (uf_obj.h). The Python binding takes the plain int.
_UF_OBJ_BLANKED = 1
_UF_OBJ_NOT_BLANKED = 0


class ShowOnly(object):

    @staticmethod
    def blank_off(part: NXOpen.TaggedObject) -> str:
        """Static.ShowOnlyBlankOff - blanks every occurrence of part in the display part. Returns their tags."""
        return _set_blank_status(part, _UF_OBJ_BLANKED)

    @staticmethod
    def unblank(part: NXOpen.TaggedObject) -> str:
        """Static.ShowOnlyUnblank - unblanks every occurrence of part in the display part. Like the C#, these
        are also returned (the C# adds them to the blanked-off set too)."""
        return _set_blank_status(part, _UF_OBJ_NOT_BLANKED)


def _set_blank_status(part: NXOpen.TaggedObject, blank_status: int) -> str:
    # Gets all the occurrences of {part} in the current assembly.
    part_occs, _count = nx.ufsession_.Assem.AskOccsOfPart(nx.display_part().Tag, part.Tag)

    touched = []

    # Iterates through the partOccurrences if {part} in the current {DisplayedPart}.
    for part_occ in part_occs or []:
        # Blanks off (or unblanks) the object.
        nx.ufsession_.Obj.SetBlankStatus(part_occ, blank_status)
        # Add the object to the set.
        touched.append(str(int(part_occ)))

    return ",".join(touched)

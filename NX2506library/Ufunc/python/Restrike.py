"""
The restrike UFunc: a standalone Python UFunc (no C# class); its menu button runs this file's main().

Auto Design's RESTRIKE program on bodies picked by hand: a GM Cast Post (CastPost.build) on each picked body, once
in LAD02 (the lower post, off and subtracting each body's component's LWR-3D) and once in UAD02 (the upper post,
UPR-3D). Run from the -000; the work part does not matter, the stations are found by display name under it.

One Question box covers both posts when a picked component is missing LWR-3D or UPR-3D: Yes builds those off the
picked body, No cancels before anything is built. The lower post's subtract switches the bodies' components' reference
sets and back, which kills the picked body occurrences, so the upper looks them up again (DeadStrike._resolve_bodies).
A missing station or a failed side is printed and the other side still builds.

The body pick is the choice to run, so there is no "Are you sure" box; a cancelled pick marks the run cancelled.

Run standalone: File -> Execute -> NX Open on this file runs main().
"""

from __future__ import annotations

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

import tsg_nx as nx  # noqa: E402
import DrawDie as drawdie  # noqa: E402
from DeadStrike import _body_ref, _resolve_bodies  # noqa: E402

ufunc_name = "restrike"

LowerStation = "lad02"
UpperStation = "uad02"


class Restrike(object):

    @staticmethod
    def execute(is_gm: bool = True) -> None:
        """The units gate, the body pick, then the lower and upper posts."""
        ok, message = drawdie._check_info_units()
        if not ok:
            nx.show_error(message)
            return

        label = "Restrike"
        version = nx.assembly_file_version()
        bodies = drawdie._select_bodies("Select solid bodies for {}: {}".format(label, version),
                                        "{}: {}".format(label, version))
        if len(bodies) == 0:
            nx.mark_cancelled("the body pick")
            return

        if not _confirm_reference_sets(bodies):
            nx.mark_cancelled("the missing reference set question")
            return

        build(is_gm, bodies)


def build(is_gm: bool, bodies: Sequence[NXOpen.Body]) -> None:
    """The lower post in LAD02, then the upper in UAD02 on the bodies looked up again."""
    top_level = nx.display_part()
    starting_work = nx.work_part()
    refs = [_body_ref(b) for b in bodies]
    nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, "Restrike")

    try:
        _build_in_station(is_gm, _resolve_bodies(refs), LowerStation, False)
        _build_in_station(is_gm, _resolve_bodies(refs), UpperStation, True)
    finally:
        nx.set_display_part(top_level)
        nx.set_work_part(starting_work)


def _build_in_station(is_gm: bool, bodies: Sequence[NXOpen.Body], station_name: str, is_upper: bool) -> None:
    """
    GM Cast Post on bodies, built into station_name (lad02 / uad02): makes that station the work component of the
    -000, as a user would before launching cast-post, and subtracts UPR-3D / LWR-3D like it does.
    """
    from CastPost import CastPost

    top_level = nx.display_part()

    if len(bodies) == 0:
        nx.print_("Restrike: no bodies left for {} - no post built there.".format(station_name.upper()))
        return

    root = nx.root_component(top_level)
    station = None
    if root is not None:
        station = next((c for c in nx.descendants(root) if station_name in c.DisplayName.lower()), None)

    if station is None:
        nx.print_("Restrike: could not find {} under {} - no post built there.".format(
            station_name.upper(), top_level.Leaf))
        return

    try:
        nx.set_display_part(top_level)
        nx.set_work_component(station)
        drawdie._set_wcs_to_absolute(top_level)
        nx.info("Restrike: building the {} post in {}.".format("upper" if is_upper else "lower",
                                                              station.DisplayName))
        # refsets_confirmed: _confirm_reference_sets asked once for both posts.
        CastPost.build(is_gm, is_upper, cast(Sequence[NXOpen.TaggedObject], list(bodies)),
                         "UPR-3D" if is_upper else "LWR-3D", False, True)
    except Exception as ex:
        nx.print_("Restrike: the post in {} failed.".format(station.DisplayName))
        nx.print_exception(ex)
    finally:
        nx.set_display_part(top_level)
        nx.set_work_part(top_level)


def _confirm_reference_sets(bodies: Sequence[NXOpen.Body]) -> bool:
    """
    The lower post is placed off LWR-3D and the upper off UPR-3D. One Question box for both lists every component
    missing either; Yes builds them off the picked bodies for that side, No cancels. True with nothing missing.
    """
    seen = set()
    missing: List[str] = []
    for body in bodies:
        component = body.OwningComponent
        if component is None or component.Tag in seen:
            continue
        seen.add(component.Tag)
        absent = [r for r in ("LWR-3D", "UPR-3D") if not nx.has_reference_set(nx.prototype(component), r)]
        if absent:
            missing.append("{} (current: {}) has no {}".format(component.DisplayName, component.ReferenceSet,
                                                                " or ".join(absent)))

    if not missing:
        return True

    response = nx.message_box(
        "Restrike",
        NXOpen.NXMessageBox.DialogType.Question,
        "The lower post is placed off LWR-3D and the upper off UPR-3D, but:\n" + "\n".join(missing)
        + "\n\nProceed using the current reference set for those?")
    if response != nx.MessageBoxYes:
        return False

    for line in missing:
        nx.info("Restrike: {} - using the current reference set.".format(line))
    return True


def main() -> None:
    """The restrike UFunc - its menu button runs this file. An escaping exception is printed."""
    import usage_db
    from tsg_dialog import ask_is_gm

    with usage_db.run(ufunc_name):
        try:
            # The Customer dialog first: GM builds with the GM parts, TSG throws.
            is_gm = ask_is_gm("Restrike")
            if is_gm is not None:
                Restrike.execute(is_gm)
        except Exception as ex:
            nx.print_exception(ex)


if __name__ == "__main__":
    main()

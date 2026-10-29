"""
The restrike UFunc: a standalone Python UFunc (no C# class); its menu button runs this file's main().

Auto Design's RESTRIKE program on bodies picked by hand: a GM Cast Post (CastPost.build) on each picked body, once
in the op's LADnn (the lower post, off and subtracting each body's component's LWR-3D) and once in its UADnn (the
upper post, UPR-3D). Run from the -000; the work part does not matter, the stations are found by display name under it.

The dialog (Restrike.dlx, tools\\make-dlx.py, 2026-10-29) is Draw Die's DrawDie.OpBodiesDialog: the Customer radio
(None / TSG / GM, None on opening; TSG uses the CTS parts), the solid bodies and a radio of the ops with both
a ladNN and a uadNN under the -000 (none is an error box before it; the work part's op is checked first). OK stays
greyed out until TSG or GM is checked and a body is picked. Auto Design's RESTRIKE (its own _restrike_posts) still
builds into 02.

One Question box covers both posts when a picked component is missing LWR-3D or UPR-3D: Yes builds those off the
picked body, No cancels before anything is built. The lower post's subtract switches the bodies' components' reference
sets and back, which kills the picked body occurrences, so the upper looks them up again (DeadStrike._resolve_bodies).
A missing station or a failed side is printed and the other side still builds.

The dialog is the choice to run, so there is no "Are you sure" box; cancelling it marks the run cancelled.

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
from tsg_dialog import is_gm_customer, title_with_version  # noqa: E402

ufunc_name = "restrike"

LowerStation = "lad"
UpperStation = "uad"


class Restrike(object):

    @staticmethod
    def execute(is_gm: bool = True) -> None:
        """
        The units gate, the dialog (customer, bodies, op), then the lower and upper posts in that op. The dialog's
        Customer radio decides is_gm (TSG uses the CTS parts); the argument is not used.
        """
        ok, message = drawdie._check_info_units()
        if not ok:
            nx.show_error(message)
            return

        numbers = sorted(drawdie.find_op_stations())
        if len(numbers) == 0:
            nx.show_error("Restrike could not find an op with both a LADnn and a UADnn under {}.".format(
                nx.display_part().Leaf))
            return

        dialog = drawdie.OpBodiesDialog("Restrike.dlx", title_with_version("Restrike"), numbers,
                                        "Select the restrike solid bodies.")
        if not dialog.run():
            return
        is_gm = is_gm_customer(dialog.customer_choice)

        if not _confirm_reference_sets(dialog.bodies):
            nx.mark_cancelled("the missing reference set question")
            return

        build(is_gm, dialog.bodies, dialog.station)


def build(is_gm: bool, bodies: Sequence[NXOpen.Body], station: str = drawdie.DefaultStation) -> None:
    """The lower post in LADnn, then the upper in UADnn (nn = station) on the bodies looked up again."""
    top_level = nx.display_part()
    starting_work = nx.work_part()
    refs = [_body_ref(b) for b in bodies]
    nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, "Restrike")

    try:
        _build_in_station(is_gm, _resolve_bodies(refs), LowerStation + station, False)
        _build_in_station(is_gm, _resolve_bodies(refs), UpperStation + station, True)
    finally:
        nx.set_display_part(top_level)
        nx.set_work_part(starting_work)


def _build_in_station(is_gm: bool, bodies: Sequence[NXOpen.Body], station_name: str, is_upper: bool) -> None:
    """
    GM Cast Post on bodies, built into station_name (ladNN / uadNN): makes that station the work component of the
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

    with usage_db.run(ufunc_name):
        try:
            # The Restrike dialog asks for the customer.
            Restrike.execute(True)
        except Exception as ex:
            nx.print_exception(ex)


if __name__ == "__main__":
    main()

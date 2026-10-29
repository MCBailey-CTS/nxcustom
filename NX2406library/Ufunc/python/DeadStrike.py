"""
The dead-strike UFunc: a standalone Python UFunc (no C# class); its menu button runs this file's main().

The dead strike tooling Auto Design builds for its DEADHIT program, on bodies picked by hand. Run from the -000.
  - Lower: a GM Split Form with backing plate and SHCS from the backside (SplitFormWithPlateBackside.execute_with)
    over the picked bodies in LAD02, subtracting each body's component's LWR-3D, Rows x Cols blocks.
  - Upper (since 2026-10-29): exactly the Draw Die's upper half (DrawDie.build_upper) - the 2 x 4 cavity steels and
    the mounting plate in UAD02, subtracting UPR-3D. Rows / Cols do not apply to it.

The lower blocks are sized off the picked bodies (size_off_bodies), not the reference sets the split form UFunc uses:
X / Y the bodies + .375" a side, the top at their highest point and the bottom 2.75"+ under their lowest. On
006066-010 the layout's LWR-3D / UPR-3D are tool bodies 20" x 42" running to Z 21 / -18, which made 26" / 23" tall
blocks with a .375" wall left standing round the subtract.

The dialog (DeadStrike.dlx, tools\\make-dlx.py): the Customer radio (None / TSG / GM, None on opening; GM builds with
the GM parts, TSG throws NotImplementedError), the solid bodies (anywhere in the assembly), Rows / Cols (1-5, as
the split form dialog, the lower's grid), and Lower / Upper boxes (both checked by default) to build only one side.
OK stays greyed out until TSG or GM is checked, a body is picked and a side is checked.

All the bodies go into one build per side. The lower form's sizing and subtract switch the bodies' components'
reference sets and back, which kills the picked body occurrences, so the upper looks them up again
(Component.FindOccurrence on the prototype body). A missing station or a failed side is printed and the other side
still builds.

AutoDesign.py's DEADHIT program calls build_in_station for each side. The C# dead-hit UFunc (MerlinUFuncs\DeadHit.cs)
runs DeadStrike.execute(is_gm) through PythonLibrary.Execute, after its units gate.

Run standalone: File -> Execute -> NX Open on this file runs main().
"""

from __future__ import annotations

import os
import sys
from typing import Callable, List, Optional, Sequence, Tuple, cast

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
import NXOpen.UF  # noqa: E402

import tsg_nx as nx  # noqa: E402
import DrawDie as drawdie  # noqa: E402
from tsg_dialog import CustomerNone, Dialog, is_gm_customer, title_with_version  # noqa: E402

ufunc_name = "dead-strike"

LowerStation = "lad02"
UpperStation = "uad02"

# UF_UI_SEL_FEATURE_SOLID_BODY - not in every UFConstants build, so the number Perfect.py uses too.
_SolidBodyDetail = 36

BodyRef = Tuple[Optional[NXOpen.Assemblies.Component], NXOpen.Body]


class DeadStrike(object):

    @staticmethod
    def execute(is_gm: bool = True) -> None:
        """
        The dialog, then both sides' split forms (or the one side checked). The dialog's Customer radio decides is_gm
        (TSG throws NotImplementedError); the argument is not used.
        """
        dialog = _DeadStrikeDialog(title_with_version("Dead Strike"))
        if not dialog.run():
            return
        build(is_gm_customer(dialog.customer_choice), dialog.bodies, dialog.rows, dialog.cols, dialog.lower,
              dialog.upper)


def build(is_gm: bool, bodies: Sequence[NXOpen.Body], rows: int, cols: int, lower: bool = True,
          upper: bool = True) -> None:
    """The lower split form in LAD02, then the upper in UAD02 on the bodies looked up again."""
    top_level = nx.display_part()
    starting_work = nx.work_part()
    refs = [_body_ref(b) for b in bodies]
    nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, "Dead Strike")

    try:
        if lower:
            build_in_station(is_gm, _resolve_bodies(refs), LowerStation, False, rows, cols)
        if upper:
            build_in_station(is_gm, _resolve_bodies(refs), UpperStation, True, rows, cols)
    finally:
        nx.set_display_part(top_level)
        nx.set_work_part(starting_work)


def build_in_station(is_gm: bool, bodies: Sequence[NXOpen.Body], station_name: str, is_upper: bool, rows: int,
                     cols: int, log: Optional[Callable[[str], None]] = None, skip_spreadsheets: bool = False,
                     quiet: bool = False) -> None:
    """
    The lower: GM Split Form with backing plate and SHCS from the backside over bodies, built into station_name
    (lad02): makes that station the work component of the -000, as a user would before opening the split form
    dialog, which sizes and subtracts off LWR-3D. The upper is exactly the Draw Die's upper half (DrawDie.build_upper:
    the cavity steels and mounting plate in UAD02, subtracting UPR-3D; rows / cols do not apply, station_name is not
    used). log also gets each step (Auto Design's progress window); skip_spreadsheets and quiet go to the draw die.
    """
    from SplitFormWithPlateBackside import SplitFormWithPlateBackside

    def say(message: str) -> None:
        if log is not None:
            log(message)

    top_level = nx.display_part()

    if len(bodies) == 0:
        say("No dead strike bodies left for {} - nothing built there.".format(station_name.upper()))
        nx.warn("Dead Strike: no bodies left for {} - nothing built there.".format(station_name.upper()))
        return

    if is_upper:
        try:
            nx.set_display_part(top_level)
            nx.set_work_part(top_level)
            say("Building the dead strike upper (the draw die's cavity steels and mounting plate)...")
            drawdie.DrawDie.build_upper(is_gm, cast(Sequence[NXOpen.TaggedObject], list(bodies)), quiet,
                                        skip_spreadsheets)
            say("Finished the dead strike upper.")
        finally:
            nx.set_display_part(top_level)
            nx.set_work_part(top_level)
        return

    station = _find_station(top_level, station_name)

    if station is None:
        say("Could not find {} - no dead strike split form built there.".format(station_name.upper()))
        nx.print_("Dead Strike: could not find {} under {} - no split form built there.".format(
            station_name.upper(), top_level.Leaf))
        return

    try:
        nx.set_display_part(top_level)
        nx.set_work_component(station)
        drawdie._set_wcs_to_absolute(top_level)
        say("Building the dead strike split form ({} x {}) in {}...".format(rows, cols, station.DisplayName))
        # Sized off the bodies: the strip layout's UPR-3D / LWR-3D is a tool body far taller and wider than the part.
        SplitFormWithPlateBackside.execute_with(is_gm, is_upper, rows, cols,
                                                  cast(Sequence[NXOpen.TaggedObject], list(bodies)),
                                                  size_off_bodies=True)
        say("Finished the dead strike split form in {}.".format(station.DisplayName))
    except Exception as ex:
        say("The dead strike split form in {} failed: {}".format(station.DisplayName, ex))
        nx.print_("Dead Strike: the split form in {} failed.".format(station.DisplayName))
        nx.print_exception(ex)
    finally:
        nx.set_display_part(top_level)
        nx.set_work_part(top_level)


def _find_station(top_level: NXOpen.Part, station_name: str) -> Optional[NXOpen.Assemblies.Component]:
    """The first component under top_level whose display name holds station_name (lad02 / uad02)."""
    root = nx.root_component(top_level)
    if root is None:
        return None
    return next((c for c in nx.descendants(root) if station_name in c.DisplayName.lower()), None)


def _body_ref(body: NXOpen.Body) -> BodyRef:
    """A body as its owning component and prototype body. Both survive a reference-set switch; the occurrence does not."""
    if body.IsOccurrence:
        return body.OwningComponent, cast(NXOpen.Body, body.Prototype)
    return None, body


def _resolve_bodies(refs: Sequence[BodyRef]) -> List[NXOpen.Body]:
    """The live body occurrence of each reference, looked up now; one no longer shown is printed and left out."""
    bodies: List[NXOpen.Body] = []
    for owner, body in refs:
        try:
            live = body if owner is None else owner.FindOccurrence(body)
            if not isinstance(live, NXOpen.Body):
                nx.warn("Dead Strike: {} no longer shows one of its bodies (reference set?) - left out.".format(
                    owner.DisplayName if owner is not None else ""))
                continue
            bodies.append(live)
        except Exception as ex:
            nx.print_exception(ex)
    return bodies


class _DeadStrikeDialog(Dialog):
    """DeadStrike.dlx: the bodies, Rows / Cols, Lower / Upper."""

    dlx_name = "DeadStrike.dlx"

    def __init__(self, title: str) -> None:
        self.title = title
        super().__init__()
        # Captured in ok(): the blocks are gone once Launch returns.
        self.bodies: List[NXOpen.Body] = []
        self.rows = 2
        self.cols = 1
        self.lower = True
        self.upper = True
        self.customer_choice = CustomerNone

    def initialize(self) -> None:
        mask = NXOpen.Selection.MaskTriple(NXOpen.UF.UFConstants.UF_solid_type, 0, _SolidBodyDetail)
        self.block("bodies").SetSelectionFilter(NXOpen.Selection.SelectionAction.ClearAndEnableSpecific, [mask])
        # The strip's solids live in components below the -000.
        self.assembly_scope(self.block("bodies"))

    def shown(self) -> None:
        # Value properties: set once the dialog is up. Not remembered (the .dlx), so both sides every time.
        self.reset_customer()
        self.block("lower").Value = True
        self.block("upper").Value = True

    def enable_ok(self) -> bool:
        return (self.customer_picked() and (bool(self.block("lower").Value) or bool(self.block("upper").Value))
                and len(self._picked_bodies()) > 0)

    def ok(self) -> bool:
        self.bodies = self._picked_bodies()
        self.lower = bool(self.block("lower").Value)
        self.upper = bool(self.block("upper").Value)

        # enable_ok greys OK out for these; they are a backstop.
        if not self.customer_picked():
            self.message("Check TSG or GM.")
            return False
        if not self.lower and not self.upper:
            self.message("Check Lower, Upper or both.")
            return False
        if not self.bodies:
            self.message("Select the dead strike solid bodies.")
            return False

        self.rows = int(self.block("rows").Value)
        self.cols = int(self.block("cols").Value)
        self.customer_choice = self.customer()
        return True

    def _picked_bodies(self) -> List[NXOpen.Body]:
        return [cast(NXOpen.Body, o) for o in self.selected(self.block("bodies"))
                if isinstance(o, NXOpen.Body) and cast(NXOpen.Body, o).IsSolidBody]


def main() -> None:
    """The dead-strike UFunc - its menu button runs this file. An escaping exception is printed."""
    import usage_db

    with usage_db.run(ufunc_name):
        try:
            DeadStrike.execute(True)
        except Exception as ex:
            nx.print_exception(ex)


if __name__ == "__main__":
    main()

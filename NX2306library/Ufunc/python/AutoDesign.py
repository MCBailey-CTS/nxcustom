"""
The auto-design UFunc: builds every station of a strip from its solids' PROGRAM object attribute, from the
"Auto Design Program" spec (text.txt, 2026-10-20). Run from the -000. Python only since 2026-10-23 - a port of
Merlin.StaticAutoDesign (src\\UFuncs\\MerlinAutoDesign.cs), its SNAP AutoDesignDialog and the WinForms
Ui\\ProgressLogForm, all in git at 5d6e47f. Its menu button runs this file's main().

Each PROGRAM value (trimmed, case-insensitive) routes to one existing program, fed the bodies directly instead of
asking for them, in this order:
  - BLANK    - GM Blank Station, -01 stations (GmBlankStation.build, is3d False)
  - TRIM     - GM 2nd Trim Station, -02 stations (GmBlankStation.build, is3d True)
  - PRC      - GM Pierce into LAD02 (buttons) and UAD02 (punches, retainers) (GmPierce.build, station "02", no
               station menu; gm-pierce only, no secondary pass)
  - DRAW     - Draw Die into LAD02 and UAD02 (DrawDie.build)
  - RESTRIKE - GM Cast Post, once in LAD02 (LWR-3D) and once in UAD02 (UPR-3D) (GmCastPost.build)
  - DEADHIT  - GM Split Form with backing plate and SHCS from the backside, once in LAD02 (LWR-3D) and once in UAD02
               (UPR-3D), the dialog's Rows x Cols over all the DEADHIT bodies (DeadStrike.build_in_station, the
               dead-strike UFunc's builder)
Unknown values print and are skipped. Each program starts from the -000 (display = work, WCS absolute) in its own
try/except, so a failed draw die still leaves the restrike posts to be built.

The dialog (AutoDesign.dlx, tools\\make-dlx.py) asks for all the strip's solids or a selection, and the construction -
Normal (S7 trim steels) or Heavy (D2) - which only the blank and 2nd trim stations use; below that, each program's
body count in the assembly (a read-out of what Select all would find), with DRAW's column / steels per row spinners
(read but not used yet: the draw die does not take them) and DEADHIT's Rows / Cols (the split forms' grid).

Kept from the C#:
  - The bodies are grouped as (owning component, prototype body), not occurrences, and re-resolved
    (Component.FindOccurrence) for every program: every subtract switches a component's reference set and back,
    which kills its body occurrences (3615013 "not alive" if a later program were handed the old ones).
  - The restrike asks one Question box for both posts when a component is missing LWR-3D / UPR-3D; the builds are
    then told not to ask again.
  - Every build runs quiet (no per-builder elapsed times or "Created reference set" lines); the run prints one
    overall time.
  - A DebugSignDotNet deploy (this file under ...\\bin\\DebugSignDotNet\\python) skips every pierce detail's
    spreadsheet - the C# #if DEBUGSIGNDOTNET.
  - Edit Spreadsheets (checked every time the dialog opens) off: no part's Excel sheet is opened - the pierce
    details (GmPierce.build's skip_spreadsheets) and the draw die's keys and guided retainers (DrawDie.build's)
    keep their seed settings.

The progress window is progress_window.ProgressWindow (ProgressWindow.ps1), a separate PowerShell window (Python in NX cannot show WinForms) that
follows this run's progress file: Auto Design's own lines (#LOG / #TITLE / #DONE) and every builder step written
through tsg_nx.progress while tsg_nx.progress_path points at the file. It stays open after the run until closed.

The builds are imported and called directly rather than through Session.Execute, so nothing crosses the managed
boundary. No undo mark, like the C#.
"""

from __future__ import annotations

import datetime
import os
import sys
from typing import Callable, Dict, List, Optional, Sequence, Set, Tuple, cast

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
import NXOpen.BlockStyler  # noqa: E402
import NXOpen.UF  # noqa: E402

import tsg_nx as nx  # noqa: E402
import DrawDie as drawdie  # noqa: E402
from progress_window import ProgressWindow  # noqa: E402
from tsg_dialog import Dialog, title_with_version  # noqa: E402

ufunc_name = "auto-design"

# The object attribute on a solid that names the program to run on it.
AutoDesignAttribute = "PROGRAM"

AutoDesignBlank = "BLANK"
AutoDesignTrim = "TRIM"
AutoDesignPierce = "PRC"
AutoDesignDraw = "DRAW"
AutoDesignRestrike = "RESTRIKE"
AutoDesignDeadHit = "DEADHIT"

# The order the programs run in.
Programs = [AutoDesignBlank, AutoDesignTrim, AutoDesignPierce, AutoDesignDraw, AutoDesignRestrike, AutoDesignDeadHit]

# The programs the dialog always shows a count for, in this order (the .dlx has a count_{program} label for each).
DisplayedPrograms = ["BLANK", "DRAW", "PRC", "RESTRIKE", "TRIM", "DEADHIT"]

# The trim-steel material for each construction (the dialog's Normal / Heavy).
ConstructionMaterials = {"Normal": "S7", "Heavy": "D2"}


# A DebugSignDotNet build leaves every pierce detail's Excel sheet unopened (GmPierce.build's skip_spreadsheets).
AutoDesignSkipSpreadsheets = "\\bin\\debugsigndotnet\\" in _here.lower() + "\\"

# NX will not build a Block Styler dialog from inside some callbacks (a menu or toolbar launch, it seems).
_ErrorCannotLaunchDialog = 3520048

# Components from here (fasteners, jacks, keys) are placed, not created - left out of the created list.
_LibraryFolder = "g:\0library\\"

# UF_UI_SEL_FEATURE_SOLID_BODY - not in every UFConstants build, so the number GmPerfect.py uses too.
_SolidBodyDetail = 36

# NXMessageBox.Show returns 1 for Yes on a Question dialog.
_MessageBoxYes = 1

# A body kept across programs: its owning component (None for a body of the -000 itself) and its prototype body.
BodyRef = Tuple[Optional[NXOpen.Assemblies.Component], NXOpen.Body]


# ---------------------------------------------------------------------------------------------------
# Progress window
# ---------------------------------------------------------------------------------------------------

class _ProgressLog(ProgressWindow):
    """Ui.ProgressLogForm - this run's progress file, and the ProgressWindow.ps1 window following it."""

    def __init__(self, title: str) -> None:
        super(_ProgressLog, self).__init__(title, "AutoDesign")


_log: Optional[_ProgressLog] = None


def _log_line(message: str) -> None:
    if _log is not None:
        _log.write_line(message)


# ---------------------------------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------------------------------

class AutoDesign(object):

    @staticmethod
    def execute(is_gm: bool = True) -> None:
        """
        Merlin.StaticAutoDesign - run from the -000: the dialog, then every PROGRAM group through its program. Each
        program is caught on its own. Progress goes to the window, opened once the dialog is accepted so it does not
        sit on top of it.
        """
        global _log

        ok, message = drawdie._check_info_units()
        if not ok:
            nx.show_error(message)
            return

        if not nx.display_part().Leaf.endswith("-000"):
            nx.show_error("Auto Design must be run from the 000.")
            return

        title = title_with_version("Auto Design")

        try:
            dialog = _AutoDesignDialog(title)
            accepted = dialog.run()
        except NXOpen.NXException as ex:
            if ex.ErrorCode != _ErrorCannotLaunchDialog:
                raise
            nx.print_exception(ex)
            nx.show_error("NX would not open the {} dialog (error {} - it will not create a dialog from inside a "
                          "callback).\n\nTry running it from File -> Execute -> NX Open rather than from a menu or "
                          "toolbar button.".format(title, _ErrorCannotLaunchDialog))
            return

        if not accepted:
            nx.print_("{} dialog was not accepted - nothing built.".format(title))
            return

        _log = _ProgressLog(title)
        try:
            # Progress lines (nx.info) go to the syslog only; the listing window gets the errors.
            with nx.quiet_listing():
                _run(is_gm, title, dialog)
        finally:
            _log.stop_following()
            _log = None


def _run(is_gm: bool, title: str, dialog: "_AutoDesignDialog") -> None:
    log = cast(_ProgressLog, _log)
    log.write_line("Auto Design started.")

    skip_spreadsheets = AutoDesignSkipSpreadsheets or not dialog.edit_spreadsheets
    if not dialog.edit_spreadsheets:
        log.write_line("Edit Spreadsheets is off - no part spreadsheet is opened.")
    elif AutoDesignSkipSpreadsheets:
        log.write_line("DebugSignDotNet build - pierce spreadsheets are skipped.")

    top_level = nx.display_part()
    candidates = all_solid_body_occurrences(top_level) if dialog.select_all else list(dialog.bodies)

    # Grouped by the attribute's value. Bodies without it are not part of the design (Select all reaches every solid
    # in the -000).
    groups: Dict[str, List[BodyRef]] = {}
    for body in candidates:
        program = auto_design_program(body)
        if program is not None:
            groups.setdefault(program, []).append(_body_ref(body))

    if not groups:
        log.write_line("No PROGRAM attribute on any of the {} solid bodies - nothing built.".format(len(candidates)))
        nx.show_error("None of the {} solid bodies has a {} attribute ({}).".format(
            len(candidates), AutoDesignAttribute, ", ".join(Programs[:-1]) + " or " + Programs[-1]))
        return

    for unknown in sorted(k for k in groups if k not in Programs):
        log.write_line("{} = {}: {} body(ies) - not a program, skipped.".format(
            AutoDesignAttribute, unknown, len(groups[unknown])))
        nx.print_("Auto Design: {} body(ies) have {} = {}, which is not a program - skipped.".format(
            len(groups[unknown]), AutoDesignAttribute, unknown))

    # Unchecked in the dialog: left out of everything below (counts, the operation total, the runs).
    for program in [p for p in Programs if p in groups and p not in dialog.run_programs]:
        log.write_line("{} is not checked - {} body(ies) skipped.".format(program, len(groups[program])))
        del groups[program]

    def group(program: str) -> List[NXOpen.Body]:
        """Fresh occurrences every call - see _body_ref."""
        return _resolve_bodies(program, groups[program]) if program in groups else []

    for program in Programs:
        line = "{} = {}: {} body(ies)".format(AutoDesignAttribute, program, len(group(program)))
        nx.info("Auto Design: " + line)
        log.write_line(line)

    material = dialog.material
    starting_work = nx.work_part()

    # One operation per program that has bodies, two each for RESTRIKE and DEADHIT (LAD02 and UAD02). The window's
    # title counts them off as each one starts.
    total = (sum(1 for p in Programs if groups.get(p)) + (1 if groups.get(AutoDesignRestrike) else 0)
             + (1 if groups.get(AutoDesignDeadHit) else 0))
    counter = [0]

    def start_operation(what: str) -> None:
        counter[0] += 1
        log.set_title("{} ({} of {}) - {}".format(title, counter[0], total, what))

    log.set_title("{} (0 of {})".format(title, total))
    log.write_line("{} operation(s) expected.".format(total))

    def run_program(program: str, build: Callable[[List[NXOpen.Body]], None]) -> None:
        """Every program starts from the -000, as it would when launched on its own."""
        bodies = group(program)
        if not bodies:
            return

        if program not in (AutoDesignRestrike, AutoDesignDeadHit):
            start_operation(program)

        nx.prompt("Auto Design: {} ({})".format(program, len(bodies)))
        log.write_line("Running the {} program on {} body(ies)...".format(program, len(bodies)))
        before = _component_tags(top_level)

        try:
            nx.set_display_part(top_level)
            nx.set_work_part(top_level)
            drawdie._set_wcs_to_absolute(top_level)
            build(bodies)
            log.write_line("Finished the {} program.".format(program))
        except Exception as ex:
            log.write_line("The {} program failed: {}".format(program, ex))
            nx.print_("Auto Design: the {} program failed.".format(program))
            nx.print_exception(ex)
        finally:
            nx.set_display_part(top_level)
            nx.set_work_part(top_level)
            _print_created(program, top_level, before)

    def blank(bodies: List[NXOpen.Body]) -> None:
        from GmBlankStation import GmBlankStation
        GmBlankStation.build(False, material, bodies, quiet=True)

    def trim(bodies: List[NXOpen.Body]) -> None:
        from GmBlankStation import GmBlankStation
        GmBlankStation.build(True, material, bodies, quiet=True)

    def pierce(bodies: List[NXOpen.Body]) -> None:
        from GmPierce import GmPierce
        # Into lad02 / uad02 like the draw die, restrike and dead strike - no station menu mid-run.
        created = GmPierce.build(is_gm, bodies, skip_spreadsheets, quiet=True, station="02")
        log.write_line("Pierce: {} detail(s) created.".format(len(created)))

    def draw(bodies: List[NXOpen.Body]) -> None:
        from DrawDie import DrawDie
        DrawDie.build(is_gm, cast(Sequence[NXOpen.TaggedObject], bodies), quiet=True,
                      skip_spreadsheets=not dialog.edit_spreadsheets)

    def restrike(bodies: List[NXOpen.Body]) -> None:
        # Asked once for both posts; the builds are then told not to ask again.
        if not _confirm_restrike_reference_sets(bodies):
            return
        start_operation(AutoDesignRestrike + " LAD02")
        _restrike_posts(is_gm, bodies, "lad02", is_upper=False)
        # The lower post's subtract switches the bodies' components to LWR-3D and back, so the upper post
        # re-resolves them rather than reusing the lower's.
        start_operation(AutoDesignRestrike + " UAD02")
        _restrike_posts(is_gm, group(AutoDesignRestrike), "uad02", is_upper=True)

    def dead_hit(bodies: List[NXOpen.Body]) -> None:
        from DeadStrike import build_in_station
        start_operation(AutoDesignDeadHit + " LAD02")
        build_in_station(is_gm, bodies, "lad02", False, dialog.deadhit_rows, dialog.deadhit_cols, _log_line)
        # The lower form's sizing and subtract switch the bodies' components to LWR-3D and back, so the upper
        # re-resolves them rather than reusing the lower's.
        start_operation(AutoDesignDeadHit + " UAD02")
        build_in_station(is_gm, group(AutoDesignDeadHit), "uad02", True, dialog.deadhit_rows, dialog.deadhit_cols,
                         _log_line)

    start = datetime.datetime.now()
    log.follow()
    try:
        run_program(AutoDesignBlank, blank)
        run_program(AutoDesignTrim, trim)
        run_program(AutoDesignPierce, pierce)
        run_program(AutoDesignDraw, draw)
        run_program(AutoDesignRestrike, restrike)
        run_program(AutoDesignDeadHit, dead_hit)
    except Exception as ex:
        log.write_line("Auto Design failed: {}".format(ex))
        nx.print_exception(ex)
    finally:
        nx.set_display_part(top_level)
        nx.set_work_part(starting_work)
        # Session.__UsingTimer prints the elapsed TimeSpan.
        nx.info(drawdie._time_span(datetime.datetime.now() - start))
        log.set_title("{} ({} of {}) - finished".format(title, counter[0], total))
        log.write_line("Auto Design finished.")


def _component_tags(top_level: NXOpen.BasePart) -> Set[int]:
    """Every component occurrence under top_level, suppressed and unloaded too - the before picture for
    _print_created."""
    root = nx.root_component(top_level)
    if root is None:
        return set()
    return {c.Tag for c in nx.descendants(root, include_root=False, include_suppressed=True, include_unloaded=True)}


def _print_created(program: str, top_level: NXOpen.BasePart, before: Set[int]) -> None:
    """
    Lists each main component the program added under top_level - a new occurrence whose parent was already there
    (a station, the -000) - with that parent, in the listing window and the progress log. Children of a new
    component and library parts (fasteners, jacks, keys) are left out. Never raises: it must not fail the run.
    """
    try:
        root = nx.root_component(top_level)
        if root is None:
            return
        for component in nx.descendants(root, include_root=False):
            if component.Tag in before:
                continue
            parent = component.Parent
            # Main components only: a new one's own children (its fasteners, jacks, keys - some Saved As into the job
            # folder) are left out with the library parts.
            if parent is not None and parent.Tag not in before:
                continue
            if nx.prototype(component).FullPath.lower().startswith(_LibraryFolder):
                continue
            line = "{}: created {} in {}".format(program, component.DisplayName,
                                                 parent.DisplayName if parent is not None else top_level.Leaf)
            nx.print_("Auto Design: " + line)
            _log_line(line)
    except Exception as ex:
        nx.print_exception(ex)


# ---------------------------------------------------------------------------------------------------
# Bodies and the PROGRAM attribute
# ---------------------------------------------------------------------------------------------------

def _body_ref(body: NXOpen.Body) -> BodyRef:
    """A body as its owning component and prototype body. Both survive a reference-set switch; the occurrence does not."""
    if body.IsOccurrence:
        return body.OwningComponent, cast(NXOpen.Body, body.Prototype)
    return None, body


def _resolve_bodies(program: str, refs: Sequence[BodyRef]) -> List[NXOpen.Body]:
    """
    The live body occurrence of each reference, looked up now. One whose component no longer shows it (its reference
    set left on something without the body) is printed and left out.
    """
    bodies: List[NXOpen.Body] = []
    for owner, body in refs:
        try:
            live = body if owner is None else owner.FindOccurrence(body)
            if not isinstance(live, NXOpen.Body):
                name = owner.DisplayName if owner is not None else ""
                _log_line("{}: a body of {} is no longer shown - left out.".format(program, name))
                nx.print_("Auto Design: {}: {} no longer shows one of its bodies (reference set?) - left out."
                          .format(program, name))
                continue
            bodies.append(live)
        except Exception as ex:
            nx.print_exception(ex)
    return bodies


def auto_design_program(body: NXOpen.Body) -> Optional[str]:
    """
    The body's PROGRAM attribute, trimmed and upper-cased; None when it has none. Read off the occurrence first (an
    attribute assigned with the -000 displayed lives there), then off the prototype body (one assigned in the strip's
    own part, as the Auto Design Labeler does).
    """
    try:
        sources = [body, cast(NXOpen.Body, body.Prototype)] if body.IsOccurrence else [body]
        for source in sources:
            if not nx.has_attribute(source, AutoDesignAttribute):
                continue
            value = (nx.get_attribute(source, AutoDesignAttribute) or "").strip().upper()
            if value:
                return value
        return None
    except Exception as ex:
        nx.print_exception(ex)
        return None


def all_solid_body_occurrences(top_level: NXOpen.Part) -> List[NXOpen.Body]:
    """
    Every solid body in top_level: its own, plus an occurrence of each loaded component's prototype bodies - what
    the user would get by picking them all in the graphics window.
    """
    bodies: List[NXOpen.Body] = [b for b in top_level.Bodies if b.IsSolidBody]
    root = nx.root_component(top_level)
    if root is None:
        return bodies

    for component in nx.descendants(root, include_root=False):
        prototype = component.Prototype
        if not isinstance(prototype, NXOpen.Part):
            continue
        for body in prototype.Bodies:
            try:
                if body.IsSolidBody:
                    occurrence = component.FindOccurrence(body)
                    if isinstance(occurrence, NXOpen.Body):
                        bodies.append(occurrence)
            except Exception as ex:
                nx.print_exception(ex)
    return bodies


def scan_programs(top_level: NXOpen.Part) -> Dict[str, List[str]]:
    """
    Every solid Select all would see that has a PROGRAM attribute, by value: the leaf of the part owning each body
    that carries it - one entry per body, so the count is the list's length.
    """
    programs: Dict[str, List[str]] = {}
    try:
        for body in all_solid_body_occurrences(top_level):
            program = auto_design_program(body)
            if program is None:
                continue
            source = cast(NXOpen.Body, body.Prototype) if body.IsOccurrence else body
            programs.setdefault(program, []).append(source.OwningPart.Leaf)
    except Exception as ex:
        nx.print_exception(ex)
    return programs


# ---------------------------------------------------------------------------------------------------
# Restrike
# ---------------------------------------------------------------------------------------------------

def _confirm_restrike_reference_sets(bodies: Sequence[NXOpen.Body]) -> bool:
    """
    The restrike posts are placed off LWR-3D (LAD02) and UPR-3D (UAD02). One Question box for both lists every
    component missing either; Yes builds them off the picked bodies for that side, No skips the restrike.
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
        "Auto Design - Restrike",
        NXOpen.NXMessageBox.DialogType.Question,
        "The lower restrike post is placed off LWR-3D and the upper off UPR-3D, but:\n" + "\n".join(missing)
        + "\n\nProceed using the current reference set for those?")

    if response != _MessageBoxYes:
        _log_line("Restrike skipped: a component is missing LWR-3D / UPR-3D.")
        nx.print_("Auto Design: restrike skipped - " + "; ".join(missing))
        return False

    for line in missing:
        nx.info("Auto Design: restrike: {} - using the current reference set.".format(line))
    return True


def _restrike_posts(is_gm: bool, bodies: Sequence[NXOpen.Body], station_name: str, is_upper: bool) -> None:
    """
    GM Cast Post on the restrike part body, built into station_name (lad02 / uad02): makes that station the work
    component of the -000, as a user would before launching gm-cast-post, and subtracts UPR-3D / LWR-3D like it does.
    """
    from GmCastPost import GmCastPost

    top_level = nx.display_part()
    root = nx.root_component(top_level)
    station = None
    if root is not None:
        station = next((c for c in nx.descendants(root) if station_name in c.DisplayName.lower()), None)

    if station is None:
        _log_line("Could not find {} - no restrike post built there.".format(station_name.upper()))
        nx.print_("Auto Design: could not find {} under {} - no restrike post built there.".format(
            station_name.upper(), top_level.Leaf))
        return

    try:
        nx.set_display_part(top_level)
        nx.set_work_component(station)
        drawdie._set_wcs_to_absolute(top_level)
        _log_line("Building the restrike post in {}...".format(station.DisplayName))
        # quiet, refsets_confirmed (_confirm_restrike_reference_sets asked already).
        GmCastPost.build(is_gm, is_upper, cast(Sequence[NXOpen.TaggedObject], list(bodies)),
                         "UPR-3D" if is_upper else "LWR-3D", True, True)
        _log_line("Finished the restrike post in {}.".format(station.DisplayName))
    except Exception as ex:
        _log_line("The restrike post in {} failed: {}".format(station.DisplayName, ex))
        nx.print_("Auto Design: the restrike post in {} failed.".format(station.DisplayName))
        nx.print_exception(ex)
    finally:
        nx.set_display_part(top_level)
        nx.set_work_part(top_level)


# ---------------------------------------------------------------------------------------------------
# Dialog
# ---------------------------------------------------------------------------------------------------

class _AutoDesignDialog(Dialog):
    """
    AutoDesign.dlx: Select all / Select solids, the body picker (shown only for Select solids), Normal / Heavy, and
    a checkbox per program labelled with its body count in the assembly (only the checked ones run), with DRAW's
    columns / steels per row and DEADHIT's rows / cols.
    """

    dlx_name = "AutoDesign.dlx"

    def __init__(self, title: str) -> None:
        self.title = title
        # Scanned before the dialog is built, as the SNAP dialog's constructor did.
        self.program_parts = scan_programs(nx.display_part())
        super().__init__()
        # Captured in ok(): the blocks are gone once Launch returns.
        self.select_all = True
        self.bodies: List[NXOpen.Body] = []
        self.material = "S7"
        self.draw_columns = 2
        self.draw_steels_per_row = 4
        self.deadhit_rows = 2
        self.deadhit_cols = 1
        self.edit_spreadsheets = True
        self.run_programs: Set[str] = set(Programs)

    def initialize(self) -> None:
        mask = NXOpen.Selection.MaskTriple(NXOpen.UF.UFConstants.UF_solid_type, 0, _SolidBodyDetail)
        self.block("bodies").SetSelectionFilter(NXOpen.Selection.SelectionAction.ClearAndEnableSpecific, [mask])
        # The strip's solids live in components below the -000.
        self.assembly_scope(self.block("bodies"))

    def shown(self) -> None:
        for program in DisplayedPrograms:
            count = len(self.program_parts.get(program, []))
            toggle = self.block("run_" + program)
            toggle.Label = "{}: {}".format(program, count)
            # Not remembered (the .dlx): checked whenever the assembly has bodies for it. With Select solids the
            # picked bodies may still hold one, so an empty program stays tickable.
            toggle.Value = count > 0

        # Anything else the scan found is not a program Auto Design runs - say so rather than hide it.
        others = ["{} ({})".format(k, len(self.program_parts[k]))
                  for k in sorted(self.program_parts) if k not in DisplayedPrograms]
        self.block("others").Label = "Not a program: " + ", ".join(others) if others else ""
        self.block("others").Show = bool(others)
        # Not remembered (the .dlx): on every time.
        self.block("edit_spreadsheets").Value = True
        self._update_bodies_block()

    def update(self, block: NXOpen.BlockStyler.UIBlock) -> None:
        if block == self.block("scope"):
            self._update_bodies_block()

    def enable_ok(self) -> bool:
        return (self._select_all() or len(self._picked_bodies()) > 0) and bool(self._checked_programs())

    def ok(self) -> bool:
        self.select_all = self._select_all()
        self.bodies = [] if self.select_all else self._picked_bodies()
        # enable_ok greys OK out; this is a backstop.
        if not self.select_all and not self.bodies:
            self.message("\"Select solids\" is chosen but no solid body is picked.")
            return False

        self.material = ConstructionMaterials.get(str(self.block("construction").ValueAsString), "S7")
        self.draw_columns = int(self.block("draw_columns").Value)
        self.draw_steels_per_row = int(self.block("draw_steels").Value)
        self.deadhit_rows = int(self.block("deadhit_rows").Value)
        self.deadhit_cols = int(self.block("deadhit_cols").Value)
        self.edit_spreadsheets = bool(self.block("edit_spreadsheets").Value)
        self.run_programs = self._checked_programs()
        if not self.run_programs:
            self.message("No program is checked - nothing to run.")
            return False
        return True

    def _checked_programs(self) -> Set[str]:
        return {p for p in DisplayedPrograms if bool(self.block("run_" + p).Value)}

    def _select_all(self) -> bool:
        return str(self.block("scope").ValueAsString) != "Select solids"

    def _update_bodies_block(self) -> None:
        """The body picker only means something for Select solids."""
        self.block("bodies").Show = not self._select_all()

    def _picked_bodies(self) -> List[NXOpen.Body]:
        return [cast(NXOpen.Body, o) for o in self.selected(self.block("bodies"))
                if isinstance(o, NXOpen.Body) and cast(NXOpen.Body, o).IsSolidBody]


def main() -> None:
    """The auto-design UFunc - its menu button runs this file. An escaping exception is printed."""
    import usage_db

    with usage_db.run(ufunc_name):
        try:
            AutoDesign.execute(True)
        except Exception as ex:
            nx.print_exception(ex)


if __name__ == "__main__":
    main()

"""
Python port of PierceMerlin (src\\UFuncs\\PierceMerlin.cs) - the pierce, pierce-secondary and full-pierce
UFuncs.
The C# wrappers were deleted 2026-10-22 (in git at 1cb53d8): the UFuncs' menu buttons run this file's main()
(pierce), FullPierce.py and PierceSecondary.py.

Pick slug bodies (english info units, display and work part). Each slug is classified by its top (+Z planar) face:
  - 1 circular edge                 -> round      (p = diameter)
  - 2 linear + 2 circular edges     -> oblong     (p = centre distance + diameter, w = diameter, both truncated to
                                                   2 decimals; the two arcs must have the same diameter)
  - 4 linear + 4 circular edges     -> rectangle  (p/w = straight edge + 2r, r = corner radius; squares included)
Anything else is printed and skipped. Every dimension is in millimetres and carried as the C# string.

The pierce and full-pierce UFuncs pick through one Block Styler dialog (Pierce.dlx, tools\\make-dlx.py, 2026-10-29):
the Customer radio (None / TSG / GM, None on opening; TSG uses the CTS parts), the slug bodies (anywhere in
the assembly) and a radio of the ops to place the details in - the display part's station numbers with both a ladNN
and a uadNN, read when the dialog opens (none is an error box before it; the work part's number, when it is a
station, is checked first). OK stays greyed out until TSG or GM is checked and a body is picked. AutoDesign passes
its station ("02") and the bodies straight to Pierce.build, with no dialog. Every button goes into that lad, every
punch and retainer into that uad (placed in the display part, then restructured under the station - same absolute
position - and added to the station's BODY reference set). The C# put all three straight into the display part.

Rounds are grouped by p, oblongs by p then w, rectangles by p, w then r. Per size group, in this order:
  1. size  - the button and punch diameters are looked up FIRST (a table miss costs only this group, before
             anything is placed or saved);
  2. place - a button (10 mm up), punch (.25" up) and flipped ball-lock retainer (3.7402" - .19689" up) per slug;
  3. save  - each of the three prototypes Save As'd to button- / punch- / retainer-{token}.prt beside the display
             part, stamped TYPE (round/oblong/rectangle), CSPC = X, GM Tool Number = X;
  4. configure - attributes first (what the secondary pass reads back), then expressions; the button's Main
             spreadsheet cells are written, recalculated, and Exp-Attr rows 3-31 copied into its expressions; the
             punch gets valueP/valueW/valueR/D + one-hot styleStandard*; the retainer's sheet gets the diameter in
             (3,4) and Exp-Attr rows 4-28 are copied, falling back to the hard-coded get_retainer_expressions table
             when the sheet applied nothing;
  5. collect - each detail joins the created list only after its configure returned.
Each size group has its own try/except naming the p/w/r, and each shape has another around it.

The secondary pass groups components by prototype and, by leaf prefix (button- / punch- / retainer-) and TYPE,
writes the Main sheet cells back from the attributes (slug type, steel-coating constant, the p > 40 flag).

Entry points:
  - Pierce.execute(is_gm)          <- PierceMerlin.StaticPierce             (pierce)
  - Pierce.build(is_gm, bodies)    <- PierceMerlin.RunPierce(bool, Body[])  (AutoDesign's build half; no units gate)
  - PierceSecondary.execute(is_gm) <- PierceMerlin.StaticSecondaryPierce    (pierce-secondary)
  - FullPierce.execute(is_gm)      <- PierceMerlin.StaticPierceAndSecondary (full-pierce)
  - super_pierce(is_gm)              <- PierceMerlin.SuperPierce              (no UFunc; dev scratch only)
File -> Execute -> NX Open on this file runs main(), i.e. pierce with is_gm = True. From C#:
Session.Execute("Pierce.py", "Pierce", "execute", is_gm). is_gm is accepted and ignored, as in the C#.

Ported from the CURRENT PierceMerlin.cs, which has moved on from .claude\\merlin.md: there is no
WriteButtonSpreadsheet1 stub any more, the punch- and retainer- branches of the secondary pass are live, every
button/retainer configure runs a sheet pass (ApplySheetExpressions with per-detail Exp-Attr row ranges), and the
retainer falls back to get_retainer_expressions only when its sheet applied nothing. PlacePierceButton still uses
the scratch seed _gmButtonPath1 (G:\\CTS\\junk\\merlin\\Smart GM Button1.prt), kept.

Not ported: set_round_punch / set_rectangle_punch (empty bodies, never called) and the commented-out set_* methods;
RectangleSlug's g_lin_edges lookup (built and never read). Nothing else is left out.

Differences from the C# / uncertainties (none of this has been run in NX):
  - Modeling spreadsheet. The calls are the NXOpen ones the C# uses, and every one is present in NX2406's
    NXOpen.pyd docstrings: Session.SpreadsheetManager, SpreadsheetManager.Open(Sheettype.Modeling, partfile),
    CreateCellData(), SpreadsheetCellData.DoubleValue / StringValue / Type (Types.String), Spreadsheet.
    GetSheetNumberOfName(name), SetNumber(row, col, cellvalue, sheet), GetValue(row, col, sheet), Recalculate(),
    Save(), Terminate(). The stubs have none of them, so they go through Any. Not seen in NX: whether the Python
    Spreadsheet behaves like the .NET one (Excel launched/terminated the same way), and str(cell) in the per-row
    error message prints the Python object rather than the .NET ToString().
  - Edge radius / centre use UF_EVAL_ask_arc (ufsession_.Eval.AskArc, in NXOpen_UF.pyd but not the stubs) and read
    the struct as arc.Radius / arc.Center (stubs/NXOpen/UF.pyi Eval.Arc). The edge mid point uses
    EvaluateUnitVectors at the mid parameter, since the Python UFEval has no Evaluate.
  - Vector3d.__IsIsParallelTo (UF_VEC3_is_parallel, tolerance .0001) is computed here: |a x b| <= .0001 |a||b|.
    Rectangle edges are either parallel or perpendicular, so the tolerance's exact meaning does not matter.
  - The pierce / full-pierce pick is the Pierce dialog (above); the C# was the SNAP select_solid_bodies plus the
    station menu. super_pierce still picks through DrawDie._select_bodies and the menu.
  - NormalizeSlugDimension is Python round(x, 6); .NET Math.Round(x, 6) can differ only on an exact binary
    midpoint at the 7th decimal, which slug noise never produces.
  - The C# exception types are mirrored by name (ArgumentOutOfRangeException, ArgumentException,
    InvalidOperationException) so print_exception's "Exception:" line reads the same. Messages follow .NET's.
  - NX enum values print through _enum_name ("Elliptical"), assuming str() of a Python NXOpen enum ends in the
    member name.
  - Session.Execute cannot hand a return value back to C#, so Pierce.build's returned list is only useful to
    Python callers.

The Merlin helpers DrawDie.py and PointComponent.py already port (CheckInfoUnits, the body pick, TimeSpan
printing, RandomFileToken) are imported from them rather than copied.
"""

from __future__ import annotations

import datetime
import math
import os
import sys
from typing import Any, Callable, Dict, Iterable, List, NamedTuple, Optional, Sequence, Tuple, TypeVar, cast

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
import NXOpen.UF  # noqa: E402
import tsg_nx as nx  # noqa: E402
import PointComponent as merlin  # noqa: E402
import DrawDie as drawdie  # noqa: E402
from tsg_dialog import is_gm_customer, title_with_version  # noqa: E402

_T = TypeVar("_T")
_K = TypeVar("_K")

Component = NXOpen.Assemblies.Component

# ---------------------------------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------------------------------

# Decimal places a slug dimension is rounded to before a table lookup.
SlugDimensionDecimals = 6

# Exp-Attr row range ApplySheetExpressions walks - each detail type's sheet has its own layout.
ButtonExpAttrFirstRow = 3
ButtonExpAttrLastRow = 31
RetainerExpAttrFirstRow = 4
RetainerExpAttrLastRow = 28

_gmButtonPath1 = "G:\\CTS\\junk\\merlin\\Smart GM Button1.prt"
_gmButtonPath = "G:\\0Library\\0Customer\\GM\\Smart GM Button.prt"  # unused, as in the C#
_gmPunchPath = "G:\\CTS\\junk\\merlin\\Smart GM Punch.prt"
_gmBallLockRetainerPath = "G:\\CTS\\junk\\merlin\\Smart GM HD Ball Lock Retainer.prt"

_VectorZ = NXOpen.Vector3d(0.0, 0.0, 1.0)

# True while a Pierce.build(..., skip_spreadsheets=True) runs - every detail's modeling sheet is left unopened.
# AutoDesign sets it in DebugSignDotNet builds, for now.
_skip_spreadsheets = False
_VectorZN = NXOpen.Vector3d(0.0, 0.0, -1.0)


# ---------------------------------------------------------------------------------------------------
# .NET exception names, so print_exception's "Exception:" line matches the C#
# ---------------------------------------------------------------------------------------------------

class ArgumentOutOfRangeException(ValueError):
    """System.ArgumentOutOfRangeException"""

    def __init__(self, message: str = "Specified argument was out of the range of valid values.") -> None:
        super().__init__(message)


class ArgumentException(ValueError):
    """System.ArgumentException"""


class InvalidOperationException(Exception):
    """System.InvalidOperationException"""


# ---------------------------------------------------------------------------------------------------
# Slug POCOs
# ---------------------------------------------------------------------------------------------------

class Round(object):
    """PierceMerlin's Round - origin, orientation and the dimension strings (mm)."""

    def __init__(self, origin: NXOpen.Point3d, orientation: NXOpen.Matrix3x3, thickness: str, p: str) -> None:
        self.origin = origin
        self.orientation = orientation
        self.thickness = thickness
        self.p = p


class Oblong(object):
    """PierceMerlin's Oblong (its unused diameter field is dropped)."""

    def __init__(self, origin: NXOpen.Point3d, orientation: NXOpen.Matrix3x3, thickness: str, p: str,
                 w: str) -> None:
        self.origin = origin
        self.orientation = orientation
        self.thickness = thickness
        self.p = p
        self.w = w


class Rectangle(object):
    """PierceMerlin's Rectangle - squares included."""

    def __init__(self, origin: NXOpen.Point3d, orientation: NXOpen.Matrix3x3, thickness: str, p: str, w: str,
                 r: str) -> None:
        self.origin = origin
        self.orientation = orientation
        self.thickness = thickness
        self.p = p
        self.w = w
        self.r = r


# ---------------------------------------------------------------------------------------------------
# UFunc classes
# ---------------------------------------------------------------------------------------------------

class Pierce(object):

    @staticmethod
    def execute(is_gm: bool = True) -> None:
        """PierceMerlin.StaticPierce(is_gm) - the pierce UFunc passes is_gm = True."""
        static_pierce(is_gm)

    @staticmethod
    def build(is_gm: bool, bodies: Sequence[NXOpen.Body], skip_spreadsheets: bool = False,
              quiet: bool = False, station: Optional[str] = None) -> List[Component]:
        """
        PierceMerlin.RunPierce(bool, Body[]) - the build half on bodies the caller picked. No units gate.
        skip_spreadsheets leaves every detail's modeling sheet unopened (AutoDesign, DebugSignDotNet builds); quiet
        leaves out the elapsed time and "Created reference set" lines (AutoDesign); station ("02") builds into that
        ladNN / uadNN without the station menu (AutoDesign).
        """
        global _skip_spreadsheets
        _skip_spreadsheets = bool(skip_spreadsheets)
        try:
            with nx.quiet_listing(quiet):
                return run_pierce_bodies(is_gm, list(bodies), station)
        finally:
            _skip_spreadsheets = False


class PierceSecondary(object):

    @staticmethod
    def execute(is_gm: bool = True) -> None:
        """PierceMerlin.StaticSecondaryPierce(is_gm) - the pierce-secondary UFunc passes is_gm = True."""
        static_secondary_pierce(is_gm)


class FullPierce(object):

    @staticmethod
    def execute(is_gm: bool = True) -> None:
        """PierceMerlin.StaticPierceAndSecondary(is_gm) - the full-pierce UFunc passes is_gm = True."""
        static_pierce_and_secondary(is_gm)


# ---------------------------------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------------------------------

def static_pierce(is_gm: bool) -> None:
    """PierceMerlin.StaticPierce => RunPierce(is_gm)."""
    run_pierce(is_gm)


def run_pierce(is_gm: bool, label: str = "Pierce") -> List[Component]:
    """
    PierceMerlin.RunPierce(bool) - units gate, then the Pierce dialog (customer, slug bodies, op), then the build.
    [] on gate failure or cancel. The dialog's Customer radio decides is_gm (TSG uses the CTS parts); the
    argument is not used.
    """
    picked = _ask_pierce(label)

    if picked is None:
        return []

    is_gm, bodies, station = picked
    return run_pierce_bodies(is_gm, bodies, station)


def run_pierce_bodies(is_gm: bool, bodies: List[NXOpen.Body], station: Optional[str] = None) -> List[Component]:
    """
    PierceMerlin.RunPierce(bool, Body[]) - classify the slugs and drop a button/punch/retainer trio per size group.
    Returns every detail created, in drop order. Does not gate on the units; the caller brings that. station ("02")
    skips the station menu.
    """
    created: List[Component] = []

    stations = _pick_pierce_stations(station)
    if stations is None:
        return created

    mark_id = nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, "Update from spreadsheet")

    _set_default_update_failure_accept_all()

    time = datetime.datetime.now()

    with nx.suppress_display():
        oblongs: List[Oblong] = []
        rounds: List[Round] = []
        rectangles: List[Rectangle] = []

        nx.prompt("Classifying {} slug(s)".format(len(bodies)))
        _classify_slugs(bodies, rounds, oblongs, rectangles)
        nx.prompt("{} round, {} oblong, {} rectangle slug(s)".format(len(rounds), len(oblongs), len(rectangles)))

        try:
            _add_rounds(rounds, created, stations)
        except Exception as ex:
            nx.print_exception(ex)

        try:
            _add_oblongs(oblongs, created, stations)
        except Exception as ex:
            nx.print_exception(ex)

        try:
            _add_rectangles(rectangles, created, stations)
        except Exception as ex:
            nx.print_exception(ex)

    nx.set_work_part(nx.display_part())
    nx.session_.UpdateManager.DoUpdate(mark_id)
    if not nx.quiet:
        nx.warn(drawdie._time_span(datetime.datetime.now() - time))
    return created


def static_pierce_and_secondary(is_gm: bool) -> None:
    """
    PierceMerlin.StaticPierceAndSecondary - the pierce, then the secondary pass over what it created, with one pick.
    The display and work parts are restored afterwards (the secondary pass leaves the last detail as work part).
    """
    top_level = nx.display_part()

    try:
        created = run_pierce(is_gm, "Full Pierce")

        if len(created) == 0:
            nx.warn("Pierce created no components - skipping the secondary pass.")
            return

        _process_secondary_pierce(created)
    finally:
        nx.set_display_part(top_level)
        nx.set_work_part(top_level)


def super_pierce(is_gm: bool) -> None:
    """
    PierceMerlin.SuperPierce - the combined pass with its own cue text and undo mark; the same builders, each shape
    in its own try/except. No UFunc runs it.
    """
    top_level = nx.display_part()

    try:
        created = _run_super_pierce(is_gm)

        if len(created) == 0:
            nx.warn("Super pierce created no components - skipping the secondary pass.")
            return

        _process_secondary_pierce(created)
    finally:
        nx.set_display_part(top_level)
        nx.set_work_part(top_level)


def _run_super_pierce(is_gm: bool) -> List[Component]:
    """PierceMerlin.RunSuperPierce - note the undo mark and failure action are set before the pick, as in the C#."""
    created: List[Component] = []

    mark_id = nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, "Super pierce")

    _set_default_update_failure_accept_all()

    bodies = _try_begin_pierce("Super Pierce")

    if bodies is None:
        return created

    stations = _pick_pierce_stations()
    if stations is None:
        return created

    time = datetime.datetime.now()

    with nx.suppress_display():
        oblongs: List[Oblong] = []
        rounds: List[Round] = []
        rectangles: List[Rectangle] = []

        _classify_slugs(bodies, rounds, oblongs, rectangles)

        # One try/except per shape, so a shape that blows up outside its own per-group handler doesn't cost the
        # other two.
        try:
            _add_rounds(rounds, created, stations)
        except Exception as ex:
            nx.print_exception(ex)

        try:
            _add_oblongs(oblongs, created, stations)
        except Exception as ex:
            nx.print_exception(ex)

        try:
            _add_rectangles(rectangles, created, stations)
        except Exception as ex:
            nx.print_exception(ex)

    nx.set_work_part(nx.display_part())
    nx.session_.UpdateManager.DoUpdate(mark_id)
    if not nx.quiet:
        nx.warn(drawdie._time_span(datetime.datetime.now() - time))
    return created


def static_secondary_pierce(is_gm: bool) -> None:
    """PierceMerlin.StaticSecondaryPierce - units gate, pick components, then the secondary pass."""
    ok, message = drawdie._check_info_units()
    if not ok:
        nx.show_error(message)
        return

    components = nx.select_many_components("Select pierce components to sort by prototype part")

    if components is None or len(components) == 0:
        return

    _process_secondary_pierce(components)


def _try_begin_pierce(label: str) -> Optional[List[NXOpen.Body]]:
    """PierceMerlin.TryBeginPierce - the units gate and the slug-body pick; None on gate failure or cancel."""
    ok, message = drawdie._check_info_units()
    if not ok:
        nx.show_error(message)
        return None

    version = nx.assembly_file_version()
    bodies = [body for body in drawdie._select_bodies("Select slug bodies for {}: {}".format(label, version),
                                                     "{}: {}".format(label, version))
              if body.IsSolidBody]

    # select_solid_bodies reports an empty OK as not selected.
    if len(bodies) == 0:
        return None

    return bodies


# ---------------------------------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------------------------------

def _classify_slugs(bodies: Iterable[NXOpen.Body], rounds: List[Round], oblongs: List[Oblong],
                    rectangles: List[Rectangle]) -> None:
    """
    PierceMerlin.ClassifySlugs - sorts the slugs into rounds, oblongs and rectangles by their top face's edges.
    Missing faces, invalid edges and unknown edge counts print and skip the body. A throw from OblongSlug /
    RectangleSlug is not caught here, as in the C# (it ends the whole build).
    """
    for body in bodies:
        try:
            top_face = _first(body.GetFaces(), lambda f: _is_planar(f) and nx.vectors_equal(nx.face_normal(f), _VectorZ))
        except Exception as ex:
            nx.print_("body {} has no top face".format(body.Tag))
            nx.print_exception(ex)
            continue

        try:
            bottom_face = _first(body.GetFaces(),
                                 lambda f: _is_planar(f) and nx.vectors_equal(nx.face_normal(f), _VectorZN))
        except Exception as ex:
            nx.print_("body {} has no bottom face".format(body.Tag))
            nx.print_exception(ex)
            continue

        thickness = _slug_thickness(top_face, bottom_face)

        top_edges = top_face.GetEdges()

        # round slug
        if len(top_edges) == 1 and top_edges[0].SolidEdgeType == NXOpen.Edge.EdgeType.Circular:
            edge = top_edges[0]
            radius, center = _edge_arc(edge)

            rounds.append(Round(origin=center,
                                orientation=nx.identity_matrix(),
                                thickness=thickness,
                                p=nx.cs_double_str(radius * 2 * 25.4)))
            continue

        invalid_edges = [e for e in top_edges
                         if e.SolidEdgeType != NXOpen.Edge.EdgeType.Linear
                         and e.SolidEdgeType != NXOpen.Edge.EdgeType.Circular]

        if len(invalid_edges) > 0:
            nx.print_("///////")
            nx.print_("body {} has invalid edges".format(body.Tag))
            for edge in invalid_edges:
                nx.print_("edge type == {}".format(_enum_name(edge.SolidEdgeType)))
            nx.print_("///////")
            continue

        lin_edges = [e for e in top_edges if e.SolidEdgeType == NXOpen.Edge.EdgeType.Linear]
        cir_edges = [e for e in top_edges if e.SolidEdgeType == NXOpen.Edge.EdgeType.Circular]

        # oblong slug
        if len(lin_edges) == 2 and len(cir_edges) == 2:
            if _oblong_slug(oblongs, top_face, bottom_face, cir_edges):
                continue

        # rounded rectangle slug
        if len(lin_edges) == 4 and len(cir_edges) == 4:
            _rectangle_slug(rectangles, top_face, bottom_face, lin_edges, cir_edges)
            continue

        for edge in top_edges:
            nx.print_("edge type == {}".format(_enum_name(edge.SolidEdgeType)))

        nx.print_("unknown edge length == {}".format(len(top_edges)))


def _rectangle_slug(rectangles: List[Rectangle], top_face: NXOpen.Face, bottom_face: NXOpen.Face,
                    lin_edges: List[NXOpen.Edge], cir_edges: List[NXOpen.Edge]) -> bool:
    """PierceMerlin.RectangleSlug - p/w are the straight edges + 2r, the origin is between the two short edges."""
    temp_edges = list(lin_edges)
    edge1 = temp_edges.pop(0)
    edge2 = _first(temp_edges, lambda e: _is_parallel(_edge_vector(e), _edge_vector(edge1)))
    radius, _center = _edge_arc(cir_edges[0])
    other_edges = _distinct_by_tag(e for e in lin_edges if e.Tag not in (edge1.Tag, edge2.Tag))

    # .ToString() then double.Parse - the round trip to 15 significant digits is kept.
    if edge1.GetLength() < other_edges[0].GetLength():
        min_edges = [edge1, edge2]
        min_length = nx.cs_double_str(edge1.GetLength())
        max_length = nx.cs_double_str(other_edges[0].GetLength())
    else:
        min_edges = other_edges
        min_length = nx.cs_double_str(other_edges[0].GetLength())
        max_length = nx.cs_double_str(edge1.GetLength())

    mid0 = _edge_mid_point(min_edges[0])
    mid1 = _edge_mid_point(min_edges[1])
    origin = nx.mid_point(mid0, mid1)
    vec = NXOpen.Vector3d(mid0.X - mid1.X, mid0.Y - mid1.Y, mid0.Z - mid1.Z)

    orientation = _set_wcs_to_slug(origin, vec)

    p_value = float(max_length) * 25.4 + radius * 25.4 * 2
    w_value = float(min_length) * 25.4 + radius * 25.4 * 2

    slug_thickness = _slug_thickness(top_face, bottom_face)

    # Squares are rectangles - they go through the rectangle tables like any other slug.
    rectangles.append(Rectangle(orientation=orientation,
                                origin=origin,
                                thickness=slug_thickness,
                                p=nx.cs_double_str(p_value),
                                w=nx.cs_double_str(w_value),
                                r=nx.cs_double_str(radius * 25.4)))

    _set_wcs_to_absolute()
    return True


def _oblong_slug(oblongs: List[Oblong], top_face: NXOpen.Face, bottom_face: NXOpen.Face,
                 cir_edges: List[NXOpen.Edge]) -> bool:
    """PierceMerlin.OblongSlug - False (not an oblong) when the two arcs' diameters differ by more than .001."""
    radius1, center1 = _edge_arc(cir_edges[0])
    p_diameter1 = radius1 * 2

    radius2, center2 = _edge_arc(cir_edges[1])
    p_diameter2 = radius2 * 2

    if not nx.doubles_equal(p_diameter1, p_diameter2):
        return False

    origin = nx.mid_point(center1, center2)
    x_axis = NXOpen.Vector3d(center1.X - center2.X, center1.Y - center2.Y, center1.Z - center2.Z)

    orientation = _set_wcs_to_slug(origin, x_axis)

    oblongs.append(Oblong(orientation=orientation,
                          origin=origin,
                          thickness=_slug_thickness(top_face, bottom_face),
                          p=_truncated_string((nx.distance(center1, center2) + p_diameter1) * 25.4, 2),
                          w=_truncated_string(p_diameter1 * 25.4, 2)))

    _set_wcs_to_absolute()
    return True


def _set_wcs_to_slug(origin: NXOpen.Point3d, v: NXOpen.Vector3d) -> NXOpen.Matrix3x3:
    """
    The orientation block OblongSlug and RectangleSlug share: X = v flattened to the XY plane, Y = Z x X, Z = world
    up, then __RotateZ(-90). The C# parks the display part's WCS there and reads Snap.Globals.WcsOrientation back,
    so this does too.
    """
    x_len = math.sqrt(v.X * v.X + v.Y * v.Y)

    x_dir = NXOpen.Vector3d(v.X / x_len, v.Y / x_len, 0.0)
    y_dir = _cross(_VectorZ, x_dir)
    m = _matrix_from_rows(x_dir, y_dir, _VectorZ)

    # __Rotate(-90) (clockwise) == the old WCS.Rotate(ZAxis, 90) (CCW).
    nx.display_part().WCS.SetOriginAndMatrix(origin, _rotate_z(m, -90))
    return nx.display_part().WCS.CoordinateSystem.Orientation.Element


def _set_wcs_to_absolute() -> None:
    """sess.SetWcs() - the display part's WCS back to absolute."""
    nx.display_part().WCS.SetOriginAndMatrix(NXOpen.Point3d(0.0, 0.0, 0.0), nx.identity_matrix())


def _slug_thickness(top_face: NXOpen.Face, bottom_face: NXOpen.Face) -> str:
    """|top face's first edge start Z - bottom face's first edge start Z| * 25.4, as double.ToString()."""
    top_z = nx.edge_start_point(top_face.GetEdges()[0]).Z
    bottom_z = nx.edge_start_point(bottom_face.GetEdges()[0]).Z
    return nx.cs_double_str(abs(top_z - bottom_z) * 25.4)


# ---------------------------------------------------------------------------------------------------
# Diameter lookup tables. p and w are in millimetres.
#
# NOTE: when p > 40 the nose shank has to be checked. These tables size the button and punch from p/w alone and say
# nothing about the shank. The secondary pass writes the p > 40 flag (Main (5,16) = 2) into the button and punch
# sheets; choosing the shank is still manual.
# ---------------------------------------------------------------------------------------------------

def _normalize_slug_dimension(mm: float) -> float:
    """
    PierceMerlin.NormalizeSlugDimension - rounds to 6 decimals before a table compares it, so mm values computed from
    inch geometry (8.49999999999939 for a nominal 8.5) do not fall off a row bound. Every get_*_diameter table calls it
    on each argument first.
    """
    return round(mm, SlugDimensionDecimals)


# The ranges are the Min P / Max P and Min W / Max W columns of the Validation sheet in each seed part's modeling
# spreadsheet (read 2026-10-23): the button (_gmButtonPath1) has a Taper and a Cbore row per body diameter, the punch
# (_gmPunchPath) a Standard row per diameter (its Nose Large rows are not used). The XP / XW (extended) columns are
# not used. Rows are (body diameter, min p, max p, min w, max w), in mm, smallest diameter first; the first row whose
# ranges hold the slug wins. A round button is the Cbore style (the seed's), oblong and rectangle buttons Taper (their
# configure sets styleTaperOblong / styleTaperRectangle), every punch Standard. The retainer is sized by the punch
# diameter (its sheet has no Validation sheet; its Lists are the punch's 10-40). If a seed's sheet changes, re-read it.
_ButtonCboreRanges = (
    (10, 1.2, 5, 1.2, 5),
    (13, 1.5, 7.2, 2, 7.2),
    (16, 2.4, 8.8, 2.4, 8.8),
    (20, 3.2, 11, 3.2, 11),
    (22, 4, 14, 4, 14),
    (25, 4.8, 16.5, 4.8, 16.5),
    (32, 5.5, 20, 5.5, 20),
    (38, 6.4, 26, 6.4, 26),
    (45, 9, 35, 8, 35),
    (50, 13, 40, 9, 40),
    (56, 16.5, 45, 10, 45),
    (63, 16.5, 50, 11, 50),
    (71, 18, 56, 12, 56),
    (76, 20, 60, 15, 60),
    (85, 26, 66, 21, 66),
    (90, 26, 70, 25, 70),
    (100, 35, 78, 33, 78),
    (125, 40, 103, 35, 103),
)
_ButtonTaperRanges = (
    (10, 1.3, 6.8, 1.3, 6.8),
    (13, 1.9, 8.8, 1.9, 8.8),
    (16, 1.9, 10.8, 1.9, 10.8),
    (20, 1.9, 13.6, 1.9, 13.6),
    (22, 1.9, 15, 1.9, 15),
    (25, 1.9, 17, 1.9, 17),
    (32, 1.9, 22, 1.9, 22),
    (38, 1.9, 27, 1.9, 27),
    (45, 2.4, 35, 2.4, 35),
    (50, 4, 40, 4, 40),
    (56, 4, 45, 4, 45),
    (63, 4, 50, 4, 50),
    (71, 4, 56, 4, 56),
    (76, 5.6, 60, 5.6, 60),
    (85, 5.6, 66, 5.6, 66),
    (90, 5.6, 70, 5.6, 70),
    (100, 5.6, 78, 5.6, 78),
    (125, 6, 103, 6, 103),
)
_PunchStandardRanges = (
    (10, 2.1, 9.97, 2.1, 9.97),
    (13, 4.5, 12.97, 4.5, 12.97),
    (16, 6, 15.97, 6, 15.97),
    (20, 8, 19.97, 8, 19.97),
    (25, 10, 24.97, 10, 24.97),
    (32, 12.5, 31.97, 12.5, 31.97),
    (40, 14, 39.97, 14, 39.97),
)


def _first_fitting(ranges, p: float, w: Optional[float] = None) -> Optional[int]:
    """The smallest body diameter in ranges whose [min p, max p] holds p (and [min w, max w] holds w, when given)."""
    p = _normalize_slug_dimension(p)
    w = None if w is None else _normalize_slug_dimension(w)

    for diameter, min_p, max_p, min_w, max_w in ranges:
        if min_p <= p <= max_p and (w is None or min_w <= w <= max_w):
            return diameter

    return None


def get_round_button_diameter(p: float) -> float:
    """PierceMerlin.get_round_button_diameter (returns double in the C#) - now the button's Cbore Validation rows."""
    diameter = _first_fitting(_ButtonCboreRanges, p)

    if diameter is None:
        raise ArgumentOutOfRangeException()

    return float(diameter)


def get_round_punch_diameter(p: float) -> int:
    """PierceMerlin.get_round_punch_diameter - now the punch's Standard Validation rows."""
    diameter = _first_fitting(_PunchStandardRanges, p)

    if diameter is None:
        raise ArgumentOutOfRangeException()

    return diameter


def get_oblong_punch_diameter(p: float) -> int:
    """PierceMerlin.get_oblong_punch_diameter(double p) - throws ArgumentException, not ...OutOfRange..."""
    diameter = _first_fitting(_PunchStandardRanges, p)

    if diameter is None:
        raise ArgumentException("p={}".format(nx.cs_double_str(_normalize_slug_dimension(p))))

    return diameter


def get_oblong_button_diameter(w: float, p: float) -> float:
    """PierceMerlin.get_oblong_button_diameter (returns double in the C#) - now the button's Taper Validation rows."""
    diameter = _first_fitting(_ButtonTaperRanges, p, w)

    if diameter is None:
        raise ArgumentOutOfRangeException()

    return float(diameter)


def get_rectangle_punch_diameter(p: float) -> int:
    """PierceMerlin.get_rectangle_punch_diameter - now the punch's Standard Validation rows."""
    diameter = _first_fitting(_PunchStandardRanges, p)

    if diameter is None:
        # ArgumentOutOfRangeException(nameof(p), p.ToString()) - .NET appends the parameter name to the message.
        raise ArgumentOutOfRangeException(
            "{}\nParameter name: p".format(nx.cs_double_str(_normalize_slug_dimension(p))))

    return diameter


def get_rectangle_button_diameter(w: float, p: float) -> int:
    """PierceMerlin.get_rectangle_button_diameter - squares come through here too; the button's Taper rows."""
    diameter = _first_fitting(_ButtonTaperRanges, p, w)

    if diameter is None:
        raise ArgumentOutOfRangeException()

    return diameter


class RetainerExpressions(NamedTuple):
    """get_retainer_expressions' out parameters, in their C# order (the tests' slot n is index n - 1 here)."""
    l: float
    w: float
    g: float
    k: float
    r: float
    s: float
    u: float
    x: float
    y: float
    thk: float
    cbore_depth: float
    cbore_dia: float
    clr_hole: float
    dwl_dia: float
    dwl_6mm_020_a: int
    shcs_8mm_045: int
    shcs_10mm_045: int
    shcs_12mm_050: int
    dwl_1: int
    dwl_shape: int
    retainer_angle: float
    dwl_6mm_020_b: int
    flat: int


def get_retainer_expressions(d: int) -> RetainerExpressions:
    """
    PierceMerlin.get_retainer_expressions - the ball-lock retainer table, now only the fallback when the retainer's
    sheet applies nothing. Rows for 10/13/16/20/25/32/40; d = 32 shares d = 25's row on purpose (the 32 retainer uses
    the 25 body). Anything else returns all zeros rather than raising.
    """
    if d == 10:
        return RetainerExpressions(35.0, 43.7, 11.1, 19.0, 9.5, 12.0, 26.93, 9.0, 7.5,
                                   41.0, 9.5, 14.0, 9.0, 6.0,
                                   1, 1, 0, 0,
                                   1, 1, 29.0, 1, 1)
    if d == 13:
        return RetainerExpressions(38.1, 50.0, 14.3, 19.0, 12.7, 15.2, 29.97, 12.0, 6.0,
                                   41.0, 9.5, 14.0, 9.0, 6.0,
                                   1, 1, 0, 0,
                                   1, 1, 29.0, 1, 1)
    if d == 16:
        return RetainerExpressions(39.7, 53.2, 15.9, 19.0, 14.3, 16.8, 31.75, 13.5, 6.0,
                                   41.0, 9.5, 14.0, 9.0, 6.0,
                                   1, 1, 0, 0,
                                   1, 1, 29.0, 1, 1)
    if d == 20:
        return RetainerExpressions(42.8, 59.5, 17.5, 19.0, 17.5, 20.0, 33.53, 16.5, 5.0,
                                   41.0, 11.5, 17.0, 11.0, 6.0,
                                   1, 0, 1, 0,
                                   1, 1, 29.0, 1, 1)
    # 32 shares the 25 retainer body - one branch, intentionally.
    if d == 25 or d == 32:
        return RetainerExpressions(47.7, 69.1, 19.8, 23.8, 22.2, 24.7, 40.64, 22.0, 7.0,
                                   41.0, 13.5, 20.0, 13.5, 6.0,
                                   1, 0, 1, 0,
                                   1, 1, 29.0, 1, 1)
    if d == 40:
        return RetainerExpressions(51.4, 76.6, 24.0, 27.0, 26.0, 28.5, 43.99, 26.0, 10.0,
                                   41.0, 13.5, 20.0, 13.5, 6.0,
                                   1, 0, 1, 1,
                                   1, 1, 29.0, 1, 1)
    return RetainerExpressions(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
                               0.0, 0.0, 0.0, 0.0, 0.0,
                               0, 0, 0, 0,
                               0, 0, 0.0, 0, 0)


# ---------------------------------------------------------------------------------------------------
# Placement and SaveAs
# ---------------------------------------------------------------------------------------------------

def _place_pierce_button(origin: NXOpen.Point3d, orientation: NXOpen.Matrix3x3) -> Component:
    """PierceMerlin.PlacePierceButton - 10 mm above the slug origin (the scratch seed _gmButtonPath1, as in the C#)."""
    return nx.add_component(nx.display_part(), _gmButtonPath1, reference_set="BODY",
                            origin=nx.add_z(origin, 10 / 25.4), orientation=orientation)


def _place_pierce_punch(origin: NXOpen.Point3d, orientation: NXOpen.Matrix3x3) -> Component:
    """PierceMerlin.PlacePiercePunch - .25 above the slug origin."""
    return nx.add_component(nx.display_part(), _gmPunchPath, reference_set="BODY",
                            origin=nx.add_z(origin, .25), orientation=orientation)


def _place_pierce_retainer(origin: NXOpen.Point3d, orientation: NXOpen.Matrix3x3) -> Component:
    """PierceMerlin.PlacePierceRetainer - 3.7402 then -.19689291339 up (two adds, as the C# chains them), flipped."""
    return nx.add_component(nx.display_part(), _gmBallLockRetainerPath, reference_set="BODY",
                            origin=nx.add_z(nx.add_z(origin, 3.7402), -0.19689291339),
                            orientation=nx.matrix_from_axes(nx.negate(nx.axis_x(orientation)),
                                                            nx.negate(nx.axis_y(orientation))))


def _place_pierce_components(origin: NXOpen.Point3d, orientation: NXOpen.Matrix3x3,
                             stations: _PierceStations) -> Tuple[Component, Component, Component]:
    """
    PierceMerlin.PlacePierceComponents - button, punch, retainer, each measured from the origin itself. Each is
    placed in the display part, then moved under its station: the button into lad, the punch and retainer into uad.
    """
    button = _move_into_station(_place_pierce_button(origin, orientation), stations.lad)
    punch = _move_into_station(_place_pierce_punch(origin, orientation), stations.uad)
    retainer = _move_into_station(_place_pierce_retainer(origin, orientation), stations.uad)
    return button, punch, retainer


# ---------------------------------------------------------------------------------------------------
# Stations
# ---------------------------------------------------------------------------------------------------

class _PierceStations(NamedTuple):
    """The lad / uad station occurrences (under the display part) the pierce details go into."""
    number: str
    lad: Component
    uad: Component


# UF_UI_display_menu shows at most 14 items.
_MaxMenuItems = 14


def _find_pierce_stations() -> Dict[str, Dict[str, Component]]:
    """Op number ("02") -> {"lad": ..., "uad": ...} occurrences with both under the display part (DrawDie's lookup)."""
    return drawdie.find_op_stations()


def _ask_pierce(label: str) -> Optional[Tuple[bool, List[NXOpen.Body], str]]:
    """
    The units gate, then the Pierce dialog titled '{version} - label': (is_gm, slug bodies, station number) once it
    is accepted. None after an error box (units, no station) or when it is cancelled (Dialog.run marked the run
    cancelled). TSG uses the CTS parts.
    """
    ok, message = drawdie._check_info_units()
    if not ok:
        nx.show_error(message)
        return None

    numbers = sorted(_find_pierce_stations())
    if len(numbers) == 0:
        nx.show_error("No op with both a ladNN and a uadNN assembly was found under {}.".format(
            nx.display_part().Leaf))
        return None

    dialog = drawdie.OpBodiesDialog("Pierce.dlx", title_with_version(label), numbers, "Select the slug bodies.")
    if not dialog.run():
        return None

    return is_gm_customer(dialog.customer_choice), dialog.bodies, dialog.station


def _pick_pierce_stations(station: Optional[str] = None) -> Optional[_PierceStations]:
    """
    The station numbers with both a ladNN and a uadNN under the display part. station ("02") is used when present;
    otherwise one is used as is and several are offered in a menu. None (after an error box) when there are none or
    station is missing, or (silently, the run marked cancelled) when the menu is cancelled.
    """
    found = _find_pierce_stations()
    numbers = sorted(found)

    if station is not None:
        if station not in numbers:
            nx.show_error("Pierce: lad{0} / uad{0} was not found under {1} - no pierce details built.".format(
                station, nx.display_part().Leaf))
            nx.progress("Pierce: lad{0} / uad{0} not found - nothing built.".format(station))
            return None
        number = station
    elif len(numbers) == 0:
        nx.show_error("No station with both a ladNN and a uadNN assembly was found under {}.".format(
            nx.display_part().Leaf))
        return None
    elif len(numbers) == 1:
        number = numbers[0]
    else:
        options = numbers[:_MaxMenuItems]
        if len(numbers) > len(options):
            nx.warn("Pierce: only the first {} of {} stations fit the menu.".format(len(options), len(numbers)))
        # DisplayMenu is not in the hand-written UFUi stub. Items start at response 5.
        response = int(cast(Any, nx.ufsession_.Ui).DisplayMenu("Pierce into station", 0, options, len(options)))
        index = response - 5
        if not 0 <= index < len(options):
            # A cancel prints nothing: the syslog and the run's END banner only.
            nx.syslog("Pierce: no station picked (menu response {}) - nothing built.".format(response))
            nx.mark_cancelled("the station menu")
            return None
        number = options[index]

    stations = _PierceStations(number, found[number]["lad"], found[number]["uad"])
    # Syslog only (2026-10-29): the station is already the one picked in the dialog.
    nx.syslog("Pierce: buttons into {}, punches and retainers into {}".format(stations.lad.DisplayName,
                                                                              stations.uad.DisplayName))
    return stations


def _move_into_station(component: Component, station: Component) -> Component:
    """
    Restructures component (an occurrence in the display part) under station, keeping its absolute position, and adds
    it to the station's BODY reference set. Returns the new occurrence (the original is deleted).
    """
    nx.set_work_part(nx.display_part())
    moved, errors = nx.display_part().ComponentAssembly.RestructureComponents([component], station, True)
    try:
        messages = [errors.GetErrorInfo(i).Description for i in range(errors.Length)]
    finally:
        errors.Dispose()

    if moved is None or len(moved) == 0:
        raise InvalidOperationException("Could not move {} into {}: {}".format(
            component.DisplayName, station.DisplayName, "; ".join(messages) or "no component returned"))

    for message in messages:
        nx.warn("Pierce: restructure into {} - {}".format(station.DisplayName, message))

    new_component = cast(Component, moved[0])
    nx.find_or_create_reference_set(nx.prototype(station), "BODY").AddObjectsToReferenceSet(
        [nx.proto_child_comp(new_component)])
    return new_component


def _save_pierce_components(button: Component, punch: Component, retainer: Component, type_: str) -> None:
    """PierceMerlin.SavePierceComponents"""
    _save_pierce_component(button, "button", type_)
    _save_pierce_component(punch, "punch", type_)
    _save_pierce_component(retainer, "retainer", type_)


def _save_pierce_component(component: Component, name_prefix: str, type_: str) -> None:
    """
    PierceMerlin.SavePierceComponent - Save As {display dir}\\{prefix}-{token}.prt, then TYPE / CSPC / GM Tool Number
    on the prototype. Does NOT add to the created list - the caller does that after the configure returns.
    """
    nx.prototype(component).SaveAs("{}\\{}-{}.prt".format(os.path.dirname(nx.display_part().FullPath), name_prefix,
                                                          merlin._random_file_token()))
    nx.set_attribute(nx.prototype(component), "TYPE", type_)
    nx.set_attribute(nx.prototype(component), "CSPC", "X")
    nx.set_attribute(nx.prototype(component), "GM Tool Number", "X")


# ---------------------------------------------------------------------------------------------------
# Configure (attributes, expressions, sheet pass)
# ---------------------------------------------------------------------------------------------------

SetCell = Callable[[int, int, float], None]


def _set_formula(name: str, formula: str) -> None:
    """work_.Expressions.FindObject(name).SetFormula(formula) - raises when the work part has no such expression."""
    nx.work_part().Expressions.FindObject(name).SetFormula(formula)


def _apply_retainer_expressions(d: int) -> None:
    """PierceMerlin.ApplyRetainerExpressions - d plus the table's dimension set. The retainer must be the work part."""
    e = get_retainer_expressions(d)
    f = nx.cs_double_str

    _set_formula("d", "{}mm".format(d))
    _set_formula("l", "{}mm".format(f(e.l)))
    _set_formula("w", "{}mm".format(f(e.w)))
    _set_formula("g", "{}mm".format(f(e.g)))
    _set_formula("k", "{}mm".format(f(e.k)))
    _set_formula("r", "{}mm".format(f(e.r)))
    _set_formula("s", "{}mm".format(f(e.s)))
    _set_formula("u", "{}mm".format(f(e.u)))
    _set_formula("x", "{}mm".format(f(e.x)))
    _set_formula("y", "{}mm".format(f(e.y)))
    _set_formula("thk", "{}mm".format(f(e.thk)))
    _set_formula("cbore_depth", "{}mm".format(f(e.cbore_depth)))
    _set_formula("cbore_dia", "{}mm".format(f(e.cbore_dia)))
    _set_formula("clr_hole", "{}mm".format(f(e.clr_hole)))
    _set_formula("dwl_dia", "{}mm".format(f(e.dwl_dia)))
    _set_formula("dwl_1", "{}".format(e.dwl_1))
    _set_formula("dwl_shape", "{}".format(e.dwl_shape))
    _set_formula("retainer_angle", "{}".format(f(e.retainer_angle)))
    _set_formula("SHCS8_45", "{}".format(e.shcs_8mm_045))
    _set_formula("SHCS10_45", "{}".format(e.shcs_10mm_045))
    _set_formula("SHCS12_50", "{}".format(e.shcs_12mm_050))
    _set_formula("DWL6_20_A", "{}".format(e.dwl_6mm_020_a))
    _set_formula("DWL6_20_B", "{}".format(e.dwl_6mm_020_b))
    _set_formula("FLAT", "{}".format(e.flat))


def _apply_sheet_expressions(detail: Component, first_exp_attr_row: int, last_exp_attr_row: int,
                             write_cells: Callable[[SetCell], None],
                             assert_expressions: Optional[Callable[[], None]] = None) -> int:
    """
    PierceMerlin.ApplySheetExpressions - write the detail's Main cells, recalculate, then copy Exp-Attr rows
    (name in column 2, value in column 3) into the part's expressions. assert_expressions runs once per row, before
    the row is read. Returns how many rows applied. A bad row prints and is stepped over; anything else prints and
    ends the walk. The sheet is saved and terminated either way, then UF_MODL_update.
    With _skip_spreadsheets the sheet is not opened: assert_expressions runs once and 0 is returned.
    """
    nx.set_work_component(detail)

    if _skip_spreadsheets:
        nx.info("Pierce: spreadsheets skipped - {} keeps its seed expressions.".format(detail.DisplayName))
        if assert_expressions is not None:
            assert_expressions()
        return 0

    ss_mgr = cast(Any, nx.session_).SpreadsheetManager
    sprread = ss_mgr.Open(cast(Any, NXOpen).SpreadsheetManager.Sheettype.Modeling,
                          nx.prototype(detail).FullPath)
    applied = 0

    try:
        main_index = sprread.GetSheetNumberOfName("Main")

        def set_cell(row: int, col: int, value: float) -> None:
            new_data = ss_mgr.CreateCellData()
            new_data.DoubleValue = float(value)
            sprread.SetNumber(row, col, new_data, main_index)

        write_cells(set_cell)

        sprread.Recalculate()

        exp_attr_index = sprread.GetSheetNumberOfName("Exp-Attr")
        string_type = cast(Any, NXOpen).SpreadsheetCellData.Types.String
        for row in range(first_exp_attr_row, last_exp_attr_row + 1):
            if assert_expressions is not None:
                assert_expressions()

            exp = sprread.GetValue(row, 2, exp_attr_index).StringValue
            cell = sprread.GetValue(row, 3, exp_attr_index)

            try:
                val = cell.StringValue if cell.Type == string_type else nx.cs_double_str(cell.DoubleValue)
                nx.work_part().Expressions.FindObject(exp).SetFormula("{}".format(val))
                applied += 1
            except Exception as ex:
                nx.print_exception(ex, "row: {}, col: {}, value: {}, exp: {}, detail {}".format(
                    row, 3, cell, exp, detail.DisplayName))
    except Exception as ex:
        nx.print_exception(ex)

    sprread.Save()
    sprread.Terminate()

    nx.ufsession_.Modeling.Update()

    # Where the sheet gets each expression (from the C#): a_key=Formulas!B14, a_dowel=Formulas!B16,
    # a_bhcs=Formulas!B19, dowelDia=Formulas!B17, dwlLocation=Lists!L4, a_angleLocator=Main!K7, a_land=Main!P17,
    # suppress6mmDwl=Formulas!B16, suppressKey=Formulas!B14, keyDepth=Formulas!F18, keyLength=Formulas!G18,
    # keyShift=Main!L7, DiaForSubTool=Formulas!I15, SubToolDiameter=D24, valueP=D25, valueW=D26, valueR=Formulas!I7,
    # maxR='Exp-Data'!G4, g=Formulas!I13, subCboreDia='Exp-Data'!S28, subTaperDia='Exp-Data'!F50.
    return applied


def _configure_round_button(button: Component, p_value: str, thickness: str, button_diameter: float) -> None:
    """PierceMerlin.ConfigureRoundButton - attributes first, then the sheet pass (valueP / a_D asserted per row)."""
    nx.set_work_component(button)
    work = nx.work_part()
    nx.set_attribute(work, "thickness", thickness)
    nx.set_attribute(work, "p", p_value)
    nx.set_attribute(work, "diameter", nx.cs_double_str(button_diameter))

    def write(set_cell: SetCell) -> None:
        set_cell(10, 3, float(p_value))      # p
        set_cell(7, 3, button_diameter)      # diameter
        set_cell(7, 7, float(thickness))     # material thickness

    def assert_expressions() -> None:
        _set_formula("valueP", "{}".format(p_value))
        _set_formula("a_D", "{}".format(nx.cs_double_str(button_diameter)))

    _apply_sheet_expressions(button, ButtonExpAttrFirstRow, ButtonExpAttrLastRow, write, assert_expressions)


def _configure_oblong_button(button: Component, p_value: str, w_value: str, thickness: str,
                             button_diameter: float) -> None:
    """PierceMerlin.ConfigureOblongButton - also w, the style selectors and slug type 2 (oblong) in (3,16)."""
    nx.set_work_component(button)
    work = nx.work_part()
    nx.set_attribute(work, "thickness", thickness)
    nx.set_attribute(work, "p", p_value)
    nx.set_attribute(work, "w", w_value)
    nx.set_attribute(work, "diameter", nx.cs_double_str(button_diameter))

    _set_formula("styleTaperOblong", "1")
    _set_formula("styleTaperRectangle", "0")
    _set_formula("styleCboreRound", "0")

    def write(set_cell: SetCell) -> None:
        set_cell(10, 3, float(p_value))      # p
        set_cell(10, 5, float(w_value))      # w
        set_cell(7, 3, button_diameter)      # diameter
        set_cell(7, 7, float(thickness))     # material thickness
        set_cell(3, 16, 2)                   # slug type - oblong

    def assert_expressions() -> None:
        _set_formula("valueP", "{}".format(p_value))
        _set_formula("valueW", "{}".format(w_value))
        _set_formula("a_D", "{}".format(nx.cs_double_str(button_diameter)))

    _apply_sheet_expressions(button, ButtonExpAttrFirstRow, ButtonExpAttrLastRow, write, assert_expressions)


def _configure_rectangle_button(button: Component, p_value: str, w_value: str, r_value: str, thickness: str,
                                button_diameter: int) -> None:
    """PierceMerlin.ConfigureRectangleButton - also r (Main (10,7); valueR is left to the sheet), slug type 4."""
    nx.set_work_component(button)
    work = nx.work_part()
    nx.set_attribute(work, "thickness", thickness)
    nx.set_attribute(work, "p", p_value)
    nx.set_attribute(work, "w", w_value)
    nx.set_attribute(work, "r", r_value)
    nx.set_attribute(work, "diameter", str(button_diameter))

    _set_formula("styleTaperOblong", "0")
    _set_formula("styleTaperRectangle", "1")
    _set_formula("styleCboreRound", "0")

    def write(set_cell: SetCell) -> None:
        set_cell(10, 3, float(p_value))      # p
        set_cell(10, 5, float(w_value))      # w
        set_cell(10, 7, float(r_value))      # r
        set_cell(7, 3, button_diameter)      # diameter
        set_cell(7, 7, float(thickness))     # material thickness
        set_cell(3, 16, 4)                   # slug type - rectangle

    def assert_expressions() -> None:
        _set_formula("valueP", "{}".format(p_value))
        _set_formula("valueW", "{}".format(w_value))
        _set_formula("a_D", "{}".format(button_diameter))

    _apply_sheet_expressions(button, ButtonExpAttrFirstRow, ButtonExpAttrLastRow, write, assert_expressions)


def _configure_round_punch(punch: Component, p_value: str, thickness: str, punch_diameter: int) -> None:
    """PierceMerlin.ConfigureRoundPunch - no sheet pass; styleStandard* one-hot."""
    nx.set_work_component(punch)
    work = nx.work_part()
    nx.set_attribute(work, "thickness", thickness)
    nx.set_attribute(work, "p", p_value)
    nx.set_attribute(work, "diameter", str(punch_diameter))

    _set_formula("valueP", "{}".format(p_value))
    _set_formula("D", "{}".format(punch_diameter))
    _set_formula("styleStandardRound", "1")
    _set_formula("styleStandardOblong", "0")
    _set_formula("styleStandardRectangle", "0")


def _configure_oblong_punch(punch: Component, p_value: str, w_value: str, thickness: str, punch_diameter: int) -> None:
    """PierceMerlin.ConfigureOblongPunch"""
    nx.set_work_component(punch)
    work = nx.work_part()
    nx.set_attribute(work, "thickness", thickness)
    nx.set_attribute(work, "p", p_value)
    nx.set_attribute(work, "w", w_value)
    nx.set_attribute(work, "diameter", str(punch_diameter))

    _set_formula("valueP", "{}".format(p_value))
    _set_formula("valueW", "{}".format(w_value))
    _set_formula("D", "{}".format(punch_diameter))
    _set_formula("styleStandardRound", "0")
    _set_formula("styleStandardOblong", "1")
    _set_formula("styleStandardRectangle", "0")


def _configure_rectangle_punch(punch: Component, p_value: str, w_value: str, r_value: str, thickness: str,
                               punch_diameter: int) -> None:
    """PierceMerlin.ConfigureRectanglePunch - the only configure that writes valueR."""
    nx.set_work_component(punch)
    work = nx.work_part()
    nx.set_attribute(work, "thickness", thickness)
    nx.set_attribute(work, "p", p_value)
    nx.set_attribute(work, "w", w_value)
    nx.set_attribute(work, "r", r_value)
    nx.set_attribute(work, "diameter", str(punch_diameter))

    _set_formula("valueP", "{}".format(p_value))
    _set_formula("valueW", "{}".format(w_value))
    _set_formula("valueR", "{}".format(r_value))
    _set_formula("D", "{}".format(punch_diameter))
    _set_formula("styleStandardRound", "0")
    _set_formula("styleStandardOblong", "0")
    _set_formula("styleStandardRectangle", "1")


def _configure_pierce_retainer(retainer: Component, punch_diameter: int) -> None:
    """
    PierceMerlin.ConfigurePierceRetainer - diameter attribute, then the retainer sheet (Main (3,4), Exp-Attr rows
    4-28); falls back to get_retainer_expressions when the sheet applied nothing.
    """
    nx.set_work_component(retainer)
    nx.set_attribute(nx.work_part(), "diameter", str(punch_diameter))

    def write(set_cell: SetCell) -> None:
        set_cell(3, 4, punch_diameter)       # diameter

    applied = _apply_sheet_expressions(retainer, RetainerExpAttrFirstRow, RetainerExpAttrLastRow, write)

    if applied > 0:
        return

    nx.warn("Retainer d={}: the spreadsheet applied no expressions - falling back to get_retainer_expressions."
              .format(punch_diameter))
    nx.set_work_component(retainer)
    _apply_retainer_expressions(punch_diameter)


# ---------------------------------------------------------------------------------------------------
# Builders - size, place, save, configure, collect
# ---------------------------------------------------------------------------------------------------

def _add_rounds(rounds: List[Round], created: List[Component], stations: _PierceStations) -> None:
    """PierceMerlin.AddRounds - one trio set per p group; the expressions are written against the last set placed."""
    p_dict_round = _to_ilook_dict(rounds, lambda rr: rr.p)

    p_value_keys = list(p_dict_round.keys())

    for i, p_value in enumerate(p_value_keys):
        nx.prompt("Round -> {} of {}".format(i + 1, len(p_value_keys)))

        try:
            # Size both first: a table miss here must not leave placed components and saved
            # button-*/punch-*/retainer-*.prt behind for a group that was never buildable.
            button_diameter = get_round_button_diameter(float(p_value))
            punch_diameter = get_round_punch_diameter(float(p_value))

            button: Optional[Component] = None
            punch: Optional[Component] = None
            retainer: Optional[Component] = None

            thickness = p_dict_round[p_value][0].thickness

            for round_slug in p_dict_round[p_value]:
                button, punch, retainer = _place_pierce_components(round_slug.origin, round_slug.orientation,
                                                                   stations)

            button, punch, retainer = _placed(button, punch, retainer)
            _save_pierce_components(button, punch, retainer, "round")

            _configure_round_button(button, p_value, thickness, button_diameter)
            created.append(button)

            _configure_round_punch(punch, p_value, thickness, punch_diameter)
            created.append(punch)

            _configure_pierce_retainer(retainer, punch_diameter)
            created.append(retainer)
        except Exception as ex:
            nx.print_exception(ex, "round p == {}".format(p_value))


def _add_oblongs(oblongs: List[Oblong], created: List[Component], stations: _PierceStations) -> None:
    """PierceMerlin.AddOblongs - grouped by p, then w."""
    p_dict_oblongs = _to_ilook_dict(oblongs, lambda rr: rr.p)

    p_value_keys = list(p_dict_oblongs.keys())

    for i, p_value in enumerate(p_value_keys):
        w_dict = _to_ilook_dict(p_dict_oblongs[p_value], lambda rr: rr.w)
        w_value_keys = list(w_dict.keys())

        for j, w_value in enumerate(w_value_keys):
            nx.prompt("Oblong -> p {} of {}, w {} of {}".format(i + 1, len(p_value_keys), j + 1, len(w_value_keys)))

            try:
                # Size both first - see _add_rounds.
                button_diameter = get_oblong_button_diameter(float(w_value), float(p_value))
                punch_diameter = get_oblong_punch_diameter(float(p_value))

                button: Optional[Component] = None
                punch: Optional[Component] = None
                retainer: Optional[Component] = None

                thickness = w_dict[w_value][0].thickness

                for oblong_slug in w_dict[w_value]:
                    button, punch, retainer = _place_pierce_components(oblong_slug.origin, oblong_slug.orientation,
                                                                       stations)

                button, punch, retainer = _placed(button, punch, retainer)
                _save_pierce_components(button, punch, retainer, "oblong")

                _configure_oblong_button(button, p_value, w_value, thickness, button_diameter)
                created.append(button)

                _configure_oblong_punch(punch, p_value, w_value, thickness, punch_diameter)
                created.append(punch)

                _configure_pierce_retainer(retainer, punch_diameter)
                created.append(retainer)
            except Exception as ex:
                nx.print_exception(ex, "oblong p == {}, w == {}".format(p_value, w_value))


def _add_rectangles(rectangles: List[Rectangle], created: List[Component], stations: _PierceStations) -> None:
    """PierceMerlin.AddRectangles - grouped by p, then w, then r. Squares included."""
    p_dict_rectangles = _to_ilook_dict(rectangles, lambda rr: rr.p)

    p_value_keys = list(p_dict_rectangles.keys())

    for i, p_value in enumerate(p_value_keys):
        w_dict = _to_ilook_dict(p_dict_rectangles[p_value], lambda rr: rr.w)
        w_value_keys = list(w_dict.keys())

        for j, w_value in enumerate(w_value_keys):
            r_dict = _to_ilook_dict(w_dict[w_value], lambda rr: rr.r)
            r_value_keys = list(r_dict.keys())

            for k, r_value in enumerate(r_value_keys):
                nx.prompt("Rectangle -> p {} of {}, w {} of {}, r {} of {}".format(
                    i + 1, len(p_value_keys), j + 1, len(w_value_keys), k + 1, len(r_value_keys)))

                try:
                    # Size both first - see _add_rounds. The button lookup is the one with the known gap.
                    button_diameter = get_rectangle_button_diameter(float(w_value), float(p_value))
                    punch_diameter = get_rectangle_punch_diameter(float(p_value))

                    button: Optional[Component] = None
                    punch: Optional[Component] = None
                    retainer: Optional[Component] = None

                    thickness = r_dict[r_value][0].thickness

                    for rectangle_slug in r_dict[r_value]:
                        button, punch, retainer = _place_pierce_components(rectangle_slug.origin,
                                                                           rectangle_slug.orientation, stations)

                    button, punch, retainer = _placed(button, punch, retainer)
                    _save_pierce_components(button, punch, retainer, "rectangle")

                    _configure_rectangle_button(button, p_value, w_value, r_value, thickness, button_diameter)
                    created.append(button)

                    _configure_rectangle_punch(punch, p_value, w_value, r_value, thickness, punch_diameter)
                    created.append(punch)

                    _configure_pierce_retainer(retainer, punch_diameter)
                    created.append(retainer)
                except Exception as ex:
                    nx.print_exception(ex, "rectangle p == {}, w == {}, r == {}".format(p_value, w_value, r_value))


def _placed(button: Optional[Component], punch: Optional[Component],
            retainer: Optional[Component]) -> Tuple[Component, Component, Component]:
    """
    Narrows the three Optional locals for mypy. A group always holds at least one slug, so none is ever None here; if
    one were, the C# would throw a NullReferenceException in SavePierceComponent - this raises the same way.
    """
    if button is None or punch is None or retainer is None:
        raise AttributeError("'NoneType' object has no attribute 'Prototype'")
    return button, punch, retainer


# ---------------------------------------------------------------------------------------------------
# Secondary pass
# ---------------------------------------------------------------------------------------------------

def _process_secondary_pierce(components: Iterable[Optional[Component]]) -> None:
    """
    PierceMerlin.ProcessSecondaryPierce - grouped by prototype (first-seen order, as GroupBy), the first component of
    each group goes to the writer its leaf prefix and TYPE pick. Per-part try/except named by the leaf.
    """
    then = datetime.datetime.now()
    with nx.suppress_display():
        by_prototype: Dict[int, Tuple[NXOpen.BasePart, List[Component]]] = {}
        for c in components:
            if c is None:
                continue
            proto = nx.prototype(c)
            by_prototype.setdefault(int(proto.Tag), (proto, []))[1].append(c)

        for part, group in by_prototype.values():
            component = group[0]

            try:
                if part.Leaf.startswith("button-"):
                    nx.set_work_part(part)
                    work = nx.work_part()
                    type_ = nx.get_attribute(work, "TYPE")
                    if type_ == "round":
                        _write_button_spreadsheet(
                            component, 1,
                            nx.get_attribute(work, "diameter"),
                            nx.get_attribute(work, "p"),
                            nx.get_attribute(work, "thickness"))
                    elif type_ == "oblong":
                        _write_button_spreadsheet(
                            component, 2,
                            nx.get_attribute(work, "diameter"),
                            nx.get_attribute(work, "p"),
                            nx.get_attribute(work, "thickness"),
                            nx.get_attribute(work, "w"))
                    elif type_ == "rectangle":
                        _write_button_spreadsheet(
                            component, 4,
                            nx.get_attribute(work, "diameter"),
                            nx.get_attribute(work, "p"),
                            nx.get_attribute(work, "thickness"),
                            nx.get_attribute(work, "w"),
                            nx.get_attribute(work, "r"))
                    else:
                        nx.print_("Unknown TYPE: {}".format(nx.get_attribute(work, "TYPE")))
                        continue

                elif "punch-" in part.Leaf:
                    nx.set_work_part(part)
                    work = nx.work_part()
                    type_ = nx.get_attribute(work, "TYPE")
                    if type_ == "round":
                        _write_punch_spreadsheet(
                            component, 1,
                            nx.get_attribute(work, "diameter"),
                            nx.get_attribute(work, "p"),
                            nx.get_attribute(work, "thickness"))
                    elif type_ == "oblong":
                        _write_punch_spreadsheet(
                            component, 2,
                            nx.get_attribute(work, "diameter"),
                            nx.get_attribute(work, "p"),
                            nx.get_attribute(work, "thickness"),
                            nx.get_attribute(work, "w"))
                    elif type_ == "rectangle":
                        _write_punch_spreadsheet(
                            component, 4,
                            nx.get_attribute(work, "diameter"),
                            nx.get_attribute(work, "p"),
                            nx.get_attribute(work, "thickness"),
                            nx.get_attribute(work, "w"),
                            nx.get_attribute(work, "r"))
                    else:
                        nx.print_("Unknown TYPE: {}".format(nx.get_attribute(work, "TYPE")))
                        continue

                elif "retainer-" in part.Leaf:
                    nx.set_work_part(part)
                    _write_retainer_spreadsheet(component, nx.get_attribute(nx.work_part(), "diameter"))

                else:
                    nx.print_("Unknown part -> {}".format(part.Leaf))
                    continue
            except Exception as ex:
                nx.print_exception(ex, part.Leaf)

    if not nx.quiet:
        nx.warn(drawdie._time_span(datetime.datetime.now() - then))


def _try_cell_value(field: str, text: Optional[str]) -> Optional[float]:
    """
    PierceMerlin.TryCellValue - the parsed value, or None after printing which field would not parse (so only that
    cell is skipped). float() stands in for double.TryParse; it also takes "_" separators, which are refused here.
    """
    if text is not None and "_" not in text:
        try:
            return float(text.strip())
        except ValueError:
            pass

    nx.warn('Pierce spreadsheet: no "{}" attribute on the part - leaving that cell alone.'.format(field)
              if text is None else
              'Pierce spreadsheet: "{}" is "{}", which is not a number - leaving that cell alone.'.format(field, text))

    return None


def _edit_pierce_spreadsheet(component: Component, write_cells: Callable[[SetCell], None]) -> bool:
    """
    PierceMerlin.EditPierceSpreadsheet - component as work component, open its prototype's modeling sheet, write the
    Main cells, Save + Terminate. False when the writes threw (printed). No Recalculate, no UF_MODL_update.
    With _skip_spreadsheets the sheet is not opened and False is returned.
    """
    nx.set_work_component(component)

    if _skip_spreadsheets:
        nx.info("Pierce: spreadsheets skipped - {}'s sheet not written.".format(component.DisplayName))
        return False

    ss_mgr = cast(Any, nx.session_).SpreadsheetManager
    sprread = ss_mgr.Open(cast(Any, NXOpen).SpreadsheetManager.Sheettype.Modeling,
                          nx.prototype(component).FullPath)
    written = True

    try:
        main_index = sprread.GetSheetNumberOfName("Main")

        def set_cell(row: int, col: int, value: float) -> None:
            new_data = ss_mgr.CreateCellData()
            new_data.DoubleValue = float(value)
            sprread.SetNumber(row, col, new_data, main_index)

        write_cells(set_cell)
    except Exception as ex:
        nx.print_exception(ex)
        written = False

    sprread.Save()
    sprread.Terminate()
    return written


def _write_button_spreadsheet(button: Component, slug_type: int, diameter: str, p: str, thickness: str,
                              w: Optional[str] = None, r: Optional[str] = None) -> None:
    """PierceMerlin.WriteButtonSpreadsheet - slug type in (3,16), steel coating 2 in (14,16), p > 40 flag in (5,16)."""
    p_val = _try_cell_value("p", p)

    def write(set_cell: SetCell) -> None:
        d = _try_cell_value("diameter", diameter)
        if d is not None:
            set_cell(7, 3, d)                                   # diameter
        if p_val is not None:
            set_cell(10, 3, p_val)                              # p
        thk = _try_cell_value("thickness", thickness)
        if thk is not None:
            set_cell(7, 7, thk)                                 # material thickness
        if w is not None:
            w_val = _try_cell_value("w", w)
            if w_val is not None:
                set_cell(10, 5, w_val)                          # w
        set_cell(3, 16, slug_type)                              # slug type
        set_cell(14, 16, 2)                                     # constant 2 - steel coating
        if p_val is not None and p_val > 40:
            set_cell(5, 16, 2)                                  # p > 40
        if r is not None:
            r_val = _try_cell_value("r", r)
            if r_val is not None:
                set_cell(10, 7, r_val)                          # r

    _edit_pierce_spreadsheet(button, write)


def _write_punch_spreadsheet(punch: Component, slug_type: int, diameter: str, p: str, thickness: str,
                             w: Optional[str] = None, r: Optional[str] = None) -> None:
    """PierceMerlin.WritePunchSpreadsheet - slug type in (9,16), steel coating 2 in (15,16), p > 40 flag in (5,16)."""
    p_val = _try_cell_value("p", p)

    def write(set_cell: SetCell) -> None:
        d = _try_cell_value("diameter", diameter)
        if d is not None:
            set_cell(7, 3, d)                                   # diameter
        if p_val is not None:
            set_cell(10, 3, p_val)                              # p
        thk = _try_cell_value("thickness", thickness)
        if thk is not None:
            set_cell(7, 7, thk)                                 # material thickness
        if w is not None:
            w_val = _try_cell_value("w", w)
            if w_val is not None:
                set_cell(10, 5, w_val)                          # w
        set_cell(9, 16, slug_type)                              # slug type
        set_cell(15, 16, 2)                                     # constant 2 - steel coating
        if p_val is not None and p_val > 40:
            set_cell(5, 16, 2)                                  # p > 40
        if r is not None:
            r_val = _try_cell_value("r", r)
            if r_val is not None:
                set_cell(10, 7, r_val)                          # r

    _edit_pierce_spreadsheet(punch, write)


def _write_retainer_spreadsheet(retainer: Component, diameter: str) -> bool:
    """
    PierceMerlin.WriteRetainerSpreadsheet - validates the diameter first, stamps DESCRIPTION / GM_DESCRIPTION / LABEL
    on the prototype, then writes the diameter into Main (3,4).
    """
    d = _try_cell_value("diameter", diameter)
    if d is None:
        return False

    prototype = nx.prototype(retainer)
    nx.set_attribute(prototype, "DESCRIPTION", "BRT-{} BL RETAINER".format(diameter))
    nx.set_attribute(prototype, "GM_DESCRIPTION", "90.60.00-{}HD BALL LOCK RETAINER".format(diameter))
    nx.set_attribute(prototype, "LABEL", "90.60.00-{}HD".format(diameter))

    def write(set_cell: SetCell) -> None:
        set_cell(3, 4, d)                                       # diameter

    return _edit_pierce_spreadsheet(retainer, write)


# ---------------------------------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------------------------------

def _set_default_update_failure_accept_all() -> None:
    """sess.UpdateManager.SetDefaultUpdateFailureAction(Update.FailureOption.AcceptAll) - not in the stubs."""
    cast(Any, nx.session_.UpdateManager).SetDefaultUpdateFailureAction(
        cast(Any, NXOpen).Update.FailureOption.AcceptAll)


def _first(items: Iterable[_T], predicate: Callable[[_T], bool]) -> _T:
    """Enumerable.First(predicate) - raises InvalidOperationException with .NET's message."""
    for item in items:
        if predicate(item):
            return item
    raise InvalidOperationException("Sequence contains no matching element")


def _to_ilook_dict(source: Iterable[_T], key_selector: Callable[[_T], _K]) -> Dict[_K, List[_T]]:
    """IEnumerable.__ToILookIDict - key -> items, keys in first-seen order."""
    result: Dict[_K, List[_T]] = {}
    for value in source:
        result.setdefault(key_selector(value), []).append(value)
    return result


def _distinct_by_tag(edges: Iterable[NXOpen.Edge]) -> List[NXOpen.Edge]:
    """Enumerable.Except's de-duplication, by tag."""
    result: List[NXOpen.Edge] = []
    for edge in edges:
        if all(e.Tag != edge.Tag for e in result):
            result.append(edge)
    return result


def _is_planar(face: NXOpen.Face) -> bool:
    """Face.__IsPlanar"""
    return face.SolidFaceType == cast(Any, NXOpen.Face).FaceType.Planar


def _edge_arc(edge: NXOpen.Edge) -> Tuple[float, NXOpen.Point3d]:
    """
    Edge.__Radius / Edge.__CenterPoint - UF_EVAL_ask_arc. Raises for a non-circular edge, as both C# members do. The
    struct fields are read as Radius / Center (stubs/NXOpen/UF.pyi Eval.Arc).
    """
    if edge.SolidEdgeType != NXOpen.Edge.EdgeType.Circular:
        raise ArgumentException("Cannot ask for the radius of a non-circular edge.")
    evaluator = nx.ufsession_.Eval.Initialize2(edge.Tag)
    arc = cast(Any, nx.ufsession_.Eval).AskArc(evaluator)
    center = arc.Center
    return float(arc.Radius), NXOpen.Point3d(center[0], center[1], center[2])


def _edge_mid_point(edge: NXOpen.Edge) -> NXOpen.Point3d:
    """Edge.__MidPoint - the point at the middle of the parameter range."""
    evaluator = nx.ufsession_.Eval.Initialize2(edge.Tag)
    limits = nx.ufsession_.Eval.AskLimits(evaluator)
    point = nx.ufsession_.Eval.EvaluateUnitVectors(evaluator, (limits[0] + limits[1]) / 2)[0]
    return NXOpen.Point3d(point[0], point[1], point[2])


def _edge_vector(edge: NXOpen.Edge) -> NXOpen.Vector3d:
    """Edge.__NormalVector - start minus end of a linear edge."""
    if edge.SolidEdgeType != NXOpen.Edge.EdgeType.Linear:
        raise ArgumentException("Cannot ask for the vector of a non linear edge")
    start, end = edge.GetVertices()
    return NXOpen.Vector3d(start.X - end.X, start.Y - end.Y, start.Z - end.Z)


def _is_parallel(a: NXOpen.Vector3d, b: NXOpen.Vector3d, tolerance: float = .0001) -> bool:
    """Vector3d.__IsIsParallelTo (UF_VEC3_is_parallel) - sine of the angle within tolerance, either sense."""
    cross = _cross(a, b)
    length_a = math.sqrt(a.X * a.X + a.Y * a.Y + a.Z * a.Z)
    length_b = math.sqrt(b.X * b.X + b.Y * b.Y + b.Z * b.Z)
    return math.sqrt(cross.X * cross.X + cross.Y * cross.Y + cross.Z * cross.Z) <= tolerance * length_a * length_b


def _cross(u: NXOpen.Vector3d, v: NXOpen.Vector3d) -> NXOpen.Vector3d:
    """Vector3d.__Cross"""
    return NXOpen.Vector3d(u.Y * v.Z - u.Z * v.Y, u.Z * v.X - u.X * v.Z, u.X * v.Y - u.Y * v.X)


def _matrix_from_rows(x: NXOpen.Vector3d, y: NXOpen.Vector3d, z: NXOpen.Vector3d) -> NXOpen.Matrix3x3:
    """Vector3d.__ToMatrix3x3(axisX, axisY, axisZ) - the three rows as given."""
    matrix = NXOpen.Matrix3x3()
    matrix.Xx, matrix.Xy, matrix.Xz = x.X, x.Y, x.Z
    matrix.Yx, matrix.Yy, matrix.Yz = y.X, y.Y, y.Z
    matrix.Zx, matrix.Zy, matrix.Zz = z.X, z.Y, z.Z
    return matrix


def _rotate_z(mat: NXOpen.Matrix3x3, degrees_to_rotate: float) -> NXOpen.Matrix3x3:
    """Matrix3x3.__RotateZ - positive is clockwise about the matrix's own Z (X turns toward -Y)."""
    radians = degrees_to_rotate * math.pi / 180.0
    cos = math.cos(radians)
    sin = math.sin(radians)
    x = nx.axis_x(mat)
    y = nx.axis_y(mat)
    new_x = NXOpen.Vector3d(x.X * cos - y.X * sin, x.Y * cos - y.Y * sin, x.Z * cos - y.Z * sin)
    new_y = NXOpen.Vector3d(x.X * sin + y.X * cos, x.Y * sin + y.Y * cos, x.Z * sin + y.Z * cos)
    return _matrix_from_rows(new_x, new_y, nx.axis_z(mat))


def _truncated_string(num: float, decimal_places: int) -> str:
    """double.__TruncatedString - double.ToString() cut (not rounded) to decimal_places after the point."""
    s = nx.cs_double_str(num)
    dot = s.find(".")
    if dot < 0:
        return s
    return s[:dot] if decimal_places == 0 else s[:min(len(s), dot + 1 + decimal_places)]


def _enum_name(value: object) -> str:
    """An NX enum as .NET prints it - the member name."""
    return str(value).rsplit(".", 1)[-1]


def main() -> None:
    """The pierce UFunc - its menu button runs this file. An escaping exception is printed."""
    import usage_db

    with usage_db.run("pierce"):
        try:
            # The Pierce dialog asks for the customer (and stands in for the "Are you sure" box).
            Pierce.execute(True)
        except Exception as ex:
            nx.print_exception(ex)


if __name__ == "__main__":
    main()

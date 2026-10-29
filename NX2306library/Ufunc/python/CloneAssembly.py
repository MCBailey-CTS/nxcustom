"""
Python port of the clone-assembly UFunc (src\\UFuncs\\CloneAssembly.cs, a _UFuncForm, with its static half in
src\\Static\\CloneAssembly.cs), as a Block UI Styler dialog (CloneAssembly.dlx, written by tools\\make-dlx.py) -
2026-10-29. NEVER RUN IN NX - untested, and not on the menu: the C# form stays until this is confirmed.

Clones the NX1919 seed die assemblies (G:\\0Library\\SeedFiles\\NX1919\\seed-*) into a job folder:
- Transfer: per 3xx shoe (seed-tran-shoe-000 + the seed-line-op shoe details) and per op (seed-tran-op-000/lsp/usp),
  then the 900 transfer assembly ({job}-900-{ops}-000/lwr/upr per shoe, {job}-900-900-000) with the strip,
  presses, constraints and strip interpart expressions;
- Progressive: one op from the seed-prog parts (needs the op's {job}-{op}-Strip);
- Line: each op from the seed-line-op parts (name rule seed-line-op- -> {job}-{op}-), then the 900 line assembly.

C# -> Python:
- Static.CloneAssemblyCloneJob (the form's Clone button body)      -> clone_job
- CloneAssemblyCloneProg / CloneLine / CloneTransfer               -> _clone_prog / _clone_line / _clone_transfer
- CloneAssemblyAddPresses / AddPress(GFolder, op)                  -> _add_presses / _add_press
- CloneAssemblyConstrainOpsToLwrUpr (+ NewMethod21, ConstraintXz1,
  ConstrainXy1, ConstrainUnits)                                    -> _constrain_ops_to_lwr_upr, _constrain_units
- CloneAssemblyReplaceStripLayoutInDisplay                         -> _replace_strip_layout_in_display
- CloneAssemblyDeleteUnitFasteners                                 -> _delete_unit_fasteners
- CloneAssemblyConstrainLSH / USH                                  -> _constrain_shoe (one body, "l" / "u")
- CloneAssemblyConstrainXzToDatumPlane / Xy / Xz / Yz              -> _constrain_xz_to_datum_plane / _constrain_abs
- CloneAssemblyExecuteClone* (seven UF_CLONE runs)                 -> _execute_clone_*
- CloneAssemblyConstrainStripInterpartExpressions                  -> _constrain_strip_interpart_expressions
- the form (CloneAssembly.cs)                                      -> _CloneAssemblyDialog, execute, main
The Globals.cs / Part_ extensions they use are local helpers, or come from src\\python\\CloneStrip.py
(__ConstrainOccProtoDistance, __AbsoluteDatumCsys, the datum planes, __FindExpression, __FindComponent,
__DeleteSelfAndConstraints, __Op10To010, __Save, GFolder.Create); _JobFolder adds the GFolder members CloneStrip's
_GFolder lacks.

Not ported (not reachable from CloneJob): add_component_and_constrain + NewMethod24/8/5,
replace_interpart_expressions, add_press(string) + NewMethod43/25/27 (CloneStrip.py ports those for Clone Strip),
NewMethod26 (no caller), and CloneProg's commented-out press / dieset-control / suppress steps.

The dialog (the confirm step - OK runs the clone, after the dialog has closed):
- Job folder, prefilled with the display part's job folder (GFolder.Create of its path; blank when there is none),
  and Browse... (a FolderBrowserDialog, nx.select_folder_or_none, starting at the typed folder or G:\\).
- Type radio Transfer / Progressive / Line, Transfer when it opens (where the form's Load left it). Changing it
  rewrites Ops as rdoTransfer_CheckedChanged did: Progressive "010", Line "010 020 030 040", Transfer
  "301 010 020; 302 030 040".
- Ops: one line (Block Styler has no multi-line text box). Rows are separated by ";" or newlines; each row is
  stripped, empty rows dropped, and the rows are joined with "\\r\\n" - the txtOps.Text CloneJob was given.
- Start with Prog Blank: shown for Transfer only, and cleared when another type is picked (the form disabled and
  unchecked it).
- Units English / Metric, Metric when it opens (the designer's default). Press Op -> Dieset Control: integer 0-100,
  0 when it opens (the NumericUpDown defaults; it is unused - see below).

Differences from the form:
- The form prefilled the job folder only for user mcbailey, with a test path (G:\\CTS\\001020-(DTS-XXXXXX)) and
  Progressive + Start with Prog Blank checked; that is dropped - the job folder comes from the display part.
- The form's double click opened the folder browser at G:\\ and wrote its SelectedPath back even on Cancel (so
  Cancel set the box to G:\\); Browse... starts at the typed folder when it exists and leaves the box alone on Cancel.
- The window location setting (clone_assembly_form_window_location) is not kept.

Quirks kept from the C# (as written; most would make a run fail part way, into the printed exception):
- CloneJob builds the GFolder twice and splits the ops into an array only the Line clone uses; Transfer gets the
  text with newlines turned into spaces and double spaces collapsed three times, Progressive the text with newlines
  turned into spaces (so a Progressive op must be one row of one op). The elapsed time is printed even when nothing ran.
- Progressive: press_dieset_op is converted but unused (every step that used it is commented out in the C#), and
  ExecuteCloneProg ends by opening {job}-010\\{job}-010-casting-text.prt whatever the op, so any op but 010 throws
  there and the op's 000 is never saved.
- Line: DeleteUnitFasteners runs before SetAllowMultipleDisplayedParts(true), so its lsh SetActiveDisplay throws
  ("Session does not allow multiple displayed parts") unless the session already allows them, and the guide pin /
  stop block deletes are skipped (printed). The 900 upr's BODY refset has its non-STRIP children REMOVED while the
  lwr's are ADDED. Each op 000's p2 gets the formula CenterLineofCoil and is renamed CenterLineofCoil_; the
  900-000's p2 is renamed to its own formula + "_" without a SetFormula. The dieset-control interpart references
  are changed from seed-prog-dieset-control.prt although the line seeds are seed-line-op-*.
- Transfer: each op's press is added twice - once in the op loop, then again for every op into whichever 000 was
  displayed last. The 900 {ops}-lwr/upr parts get usp / lsp / lsh / ush children from
  {job}-900\\{job}-{op}-usp.prt etc., although ExecuteCloneTranOp / TranShoe cloned those into each op's own folder.
  The CenterLineofCoil interpart expression and datum_plane_12_offset edit in the op loop are outside the try, so one
  op without them stops the whole transfer. ConstrainLSH / USH only link the strip's T{op}X/Y/Z (or P010X/Y/Z)
  expressions - the constraints come later, and for op 010 with Start with Prog Blank they are outside any try.
  "Designer will have to link up presses to proper dieset control manualy." is printed at the end, as in the C#.
- DeleteUnitFasteners deletes the recorded-journal objects ("HANDLE R-21229", "COMPONENT 1500-shcs-500 7", ...) of
  the seed lwrplate / uprplate; the first one missing stops the rest of the method (the outer try prints it). It
  deletes the displayed constraints (not the constraints) of the MM / non-MM children of 002/012/502/512.
- AddPresses adds every file in the Layout folder whose full path contains "press" (case-insensitive), so a job
  folder with "press" in its path adds every Layout file. Its AddComponents call is not wrapped per press.
- constrain_xz_to_datum_plane names the DISPLAYED constraint PRESS-XZ; the XY / YZ press constraints name the
  component constraint. Its NX error 3520016 is rethrown as "Could not find object {leaf}" (a RuntimeError here:
  Python cannot construct an NXException) and any other NX error is rethrown; other errors are printed.
- constrain_xy / xz / yz use the WORK part's absolute datum csys for the prototype plane.
- FeedDirection is read as int.Parse of the expression value's text: a fractional value throws.
- Directory.GetFiles order is taken as name order (sorted, case-insensitive); .NET does not promise one.

NXOpen Python bindings assumed, not confirmed (nothing here has run):
- UF_CLONE: NameRuleDef() with Type / BaseString / NewString (the field names in NXOpen_UF.pyd), NameRuleType.
  REPLACE_STRING, NamingTechnique.NAMING_RULE, and SetNameRule(rule, failures) / PerformClone(failures) returning the
  modified failures; the failure fields printed on a TranOp clone error are read with getattr (NFailures,
  InputNames, OutputNames, Statuses).
- AddComponents(...) returns a tuple holding the new components (found by type); OpenComponents and
  SetActiveDisplay return tuples (ignored).
- Expression.IsInterpartExpression is a property; UnitCollection iterates its Units; LoadOptions.PartLoadOption /
  LoadOption.FullyLoad, PartCollection.MultipleDisplayedPartStatus.Enabled, Session.NewestVisibleUndoMark,
  ExpressionCollection.EditWithUnits / EditExpression / ChangeInterpartReferences and ReplaceComponentBuilder's
  members are spelled as in .NET.
"""

from __future__ import annotations

import fnmatch
import os
import re
import sys
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple, cast

# Session.Execute does not put the script's folder on sys.path, so the shared module would not import.
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
import NXOpen.Features  # noqa: E402
import NXOpen.UF  # noqa: E402

import CloneStrip as clone_strip  # noqa: E402
import tsg_nx as nx  # noqa: E402
from tsg_dialog import Dialog, title_with_version  # noqa: E402

ufunc_name = "clone-assembly"

# NX will not create a dialog from inside another dialog's callback.
_ErrorCannotLaunchDialog = 3520048

_Seed = "G:\\0Library\\SeedFiles\\NX1919\\"
_RefsetBody = "BODY"
_NewLine = "\r\n"  # Environment.NewLine

# rdoTransfer_CheckedChanged's Ops text per type (Transfer's rows ";"-separated here).
TypeTransfer, TypeProgressive, TypeLine = "Transfer", "Progressive", "Line"
_DefaultOps = {
    TypeTransfer: "301 010 020; 302 030 040",
    TypeProgressive: "010",
    TypeLine: "010 020 030 040",
}
UnitsEnglish, UnitsMetric = "English", "Metric"

# Shared helpers from CloneStrip.py (its ports of the Globals.cs extensions).
_constrain_occ_proto_distance = clone_strip._constrain_occ_proto_distance
_absolute_datum_csys = clone_strip._absolute_datum_csys
_datum_plane_xy = clone_strip._datum_plane_xy
_datum_plane_yz = clone_strip._datum_plane_yz
_datum_plane_xz = clone_strip._datum_plane_xz
_find_expression = clone_strip._find_expression
_find_component = clone_strip._find_component
_delete_self_and_constraints = clone_strip._delete_self_and_constraints
_op_10_to_010 = clone_strip._op_10_to_010
_single = clone_strip._single
_save = clone_strip._save
_int_try_parse = clone_strip._int_try_parse


# ---------------------------------------------------------------------------------------------------
# GFolder
# ---------------------------------------------------------------------------------------------------

class _JobFolder(clone_strip._GFolder):
    """GFolder (src\\Utilities\\GFolder.cs) - CloneStrip's _GFolder plus the members CloneAssembly reads."""

    @staticmethod
    def create_job(job_folder: str) -> "_JobFolder":
        """GFolder.Create(string)"""
        folder = clone_strip._GFolder.create(job_folder)
        return _JobFolder(folder.DirJob, folder.CustomerNumber)

    @property
    def FileStrip010(self) -> str:
        return self.file_strip("010")

    def dir_op(self, op: str) -> str:
        return "{}\\{}-{}".format(self.DirJob, self.CustomerNumber, op)

    def path_op_op_detail(self, dir_op: str, detail_op: str, detail: str) -> str:
        return self.dir_op(dir_op) + "\\{}-{}-{}.prt".format(self.CustomerNumber, detail_op, detail)

    def path_op_detail(self, detail_op: str, detail: str) -> str:
        return self.path_op_op_detail(detail_op, detail_op, detail)

    def file_detail0(self, op: str, detail: str) -> str:
        return "{}\\{}-{}-{}.prt".format(self.dir_op(op), self.CustomerNumber, op, detail)

    def file_detail_000(self, op: str) -> str:
        return self.file_detail0(op, "000")

    def path_detail1(self, dir_op: str, op: str, detail: str) -> str:
        return "{}\\{}-{}-{}.prt".format(self.dir_op(dir_op), self.CustomerNumber, op, detail)

    def file_dir_op_op_detail(self, dir_op: str, detail_op: str, detail: str) -> str:
        return self.path_detail1(dir_op, detail_op, detail)

    def file_press_t(self, op: str) -> str:
        return "{}\\{}-T{}-Press.prt".format(self.DirLayout, self.CustomerNumber, op)


# ---------------------------------------------------------------------------------------------------
# Small Globals / Part_ / .NET helpers
# ---------------------------------------------------------------------------------------------------

def _disp() -> Any:
    """disp (the display part)"""
    return nx.display_part()


def _set_disp(part: Any) -> None:
    """disp = part"""
    nx.set_display_part(part)


def _open(path_or_leaf: str) -> Any:
    """sess.FindOrOpen"""
    return nx.find_or_open(path_or_leaf)


def _save_part(part: Any) -> None:
    """Part_.Save() / Save(SaveComponents.True, CloseAfterSave.False) - saves the children too."""
    _save(part)


def _fit(part: Any) -> None:
    """BasePart.__Fit"""
    part.ModelingViews.WorkView.Fit()


def _children(part: Any) -> List[Any]:
    """BasePart.__Children"""
    return list(nx.children(part))


def _root(part: Any) -> Any:
    return part.ComponentAssembly.RootComponent


def _expressions(part: Any) -> List[Any]:
    """part.Expressions.ToArray()"""
    return list(part.Expressions)


def _formula(expression: Any) -> str:
    """Expression.GetFormula()"""
    return str(expression.RightHandSide)


def _mm_unit(part: Any) -> Any:
    """part.UnitCollection.ToArray().Single(u => u.TypeName == "MilliMeter")"""
    return _single([u for u in part.UnitCollection if u.TypeName == "MilliMeter"])


def _edit_with_mm(expression: Any) -> None:
    """expression.OwningPart.Expressions.EditWithUnits(expression, <MilliMeter>, expression.GetFormula())"""
    owner = expression.OwningPart
    owner.Expressions.EditWithUnits(expression, _mm_unit(owner), _formula(expression))


def _rename(expression: Any, new_name: str) -> None:
    expression.OwningPart.Expressions.Rename(expression, new_name)


def _create_interpart_expression(part: Any, source_expression: Any, destination_name: str) -> None:
    """BasePart.__CreateInterpartExpression"""
    if part.Tag != _disp().Tag:
        raise Exception("Part must be displayed part to create interpart expressions")
    builder = _disp().Expressions.CreateInterpartExpressionsBuilder()
    try:
        builder.SetExpressions([source_expression], [destination_name])
        builder.Commit()
    finally:
        builder.Destroy()


def _open_assembly_whole(part: Any) -> None:
    """BasePart.__RightClickOpenAssemblyWhole (Part_.OpenAssemblyWhole)"""
    if nx.session_.Parts.Display is None:
        raise Exception("There is no open display part to right click open assembly")
    if nx.work_part().Tag != _disp().Tag:
        raise Exception("DisplayPart does not equal work_")
    if _disp().Tag != part.Tag:
        raise Exception("Part {} is not the current display part".format(part.Leaf))
    assemblies: Any = NXOpen.Assemblies
    _disp().ComponentAssembly.OpenComponents(assemblies.ComponentAssembly.OpenOption.WholeAssembly,
                                             [_root(part)])


def _set_active_display(part: Any) -> None:
    """BasePart.__SetActiveDisplay - throws unless the session allows multiple displayed parts."""
    parts: Any = nx.session_.Parts
    nxopen: Any = NXOpen
    if parts.AllowMultipleDisplayedParts != nxopen.PartCollection.MultipleDisplayedPartStatus.Enabled:
        raise Exception("Session does not allow multiple displayed parts")
    parts.SetActiveDisplay(part, NXOpen.DisplayPartOption.AllowAdditional,
                           NXOpen.PartDisplayPartWorkPartOption.UseLast)


def _find_reference_set(part: Any, title: str) -> Any:
    """BasePart.__FindReferenceSet - throws when there is none."""
    refset = nx.find_reference_set_or_null(part, title)
    if refset is None:
        raise Exception('Could not find reference set with title "{}" in part "{}".'.format(title, part.Leaf))
    return refset


def _replace_component(component: Any, path: str, name: str, replace_all: bool) -> None:
    """Component.__ReplaceComponent"""
    assemblies: Any = NXOpen.Assemblies
    work: Any = nx.work_part()
    builder = work.AssemblyManager.CreateReplaceComponentBuilder()
    try:
        builder.ComponentNameType = assemblies.ReplaceComponentBuilder.ComponentNameOption.AsSpecified
        builder.ComponentsToReplace.Add(component)
        builder.ReplaceAllOccurrences = replace_all
        builder.ComponentName = name
        builder.ReplacementPart = path
        builder.SetComponentReferenceSetType(assemblies.ReplaceComponentBuilder.ComponentReferenceSet.Maintain, None)
        builder.Commit()
    finally:
        builder.Destroy()


def _abs_occ(component: Any, index: int) -> Any:
    """Component.__AbsOccDatumPlaneXY (0) / YZ (1) / XZ (2)"""
    return clone_strip._abs_occ_datum_plane(component, index)


def _abs_xy(part: Any) -> Any:
    """part.AbsoluteDatumCsys.__DatumPlaneXY()"""
    return _datum_plane_xy(_absolute_datum_csys(part))


def _abs_yz(part: Any) -> Any:
    return _datum_plane_yz(_absolute_datum_csys(part))


def _abs_xz(part: Any) -> Any:
    return _datum_plane_xz(_absolute_datum_csys(part))


def _op_020_to_010(op: str) -> str:
    """Extensions.__Op020To010"""
    return _op_10_to_010(int(op) - 10)


def _feed_point(folder: _JobFolder) -> NXOpen.Point3d:
    """int.Parse($"{FileStrip900's FeedDirection.Value}") > 0 ? (10, 0, 0) : (-10, 0, 0)"""
    value = float(_find_expression(_open(folder.FileStrip900), "FeedDirection").Value)
    if value != int(value):
        # int.Parse("1.5") - FormatException.
        raise ValueError("Input string was not in a correct format: '{}'".format(value))
    return NXOpen.Point3d(10.0, 0.0, 0.0) if int(value) > 0 else NXOpen.Point3d(-10.0, 0.0, 0.0)


def _make_dirs(path: str) -> None:
    """if (!Directory.Exists(path)) Directory.CreateDirectory(path)"""
    if not os.path.isdir(path):
        os.makedirs(path)


def _get_files(directory: str, pattern: str = "*") -> List[str]:
    """Directory.GetFiles(directory, pattern, TopDirectoryOnly) - in name order; raises when the folder is missing."""
    names = sorted(os.listdir(directory), key=lambda n: n.lower())
    return [os.path.join(directory, n) for n in names
            if os.path.isfile(os.path.join(directory, n)) and fnmatch.fnmatch(n.lower(), pattern.lower())]


def _stem(path: str) -> str:
    """Path.GetFileNameWithoutExtension"""
    return os.path.splitext(os.path.basename(path))[0]


def _lwr_upr_files(folder: _JobFolder) -> List[str]:
    """The *.prt files of the 900 folder whose name ends with lwr or upr."""
    return [f for f in _get_files(folder.dir_op("900"), "*.prt")
            if _stem(f).endswith("lwr") or _stem(f).endswith("upr")]


def _delete_list_and_update(objects: Sequence[Any], mark: Any) -> None:
    nx.session_.UpdateManager.AddObjectsToDeleteList(list(objects))
    nx.session_.UpdateManager.DoUpdate(mark)


def _cs_split_whitespace(text: str) -> List[str]:
    """string.Split() - splits on each whitespace character, keeping empty entries."""
    return re.split(r"\s", text)


def _timespan(seconds: float) -> str:
    """A TimeSpan's ToString: hh:mm:ss.fffffff"""
    whole = int(seconds)
    return "{:02d}:{:02d}:{:02d}.{:07d}".format(whole // 3600, (whole // 60) % 60, whole % 60,
                                                 int(round((seconds - whole) * 10000000)) % 10000000)


# ---------------------------------------------------------------------------------------------------
# CloneJob
# ---------------------------------------------------------------------------------------------------

def ops_text_from_rows(text: str) -> str:
    """The dialog's Ops (rows separated by ";" or newlines) as the multi-line txtOps.Text CloneJob was given."""
    rows = [row.strip() for row in re.split(r"[;\r\n]", text)]
    return _NewLine.join(row for row in rows if row)


def clone_job(job_folder: str, ops_text: str, transfer: bool, line: bool, progressive: bool,
              start_with_blank: bool, metric: bool, press_dieset_op: int) -> None:
    """Static.CloneAssemblyCloneJob. ops_text is the txtOps.Text: rows separated by "\\r\\n"."""
    started = time.monotonic()
    try:
        folder1 = _JobFolder.create_job(job_folder)
        collapsed = ops_text.replace(_NewLine, " ").replace("  ", " ").replace("  ", " ").replace("  ", " ").strip()
        array = collapsed.split(" ")
        load_options: Any = nx.session_.Parts.LoadOptions
        nxopen: Any = NXOpen
        load_options.ComponentLoadMethod = NXOpen.LoadOptions.LoadMethod.AsSaved
        load_options.ComponentsToLoad = NXOpen.LoadOptions.LoadComponents.All
        load_options.PartLoadOption = nxopen.LoadOptions.LoadOption.FullyLoad
        load_options.SetInterpartData(True, NXOpen.LoadOptions.Parent.Partial)
        folder2 = _JobFolder.create_job(job_folder)
        if transfer:
            _clone_transfer(folder1, collapsed, start_with_blank, metric)
        elif line:
            _clone_line(folder2, array, metric)
        else:
            if not progressive:
                return
            op = ops_text.replace(_NewLine, " ").strip()
            if not os.path.isfile(folder2.file_strip(op)):
                nx.print_("Can't clone prog die without {}-Strip.".format(op))
            elif not _int_try_parse(op):
                nx.print_("Invalid op")
            else:
                _clone_prog(folder2, op, metric, int(press_dieset_op))
    except Exception as ex:
        nx.print_exception(ex)
    finally:
        nx.print_(_timespan(time.monotonic() - started))


def _clone_prog(folder: _JobFolder, op: str, units_mm: bool, press_op_dieset: int) -> None:
    """Static.CloneAssemblyCloneProg - units_mm and press_op_dieset are unused (their steps are commented out)."""
    try:
        _make_dirs(folder.dir_op(op))
        _execute_clone_prog(folder, op)
        _set_disp(_open(folder.file_detail_000(op)))
        _save_part(_disp())
    except Exception as ex:
        nx.print_exception(ex)


def _clone_line(folder: _JobFolder, ops: List[str], units_mm: bool) -> None:
    """Static.CloneAssemblyCloneLine"""
    try:
        for op in ops:
            _make_dirs(folder.dir_op(op))
            _execute_clone_line_op(folder, op)
            _set_disp(_open(folder.file_detail_000(op)))
            try:
                _replace_strip_layout_in_display(folder.file_layout_t(op), "LAYOUT", True)
            except Exception as ex:
                nx.print_exception(ex)
            with nx.display_part_reset():
                _delete_unit_fasteners(folder, op, units_mm)
            _add_press(folder, op)
            for feature in _open(folder.path_op_detail(op, "lsh")).Features.GetFeatures():
                if isinstance(feature, NXOpen.Features.DatumCsys):
                    feature.Suppress()

        cast(Any, nx.session_.Parts).SetAllowMultipleDisplayedParts(True)
        for op in ops:
            _set_active_display(_open(folder.file_detail0(op, "000")))

        _make_dirs(folder.dir_op("900"))
        _execute_clone_line_900(folder)

        _set_active_display(_open(folder.file_detail_000("900")))
        try:
            _replace_strip_layout_in_display(folder.FileStrip900, "STRIP", True)
        except Exception as ex:
            nx.print_exception(ex)

        with nx.display_part_reset():
            try:
                _constrain_ops_to_lwr_upr(folder, ops, "lwr", 1)
                _constrain_ops_to_lwr_upr(folder, ops, "upr", 101)
            except Exception as ex:
                nx.print_exception(ex)

        with nx.display_part_reset():
            nx.set_reference_set(_single([c for c in _children(_disp()) if "LWR" in c.Name]), "BODY")
            _fit(_disp())
            nx.set_reference_set(_single([c for c in _children(_disp()) if "UPR" in c.Name]), "BODY")
            _fit(_disp())

        with nx.display_part_reset():
            _set_disp(_open(folder.file_detail0("900", "upr")))
            _find_reference_set(_disp(), "BODY").RemoveObjectsFromReferenceSet(
                [c for c in _children(_disp()) if c.Name != "STRIP"])
            _fit(_disp())

        with nx.display_part_reset():
            _set_disp(_open(folder.file_detail0("900", "lwr")))
            _find_reference_set(_disp(), "BODY").AddObjectsToReferenceSet(
                [c for c in _children(_disp()) if c.Name != "STRIP"])
            _fit(_disp())

        with nx.display_part_reset():
            for op in ops:
                or_open = _open(folder.file_detail_000(op))
                _set_disp(or_open)
                _create_interpart_expression(
                    _disp(), _find_expression(_open(folder.file_strip("900")), "CenterLineofCoil"), "CenterLineofCoil")
                expression = _find_expression(_disp(), "p2")
                expression.SetFormula("CenterLineofCoil")
                _disp().Expressions.Rename(expression, _formula(expression) + "_")
                _disp().Expressions.EditWithUnits(expression, _mm_unit(expression.OwningPart), _formula(expression))
                or_open.ModelingViews.WorkView.Fit()
                _save_part(or_open)

        with nx.display_part_reset():
            _add_presses(folder)

        with nx.display_part_reset():
            _disp().Layers.MoveDisplayableObjects(256, list(_disp().DisplayedConstraints))

        with nx.display_part_reset():
            for op in ops:
                _save_part(_open(folder.file_detail_000(op)))
            for file in _get_files(folder.dir_op("900"), "*-000.prt"):
                _save_part(_open(file))

        with nx.display_part_reset():
            expression = _find_expression(_disp(), "p2")
            _disp().Expressions.Rename(expression, _formula(expression) + "_")
            _disp().Expressions.EditWithUnits(expression, _mm_unit(expression.OwningPart), _formula(expression))
            _fit(_disp())
            _save_part(_disp())

        with nx.display_part_reset():
            for op in ops:
                new_part_name = "{}-{}-dieset-control.prt".format(folder.CustomerNumber, op)
                for detail in ("002", "012", "502", "512"):
                    _set_disp(_open(folder.file_detail0(op, detail)))
                    _disp().Expressions.ChangeInterpartReferences("seed-prog-dieset-control.prt", new_part_name,
                                                                  True, True)

        with nx.display_part_reset():
            for op in ops:
                try:
                    _set_disp(_open("{}-{}-dieset-control.prt".format(folder.CustomerNumber, op)))
                    _disp().Expressions.ChangeInterpartReferences(
                        "XXXXX-Press-XX-Assembly.prt", "{}-T{}-Press.prt".format(folder.CustomerNumber, op),
                        True, True)
                except NXOpen.NXException as ex:
                    if ex.ErrorCode != 1050033:
                        raise
                    nx.print_("Could not find file {}-T{}-Press.prt".format(folder.CustomerNumber, op))
    except Exception as ex:
        nx.print_exception(ex)


def _clone_transfer(folder: _JobFolder, ops: str, chk_start_with_blank: bool, units_mm: bool) -> None:
    """Static.CloneAssemblyCloneTransfer - not wrapped in a try (CloneJob prints what escapes)."""
    pieces = [s for s in re.split(r"(3\d\d)", ops) if s and s.strip()]
    dictionary: Dict[str, List[str]] = {}
    for index in range(0, len(pieces), 2):
        key = pieces[index].strip().replace("  ", " ")
        dictionary[key] = _cs_split_whitespace(pieces[index + 1].strip().replace("  ", " "))

    source: List[str] = []
    for key in dictionary:
        source.append(key)
        source.extend(dictionary[key])

    start_with_strip = chk_start_with_blank
    for op in source:
        if op.startswith("3"):
            _make_dirs(folder.dir_op(op))
            _execute_clone_tran_shoe(folder, op)
            _set_disp(_open(folder.file_detail_000(op)))
            with nx.display_part_reset():
                _delete_unit_fasteners(folder, op, units_mm)
        else:
            _make_dirs(folder.dir_op(op))
            _execute_clone_tran_op(folder, op)
            _set_disp(_open(folder.file_detail_000(op)))
            _open_assembly_whole(_disp())
            try:
                if not start_with_strip:
                    _replace_strip_layout_in_display(folder.file_layout_t(op), "LAYOUT", True)
                elif op == "010":
                    _replace_strip_layout_in_display(folder.FileStrip900, "STRIP", True)
                else:
                    _replace_strip_layout_in_display(folder.file_layout_t(_op_020_to_010(op)), "LAYOUT", True)
            except Exception as ex:
                nx.print_exception(ex)
            _create_interpart_expression(
                _disp(), _find_expression(_open(folder.file_strip("900")), "CenterLineofCoil"), "CenterLineofCoil")
            offset: Any = _find_expression(_disp(), "datum_plane_12_offset")
            offset.OwningPart.Expressions.EditExpression(offset, "CenterLineofCoil")
            _add_press(folder, op)

    for op in source:
        _set_disp(_open(folder.file_detail0(op, "000")))

    _make_dirs(folder.dir_op("900"))

    # Into the 000 displayed last - see the module docstring.
    for op in source:
        if not op.startswith("3"):
            _add_press(folder, op)

    for key in dictionary:
        str_array = dictionary[key]
        str1 = "".join("{}{}".format(s[1], s[2]) for s in str_array)
        clone_dict = {
            _Seed + "seed-tran-op-000.prt": folder.file_dir_op_op_detail("900", str1, "000"),
            _Seed + "seed-tran-op-lsp.prt": folder.file_dir_op_op_detail("900", str1, "lwr"),
            _Seed + "seed-tran-op-usp.prt": folder.file_dir_op_op_detail("900", str1, "upr"),
        }
        _execute_clone_tran_assembly_op(folder.dir_op("900"), clone_dict)
        _set_disp(_open(folder.path_detail1("900", str1, "000")))
        component1 = _find_component(_root(_disp()), "COMPONENT {}-{}-upr 1".format(folder.CustomerNumber, str1))
        component2 = _find_component(_root(_disp()), "COMPONENT {}-{}-lwr 1".format(folder.CustomerNumber, str1))
        point3d = _feed_point(folder)
        _set_disp(nx.prototype(component1))
        for op in str_array:
            nx.add_component(_disp(), folder.path_detail1("900", op, "usp"), origin=point3d)
        _set_disp(nx.prototype(component2))
        for op in str_array:
            nx.add_component(_disp(), folder.path_detail1("900", op, "lsp"), origin=point3d)
        nx.add_component(nx.prototype(component2), folder.path_detail1("900", key, "lsh"))
        nx.add_component(nx.prototype(component1), folder.path_detail1("900", key, "ush"))
        _set_disp(_open(folder.path_detail1("900", str1, "000")))
        if os.path.isfile(folder.FileStrip900):
            _replace_strip_layout_in_display(folder.FileStrip900, "STRIP", True)

    _execute_clone_tran_900(folder)
    _set_disp(_open(folder.path_detail1("900", "900", "000")))
    try:
        _delete_self_and_constraints(_find_component(_root(_disp()), "COMPONENT seed-tran-op-lsp 1"))
    except Exception as ex:
        nx.print_exception(ex)
    try:
        _delete_self_and_constraints(_find_component(_root(_disp()), "COMPONENT seed-tran-op-usp 1"))
    except Exception as ex:
        nx.print_exception(ex)

    with nx.display_part_reset():
        for file in _lwr_upr_files(folder):
            nx.add_component(_disp(), file)

    _replace_strip_layout_in_display(folder.FileStrip900, "STRIP", False)

    for key in dictionary:
        _save_part(_open(folder.file_detail0(key, "000")))
        for op in dictionary[key]:
            _save_part(_open(folder.file_detail0(op, "000")))

    for file in _get_files(folder.DirLayout, folder.CustomerNumber + "-T*-Press.prt"):
        match = re.match(r"^\d+-T(?P<op>\d+)-Press", os.path.basename(file), re.IGNORECASE)
        if match:
            _add_press(folder, match.group("op"))

    for file in _get_files(folder.dir_op("900"), "*-000.prt"):
        _save_part(_open(file))

    for child in _children(_disp()):
        child.SetName(child.DisplayName.replace(folder.CustomerNumber + "-", ""))
        if child.DisplayName.endswith("lwr") or child.DisplayName.endswith("upr"):
            nx.set_reference_set(child, "BODY")
            nx.set_layer(child, 101 if child.DisplayName.endswith("upr") else 1)

    with nx.display_part_reset():
        for file in _lwr_upr_files(folder):
            is_lwr = _stem(file).endswith("lwr")
            _set_disp(_open(file))
            _constrain_shoe(folder, start_with_strip, "l" if is_lwr else "u")

    with nx.display_part_reset():
        for child in _children(_disp()):
            name = child.DisplayName.lower()
            if name.endswith("-lwr") or name.endswith("-upr"):
                nx.set_reference_set(child, "MATE")
                _constrain_abs(child, child.DisplayName + "-XY", 0)
                _constrain_abs(child, child.DisplayName + "-XZ", 2)
                _constrain_abs(child, child.DisplayName + "-YZ", 1)
                nx.set_reference_set(child, "BODY")

    with nx.display_part_reset():
        for file in _lwr_upr_files(folder):
            _set_disp(_open(file))
            for child in _children(_disp()):
                if "strip" not in child.DisplayName.lower():
                    nx.set_reference_set(child, "BODY")
                    _find_reference_set(_disp(), _RefsetBody).AddObjectsToReferenceSet([child])
            _disp().Undisplay()

    with nx.display_part_reset():
        for file in _lwr_upr_files(folder):
            _set_disp(_open(file))
            for expression in _expressions(_open(file)):
                match = re.match(r"^(?P<name>T\d{3}[XYZ])$", _formula(expression))
                if match:
                    _rename(expression, match.group("name") + "_")
                    nx.ufsession_.Modeling.Update()
                    _edit_with_mm(expression)
            if "upr" in _disp().Leaf.lower():
                for child in _children(_disp()):
                    if "strip" not in child.Name.lower():
                        nx.set_layer(child, 101)
            _disp().Undisplay()

    with nx.display_part_reset():
        _create_interpart_expression(
            _disp(), _find_expression(_open(folder.file_strip("900")), "CenterLineofCoil"), "CenterLineofCoil")
        expression = _find_expression(_disp(), "datum_plane_12_offset")
        expression.SetFormula("CenterLineofCoil")
        _disp().Expressions.Rename(expression, _formula(expression) + "_")
        _disp().Expressions.EditWithUnits(expression, _mm_unit(expression.OwningPart), _formula(expression))

    with nx.display_part_reset():
        _disp().Layers.MoveDisplayableObjects(256, list(_disp().DisplayedConstraints))

    with nx.display_part_reset():
        for op in source:
            _save_part(_open(folder.file_detail_000(op)))
        for file in _get_files(folder.dir_op("900"), "*-000.prt"):
            _save_part(_open(file))

    nx.print_("/////////////////////////////////////")

    with nx.display_part_reset():
        for file in _lwr_upr_files(folder):
            _set_disp(_open(file))
            array = [c for c in _children(_disp())
                     if c.DisplayName.lower().endswith("-lsp") or c.DisplayName.lower().endswith("-usp")]
            nx.replace_ref_sets(_disp(), array, "MATE")
            if chk_start_with_blank:
                strip = _open(folder.file_strip("900"))
                for name in ("P010X", "P010Y", "P010Z"):
                    _create_interpart_expression(_disp(), _find_expression(strip, name), name)
            for component in array:
                match = re.match(r"^\d+-(?P<op>\d+)-(usp|lsp)$", component.DisplayName, re.IGNORECASE)
                if match is None:
                    nx.print_("Wasn't a success")
                    continue
                op = match.group("op")
                if chk_start_with_blank and op == "010":
                    # Not in a try - see the module docstring.
                    _constrain_occ_proto_distance(_disp(), _abs_occ(component, 1), _abs_yz(_disp()), "P010X")
                    _constrain_occ_proto_distance(_disp(), _abs_occ(component, 2), _abs_xz(_disp()), "P010Y")
                    _constrain_occ_proto_distance(_disp(), _abs_occ(component, 0), _abs_xy(_disp()), "P010Z")
                    continue
                if chk_start_with_blank:
                    station = _op_020_to_010(op)
                    y_message: Optional[str] = "T{}Y - {} - {}".format(station, _disp().Leaf, component.DisplayName)
                else:
                    _op_020_to_010(op)  # computed and discarded, as in the C#
                    station = op
                    y_message = None
                try:
                    _constrain_occ_proto_distance(_disp(), _abs_occ(component, 1), _abs_yz(_disp()),
                                                  "T{}X".format(station))
                except Exception as ex:
                    nx.print_exception(ex)
                try:
                    _constrain_occ_proto_distance(_disp(), _abs_occ(component, 2), _abs_xz(_disp()),
                                                  "T{}Y".format(station))
                except Exception as ex:
                    nx.print_exception(ex, y_message)
                try:
                    _constrain_occ_proto_distance(_disp(), _abs_occ(component, 0), _abs_xy(_disp()),
                                                  "T{}Z".format(station))
                except Exception as ex:
                    nx.print_exception(ex)
            for expression in _expressions(_disp()):
                if (not cast(Any, expression).IsInterpartExpression
                        and re.match(r"^(?P<pt>P|T)(?P<op>\d+)(?P<xyz>X|Y|Z)$", _formula(expression))):
                    _rename(expression, _formula(expression) + "_")
                    _edit_with_mm(expression)

    with nx.display_part_reset():
        for op in source:
            if op.startswith("3"):
                new_part_name = "{}-{}-dieset-control.prt".format(folder.CustomerNumber, op)
                for detail in ("002", "012", "502", "512"):
                    _set_disp(_open(folder.file_detail0(op, detail)))
                    _disp().Expressions.ChangeInterpartReferences("seed-prog-dieset-control.prt", new_part_name,
                                                                  True, True)

    for op in source + ["900"]:
        for file in _get_files(folder.dir_op(op), "*-000.prt"):
            _save_part(_open(file))

    nx.print_("Designer will have to link up presses to proper dieset control manualy.")


# ---------------------------------------------------------------------------------------------------
# Presses and constraints
# ---------------------------------------------------------------------------------------------------

def _add_presses(folder: _JobFolder) -> None:
    """Static.CloneAssemblyAddPresses - every Layout file whose path contains "press", at the origin on layer 245."""
    try:
        part_list = [_open(os.path.join(folder.DirLayout, name))
                     for name in sorted(os.listdir(folder.DirLayout), key=lambda n: n.lower())
                     if os.path.isfile(os.path.join(folder.DirLayout, name))
                     and "press" in os.path.join(folder.DirLayout, name).lower()]
        result: Any = _disp().ComponentAssembly.AddComponents(
            part_list, NXOpen.Point3d(0.0, 0.0, 0.0), nx.identity_matrix(), 245, "Entire Part", 1, False)
        components = _components_in(result)
        for press in components:
            _constrain_xz_to_datum_plane(press)
            _constrain_abs(press, "PRESS-XY", 0)
            _constrain_abs(press, "PRESS-YZ", 1)
        nx.replace_ref_sets(_disp(), components, "BODY")
    except Exception as ex:
        nx.print_exception(ex)


def _components_in(result: Any) -> List[Any]:
    """The Component[] out parameter of AddComponents, wherever the Python binding puts it in its result."""
    values = list(result) if isinstance(result, (tuple, list)) else [result]
    for value in values:
        if isinstance(value, (tuple, list)) and all(isinstance(v, NXOpen.Assemblies.Component) for v in value):
            return list(value)
    if values and all(isinstance(v, NXOpen.Assemblies.Component) for v in values):
        return values
    return []


def _add_press(folder: _JobFolder, op: str) -> None:
    """Static.CloneAssemblyAddPress(GFolder, op) - {job}-T{op}-Press from the Layout folder into the display part."""
    try:
        path = folder.file_press_t(op)
        if not os.path.isfile(path):
            nx.print_("////////////////////////////")
            nx.print_("Did not add press to " + _disp().Leaf)
            nx.print_("Could not find press path " + path)
            nx.print_("////////////////////////////")
        else:
            press = nx.add_component(_disp(), path, "Entire Part", "PRESS-T" + op, NXOpen.Point3d(0.0, 0.0, 0.0),
                                     nx.identity_matrix(), 245)
            try:
                _constrain_xz_to_datum_plane(press)
            except Exception as ex:
                nx.print_exception(ex)
            _constrain_abs(press, "PRESS-XY", 0)
            _constrain_abs(press, "PRESS-YZ", 1)
    except Exception as ex:
        nx.print_exception(ex)


def _constrain_xz_to_datum_plane(press: Any) -> None:
    """Static.CloneAssemblyConstrainXzToDatumPlane - the press's PROTO#HANDLE R-807 plane to DATUM_PLANE(12)."""
    try:
        constraint = _constrain_occ_proto_distance(
            _disp(), press.FindObject("PROTO#HANDLE R-807"), _disp().Datums.FindObject("DATUM_PLANE(12)"), "0")
        constraint.GetDisplayedConstraint().SetName("PRESS-XZ")
    except NXOpen.NXException as ex:
        if ex.ErrorCode == 3520016:
            raise RuntimeError("Could not find object " + _disp().Leaf) from ex
        raise
    except Exception as ex:
        nx.print_exception(ex)


def _constrain_abs(component: Any, constraint_name: str, index: int) -> None:
    """Static.CloneAssemblyConstrainXy (0) / Yz (1) / Xz (2): the component's absolute plane to the WORK part's,
    distance 0."""
    try:
        work_plane = clone_strip._datum_plane(_absolute_datum_csys(nx.work_part()), index)
        _constrain_occ_proto_distance(_disp(), _abs_occ(component, index), work_plane, "0").SetName(constraint_name)
    except Exception as ex:
        nx.print_exception(ex)


def _constrain_ops_to_lwr_upr(folder: _JobFolder, ops: List[str], lwrupr: str, layer: int) -> None:
    """Static.CloneAssemblyConstrainOpsToLwrUpr - each op's lwr / upr into the 900 lwr / upr, constrained to the
    strip's T{op}X/Y/Z."""
    point3d = _feed_point(folder)
    _set_disp(_open(folder.file_detail0("900", lwrupr)))
    nx.set_reference_set(_single([c for c in _children(_disp()) if c.Name == "STRIP"]), "BODY")
    for op in ops:
        component = nx.add_component(_disp(), folder.file_detail0(op, lwrupr), "MATE", origin=point3d, layer=layer)
        exp_x = "T{}X".format(op)
        exp_y = "T{}Y".format(op)
        exp_z = "T{}Z".format(op)
        builder = _disp().Expressions.CreateInterpartExpressionsBuilder()
        strip = _open(folder.FileStrip900)
        try:
            _constrain_strip_interpart_expressions(exp_x, exp_y, exp_z, builder, strip)
        except Exception as ex:
            nx.print_exception(ex)
        # ConstrainXy1 / ConstraintXz1 / NewMethod21
        _constrain_units(component, exp_z, _abs_occ(component, 0), _abs_xy(_disp()), "XY")
        _constrain_units(component, exp_y, _abs_occ(component, 2), _abs_xz(_disp()), "XZ")
        _constrain_units(component, exp_x, _abs_occ(component, 1), _abs_yz(_disp()), "YZ")
        nx.set_reference_set(component, "BODY")


def _constrain_units(comp: Any, exp_name: str, datum_plane1: Any, datum_plane2: Any, suffix: str) -> None:
    """Static.CloneAssemblyConstrainUnits"""
    constraint = _constrain_occ_proto_distance(_disp(), datum_plane1, datum_plane2, exp_name)
    nx.set_layer(constraint.GetDisplayedConstraint(), 256)
    constraint.SetName("{}-{}".format(comp.Name, suffix))
    expression = _single([e for e in _expressions(_disp()) if _formula(e) == exp_name])
    _edit_with_mm(expression)
    _rename(expression, exp_name + "_")


def _constrain_shoe(folder: _JobFolder, start_with_strip: bool, side: str) -> None:
    """Static.CloneAssemblyConstrainLSH (side "l") / ConstrainUSH ("u") - constrains the {side}sh shoe to the
    absolute planes and links the strip's station expressions for each {side}sp child (no constraints yet)."""
    shoe = "-{}sh".format(side)
    plate = "-{}sp".format(side)
    prefix = shoe[1:].upper()
    press = _single([c for c in _children(_disp()) if c.DisplayName.lower().endswith(shoe)])
    try:
        _constrain_abs(press, prefix + "-XY", 0)
        _constrain_abs(press, prefix + "-XZ", 2)
        _constrain_abs(press, prefix + "-YZ", 1)
    except Exception as ex:
        nx.print_exception(ex)
    for child in _children(_disp()):
        if not child.DisplayName.endswith(plate):
            continue
        op = child.DisplayName.replace(folder.CustomerNumber + "-", "").replace(plate, "")
        _absolute_datum_csys(nx.prototype(child))  # read and discarded; throws when there is none
        station = _op_020_to_010(op) if start_with_strip else op
        if op == "010" and start_with_strip:
            exp_x, exp_y, exp_z = "P010X", "P010Y", "P010Z"
        else:
            exp_x, exp_y, exp_z = "T{}X".format(station), "T{}Y".format(station), "T{}Z".format(station)
        builder = _disp().Expressions.CreateInterpartExpressionsBuilder()
        strip = _open(folder.FileStrip900)
        try:
            _constrain_strip_interpart_expressions(exp_x, exp_y, exp_z, builder, strip)
        except Exception as ex:
            nx.print_exception(ex)


def _constrain_strip_interpart_expressions(exp_x: str, exp_y: str, exp_z: str, builder: Any, strip: Any) -> None:
    """Static.CloneAssemblyConstrainStripInterpartExpressions - links the strip's exp_x/y/z under the same names;
    the builder is destroyed either way."""
    try:
        expressions = _expressions(strip)
        builder.SetExpressions([_single([e for e in expressions if e.Name == exp_x]),
                                _single([e for e in expressions if e.Name == exp_y]),
                                _single([e for e in expressions if e.Name == exp_z])],
                               [exp_x, exp_y, exp_z])
        builder.Commit()
    finally:
        builder.Destroy()


def _replace_strip_layout_in_display(path: str, name: str, replace_all: bool) -> None:
    """Static.CloneAssemblyReplaceStripLayoutInDisplay"""
    _replace_component(_find_component(_root(_disp()), "COMPONENT seed-strip-layout 1"), path, name, replace_all)


# ---------------------------------------------------------------------------------------------------
# DeleteUnitFasteners - the recorded-journal deletes, as tables
# ---------------------------------------------------------------------------------------------------

_LwrPlateMm = (
    ["HANDLE R-21229", "HANDLE R-21244", "HANDLE R-21259", "HANDLE R-21274", "HANDLE R-21287", "HANDLE R-21302",
     "HANDLE R-21316", "HANDLE R-21330", "HANDLE R-21348", "HANDLE R-21357", "HANDLE R-21377", "HANDLE R-21388",
     "HANDLE R-21407", "HANDLE R-21416", "HANDLE R-21425", "HANDLE R-21451"],
    ["COMPONENT 1500-shcs-500 7", "COMPONENT 1500-shcs-500 3", "COMPONENT 1500-shcs-500 1",
     "COMPONENT 1500-shcs-500 8", "COMPONENT 1500-shcs-500 5", "COMPONENT 1500-shcs-500 2",
     "COMPONENT 1500-shcs-500 6", "COMPONENT 1500-shcs-500 4"])
_LwrPlateEnglish = (
    ["HANDLE R-2213", "HANDLE R-2254", "HANDLE R-2312", "HANDLE R-2354", "HANDLE R-2649", "HANDLE R-2703",
     "HANDLE R-2762", "HANDLE R-2819", "HANDLE R-3102", "HANDLE R-3160", "HANDLE R-3232", "HANDLE R-3291",
     "HANDLE R-3572", "HANDLE R-3628", "HANDLE R-3686", "HANDLE R-3743"],
    ["COMPONENT 36mm-shcs-100 7", "COMPONENT 36mm-shcs-100 1", "COMPONENT 36mm-shcs-100 6",
     "COMPONENT 36mm-shcs-100 3", "COMPONENT 36mm-shcs-100 4", "COMPONENT 36mm-shcs-100 8",
     "COMPONENT 36mm-shcs-100 5", "COMPONENT 36mm-shcs-100 2"])
_UprPlateMm = (
    ["HANDLE R-2145", "HANDLE R-2163", "HANDLE R-2185", "HANDLE R-2201", "HANDLE R-2220", "HANDLE R-2242",
     "HANDLE R-2264", "HANDLE R-2288", "HANDLE R-2308", "HANDLE R-2332", "HANDLE R-2352", "HANDLE R-2370",
     "HANDLE R-2390", "HANDLE R-2408", "HANDLE R-2426", "HANDLE R-2448", "HANDLE R-2471"],
    ["COMPONENT 1500-shcs-500 5", "COMPONENT 1500-shcs-500 7", "COMPONENT 1500-shcs-500 3",
     "COMPONENT 1500-shcs-500 2", "COMPONENT 1500-shcs-500 4", "COMPONENT 1500-shcs-500 8",
     "COMPONENT 1500-shcs-500 6", "COMPONENT 1500-shcs-500 1"])
_UprPlateEnglish = (
    ["HANDLE R-2893", "HANDLE R-2911", "HANDLE R-2498", "HANDLE R-2519", "HANDLE R-2542", "HANDLE R-2560",
     "HANDLE R-2582", "HANDLE R-2608", "HANDLE R-2637", "HANDLE R-2660", "HANDLE R-2708", "HANDLE R-2728",
     "HANDLE R-2760", "HANDLE R-2796", "HANDLE R-2817", "HANDLE R-2832"],
    ["COMPONENT 36mm-shcs-100 8", "COMPONENT 36mm-shcs-100 5", "COMPONENT 36mm-shcs-100 4",
     "COMPONENT 36mm-shcs-100 1", "COMPONENT 36mm-shcs-100 3", "COMPONENT 36mm-shcs-100 7",
     "COMPONENT 36mm-shcs-100 6", "COMPONENT 36mm-shcs-100 2"])


def _guide_components(unit: str) -> List[str]:
    """The lsh's guide pins, bushings and stop blocks of one unit ("English" / "Metric"), in the C#'s order."""
    stop = "TSG-E-StopBlock-specify hgt-groove" if unit == "English" else "TSG-M-StopBlock-specify hgt-groove"
    names = ["Smart Demountable Guide Pin " + unit, "Smart Demountable Bushing " + unit, "Smart " + stop]
    return ["COMPONENT {} {}".format(name, n) for name in names for n in (4, 3, 2, 1)]


def _delete_plate_mm(handles: List[str], components: List[str]) -> None:
    """The units_mm branch of a plate's journal delete: handles, then the 1500-shcs-500s."""
    session: Any = nx.session_
    session.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, "Delete")
    work_part: Any = nx.work_part()
    newest_visible_undo_mark = session.NewestVisibleUndoMark
    objects1 = [work_part.FindObject(h) for h in handles]
    _delete_list_and_update(objects1, newest_visible_undo_mark)
    undo_mark = session.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, "Delete")
    objects2 = [_root(work_part).FindObject(c) for c in components]
    _delete_list_and_update(objects2, undo_mark)


def _delete_plate_english(handles: List[str], components: List[str]) -> None:
    """The english branch: each delete between an invisible mark (deleted after) and a visible one."""
    session: Any = nx.session_
    session.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, "Delete")
    for names, is_components in ((handles, False), (components, True)):
        work: Any = session.Parts.Work
        mark_id = session.SetUndoMark(NXOpen.Session.MarkVisibility.Invisible, "Delete")
        session.UpdateManager.ClearErrorList()
        session.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, "Delete")
        owner = _root(work) if is_components else work
        objects = [owner.FindObject(n) for n in names]
        session.UpdateManager.AddObjectsToDeleteList(objects)
        session.UpdateManager.DoUpdate(session.NewestVisibleUndoMark)
        session.DeleteUndoMark(mark_id, None)


def _delete_unit_fasteners(folder: _JobFolder, op: str, units_mm: bool) -> None:
    """Static.CloneAssemblyDeleteUnitFasteners - deletes the other unit's constraints, fasteners, guide pins,
    bushings and stop blocks from an op's 002/012/502/512, lwrplate, uprplate and lsh."""
    try:
        session: Any = nx.session_
        with nx.display_part_reset():
            parts = [_open("{}-{}-{}".format(folder.CustomerNumber, op, detail))
                     for detail in ("002", "012", "502", "512")]
            for part in parts:
                _set_disp(part)
                _open_assembly_whole(_disp())
                session.UpdateManager.ClearErrorList()
                undo_mark1 = session.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, "parallels")
                constraints = list(_disp().DisplayedConstraints)
                if not units_mm:
                    session.UpdateManager.AddObjectsToDeleteList([c for c in constraints if c.Layer == 255])
                else:
                    session.UpdateManager.AddObjectsToDeleteList([c for c in constraints if c.Layer != 255])
                session.UpdateManager.DoUpdate(undo_mark1)
                session.UpdateManager.ClearErrorList()
                undo_mark2 = session.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, "parallels")
                for child in _children(part):
                    is_mm = "MM" in child.Name.upper()
                    if (is_mm and not units_mm) or (not is_mm and units_mm):
                        session.UpdateManager.AddObjectsToDeleteList(
                            [c.GetDisplayedConstraint() for c in child.GetConstraints()])
                        session.UpdateManager.AddObjectsToDeleteList([child])
                session.UpdateManager.DoUpdate(undo_mark2)

        with nx.display_part_reset():
            _set_disp(_open("{}-{}-lwrplate".format(folder.CustomerNumber, op)))
            if units_mm:
                _delete_plate_mm(*_LwrPlateMm)
            else:
                _delete_plate_english(*_LwrPlateEnglish)

        with nx.display_part_reset():
            _set_disp(_open("{}-{}-uprplate".format(folder.CustomerNumber, op)))
            if units_mm:
                _delete_plate_mm(*_UprPlateMm)
            else:
                _delete_plate_english(*_UprPlateEnglish)

        with nx.display_part_reset():
            _set_active_display(_open(folder.file_detail0(op, "lsh")))
            for name in _guide_components("English" if units_mm else "Metric"):
                _delete_self_and_constraints(_find_component(_root(_disp()), name))
    except Exception as ex:
        nx.print_exception(ex)


# ---------------------------------------------------------------------------------------------------
# UF_CLONE runs
# ---------------------------------------------------------------------------------------------------

_LineOpDetails = ["lsh", "002", "012", "lwrcast", "lwrplate", "lwr-c-clamp", "lwr-d-clamp", "lwr-e-clamp"]

# ExecuteCloneProg: (seed leaf, detail), in the C#'s order.
_ProgParts: List[Tuple[str, str]] = (
    [("seed-prog-000", "000"), ("seed-prog-lwr", "lwr"), ("seed-prog-upr", "upr")]
    + [("seed-line-op-" + d, d) for d in _LineOpDetails]
    + [("seed-line-op-" + d, d) for d in ("ush", "502", "512", "uprcast", "uprplate", "upr-c-clamp", "upr-d-clamp",
                                          "upr-e-clamp", "dieset-control", "casting-text", "lwr-smart-rollover",
                                          "upr-smart-rollover")]
    + [("seed-prog-" + d, d) for d in ("lsp1", "lsp2", "lsp3", "lsp4", "usp1", "usp2", "usp3", "usp4")])

# ExecuteCloneTranShoe
_TranShoeParts: List[Tuple[str, str]] = (
    [("seed-tran-shoe-000", "000")]
    + [("seed-line-op-" + d, d) for d in _LineOpDetails]
    + [("seed-line-op-" + d, d) for d in ("lwr-smart-rollover", "ush", "502", "512", "uprcast", "uprplate",
                                          "upr-c-clamp", "upr-d-clamp", "upr-e-clamp", "upr-smart-rollover",
                                          "dieset-control", "casting-text")])

# ExecuteCloneLineOp (name rule seed-line-op- -> {job}-{op}-)
_LineOpSeeds = ["000", "002", "012", "502", "512", "casting-text", "dieset-control", "lsh", "lsp", "lwr", "lwrcast",
                "lwr-c-clamp", "lwr-d-clamp", "lwr-e-clamp", "lwrplate", "lwr-smart-rollover", "ush", "usp", "upr",
                "uprcast", "upr-c-clamp", "upr-d-clamp", "upr-e-clamp", "uprplate", "upr-smart-rollover"]


def _clone_begin(naming: Any) -> Any:
    clone: Any = nx.ufsession_.Clone
    clone.Terminate()
    clone.Initialise(NXOpen.UF.Clone.OperationClass.CLONE_OPERATION)
    clone.SetDefNaming(naming)
    return clone


def _clone_user_named(def_directory: str, names: Sequence[Tuple[str, str]]) -> None:
    """A USER_NAME clone of (seed path, output path) pairs into def_directory."""
    clone = _clone_begin(NXOpen.UF.Clone.NamingTechnique.USER_NAME)
    for seed, output in names:
        clone.AddPart(seed)
        clone.SetNaming(seed, NXOpen.UF.Clone.NamingTechnique.USER_NAME, output)
    clone.SetDefDirectory(def_directory)
    failures = clone.InitNamingFailures()
    clone.PerformClone(failures)
    clone.Terminate()


def _name_rule(base_string: str, new_string: str) -> Any:
    """UFClone.NameRuleDef { base_string, new_string, type = ReplaceString }"""
    uf_clone: Any = NXOpen.UF.Clone
    rule = uf_clone.NameRuleDef()
    rule.Type = uf_clone.NameRuleType.REPLACE_STRING
    rule.BaseString = base_string
    rule.NewString = new_string
    return rule


def _clone_name_ruled(def_directory: str, seeds: Sequence[str], base_string: str, new_string: str,
                      print_failures: bool = False) -> None:
    """A NAMING_RULE clone (replace base_string with new_string) of the seed paths into def_directory.
    print_failures: ExecuteCloneTranOp's catch around PerformClone."""
    clone = _clone_begin(NXOpen.UF.Clone.NamingTechnique.NAMING_RULE)
    for seed in seeds:
        clone.AddPart(seed)
    clone.SetDefDirectory(def_directory)
    failures = clone.InitNamingFailures()
    updated = clone.SetNameRule(_name_rule(base_string, new_string), failures)
    if updated is not None:
        failures = updated
    if not print_failures:
        clone.PerformClone(failures)
    else:
        try:
            clone.PerformClone(failures)
        except Exception as ex:
            nx.print_exception(ex)
            count = int(getattr(failures, "NFailures", 0) or 0)
            nx.print_(count)
            inputs = list(getattr(failures, "InputNames", None) or [])
            outputs = list(getattr(failures, "OutputNames", None) or [])
            statuses = list(getattr(failures, "Statuses", None) or [])
            for i in range(count):
                nx.print_(inputs[i] if i < len(inputs) else "")
                nx.print_(outputs[i] if i < len(outputs) else "")
                nx.print_(statuses[i] if i < len(statuses) else "")
                nx.print_("//////////")
    clone.Terminate()


def _execute_clone_prog(folder: _JobFolder, op: str) -> None:
    """Static.CloneAssemblyExecuteCloneProg - ends by opening the 010 casting-text whatever the op."""
    _clone_user_named(folder.dir_op(op),
                      [(_Seed + seed + ".prt", folder.path_op_detail(op, detail)) for seed, detail in _ProgParts])
    _open(folder.path_op_detail("010", "casting-text"))


def _execute_clone_line_900(folder: _JobFolder) -> None:
    """Static.CloneAssemblyExecuteCloneLine900"""
    _clone_name_ruled(folder.dir_op("900"),
                      [_Seed + "seed-line-900-{}.prt".format(d) for d in ("000", "lwr", "upr")],
                      "seed-line-900-", folder.CustomerNumber + "-900-")


def _execute_clone_line_op(folder: _JobFolder, op: str) -> None:
    """Static.CloneAssemblyExecuteCloneLineOp"""
    _clone_name_ruled(folder.dir_op(op), [_Seed + "seed-line-op-{}.prt".format(d) for d in _LineOpSeeds],
                      "seed-line-op-", "{}-{}-".format(folder.CustomerNumber, op))


def _execute_clone_tran_assembly_op(def_directory: str, clone_dict: Dict[str, str]) -> None:
    """Static.CloneAssemblyExecuteCloneTranAssemblyOp"""
    _clone_user_named(def_directory, list(clone_dict.items()))


def _execute_clone_tran_shoe(folder: _JobFolder, op: str) -> None:
    """Static.CloneAssemblyExecuteCloneTranShoe"""
    _clone_user_named(folder.dir_op(op),
                      [(_Seed + seed + ".prt", folder.path_op_detail(op, detail)) for seed, detail in _TranShoeParts])


def _execute_clone_tran_op(folder: _JobFolder, op: str) -> None:
    """Static.CloneAssemblyExecuteCloneTranOp - prints the naming failures when PerformClone throws."""
    _clone_name_ruled(folder.dir_op(op), [_Seed + "seed-tran-op-{}.prt".format(d) for d in ("000", "lsp", "usp")],
                      "seed-tran-op-", "{}-{}-".format(folder.CustomerNumber, op), print_failures=True)


def _execute_clone_tran_900(folder: _JobFolder) -> None:
    """Static.CloneAssemblyExecuteCloneTran900"""
    _clone_user_named(folder.dir_op("900"),
                      [(_Seed + "seed-tran-op-000.prt", folder.path_detail1("900", "900", "000"))])


# ---------------------------------------------------------------------------------------------------
# Dialog
# ---------------------------------------------------------------------------------------------------

def _display_job_folder() -> str:
    """The display part's job folder (GFolder.Create of its path), or "" when there is none."""
    display = nx.display_part()
    if display is None:
        return ""
    try:
        return clone_strip._GFolder.create(display.FullPath).DirJob
    except Exception:
        return ""


class _CloneAssemblyDialog(Dialog):
    dlx_name = "CloneAssembly.dlx"

    def __init__(self, title: str) -> None:
        self.title = title
        super().__init__()
        # Captured in ok(): the blocks are gone once Launch returns.
        self.job_folder = ""
        self.ops_text = ""
        self.clone_type = TypeTransfer
        self.start_with_blank = False
        self.metric = True
        self.press_dieset_op = 0

    def shown(self) -> None:
        self.set_string_value(self.block("job_folder"), _display_job_folder())
        self.block("type").ValueAsString = TypeTransfer
        self.block("units").ValueAsString = UnitsMetric
        self.block("press_dieset_op").Value = 0
        self.block("start_with_blank").Value = False
        self._type_changed()

    def _type_changed(self) -> None:
        """rdoTransfer_CheckedChanged"""
        clone_type = str(self.block("type").ValueAsString)
        transfer = clone_type == TypeTransfer
        self.block("start_with_blank").Show = transfer
        if not transfer:
            self.block("start_with_blank").Value = False
        self.set_string_value(self.block("ops"), _DefaultOps.get(clone_type, ""))

    def update(self, block: NXOpen.BlockStyler.UIBlock) -> None:
        if block == self.block("type"):
            self._type_changed()
        elif block == self.block("browse_job"):
            current = self.string_value(self.block("job_folder"))
            path = nx.select_folder_or_none("Job Folder", current if current and os.path.isdir(current) else "G:\\")
            if path:
                self.set_string_value(self.block("job_folder"), path)

    def enable_ok(self) -> bool:
        return bool(self.string_value(self.block("job_folder"))) and bool(self.string_value(self.block("ops")))

    def ok(self) -> bool:
        self.job_folder = self.string_value(self.block("job_folder"))
        self.ops_text = ops_text_from_rows(self.string_value(self.block("ops")))
        self.clone_type = str(self.block("type").ValueAsString)
        self.start_with_blank = self.clone_type == TypeTransfer and bool(self.block("start_with_blank").Value)
        self.metric = str(self.block("units").ValueAsString) == UnitsMetric
        self.press_dieset_op = int(self.block("press_dieset_op").Value)
        return bool(self.job_folder) and bool(self.ops_text)


def execute() -> None:
    title = title_with_version("Clone Assembly")
    try:
        dialog = _CloneAssemblyDialog(title)
        if not dialog.run():
            return
    except NXOpen.NXException as ex:
        if ex.ErrorCode != _ErrorCannotLaunchDialog:
            raise
        nx.print_exception(ex)
        nx.show_error("NX would not open the {} dialog (error {} - it will not create a dialog from inside a "
                      "callback).\n\nTry running it from File -> Execute -> NX Open rather than from a menu or "
                      "toolbar button.".format(title, _ErrorCannotLaunchDialog))
        return

    clone_job(dialog.job_folder, dialog.ops_text, dialog.clone_type == TypeTransfer, dialog.clone_type == TypeLine,
              dialog.clone_type == TypeProgressive, dialog.start_with_blank, dialog.metric, dialog.press_dieset_op)


def main() -> None:
    """The clone-assembly UFunc - its menu button runs this file. An escaping exception is printed."""
    import usage_db

    with usage_db.run(ufunc_name):
        try:
            execute()
        except Exception as ex:
            nx.print_exception(ex)


if __name__ == "__main__":
    main()

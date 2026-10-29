"""
The clone-strip UFunc: a standalone Python UFunc (no C# class, 2026-10-29); its menu button runs this file's main().
It replaced the WinForms CloneStrip form and src\\Static\\CloneStrip.cs (in git at 5fb0e3c), whose NX work this
module had ported since 2026-10-21.

The dialog (CloneStrip.dlx, tools\\make-dlx.py) is the form:
- Job Path (the display part's job folder on opening; Browse... is the form's double click, a folder box), and the
  Create group's Transfer / Prog Stations, Transfer / Prog Presses, Prog 005 and Offline Die. OK runs Create
  (create_station: the job-path check, then CloneStrip.create).
- The Edit group's buttons run at once and leave the dialog open: Add Station / Delete Station on the Station Layout
  picked in the dialog (NX opens no selection dialog from a dialog callback, so the old pick-after-the-button is a
  selection block), Add Tran Press / Add Prog Press, and Add Simulation (the Simulation Reference Set option) /
  Delete Simulation. One Edit button run counts as done, so a Cancel after it does not mark the run cancelled.
- Reset()'s rules: transfer stations without Offline Die take no prog presses (0, greyed out); no transfer
  stations take no transfer presses and no Offline Die. The reference set list is rebuilt after each Edit button
  (the form's combo box only ever grew); with no simulation, or more than one, Add Simulation is greyed out.

The C# it ports, member by member:

- CloneStripCreate (+ clone_non_offline_die / clone_offline_die / ExecuteCloneStrip / ExecuteCloneStrip1 and
  the per-station tran_* / prog_* adds)                                   -> CloneStrip.create
- CloneStripAddStation, after its component pick                         -> CloneStrip.add_station
- CloneStripDeleteStation(Component)                                     -> CloneStrip.delete_station
- update_sim_components                                                  -> CloneStrip.update_sim_components
- CloneStripMoveStation, ask_prog_station_10, ask_tran_station_10,
  delete_prog_presses_from_display, prog_transfer                        -> module-level helpers

The CloneAssembly members CloneStrip calls (add_component_and_constrain and its NewMethod24/8/5,
replace_interpart_expressions, add_press(string) and its NewMethod43/25/27) are ported here as private helpers,
along with the Globals.cs extensions they need (__ConstrainOccProtoDistance, __Op10To010, __FindExpression,
__DeleteSelfAndConstraints, ...) and the GFolder members CloneStrip reads.

- CloneStripCreateStation (job-path check, GFolder.create_or_null, timing) -> create_station
- CloneStripAddSimulation / CloneStripDeleteSimulation                    -> add_simulation / delete_simulation
- the form's Load / Reset / button handlers                              -> _CloneStripDialog

NEVER RUN IN NX - untested, the 2026-10-21 port included.

Difference: CloneStripCreate's Layers.ChangeStates([StateInfo(layer 5, Selectable)]) is Layers.SetState(5, Selectable)
here.

Quirks kept from the C#:
- prog_transfer(GFolder, op_str, prefix) calls itself with GFolder.Create(op_str). GFolder.Create("010") throws
  (fewer than three path segments) before the recursion can start, so add_station's progressive "last station
  with transfer stations" branch always fails into the outer catch. Here _GFolder.create raises IndexError the
  same way.
- File.Exists is used on directories (always false), so the three job folders are always (re)created.
- delete_prog_presses_from_display has no caller; ported for completeness.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
from typing import Any, Callable, List, Optional, cast

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
import NXOpen.Layer  # noqa: E402
import NXOpen.Positioning  # noqa: E402
import NXOpen.UF  # noqa: E402

import tsg_nx as nx  # noqa: E402
from tsg_dialog import Dialog, components_of, title_with_version  # noqa: E402

# GFolder constants.
_SeedFilesNx1919 = "G:\\0Library\\SeedFiles\\NX1919"
_XxxxxStrip = _SeedFilesNx1919 + "\\XXXXXX-Strip.prt"
_XxxxxxOpXxxLayout = _SeedFilesNx1919 + "\\XXXXXX-OP-XXX-Layout.prt"
_StripFlangeCarrierTracking = _SeedFilesNx1919 + "\\Strip Flange Carrier_Tracking Tab.prt"
# CloneAssembly.add_press - hard-coded there rather than GFolder.XxxxxPressXxAssembly (same path).
_PressSeed = "G:\\0Library\\SeedFiles\\NX1919\\XXXXX-Press-XX-Assembly.prt"

_LayoutRegex = r"^(\d{6})-(?P<__prefix>[TP])(?P<__op>\d{3})-Layout$"
_StationRegex = r"^(?P<cust_num>\d{6})-(?P<prefix>[TP])(?P<detail>\d{3})-Layout$"

# _Matrix3x3Identity / _Point3dOrigin
_Origin = NXOpen.Point3d(0.0, 0.0, 0.0)


class CloneStrip(object):

    @staticmethod
    def create(dir_job: str, customer_number: str, transfer_layouts: int, tran_presses: int, prog_layouts: int,
               prog_presses: int, start_at_005: bool, offline_die: bool) -> None:
        """
        Static.CloneStripCreate. Session.Execute cannot pass a GFolder, so the caller passes its DirJob and
        CustomerNumber (the C# builds it with GFolder.create_or_null(txtJobPath.Text)). start_at_005 is unused,
        as in the C#.
        """
        folder = _GFolder(dir_job, customer_number)

        if not os.path.isfile(folder.DirJob):
            os.makedirs(folder.DirJob, exist_ok=True)

        if not os.path.isfile(folder.DirLayout):
            os.makedirs(folder.DirLayout, exist_ok=True)

        if not os.path.isfile(folder.DirSimulation):
            os.makedirs(folder.DirSimulation, exist_ok=True)

        if not os.path.isfile(folder.PathSimulation):
            nx.print_("Couldn't find a simulation file")
            return

        if not offline_die:
            _clone_non_offline_die(folder, transfer_layouts, tran_presses, prog_layouts, prog_presses,
                                   "900" if transfer_layouts > 0 else "010")
        else:
            _clone_offline_die(folder, prog_layouts, transfer_layouts, prog_presses, tran_presses, "010")

        if os.path.isfile(folder.file_strip("010")):
            nx.add_component(nx.find_or_open(folder.file_strip("010")), folder.PathSimulation,
                             component_name="SIMULATION-STRIP", layer=8)

        if os.path.isfile(folder.file_strip("900")):
            nx.add_component(nx.find_or_open(folder.file_strip("900")), folder.PathSimulation,
                             component_name="SIMULATION-STRIP", layer=8)

        nx.ufsession_.Modeling.Update()
        nx.set_work_part(nx.display_part())
        CloneStrip.update_sim_components()

        _save(nx.display_part())

        for part in list(nx.session_.Parts):
            if part.IsModified and part.Leaf.startswith(folder.CustomerNumber):
                _save(part)

        # SetActiveDisplay returns the PartLoadStatus (C# out param); not confirmed against the Python binding.
        if os.path.isfile(folder.file_strip("010")):
            nx.session_.Parts.SetActiveDisplay(
                nx.find_or_open(folder.file_strip("010")),
                NXOpen.DisplayPartOption.AllowAdditional,
                NXOpen.PartDisplayPartWorkPartOption.SameAsDisplay)

        if os.path.isfile(folder.file_strip("900")):
            nx.session_.Parts.SetActiveDisplay(
                nx.find_or_open(folder.file_strip("900")),
                NXOpen.DisplayPartOption.AllowAdditional,
                NXOpen.PartDisplayPartWorkPartOption.SameAsDisplay)

        nx.display_part().Layers.WorkLayer = 1
        # C#: Layers.ChangeStates(new[] { new StateInfo { State = State.Selectable, Layer = 5 } }). StateInfo's Python
        # constructor is unconfirmed, so the one layer goes through SetState (used by the other ports) instead.
        nx.display_part().Layers.SetState(5, NXOpen.Layer.State.Selectable)
        _save(nx.display_part())

    @staticmethod
    def add_station(selected_comp: NXOpen.Assemblies.Component) -> None:
        """Static.CloneStripAddStation after its Selection.SelectSingleComponent() pick (None returns)."""
        try:
            if selected_comp is None:
                return

            selected_part_path = nx.prototype(selected_comp).FullPath

            match0 = re.match(_StationRegex, selected_comp.DisplayName)

            _progs = _ask_prog_station_10()

            _trans = _ask_tran_station_10()

            if match0 is None:
                raise Exception("Please select a valid transfer or progressive station")

            prefix = match0.group("prefix")

            if prefix == "T":
                ops = _ask_tran_station_10()
            elif prefix == "P":
                ops = _ask_prog_station_10()
            else:
                raise Exception()
            ops = sorted(set(ops), reverse=True)

            cust_num = match0.group("cust_num")

            selected_op = int(match0.group("detail"))

            for op in ops:
                if op < selected_op:
                    break

                _move_station(op, op + 10, cust_num, prefix)

            if selected_op == 10:
                _file_copy(_XxxxxxOpXxxLayout, selected_part_path)
            else:
                new_part_file = selected_part_path.replace(
                    "-{}{}-Layout".format(prefix, _op_10_to_010(selected_op)),
                    "-{}{}-Layout".format(prefix, _op_10_to_010(selected_op - 10)))
                _file_copy(new_part_file, selected_part_path)

            op_str = _op_10_to_010(selected_op)

            if prefix == "P":
                _prog_work(op_str, selected_part_path, prefix)
                _prog_lifted(op_str, selected_part_path, prefix)

                max_op = max(ops)

                if len(_ask_prog_station_10()) > 0 and len(_ask_tran_station_10()) > 0 and selected_op == max_op:
                    # GFolder.Create(op_str) throws - see the module docstring.
                    _prog_transfer(_GFolder.create(op_str), selected_part_path, prefix)

                    if max_op > 0:
                        _max_op_str = _op_10_to_010(max_op)
                        comp = _single(
                            [c for c in nx.children(nx.display_part())
                             if c.Name == "P{}-TRANSFER".format(_op_10_to_010(max_op))])
                        _delete_self_and_constraints(comp)

            if prefix == "T":
                _tran_work(op_str, selected_part_path, prefix)
                _tran_lifted(op_str, selected_part_path, prefix)
                _tran_transfer(op_str, selected_part_path, prefix)

            nx.ufsession_.Modeling.Update()
            CloneStrip.update_sim_components()
        except Exception as ex:
            nx.print_exception(ex)

    @staticmethod
    def delete_station(selected_comp: NXOpen.Assemblies.Component) -> None:
        """Static.CloneStripDeleteStation(Component). No outer try/except, as in the C#."""
        match0 = re.match(_StationRegex, selected_comp.DisplayName)

        if match0 is None:
            nx.print_("Please select a valid transfer or progressive station")
            return

        prefix = match0.group("prefix")

        if prefix == "T":
            ops = _ask_tran_station_10()
        elif prefix == "P":
            ops = _ask_prog_station_10()
        else:
            raise Exception()

        ops = sorted(set(ops))

        cust_num = match0.group("cust_num")
        selected_prefix = match0.group("prefix")
        selected_op = int(match0.group("detail"))
        selected_display_name = selected_comp.DisplayName
        selected_full_path = nx.prototype(selected_comp).FullPath

        selected_part = nx.prototype(selected_comp)
        _file_delete(selected_part.FullPath)

        part_occs, _count = nx.ufsession_.Assem.AskOccsOfPart(nx.display_part().Tag, nx.prototype(selected_comp).Tag)
        for part_occ in part_occs:
            _delete_self_and_constraints(cast(NXOpen.Assemblies.Component, nx.tagged_object(part_occ)))

        _close(selected_part)

        for op in ops:
            if op <= selected_op:
                continue
            _move_station(op, op - 10, cust_num, selected_prefix)

        # check if contains both T and P layouts
        prog_ops = [int(m.group("op")) for m in
                    (re.match(r"^P(?P<op>\d\d\d)-", c.Name) for c in nx.children(nx.display_part())) if m]

        tran_ops = [int(m.group("op")) for m in
                    (re.match(r"^T(?P<op>\d\d\d)-", c.Name) for c in nx.children(nx.display_part())) if m]

        if len(prog_ops) > 0 and len(tran_ops) > 0 and prefix == "P":
            _folder = _GFolder.create(nx.display_part().FullPath)

            _paths = [nx.prototype(c).FullPath for c in nx.children(nx.display_part())
                      if nx.is_loaded(c) and re.match(r"^P(?P<op>\d\d\d)-", c.Name)]

            _children = [n for n in (c.Name for c in nx.children(nx.display_part())) if n.startswith("P0")]

            max_op = _op_10_to_010(max(prog_ops))

            new_path = selected_full_path.replace(selected_display_name, "{}-P{}-Layout".format(cust_num, max_op))

            if selected_op - 10 == int(max_op):
                _prog_p_transfer(max_op, new_path, "P")

        nx.ufsession_.Modeling.Update()
        CloneStrip.update_sim_components()

    @staticmethod
    def update_sim_components() -> None:
        """Static.update_sim_components - deletes the root's layer-254 *SIMULATION* children, one DoUpdate each."""
        for child in nx.children(nx.display_part()):
            if child.Layer == 254 and "SIMULATION" in child.Name.upper():
                _delete_objects(child)


# ---------------------------------------------------------------------------------------------------
# Stations
# ---------------------------------------------------------------------------------------------------

def _ask_station_10(prefix: str) -> List[int]:
    """Static.ask_prog_station_10 / ask_tran_station_10 - the root children's layout ops, reversed."""
    ops = []
    for child in nx.children(nx.display_part()):
        match = re.match(_LayoutRegex, child.DisplayName)
        if match and match.group("__prefix") == prefix:
            ops.append(int(match.group("__op")))
    ops.reverse()
    return ops


def _ask_prog_station_10() -> List[int]:
    """Static.ask_prog_station_10"""
    return _ask_station_10("P")


def _ask_tran_station_10() -> List[int]:
    """Static.ask_tran_station_10"""
    return _ask_station_10("T")


def _move_station(op: int, op_next: int, cust_num: str, selected_prefix: str) -> None:
    """Static.CloneStripMoveStation - renumbers one layout part, its occurrences and their constraints."""
    old_op = _op_10_to_010(op)
    next_op = _op_10_to_010(op_next)
    leaf = "{}-{}{}-Layout".format(cust_num, selected_prefix, old_op)
    old_part = nx.find_or_open(leaf)
    old_file_path = old_part.FullPath
    new_file_path = old_file_path.replace(leaf, "{}-{}{}-Layout".format(cust_num, selected_prefix, next_op))
    nx.set_work_part(old_part)
    old_part.SaveAs(new_file_path)
    nx.set_work_part(nx.display_part())
    _file_delete(old_file_path)
    part_occs, length = nx.ufsession_.Assem.AskOccsOfPart(nx.display_part().Tag, old_part.Tag)

    for i in range(length):
        comp = cast(NXOpen.Assemblies.Component, nx.tagged_object(part_occs[i]))
        comp.SetName(comp.Name.replace(old_op, next_op))

        for const in comp.GetConstraints():
            const.Expression.RightHandSide = const.Expression.RightHandSide.replace(old_op, next_op)

            try:
                nx.display_part().Expressions.Rename(const.Expression, const.Expression.Name.replace(old_op, next_op))
            except Exception as ex:
                nx.print_exception(ex)

            const.SetName(const.Name.replace(old_op, next_op))


def _delete_prog_presses_from_display(folder: _GFolder) -> None:
    """Static.delete_prog_presses_from_display (no caller in the C#)."""
    for child in nx.children(nx.display_part()):
        if child.DisplayName.startswith("{}-P".format(folder.CustomerNumber)) and child.DisplayName.endswith("-Press"):
            _delete_self_and_constraints(child)


def _clone_non_offline_die(folder: _GFolder, transfer_layouts: int, tran_presses: int, prog_layouts: int,
                           prog_presses: int, op: str) -> None:
    """Static.clone_non_offline_die"""
    strip_tran_path = folder.file_strip(op)
    _execute_clone_strip(folder, strip_tran_path)
    nx.set_display_part(nx.find_or_open(strip_tran_path))

    # add the prog layout-stations
    for i in range(10, (prog_layouts + 1) * 10, 10):
        try:
            _prog_work_lifted(folder, _op_10_to_010(i), "P")
        except Exception as ex:
            nx.print_exception(ex)

    # adds a P{last}-TRANSFER component if this is a transfer die and has prog stations
    if transfer_layouts > 0 and prog_layouts > 0:
        try:
            op_str = _op_10_to_010(prog_layouts * 10)
            layout_path = folder.file_layout_p(op_str)
            if not os.path.isfile(layout_path):
                _file_copy(_XxxxxxOpXxxLayout, layout_path)
            _prog_work(op_str, layout_path, "P")
            _prog_lifted(op_str, layout_path, "P")
            _prog_p_transfer(_op_10_to_010(prog_layouts * 10), layout_path, "P")
        except Exception as ex:
            nx.print_exception(ex)

    # add the transfer layout-stations
    for i in range(10, (transfer_layouts + 1) * 10, 10):
        try:
            _tran_work_lifted_transfer(folder, _op_10_to_010(i), "T")
        except Exception as ex:
            nx.print_exception(ex)

    # add the prog press-stations
    for _i in range(10, (prog_presses + 1) * 10, 10):
        try:
            _add_press("P")
        except Exception as ex:
            nx.print_exception(ex)

    # add the transfer press-stations
    for _i in range(10, (tran_presses + 1) * 10, 10):
        try:
            _add_press("T")

            _save(nx.display_part())
        except Exception as ex:
            nx.print_exception(ex)


def _clone_offline_die(folder: _GFolder, prog_layouts: int, transfer_layouts: int, prog_presses: int,
                       tran_presses: int, op: str) -> None:
    """Static.clone_offline_die - no per-station try/except, as in the C#."""
    strip_tran_path = folder.FileStrip900
    strip_prog_path = folder.file_strip(op)
    _execute_clone_strip1(folder, op, strip_prog_path)
    _file_copy(strip_prog_path, strip_tran_path)
    if not os.path.isfile(strip_tran_path):
        _file_copy(_XxxxxStrip, strip_tran_path)

    nx.set_display_part(nx.find_or_open(strip_tran_path))

    # add the transfer layout-stations
    for i in range(10, (transfer_layouts + 1) * 10, 10):
        _tran_work_lifted_transfer(folder, _op_10_to_010(i), "T")

    # add the transfer press-stations
    for _i in range(10, (tran_presses + 1) * 10, 10):
        _add_press("T")

    try:
        nx.find_or_open(folder.PathStripFlange)

        obj = _find_component(
            cast(NXOpen.Assemblies.Component, nx.display_part().ComponentAssembly.RootComponent),
            "COMPONENT {}-Strip Flange Carrier_Tracking Tab 1".format(folder.CustomerNumber))

        _delete_objects(obj)
    except Exception as ex:
        nx.print_exception(ex, "Failed to delete strip flange")

    _save(nx.display_part())

    if not os.path.isfile(strip_prog_path):
        _file_copy(_XxxxxStrip, strip_prog_path)
    nx.set_display_part(nx.find_or_open(strip_prog_path))

    # add the prog layout-stations
    for i in range(10, (prog_layouts + 1) * 10, 10):
        _prog_work_lifted(folder, _op_10_to_010(i), "P")

    # add the prog press-stations
    for _i in range(10, (prog_presses + 1) * 10, 10):
        _add_press("P")


def _tran_transfer(op_str: str, selected_part_path: str, prefix: str) -> None:
    """Static.tran_transfer"""
    _add_component_and_constrain(selected_part_path, op_str, 102, "{}{}-TRANSFER".format(prefix, op_str), prefix,
                                 "X", "Y", "ZTransfer")


def _tran_lifted(op_str: str, selected_part_path: str, prefix: str) -> None:
    """Static.tran_lifted"""
    _add_component_and_constrain(selected_part_path, op_str, 101, "{}{}-LIFTED".format(prefix, op_str), prefix,
                                 "X", "Y", "ZLifted")


def _tran_work(op_str: str, selected_part_path: str, prefix: str) -> None:
    """Static.tran_work"""
    _add_component_and_constrain(selected_part_path, op_str, 100, "{}{}-WORK".format(prefix, op_str), prefix,
                                 "X", "Y", "Z")


def _prog_lifted(op_str: str, selected_part_path: str, prefix: str) -> None:
    """Static.prog_lifted"""
    _add_component_and_constrain(selected_part_path, op_str, 101, "{}{}-LIFTED".format(prefix, op_str), prefix,
                                 "X", "Y", "ZLifted")


def _prog_work(op_str: str, selected_part_path: str, prefix: str) -> None:
    """Static.prog_work"""
    _add_component_and_constrain(selected_part_path, op_str, 100, "{}{}-WORK".format(prefix, op_str), prefix,
                                 "X", "Y", "Z")


def _prog_p_transfer(op_str: str, selected_part_path: str, prefix: str) -> None:
    """Static.prog_P_TRANSFER"""
    _add_component_and_constrain(selected_part_path, op_str, 102, "{}{}-TRANSFER".format(prefix, op_str), prefix,
                                 "X", "Y", "ZTransfer")


def _tran_work_lifted_transfer(folder: _GFolder, op_str: str, prefix: str) -> None:
    """Static.tran_work_lifted_transfer"""
    layout_path = folder.file_layout_t(op_str)

    if not os.path.isfile(layout_path):
        _file_copy(_XxxxxxOpXxxLayout, layout_path)

    _tran_work(op_str, layout_path, prefix)
    _tran_lifted(op_str, layout_path, prefix)
    _tran_transfer(op_str, layout_path, prefix)


def _prog_work_lifted(folder: _GFolder, op_str: str, prefix: str) -> None:
    """Static.prog_work_lifted"""
    layout_path = folder.file_layout_p(op_str)

    if not os.path.isfile(layout_path):
        _file_copy(_XxxxxxOpXxxLayout, layout_path)

    _prog_work(op_str, layout_path, prefix)
    _prog_lifted(op_str, layout_path, prefix)


def _prog_transfer(folder: _GFolder, op_str: str, prefix: str) -> None:
    """Static.prog_transfer(GFolder, string, string) - recurses into itself through GFolder.Create(op_str), which
    throws first (see the module docstring)."""
    layout_path = folder.file_layout(prefix, op_str)

    if not os.path.isfile(layout_path):
        _file_copy(_XxxxxxOpXxxLayout, layout_path)

    _prog_transfer(_GFolder.create(op_str), layout_path, prefix)


# ---------------------------------------------------------------------------------------------------
# Clone
# ---------------------------------------------------------------------------------------------------

def _execute_clone_strip1(folder: _GFolder, op: str, strip_prog_path: str) -> None:
    """Static.ExecuteCloneStrip1. Enum member names (CLONE_OPERATION, USER_NAME) read from the strings in
    NXOpen_UF.pyd; PerformClone takes and returns the NamingFailures."""
    clone = nx.ufsession_.Clone
    clone.Terminate()
    clone.Initialise(NXOpen.UF.Clone.OperationClass.CLONE_OPERATION)
    clone.SetDefNaming(NXOpen.UF.Clone.NamingTechnique.USER_NAME)
    clone.SetDryrun(False)
    clone.AddPart(_XxxxxStrip)
    clone.SetNaming(_XxxxxStrip, NXOpen.UF.Clone.NamingTechnique.USER_NAME, strip_prog_path)

    if op != "900":
        clone.AddPart(_StripFlangeCarrierTracking)
        clone.SetNaming(_StripFlangeCarrierTracking, NXOpen.UF.Clone.NamingTechnique.USER_NAME,
                        folder.PathStripFlange)

    failures = clone.InitNamingFailures()
    clone.PerformClone(failures)
    clone.Terminate()


def _execute_clone_strip(folder: _GFolder, strip_tran_path: str) -> None:
    """Static.ExecuteCloneStrip"""
    clone = nx.ufsession_.Clone
    clone.Terminate()
    clone.Initialise(NXOpen.UF.Clone.OperationClass.CLONE_OPERATION)
    clone.SetDefNaming(NXOpen.UF.Clone.NamingTechnique.USER_NAME)
    clone.SetDryrun(False)
    clone.AddPart(_XxxxxStrip)
    clone.SetNaming(_XxxxxStrip, NXOpen.UF.Clone.NamingTechnique.USER_NAME, strip_tran_path)

    if not os.path.isfile(folder.PathStripFlange):
        clone.AddPart(_StripFlangeCarrierTracking)
        clone.SetNaming(_StripFlangeCarrierTracking, NXOpen.UF.Clone.NamingTechnique.USER_NAME,
                        folder.PathStripFlange)

    failures = clone.InitNamingFailures()
    clone.PerformClone(failures)
    clone.Terminate()


# ---------------------------------------------------------------------------------------------------
# CloneAssembly members CloneStrip calls
# ---------------------------------------------------------------------------------------------------

def _add_component_and_constrain(layout_path: str, op_str: str, layer: int, comp_name: str, prefix: str,
                                 exp_x: str, exp_y: str, exp_z: str) -> None:
    """CloneAssembly.add_component_and_constrain - prints and swallows any failure."""
    try:
        expression1 = _find_expression(nx.display_part(), prefix + op_str + exp_x)
        expression2 = _find_expression(nx.display_part(), prefix + op_str + exp_y)
        expression3 = _find_expression(nx.display_part(), prefix + op_str + exp_z)
        component = nx.add_component(
            nx.display_part(), layout_path, component_name=comp_name,
            origin=NXOpen.Point3d(expression1.Value, expression2.Value, expression3.Value),
            orientation=nx.identity_matrix(), layer=layer)
        datum_csys1 = _absolute_datum_csys(nx.prototype(component))
        datum_csys2 = _absolute_datum_csys(nx.display_part())
        proto = _datum_plane_xy(datum_csys1)
        occurrence = cast(NXOpen.DatumPlane, component.FindOccurrence(proto))
        datum_plane_xy = _datum_plane_xy(datum_csys2)
        # NewMethod24
        _constrain_z(comp_name, expression3, occurrence, datum_plane_xy)
        # NewMethod8
        constraint = _constrain_occ_proto_distance(
            nx.display_part(), _abs_occ_datum_plane(component, 1), _datum_plane_yz(datum_csys2), expression1.Name)
        nx.set_layer(constraint.GetDisplayedConstraint(), 256)
        constraint.SetName(comp_name + "-YZ")
        constraint.Expression.SetName("{}_{}_".format(comp_name.replace("-", "_"), expression1.Name))
        # NewMethod5
        constraint = _constrain_occ_proto_distance(
            nx.display_part(), _abs_occ_datum_plane(component, 2), _datum_plane_xz(datum_csys2), expression2.Name)
        constraint.SetName(comp_name + "-XZ")
        nx.set_layer(constraint.GetDisplayedConstraint(), 256)
        constraint.Expression.SetName("{}_{}_".format(comp_name.replace("-", "_"), expression2.Name))
        _replace_interpart_expressions(component, prefix)
    except Exception as ex:
        nx.print_exception(ex)


def _constrain_z(comp_name: str, expression_z: NXOpen.Expression, plane_occ: NXOpen.DatumPlane,
                 datum_plane_xy: NXOpen.DatumPlane) -> None:
    """CloneAssembly.NewMethod24 - the three SetName calls are kept; the last one wins."""
    constraint = _constrain_occ_proto_distance(nx.display_part(), plane_occ, datum_plane_xy, expression_z.Name)
    constraint.GetDisplayedConstraint().Layer = 256
    constraint.SetName(comp_name + "-XY")
    name = "{}_{}_".format(comp_name.replace("-", "_"), expression_z.Name)
    constraint.SetName(comp_name + "-XY")
    constraint.SetName(name)


def _replace_interpart_expressions(layout_comp: NXOpen.Assemblies.Component, prefix: str) -> None:
    """CloneAssembly.replace_interpart_expressions - links b/e/em/m/p (+TP or pp) from the display part into the
    layout's prototype."""
    source = ["b", "e", "em", "m", "p"]
    if prefix == "T":
        source.append("TP")
    if prefix == "P":
        source.append("pp")
    array = [_find_expression(nx.display_part(), s) for s in source]
    with nx.display_part_reset():
        nx.set_display_part(nx.prototype(layout_comp))
        builder = nx.display_part().Expressions.CreateInterpartExpressionsBuilder()
        try:
            builder.SetExpressions(array, source)
            builder.Commit()
        finally:
            builder.Destroy()
        nx.ufsession_.Modeling.Update()


def _add_press(prefix: str) -> None:
    """CloneAssembly.add_press(string) - adds the first missing {cus_num}-{prefix}{op}-Press, stepping op by 10
    past every press file that already exists."""
    match = re.match(r"^(?P<cus_num>\d{6})-.*$", nx.display_part().Leaf)
    if match is None:
        nx.print_("Could not find customer number")
        return

    str1 = match.group("cus_num")
    str2 = os.path.dirname(os.path.dirname(nx.display_part().FullPath)) + "\\Layout"
    op = 10
    while True:
        op_str = _op_10_to_010(op)
        str3 = "{}\\{}-{}{}-Press.prt".format(str2, str1, prefix, op_str)
        try:
            if os.path.isfile(str3):
                continue
            _file_copy(_PressSeed, str3)
            component = nx.add_component(nx.display_part(), str3, "Entire Part",
                                         "PRESS-{}{}".format(prefix, op_str), _Origin, nx.identity_matrix(), 245)
            nx.display_part().Layers.SetState(256, NXOpen.Layer.State.WorkLayer)
            proto_press_csys = _absolute_datum_csys(nx.prototype(component))
            strip_csys0 = _absolute_datum_csys(nx.display_part())
            _constrain_press(prefix, op_str, component, proto_press_csys, strip_csys0)
            nx.set_reference_set(component, "BODY")
            return
        finally:
            op += 10


def _constrain_press(prefix: str, op_str: str, press_comp: NXOpen.Assemblies.Component,
                     proto_press_csys: NXOpen.Features.Feature, strip_csys0: NXOpen.Features.Feature) -> None:
    """CloneAssembly.NewMethod43 (+ NewMethod25 and the [Obsolete] but implemented NewMethod27)."""
    # NewMethod25
    constraint = _constrain_occ_proto_distance(
        nx.display_part(), _abs_occ_datum_plane(press_comp, 0), _datum_plane_xy(strip_csys0), "0.0")
    constraint.SetName("PRESS-{}{}-XY".format(prefix, op_str))
    nx.set_layer(constraint.GetDisplayedConstraint(), 256)

    constraint = _constrain_occ_proto_distance(
        nx.display_part(), _abs_occ_datum_plane(press_comp, 1), _datum_plane_yz(strip_csys0), "0.0")
    constraint.SetName("PRESS-{}{}-YZ".format(prefix, op_str))
    nx.set_layer(constraint.GetDisplayedConstraint(), 256)

    # NewMethod27 - the display part's second DatumPlaneFeature, against the press's YZ plane, named -XZ.
    planes = [f for f in nx.display_part().Features.GetFeatures() if isinstance(f, NXOpen.Features.DatumPlaneFeature)]
    entity = planes[1].GetEntities()[0]
    constraint = _constrain_occ_proto_distance(
        nx.display_part(),
        cast(NXOpen.DatumPlane, press_comp.FindOccurrence(_datum_plane_yz(proto_press_csys))),
        cast(NXOpen.DatumPlane, entity), "0.0")
    constraint.SetName("PRESS-{}{}-XZ".format(prefix, op_str))
    nx.set_layer(constraint.GetDisplayedConstraint(), 256)


# ---------------------------------------------------------------------------------------------------
# Globals.cs extensions
# ---------------------------------------------------------------------------------------------------

def _constrain_occ_proto_distance(part: NXOpen.BasePart, occ_plane: NXOpen.DatumPlane,
                                  proto_plane: NXOpen.DatumPlane, distance_or_expression_name: str) -> Any:
    """BasePart.__ConstrainOccProtoDistance(occPlane, protoPlane, distanceOrExpressionName) - returns the
    ComponentConstraint."""
    if nx.work_part().Tag != nx.display_part().Tag:
        raise Exception("Display part must be Work part")

    if not occ_plane.IsOccurrence:
        raise Exception("Occurrence plane for constraint was actually a prototype.")

    if proto_plane.IsOccurrence:
        raise Exception("Prototype plane for constraint was actually an occurrence.")

    # __AssertIsDisplayPart
    if nx.session_.Parts.Display.Tag != part.Tag:
        raise ValueError("Part must be display part to __AssertIsDisplayPart")
    mark_id3 = nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, "Start")
    positioner = part.ComponentAssembly.Positioner
    positioner.ClearNetwork()
    positioner.BeginAssemblyConstraints()
    network = positioner.EstablishNetwork()
    constraint = cast(NXOpen.Positioning.ComponentConstraint, positioner.CreateConstraint(True))
    constraint.ConstraintType = NXOpen.Positioning.Constraint.Type.Distance
    # __CreateConstRefOcc / __CreateConstRefProto
    constraint.CreateConstraintReference(occ_plane.OwningComponent, occ_plane, False, False, False)
    constraint.CreateConstraintReference(proto_plane.OwningPart.ComponentAssembly, proto_plane, False, False, False)
    constraint.SetExpression(distance_or_expression_name)
    network.AddConstraint(constraint)
    network.Solve()
    positioner.ClearNetwork()
    nx.session_.UpdateManager.AddToDeleteList(network)
    nx.session_.UpdateManager.DoUpdate(mark_id3)
    positioner.EndAssemblyConstraints()
    nx.session_.DisplayManager.BlankObjects([constraint.GetDisplayedConstraint()])
    return constraint


def _absolute_datum_csys(part: NXOpen.BasePart) -> NXOpen.Features.Feature:
    """BasePart.__AbsoluteDatumCsys - the first DatumCsys feature (raises like First() when there is none)."""
    for feature in part.Features.GetFeatures():
        if isinstance(feature, NXOpen.Features.DatumCsys):
            return feature
    raise ValueError("Sequence contains no elements")


def _datum_plane(datum_csys: NXOpen.Features.Feature, index: int) -> NXOpen.DatumPlane:
    """DatumCsys.__DatumPlaneXY (0) / __DatumPlaneYZ (1) / __DatumPlaneXZ (2)."""
    _csys, _origin, _daxes, dplanes = nx.ufsession_.ModlFeatures.AskDatumCsysComponents(datum_csys.Tag)
    return cast(NXOpen.DatumPlane, nx.tagged_object(dplanes[index]))


def _datum_plane_xy(datum_csys: NXOpen.Features.Feature) -> NXOpen.DatumPlane:
    return _datum_plane(datum_csys, 0)


def _datum_plane_yz(datum_csys: NXOpen.Features.Feature) -> NXOpen.DatumPlane:
    return _datum_plane(datum_csys, 1)


def _datum_plane_xz(datum_csys: NXOpen.Features.Feature) -> NXOpen.DatumPlane:
    return _datum_plane(datum_csys, 2)


def _abs_occ_datum_plane(component: NXOpen.Assemblies.Component, index: int) -> NXOpen.DatumPlane:
    """Component.__AbsOccDatumPlaneXY (0) / YZ (1) / XZ (2)."""
    return cast(NXOpen.DatumPlane, component.FindOccurrence(
        _datum_plane(_absolute_datum_csys(nx.prototype(component)), index)))


def _find_expression(part: NXOpen.BasePart, expression_name: str) -> NXOpen.Expression:
    """BasePart.__FindExpression - Python cannot construct an NXException, so the rewrapped message is a
    RuntimeError chained to the original."""
    try:
        return part.Expressions.FindObject(expression_name)
    except NXOpen.NXException as ex:
        if ex.ErrorCode == 3520016:
            raise RuntimeError("Could not find expression '{}' in part {}".format(expression_name, part.Leaf)) from ex
        raise


def _find_component(component: NXOpen.Assemblies.Component, journal_identifier: str) -> NXOpen.Assemblies.Component:
    """Component.__FindComponent"""
    try:
        return cast(NXOpen.Assemblies.Component, component.FindObject(journal_identifier))
    except NXOpen.NXException as ex:
        if ex.ErrorCode != 3520016:
            raise
        raise Exception("Could not find component with journal identifier: '{}' in component '{}'".format(
            journal_identifier, component.DisplayName))


def _delete_objects(*objects: NXOpen.TaggedObject) -> None:
    """Session.__DeleteObjects - the delete list inside a DoUpdate. Local because tsg_nx defines delete_objects
    twice with different signatures."""
    mark = nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, "Do Update")
    try:
        nx.session_.UpdateManager.AddObjectsToDeleteList(list(objects))
    finally:
        nx.session_.UpdateManager.DoUpdate(mark)
        nx.session_.DeleteUndoMark(mark, "")


def _delete_self_and_constraints(component: NXOpen.Assemblies.Component) -> None:
    """Component.__DeleteSelfAndConstraints"""
    constraints = component.GetConstraints()

    if len(constraints) > 0:
        _delete_objects(*constraints)

    _delete_objects(component)


def _save(part: NXOpen.BasePart) -> None:
    """BasePart.__Save() - saves the child components too."""
    part.Save(NXOpen.BasePart.SaveComponents.TrueValue, NXOpen.BasePart.CloseAfterSave.FalseValue)


def _close(part: NXOpen.BasePart) -> None:
    """BasePart.__Close() - not the whole tree, don't close modified."""
    part.Close(NXOpen.BasePart.CloseWholeTree.FalseValue, NXOpen.BasePart.CloseModified.DontCloseModified, None)


def _op_10_to_010(op: int) -> str:
    """Extensions.__Op10To010"""
    if op == 0:
        return "000"
    if op < 10:
        raise Exception("op integer must be 0 or greater than 9")
    if op < 100:
        return "0{}".format(op)
    return "{}".format(op)


def _single(items: List[Any]) -> Any:
    """Enumerable.Single"""
    if len(items) != 1:
        raise ValueError("Sequence contains no matching element" if not items
                         else "Sequence contains more than one matching element")
    return items[0]


def _file_copy(source: str, destination: str) -> None:
    """File.Copy(source, destination) - refuses to overwrite, like the C#."""
    if os.path.exists(destination):
        raise FileExistsError("The file '{}' already exists.".format(destination))
    shutil.copy2(source, destination)


def _file_delete(path: str) -> None:
    """File.Delete - no error when the file is missing."""
    if os.path.isfile(path):
        os.remove(path)


class _GFolder(object):
    """GFolder (src\\Utilities\\GFolder.cs) - only the members CloneStrip reads."""

    def __init__(self, dir_job: str, customer_number: str) -> None:
        self.DirJob = dir_job
        self.CustomerNumber = customer_number

    @property
    def DirLayout(self) -> str:
        return "{}\\Layout".format(self.DirJob)

    @property
    def DirSimulation(self) -> str:
        return "{}\\Simulation".format(self.DirJob)

    @property
    def PathSimulation(self) -> str:
        return "{}\\{}-simulation.prt".format(self.DirSimulation, self.CustomerNumber)

    @property
    def FileStrip900(self) -> str:
        return self.file_strip("900")

    @property
    def PathStripFlange(self) -> str:
        return "{}\\{}-Strip Flange Carrier_Tracking Tab.prt".format(self.DirLayout, self.CustomerNumber)

    def file_strip(self, op: str) -> str:
        return "{}\\{}-{}-Strip.prt".format(self.DirLayout, self.CustomerNumber, op)

    def file_layout_t(self, op: str) -> str:
        return self.file_layout("T", op)

    def file_layout_p(self, op: str) -> str:
        return self.file_layout("P", op)

    def file_layout(self, prefix: str, op: str) -> str:
        return "{}\\{}-{}{}-Layout.prt".format(self.DirLayout, self.CustomerNumber, prefix, op)

    @staticmethod
    def create(job_folder: str) -> "_GFolder":
        """GFolder.Create(string)"""
        split = job_folder.split("\\")

        if len(split) < 3:
            # C#: IndexOutOfRangeException(jobFolder)
            raise IndexError(job_folder)

        directory = "{}\\{}\\{}".format(split[0], split[1], split[2])
        number = _GFolder._job_number(directory, split[2])
        if number:
            return _GFolder(directory, number)

        # Not the C#: a job copied below the usual depth (G:\CTS\junk\Mark B\006073\006073-010\...) has no job
        # number in the third piece, so the job folder is the first deeper folder whose name starts with one.
        for i in range(3, len(split) - 1):
            deeper = "\\".join(split[:i + 1])
            number = _GFolder._job_number(deeper, split[i])
            if number:
                return _GFolder(deeper, number)

        if "\\cts\\" not in directory.lower():
            return _GFolder(directory, "")

        raise ValueError("Could not make GFolder from '{}'".format(job_folder))

    @staticmethod
    def _job_number(directory: str, leaf: str) -> Optional[str]:
        """GFolder.Create's rules for the job folder `directory` named `leaf`: its customer number, or None."""
        if "\\cts\\" not in directory.lower():
            match0 = re.match(r"^(?P<num_0>\d{2,})", leaf)
            return match0.group("num_0") if match0 else None

        if _int_try_parse(leaf):
            return leaf

        match = re.match(r"^(?P<cts_number>\d{2,}) \([A-Z]+-[xX]+\)", leaf)
        if match:
            return match.group("cts_number")

        match = re.match(r"^(?P<cts_number>\d{2,}) \([A-Za-z]+-(?P<customer_number>\d+)\)", leaf)
        if match:
            return match.group("customer_number")

        match = re.match(r"^(?P<customer_number>\d{2,})", leaf)
        if match:
            return match.group("customer_number")

        return None


def _int_try_parse(text: str) -> bool:
    """int.TryParse(string, out _) with the default NumberStyles.Integer."""
    match = re.match(r"^\s*([+-]?\d+)\s*$", text)
    if match is None:
        return False
    try:
        value = int(match.group(1))
    except ValueError:
        return False
    return -2147483648 <= value <= 2147483647


# ---------------------------------------------------------------------------------------------------
# The clone-strip UFunc: the form's Create / Edit work and its Block Styler dialog (2026-10-29)
# ---------------------------------------------------------------------------------------------------

ufunc_name = "clone-strip"

# NX will not create a dialog from inside another dialog's callback.
_ErrorCannotLaunchDialog = 3520048

_JobDirRegex = r"^([gcph]:)\\(cts|rts|hts|dts|ats|ets)\\(?P<top_dir>\d{4,6})"

_NoSim = "no sim detected"
_ManySims = "more than one sim file detected"


def create_station(job_dir: str, transfer: int, prog: int, prog_presses: int, tran_presses: int, start_005: bool,
                   offline_die: bool) -> None:
    """Static.CloneStripCreateStation: the job-path check, then CloneStrip.create, timed."""
    import time

    started = time.time()
    try:
        if re.match(_JobDirRegex, job_dir, re.IGNORECASE) is None:
            nx.print_("Could not determine Job Folder")
            return

        # GFolder.create_or_null
        try:
            folder = _GFolder.create(job_dir)
        except Exception as ex:
            nx.print_exception(ex, "Exception caught for GFolder '{}'".format(job_dir))
            return

        CloneStrip.create(folder.DirJob, folder.CustomerNumber, transfer, tran_presses, prog, prog_presses, start_005,
                          offline_die)
    except Exception as ex:
        nx.print_exception(ex)
    finally:
        nx.prompt("Complete")
        nx.print_("{:.1f} s".format(time.time() - started))
        nx.print_("Clone Strip complete")


def add_simulation(refset: str) -> None:
    """
    Static.CloneStripAddSimulation: for each layer-8 *simulation* child of the display part, adds the simulation
    to every unsuppressed *-WORK child's part (at the simulation's position, named *-SIMULATION, layer 8) and to the
    display part at the simulation's position plus the -WORK child's origin.
    """
    try:
        display = nx.display_part()
        for comp in nx.children(display):
            if comp.Layer != 8 or "simulation" not in comp.Name.lower():
                continue

            sim_comp = comp
            if not nx.is_loaded(sim_comp):
                nx.print_("Please load the simulation file")
                return

            sim_path = nx.prototype(sim_comp).FullPath
            sim_origin = nx.component_origin(sim_comp)
            sim_orientation = nx.component_orientation(sim_comp)

            for child in nx.children(display):
                if not child.Name.endswith("-WORK") or child.IsSuppressed:
                    continue
                try:
                    name = child.Name.replace("-WORK", "-SIMULATION")
                    nx.add_component(nx.prototype(child), sim_path, refset, name, sim_origin, sim_orientation, 8)
                    child_origin = nx.component_origin(child)
                    nx.add_component(display, sim_path, refset, name,
                                     NXOpen.Point3d(sim_origin.X + child_origin.X, sim_origin.Y + child_origin.Y,
                                                    sim_origin.Z + child_origin.Z),
                                     sim_orientation, 8)
                except Exception as ex:
                    nx.print_exception(ex, child.DisplayName)
    except Exception as ex:
        nx.print_exception(ex)


def delete_simulation() -> None:
    """Static.CloneStripDeleteSimulation: the *SIMULATION* grandchildren under the non-layer-8 children and the
    layer-8 *SIMULATION children, deleted in one update."""
    try:
        mark = nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, "")
        doomed: List[NXOpen.Assemblies.Component] = []
        for child in nx.children(nx.display_part()):
            if child.Layer != 8:
                doomed.extend(c for c in child.GetChildren() if "SIMULATION" in c.Name.upper())
            elif child.Name.upper().endswith("SIMULATION"):
                doomed.append(child)
        for comp in doomed:
            nx.session_.UpdateManager.AddObjectsToDeleteList([comp])
        nx.session_.UpdateManager.DoUpdate(mark)
    except Exception as ex:
        nx.print_exception(ex)


def simulation_reference_sets() -> List[str]:
    """
    The form's Reset() combo box: with exactly one *simulation* part loaded under the display part, Entire Part,
    Empty and its reference sets (reversed); otherwise the one "no sim" / "more than one sim" item.
    """
    display = nx.display_part()
    root = nx.root_component(display) if display is not None else None
    if root is None:
        return [_NoSim]

    sims: List[NXOpen.BasePart] = []
    for comp in nx.descendants(root, include_root=False):
        if not nx.is_loaded(comp):
            continue
        part = nx.prototype(comp)
        if "simulation" in part.Leaf.lower() and part not in sims:
            sims.append(part)

    if not sims:
        return [_NoSim]
    if len(sims) > 1:
        return [_ManySims]

    names = [r.Name for r in sims[0].GetAllReferenceSets()] + ["Empty", "Entire Part"]
    names.reverse()
    return names


def _default_job_path() -> str:
    """MainForm_Load: the display part's job folder, or "" with none."""
    display = nx.display_part()
    if display is None:
        return ""
    try:
        return _GFolder.create(display.FullPath).DirJob
    except Exception:
        return ""


class _CloneStripDialog(Dialog):
    """CloneStrip.dlx: Job Path, the Create group (OK) and the Edit group's buttons."""

    dlx_name = "CloneStrip.dlx"

    def __init__(self, title: str) -> None:
        self.title = title
        super().__init__()
        # Captured in ok(): the blocks are gone once Launch returns.
        self.job_path = ""
        self.transfer = 1
        self.prog = 1
        self.tran_presses = 1
        self.prog_presses = 1
        self.prog_005 = False
        self.offline_die = False

    def initialize(self) -> None:
        self.component_filter(self.block("station"))
        self.assembly_scope(self.block("station"))

    def shown(self) -> None:
        self.set_string_value(self.block("job_path"), _default_job_path())
        self._reset()

    def update(self, block: NXOpen.BlockStyler.UIBlock) -> None:
        if block in (self.block("transfer"), self.block("prog"), self.block("offline_die"), self.block("prog_005")):
            self._reset_presses()
        elif block == self.block("browse_job"):
            picked = nx.select_folder_or_none("Job Path", self.string_value(self.block("job_path")) or "G:\\")
            if picked:
                self.set_string_value(self.block("job_path"), picked)
        elif block == self.block("add_station"):
            self._on_station(CloneStrip.add_station)
        elif block == self.block("delete_station"):
            self._on_station(CloneStrip.delete_station)
        elif block == self.block("add_tran_press"):
            self._edit(lambda: _add_press("T"))
        elif block == self.block("add_prog_press"):
            self._edit(lambda: _add_press("P"))
        elif block == self.block("add_simulation"):
            refset = str(self.block("sim_refset").ValueAsString)
            if refset in (_NoSim, _ManySims):
                self.message(refset)
            else:
                self._edit(lambda: add_simulation(refset))
        elif block == self.block("delete_simulation"):
            self._edit(delete_simulation)

    def enable_ok(self) -> bool:
        return bool(self.string_value(self.block("job_path")).strip())

    def ok(self) -> bool:
        self.job_path = self.string_value(self.block("job_path")).strip()
        self.transfer = int(self.block("transfer").Value)
        self.prog = int(self.block("prog").Value)
        self.tran_presses = int(self.block("tran_presses").Value)
        self.prog_presses = int(self.block("prog_presses").Value)
        self.prog_005 = bool(self.block("prog_005").Value)
        self.offline_die = bool(self.block("offline_die").Value)
        return True

    def _on_station(self, action: Callable[[NXOpen.Assemblies.Component], None]) -> None:
        picked = components_of(self.selected(self.block("station")))
        if not picked:
            self.message("Select the station's layout component first.")
            return
        self._edit(lambda: action(picked[0]))
        self.block("station").SetSelectedObjects([])

    def _edit(self, action: Callable[[], None]) -> None:
        """An Edit button's work. It counts as done, so a Cancel afterwards does not mark the run cancelled."""
        try:
            action()
        except Exception as ex:
            nx.print_exception(ex)
        self.applied = True
        self._reset()

    def _reset(self) -> None:
        self._reset_presses()
        # Reset() kept adding to the combo box; here the list is rebuilt.
        refsets = simulation_reference_sets()
        self.block("sim_refset").SetEnumMembers(refsets)
        self.block("sim_refset").ValueAsString = refsets[0]
        self.block("add_simulation").Enable = refsets[0] not in (_NoSim, _ManySims)

    def _reset_presses(self) -> None:
        """Reset()'s press rules: transfer stations without Offline Die take no prog presses; no transfer stations
        take no transfer presses and no Offline Die."""
        transfer = int(self.block("transfer").Value)
        offline = bool(self.block("offline_die").Value)

        if transfer > 0 and not offline:
            self.block("prog_presses").Value = 0
            self.block("prog_presses").Enable = False
        else:
            self.block("prog_presses").Enable = True

        if transfer == 0:
            self.block("tran_presses").Value = 0
            self.block("tran_presses").Enable = False
            self.block("offline_die").Value = False
            self.block("offline_die").Enable = False
        else:
            self.block("tran_presses").Enable = True
            self.block("offline_die").Enable = True


def execute() -> None:
    title = title_with_version("Clone Strip")
    dialog: Optional[_CloneStripDialog] = None
    try:
        dialog = _CloneStripDialog(title)
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

    create_station(dialog.job_path, dialog.transfer, dialog.prog, dialog.prog_presses, dialog.tran_presses,
                   dialog.prog_005, dialog.offline_die)


def main() -> None:
    """The clone-strip UFunc - its menu button runs this file. An escaping exception is printed."""
    import usage_db

    with usage_db.run(ufunc_name):
        try:
            execute()
        except Exception as ex:
            nx.print_exception(ex)


if __name__ == "__main__":
    main()

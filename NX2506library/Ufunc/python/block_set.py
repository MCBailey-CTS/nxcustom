"""
Merlin block sets (2026-11-07): records, as UDOs, of the components Merlin UFuncs create, so a later tool can find a
whole set - or everything one run made - from any one of its components. Record only: the UDO has no callbacks and
nothing reacts to it. Two kinds share the class:

  - a run record (label "run"): every component one Merlin UFunc run created - the blocks, and the keys, fasteners,
    jacks, posts and other children added to them or to the station. nx.merlin_run (every Merlin entry's main())
    runs inside recording(name): it snapshots each loaded part's own components when the run starts, and at the end
    records the new ones, one UDO in each part they were added to (the station holds its blocks, each block part its
    fasteners and keys), all sharing one run key;
  - a grid set (label "lower split form", "upper draw-die-cavity", ...): the blocks one build split a block or
    region into, with their rows (x) / cols (y) - Split Form (so Dead Strike's lower), Draw Die's form steels (so
    Dead Strike's upper), Flange Up's lower and upper steels, Point Component. record() writes it, with the run key
    of the run it was made in.

Each UDO (class MerlinBlockSet) is in the part its members were added to:
  - Type1 links: the member components (the Component objects in that part, not assembly occurrences);
  - strings: builder (the UFunc name for a run record, "Draw Die" for a grid set), label, when, the TSG_Library
    version, the user, the run key, the usage run id (tblUFuncsExe; negative with the database down), then each
    member's part leaf (a member whose link is lost can still be named);
  - integers: the record's format (1), rows (x), cols (y) (0 for a run record) and the member count.

A run record leaves out parts in G:\\0Library, and parts the run did not change: loaded before it and unmodified,
or opened during it from a file older than the run (a part the run made and Saved As counts). Components the run
made and then deleted are simply gone.

The class has no callbacks, so it is registered from Python (the AutoSize class has to come from C#: its update
callback has to outlive the script). Registering is done before every create and read, so a part opened in a later
session is read the same way.

    with block_set.recording("draw-die"): ...   # nx.merlin_run does this
    block_set.record(components, "Draw Die", "lower draw-die-post", rows, cols)
    block_set.sets_of(component)       # every set holding component (its run record and any grid set)
    block_set.find(component)          # its grid set, else its run record, or None
    block_set.run_of(component)        # the run record UDOs of the run that made it, across every loaded part
    block_set.sets_in(part)            # every set recorded in part
"""

from __future__ import annotations

import contextlib
import datetime
import os
import time
import uuid
from typing import Dict, Iterator, List, Optional, Sequence, Set, cast

import NXOpen
import NXOpen.Assemblies
import NXOpen.UserDefinedObjects

import tsg_nx as nx

ClassName = "MerlinBlockSet"
FriendlyName = "Merlin Block Set"
# integers[0]: bumped when the strings / integers change meaning.
FormatVersion = 1
# The strings ahead of the member leaves: builder, label, created, version, user, run key, usage run id.
_HeaderStrings = 7
# A run record's label.
RunLabel = "run"
# A run record leaves out components in library parts.
_LibraryFolder = "g:\\0library"

_udo_class: Optional[NXOpen.UserDefinedObjects.UserDefinedClass] = None
# The run recording() is in: (run key, usage run id), or None outside one.
_current_run: Optional[tuple] = None


class BlockSet(object):
    """One recorded set, read off its UDO."""

    def __init__(self, udo: NXOpen.UserDefinedObjects.UserDefinedObject) -> None:
        self.udo = udo
        self.part = cast(NXOpen.Part, udo.OwningPart)
        strings = list(udo.GetStrings())
        integers = list(udo.GetIntegers())
        header = strings[:_HeaderStrings] + [""] * (_HeaderStrings - len(strings[:_HeaderStrings]))
        self.builder, self.label, self.created, self.version, self.user, self.run_key, self.usage_run_id = header
        self.member_leaves: List[str] = strings[_HeaderStrings:]
        self.format = integers[0] if len(integers) > 0 else 0
        self.rows = integers[1] if len(integers) > 1 else 0
        self.cols = integers[2] if len(integers) > 2 else 0
        self.count = integers[3] if len(integers) > 3 else len(self.member_leaves)

    @property
    def is_run(self) -> bool:
        return self.label == RunLabel

    @property
    def members(self) -> List[NXOpen.Assemblies.Component]:
        """The member components still alive (a deleted one drops out of the links)."""
        links = self.udo.GetLinks(NXOpen.UserDefinedObjects.UserDefinedObject.LinkType.Type1)
        return [cast(NXOpen.Assemblies.Component, link.AssociatedObject) for link in links
                if link is not None and isinstance(link.AssociatedObject, NXOpen.Assemblies.Component)]

    def __repr__(self) -> str:
        grid = " {} x {}".format(self.rows, self.cols) if self.rows or self.cols else ""
        return "{} {}{} in {}: {}".format(self.builder, self.label, grid, self.part.Leaf, ", ".join(self.member_leaves))


def udo_class() -> NXOpen.UserDefinedObjects.UserDefinedClass:
    """The MerlinBlockSet class, registered in this session first if it is not yet."""
    global _udo_class
    manager = nx.session_.UserDefinedClassManager
    try:
        found = manager.GetUserDefinedClassFromClassName(ClassName)
        if found is not None:
            _udo_class = found
            return found
    except NXOpen.NXException as ex:
        if ex.ErrorCode != nx.ErrorUdoClassNotRegistered:
            raise
    created = manager.CreateUserDefinedObjectClass(ClassName, FriendlyName)
    created.AllowQueryClassFromName = NXOpen.UserDefinedObjects.UserDefinedClass.AllowQueryClass.On
    _udo_class = created
    return created


def _in_owning_part(component: NXOpen.Assemblies.Component) -> NXOpen.Assemblies.Component:
    """
    The component as it is in the part it was added to (the station). A component in that part's own tree already
    is: its parent is the part's root, and its OwningPart the station (every child component reports IsOccurrence,
    and its Prototype is its own part, not a component). One reached deeper - a station's child seen from the -000 -
    is mapped into the station by nx.proto_child_comp, a level at a time.
    """
    while component.Parent is not None and component.Parent.Parent is not None:
        component = nx.proto_child_comp(component)
    return component


# ---------------------------------------------------------------------------------------------------
# Run records
# ---------------------------------------------------------------------------------------------------

def _own_components() -> Dict[int, NXOpen.Assemblies.Component]:
    """Every loaded part's own components (its root's children, suppressed ones too), by tag."""
    found: Dict[int, NXOpen.Assemblies.Component] = {}
    for part in nx.session_.Parts:
        try:
            root = part.ComponentAssembly.RootComponent
            if root is None:
                continue
            for child in root.GetChildren():
                found[child.Tag] = child
        except Exception:
            continue
    return found


@contextlib.contextmanager
def recording(ufunc_name: str, usage_run_id: object = "") -> Iterator[None]:
    """
    Records, as a run record, every component created inside the block (see the module docstring). A nested
    recording (Auto Design's programs, a UFunc that calls another's main) is left to the outer one. Never raises
    from the record itself.
    """
    global _current_run
    if _current_run is not None:
        yield
        return

    try:
        before: Set[int] = set(_own_components())
        parts_before: Set[int] = {part.Tag for part in nx.session_.Parts}
        # A second back, so a part saved in the run's first moment is not on the line.
        started = time.time() - 1.0
    except Exception as ex:
        nx.syslog("Block set: no run record for {} - the snapshot failed: {}".format(ufunc_name, ex))
        yield
        return

    _current_run = (str(uuid.uuid4()), str(usage_run_id))
    try:
        yield
    finally:
        run = _current_run
        _current_run = None
        _record_run(ufunc_name, before, parts_before, started, run)


def _made_by_run(part: NXOpen.BasePart, parts_before: Set[int], started: float) -> bool:
    """
    Whether part's own new components are the run's: not a library part, and modified in this run, or loaded during
    it and never saved before it (no file, or a file written since the run started - a detail the run Saved As). A
    part opened from disk during the run and left alone is not, so its children are not taken for new ones.
    """
    path = part.FullPath or ""
    if path.lower().startswith(_LibraryFolder):
        return False
    if part.IsModified:
        return True
    if part.Tag in parts_before:
        return False
    try:
        return not os.path.exists(path) or max(os.path.getmtime(path), os.path.getctime(path)) >= started
    except OSError:
        return False


def _record_run(ufunc_name: str, before: Set[int], parts_before: Set[int], started: float, run: tuple) -> None:
    try:
        new = [c for tag, c in _own_components().items() if tag not in before]
        members = []
        made: Dict[int, bool] = {}
        for component in new:
            part = component.OwningPart
            if part.Tag not in made:
                made[part.Tag] = _made_by_run(part, parts_before, started)
            if made[part.Tag]:
                members.append(component)
        if len(members) == 0:
            return
        _record(members, ufunc_name, RunLabel, 0, 0, run, minimum=1)
        nx.syslog("Block set: {} run recorded, {} component(s) in {} part(s)".format(
            ufunc_name, len(members), len({m.OwningPart.Tag for m in members})))
    except Exception as ex:
        nx.print_("Block set: could not record the {} run - {}".format(ufunc_name, ex))


# ---------------------------------------------------------------------------------------------------
# Grid sets and the shared writer
# ---------------------------------------------------------------------------------------------------

def record(components: Sequence[Optional[NXOpen.Assemblies.Component]], builder: str, label: str, rows: int = 0,
           cols: int = 0) -> List[NXOpen.UserDefinedObjects.UserDefinedObject]:
    """
    Records components (None entries - failed blocks - are skipped) as one grid set: a MerlinBlockSet UDO in each
    part they are in, with the run key of the recording() it is made in. A set of fewer than two is not recorded.
    Never raises: a failure is printed and the build carries on, since the set is only a record.
    """
    try:
        members = [_in_owning_part(c) for c in components if c is not None]
        return _record(members, builder, label, rows, cols, _current_run or ("", ""), minimum=2)
    except Exception as ex:
        nx.print_("Block set: could not record the {} {} set - {}".format(builder, label, ex))
        return []


def _record(members: Sequence[NXOpen.Assemblies.Component], builder: str, label: str, rows: int, cols: int,
            run: tuple, minimum: int) -> List[NXOpen.UserDefinedObjects.UserDefinedObject]:
    """One UDO per part members are in; the work part is put back after each. A part's failure is printed."""
    if len(members) < minimum:
        return []
    by_part: Dict[int, List[NXOpen.Assemblies.Component]] = {}
    for member in members:
        by_part.setdefault(member.OwningPart.Tag, []).append(member)

    klass = udo_class()
    header = [builder, label, datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), nx.assembly_file_version(),
              os.environ.get("USERNAME") or "", run[0], run[1]]
    udos = []
    starting_display = nx.display_part()
    starting_work = nx.work_part()
    try:
        for part_members in by_part.values():
            part = cast(NXOpen.Part, part_members[0].OwningPart)
            try:
                udos.append(_record_in(part, part_members, klass, header, rows, cols))
            except Exception as ex:
                nx.print_("Block set: could not record the {} {} set in {} - {}".format(builder, label, part.Leaf,
                                                                                       ex))
    finally:
        if nx.display_part().Tag != starting_display.Tag:
            nx.set_display_part(starting_display)
        if nx.work_part().Tag != starting_work.Tag:
            nx.set_work_part(starting_work)
    return udos


def _record_in(part: NXOpen.Part, part_members: Sequence[NXOpen.Assemblies.Component],
               klass: NXOpen.UserDefinedObjects.UserDefinedClass, header: List[str], rows: int,
               cols: int) -> NXOpen.UserDefinedObjects.UserDefinedObject:
    """One part's UDO. NX links a UDO only to objects in the work part, so part is made the work part - displayed
    first when it is not under the display part, which SetWork refuses ("not a descendant of the root part"); the
    caller puts both back. A UDO whose links fail is deleted again."""
    if nx.work_part().Tag != part.Tag:
        try:
            nx.set_work_part(part)
        except NXOpen.NXException:
            nx.set_display_part(part)
            nx.set_work_part(part)
    udo = part.UserDefinedObjectManager.CreateUserDefinedObject(klass)
    try:
        links = []
        for member in part_members:
            link = NXOpen.UserDefinedObjects.UserDefinedObject.LinkDefinition()
            link.AssociatedObject = member
            link.Status = NXOpen.UserDefinedObjects.UserDefinedObject.LinkStatus.UpToDate
            links.append(link)
        udo.SetLinks(NXOpen.UserDefinedObjects.UserDefinedObject.LinkType.Type1, links)
        leaves = [member.Prototype.Leaf if isinstance(member.Prototype, NXOpen.BasePart) else member.DisplayName
                  for member in part_members]
        udo.SetStrings(header + leaves)
        udo.SetIntegers([FormatVersion, max(0, rows), max(0, cols), len(part_members)])
    except Exception:
        _delete(udo)
        raise
    nx.syslog("Block set: {} {} ({} x {}) recorded in {}: {}".format(
        header[0], header[1], rows, cols, part.Leaf, ", ".join(leaves)))
    return udo


def _delete(obj: NXOpen.NXObject) -> None:
    mark = nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Invisible, "Block set")
    nx.session_.UpdateManager.AddObjectsToDeleteList([obj])
    nx.session_.UpdateManager.DoUpdate(mark)
    nx.session_.DeleteUndoMark(mark, "Block set")


# ---------------------------------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------------------------------

def sets_in(part: NXOpen.BasePart) -> List[BlockSet]:
    """Every set (run records and grid sets) recorded in part."""
    return [BlockSet(udo) for udo in part.UserDefinedObjectManager.GetUdosOfClass(udo_class())]


def sets_of(component: NXOpen.Assemblies.Component) -> List[BlockSet]:
    """Every set component (an occurrence or not) is a member of: its run record and any grid set."""
    member = _in_owning_part(component)
    return [s for s in sets_in(member.OwningPart) if any(m.Tag == member.Tag for m in s.members)]


def find(component: NXOpen.Assemblies.Component) -> Optional[BlockSet]:
    """The grid set component is a member of, else its run record, or None."""
    sets = sets_of(component)
    grids = [s for s in sets if not s.is_run]
    chosen = grids or sets
    return chosen[0] if chosen else None


def run_of(component: NXOpen.Assemblies.Component) -> List[BlockSet]:
    """The run records of the run that made component, in every loaded part (the station's, each block part's)."""
    runs = [s for s in sets_of(component) if s.is_run and s.run_key]
    if len(runs) == 0:
        return []
    key = runs[0].run_key
    found = []
    for part in nx.session_.Parts:
        try:
            found += [s for s in sets_in(part) if s.is_run and s.run_key == key]
        except Exception:
            continue
    return found

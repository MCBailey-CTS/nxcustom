"""
Python port of the SimRefSets form's reference-set builder (src\\Static\\SimRefSets.cs, moved out of
src\\UFuncs\\SimRefSets.cs): Static.MakeRefSets, SimRefSetsGetNewReferenceSetName and
SimRefSetsPrintReferenceSetResult.
The C# wrapper was deleted 2026-10-22 (in git at f32694f): the UFunc's menu button runs this file's main().

Wired (2026-10-20): the sim-ref-sets UFunc runs SimRefSets.execute, which replaces the WinForms form with a modal
dialog (SimRefSets.dlx, built by tools\make-dlx.py) and then runs add_reference_sets - the port of
SimRefSetsAddReferenceSets (Add All / Add To, the optional delete of the non-MASTER reference sets) - and
make_ref_sets. Never run in NX yet.

Differences from the C#:
  - The "already exists - override it?" WinForms MessageBox (YesNo) is the NX Question box. Yes deletes and
    rebuilds, No prints and skips; any other return value raises, like the C# default branch's
    ArgumentOutOfRangeException (caught and printed per component).
"""

from __future__ import annotations

import os
import sys
from typing import List, Optional, Sequence, cast

# Session.Execute does not put the script's folder on sys.path, so the shared module would not import.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)
# From the source tree (src\UFuncs) the shared modules are in src\python; deployed, they are beside this file.
_shared_python = os.path.join(os.path.dirname(_here), "python")
if os.path.isdir(_shared_python) and _shared_python not in sys.path:
    sys.path.insert(1, _shared_python)

import NXOpen  # noqa: E402
import NXOpen.BlockStyler  # noqa: E402
import NXOpen.Assemblies  # noqa: E402

import tsg_nx as nx  # noqa: E402
from tsg_dialog import Dialog, components_of  # noqa: E402

# NXMessageBox.Show return values on a Question dialog. Yes = 1 matches CleanJobDirectory.py; No = 2 is
# assumed (not yet confirmed in NX).
_MessageBoxYes = 1
_MessageBoxNo = 2


def _delete_objects(objects: Sequence[NXOpen.TaggedObject]) -> None:
    """Session.__DeleteObjects - adds the objects to the delete list inside a DoUpdate.

    Private copy: tsg_nx.delete_objects is defined twice with different signatures."""
    with nx.do_update():
        nx.session_.UpdateManager.AddObjectsToDeleteList(list(objects))


def _get_new_reference_set_name(nx_comp: NXOpen.Assemblies.Component) -> Optional[str]:
    """Static.SimRefSetsGetNewReferenceSetName"""
    if "MASTER" in nx_comp.Name.upper():
        return nx_comp.Name

    first_hyphen = nx_comp.Name.find('-')

    if first_hyphen >= 0:
        return nx_comp.Name[first_hyphen + 1:]

    nx.print_(
        "Could not find a hyphen in the \"Component.Name\" of {0}. Reference Set {0} will not be made.".format(
            nx_comp.Name))
    return None


def _print_reference_set_result(new_ref_set_name: str) -> None:
    """Static.SimRefSetsPrintReferenceSetResult - prints whether or not a reference set with the given name was
    successfully created."""
    if any(s.Name == new_ref_set_name for s in nx.work_part().GetAllReferenceSets()):
        nx.print_("Reference Set {} was successfully created.".format(new_ref_set_name))
    else:
        nx.print_("Reference Set {} was not able to be created.".format(new_ref_set_name))


class SimRefSets(object):

    @staticmethod
    def execute() -> None:
        """sim-ref-sets: the dialog, then the reference sets."""
        _run()

    @staticmethod
    def make_ref_sets(nx_components: Sequence[NXOpen.Assemblies.Component]) -> None:
        """Static.MakeRefSets - one display-part reference set per component, named after the component name
        minus its first hyphen-delimited token (a MASTER component keeps its whole name)."""
        nx_components = list(nx_components or [])

        if len(nx_components) == 0:
            raise Exception("No ref sets made for 0 components")

        # Not null-checked, like the C# (which would throw a NullReferenceException on a non-assembly).
        root = cast(NXOpen.Assemblies.Component, nx.display_part().ComponentAssembly.RootComponent)
        valid_children_display_names = [c.Name for c in root.GetChildren() if not c.IsSuppressed]

        for nx_comp in nx_components:
            try:
                # Checks to make sure that there aren't two components with the same "Component Name".
                nx_comp_name = nx_comp.Name
                components_with_same_name = [s for s in valid_children_display_names if nx_comp_name == s]

                if len(components_with_same_name) == 0:
                    # This should never be reached.
                    raise Exception("Thrown from switch statement.")
                if len(components_with_same_name) > 1:
                    # This occurs when they select a component who has the same name as a different component
                    # under the Simulation Part. (C# InvalidDataException.)
                    raise ValueError("You have more than one component named " + nx_comp_name +
                                     ". Reference set will not be made.")

                # Gets the name for the to be created reference set.
                new_ref_set_name = _get_new_reference_set_name(nx_comp)

                # If None then the "Component.Name" of nx_comp was weird and the reference set name could not
                # be determined.
                if new_ref_set_name is None:
                    continue

                # SingleOrDefault: throws when more than one reference set has the name.
                already_named = [s for s in nx.display_part().GetAllReferenceSets() if s.Name == new_ref_set_name]
                if len(already_named) > 1:
                    raise Exception("Sequence contains more than one matching element")
                already_named_ref_set = already_named[0] if already_named else None

                # The selected component's "Component.Name" is already the name of a reference set in the
                # Simulation file: ask whether to delete it and create a new one, or skip it.
                if already_named_ref_set is not None:
                    result = nx.message_box(
                        "Warning",
                        NXOpen.NXMessageBox.DialogType.Question,
                        "A reference set named {} already exists. Would you like to override it?".format(
                            new_ref_set_name))

                    if result == _MessageBoxYes:
                        _delete_objects([already_named_ref_set])
                        if nx.has_reference_set(nx.work_part(), new_ref_set_name):
                            nx.print_("Reference Set " + new_ref_set_name + " was unable to be deleted")
                        else:
                            nx.print_("Reference Set " + new_ref_set_name + " was successfully deleted.")
                    elif result == _MessageBoxNo:
                        nx.print_("Reference Set " + new_ref_set_name + " was not overridden.")
                        continue
                    else:
                        raise ValueError("Specified argument was out of the range of valid values.")

                reference_set = nx.find_reference_set_or_null(nx.display_part(), new_ref_set_name)

                if reference_set is None:
                    reference_set = nx.display_part().CreateReferenceSet()
                    reference_set.SetName(new_ref_set_name)

                reference_set.AddObjectsToReferenceSet([nx_comp])

                _print_reference_set_result(new_ref_set_name)
            except Exception as ex:
                nx.print_exception(ex)


# ---------------------------------------------------------------------------------------------------
# The sim-ref-sets UFunc: a modal dialog (SimRefSets.dlx) in place of the WinForms form
# ---------------------------------------------------------------------------------------------------

# _UFunc.ufunc_sim_ref_sets
ufunc_sim_ref_sets = "sim-ref-sets"


class _SimRefSetsDialog(Dialog):
    """
    The form's Add To / Add All buttons as a radio enum (the picker shows for Add To) and its Delete Refsets
    checkbox as a toggle. OK does what pressing the button did.
    """

    dlx_name = "SimRefSets.dlx"
    title = "Sim Ref Sets"

    def __init__(self) -> None:
        super().__init__()
        self.add_all = False
        self.delete_existing = False
        self.components: List[NXOpen.Assemblies.Component] = []

    def initialize(self) -> None:
        self.component_filter(self.block("components"))
        self._show_picker()

    def update(self, block: NXOpen.BlockStyler.UIBlock) -> None:
        if block == self.block("mode"):
            self._show_picker()

    def ok(self) -> bool:
        self.add_all = self.block("mode").ValueAsString == "Add All"
        self.delete_existing = bool(self.block("delete_refsets").Value)
        self.components = components_of(self.selected(self.block("components")))

        if not self.add_all and not self.components:
            self.message("Select the components, or choose Add All.")
            return False

        return True

    def _show_picker(self) -> None:
        self.block("components").Show = self.block("mode").ValueAsString != "Add All"


def add_reference_sets(ufunc_rev_name: str, add_all: bool,
                       picked: Sequence[NXOpen.Assemblies.Component], delete_existing: bool) -> None:
    """
    Static.SimRefSetsAddReferenceSets - the display part's non-Master children (Add All) or the picked components
    (Add To); with delete_existing, every non-MASTER reference set is deleted first; then make_ref_sets.
    """
    try:
        nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, ufunc_rev_name)
        display = nx.display_part()

        if add_all:
            root = nx.root_component(display)
            nx_components = [] if root is None else [c for c in root.GetChildren() if "Master" not in c.DisplayName]
        else:
            nx_components = list(picked)

        if len(nx_components) == 0:
            return

        if delete_existing:
            refsets = [s for s in display.GetAllReferenceSets() if "MASTER" not in s.Name.upper()]

            for refset in refsets:
                nx.print_(refset.Name)

            for refset in refsets:
                display.DeleteReferenceSet(refset)

        SimRefSets.make_ref_sets(nx_components)
    except Exception as ex:
        nx.print_exception(ex)


def _run() -> None:
    """SimRefSets.Button_Selected, behind the dialog."""
    if nx.display_part() is None:
        nx.print_("There is no displayed part loaded")
        return

    dialog = _SimRefSetsDialog()

    if not dialog.run():
        return

    add_reference_sets(nx.ufunc_rev_name(ufunc_sim_ref_sets), dialog.add_all, dialog.components,
                       dialog.delete_existing)



def main() -> None:
    """The sim-ref-sets UFunc - its menu button runs this file. An escaping exception is printed."""
    import usage_db

    with usage_db.run("sim-ref-sets"):
        try:
            _run()
        except Exception as ex:
            nx.print_exception(ex)


if __name__ == "__main__":
    main()

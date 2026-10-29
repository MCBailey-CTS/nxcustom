"""
The tap-and-ream UFunc as a Block UI Styler dialog (TapAndReam.dlx, tools\\make-dlx.py): a port of the C# TapAndReam
form (src\\UFuncs\\TapAndReam.cs) and its Static methods (src\\Static\\TapAndReam.cs). The menu button runs this
file's main().

The dialog replaces the form's seven buttons and the component pick each one started with:
  - Component - the single component whose part is worked on (Ui.Selection.SelectOneComponent in the C#); its
                prototype is made the work part for the action, as the handlers did.
  - Action    - Move Features to End / Suppress / Delete (the form's three groups).
  - Holes     - Taps / Reams / Taps and Reams (hidden for Move Features to End, which takes every HOLECHART boolean
                whatever its color, as the C# did).
OK runs the action and closes; Apply runs it and keeps the dialog open (the form stayed open between buttons);
Cancel closes. Each run sets the visible undo mark its button set ("ReOrder Feature", "Suppress Taps",
"Suppress Reams", "Delete Taps", "Delete Reams" - and "Suppress Taps" / "Delete Taps" for the both-colors buttons,
as the C# comments say they always were) and prints any exception, as the handlers' catch did.

Button (Action + Holes) -> C# chain:
- move_to_end         <- Move to End:                 TapAndReamNewMethod26/25/24 + TapAndReamNewMethod
- suppress_taps       <- Suppress + Taps:             TapAndReamNewMethod19/18/17/16 + TapAndReamNewMethod1
- suppress_reams      <- Suppress + Reams:            TapAndReamNewMethod10/9/8/7 + TapAndReamNewMethod2
- suppress_taps_reams <- Suppress + Taps and Reams:   TapAndReamNewMethod15/14/13/12/11 + TapAndReamNewMethod3
- delete_taps         <- Delete + Taps:               TapAndReamNewMethod30/29/28/27 + TapAndReamNewMethod4
- delete_reams        <- Delete + Reams:              TapAndReamNewMethod23/22/21/20 + TapAndReamNewMethod5
- delete_taps_reams   <- Delete + Taps and Reams:     TapAndReamNewMethod35/34/33/32/31 + TapAndReamNewMethod6

The C# has one copy of the scan per button; they differ only in the HOLECHART face color they accept (181 taps,
42 reams, either for both), so here they are one scan (_collect_hole_groups) with the colors as a parameter.
Likewise the three suppress and three delete finishers are identical and are one function each. The move scan
(TapAndReamNewMethod24) is different - no color, no face-feature check, no de-duplication, and a break after the
first match per body - so it has its own.

The TapAndReam class's static methods (one per button, taking the picked component) are kept for
PythonLibrary.Execute("TapAndReam.py", "TapAndReam", "suppress_taps", selectedComp) callers and keep the C#
quirks. The dialog goes through _run_action instead, which differs from the form in:
  - The work part goes back to what it was before the action (in a finally). The C# "restore" went to a static
    captured on its first use - after the handler had already made the picked prototype the work part - so the
    first run restored nothing and later runs went back to the first run's prototype. _original_work_part copies
    that for the static methods.
  - Move Features to End with no HOLECHART boolean says so in a message box; the C# indexed an empty list and
    printed an ArgumentOutOfRangeException (the static method still raises IndexError and prints it).
  - Each action writes what it found to the syslog (nx.syslog).
The form's Load/FormClosed (version title, remembered location) and Cancel handlers were WinForms only; the dialog is
titled with the version by tsg_dialog.title_with_version. Delete had no confirm in the C# and has none here (the
undo mark is the way back).

Quirks kept on both paths:
- A META child of a linked body that is not a BooleanFeature throws, as the C# cast does (TypeError here).

Bindings read off the pyd docstrings but not seen in NX:
- UF_MODL_ask_face_feats (Modl.AskFaceFeats) and UF_MODL_reorder_feature (Modl.ReorderFeature) take/return a
  UF list (NXOpen.UF.Uf.List) in Python, where .NET hides it behind Tag[]. The list is walked with
  Modl.AskListCount/AskListItem (index assumed 0-based, as in UF_MODL_ask_list_item) and built with
  Modl.CreateList/PutListItem. The Python binding has no Modl.DeleteList, so the lists are not freed here.
- Obj.AskTypeAndSubtype returns (type, subtype).
- Apply is tsg_dialog.Dialog.apply(), which defaults to ok() - the same action, dialog left open.

**Never run in NX** (2026-10-23).
"""

from __future__ import annotations

import os
import sys
from typing import Callable, Iterable, List, NamedTuple, Optional, Sequence, Tuple

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

import tsg_nx as nx  # noqa: E402
from tsg_dialog import Dialog, components_of, title_with_version  # noqa: E402

ufunc_name = "tap-and-ream"

# NX will not create a Block Styler dialog from inside a callback (BillOfMaterial.execute handles it the same way).
_ErrorCannotLaunchDialog = 3520048

# HOLECHART face colors: taps and reams.
_TapColor = 181
_ReamColor = 42

# UF_MODL_reorder_feature method: 1 = before, 2 = after.
_ReOrderAfter = 2

# The C# static originalWorkPart - see the module docstring.
_original_work_part: Optional[NXOpen.Part] = None


class _FeatureGroup(NamedTuple):
    """Static.TapAndReamFeatureGroup"""
    linked_body: NXOpen.Features.Feature
    boolean_feature: NXOpen.Features.BooleanFeature
    cylindrical_face: Optional[NXOpen.Face]


# ---------------------------------------------------------------------------------------------------
# Scans
# ---------------------------------------------------------------------------------------------------

def _as_boolean(feature: NXOpen.Features.Feature) -> NXOpen.Features.BooleanFeature:
    """The C# (NXOpen.Features.BooleanFeature)bFeature cast - throws when the META feature is not a boolean."""
    if not isinstance(feature, NXOpen.Features.BooleanFeature):
        raise TypeError("Unable to cast {} to NXOpen.Features.BooleanFeature".format(type(feature).__name__))
    return feature


def _linked_body_booleans() -> Iterable[Tuple[NXOpen.Features.Feature, NXOpen.Features.BooleanFeature]]:
    """
    The outer two loops every scan shares (TapAndReamNewMethod26/19/10/15/30/23/35 and the 25/18/9/14/29/22/34
    they call): each unsuppressed LINKED_BODY in the work part, paired with each of its unsuppressed META children.
    """
    for feature in nx.work_part().Features:
        if feature.FeatureType != "LINKED_BODY":
            continue

        if feature.Suppressed:
            continue

        feat_children = feature.GetChildren()

        for b_feature in feat_children:
            if b_feature.Suppressed:
                continue

            if b_feature.FeatureType != "META":
                continue

            yield feature, _as_boolean(b_feature)


def _holechart_faces(b_body: NXOpen.Body) -> Iterable[NXOpen.Face]:
    """The face filter every scan shares: solid faces, cylindrical, named HOLECHART."""
    for b_face in b_body.GetFaces():
        face_type, sub_type = nx.ufsession_.Obj.AskTypeAndSubtype(b_face.Tag)

        if face_type != NXOpen.UF.UFConstants.UF_solid_type \
                or sub_type != NXOpen.UF.UFConstants.UF_solid_face_subtype:
            continue

        c_face = b_face

        if c_face.SolidFaceType != NXOpen.Face.FaceType.Cylindrical:
            continue

        if c_face.Name != "HOLECHART":
            continue

        yield c_face


def _face_feature_tags(face: NXOpen.Face) -> List[NXOpen.Tag]:
    """ufsession_.Modl.AskFaceFeats - the Python binding hands back a UF list instead of a Tag[]."""
    uf_list = nx.ufsession_.Modeling.AskFaceFeats(face.Tag)
    count = nx.ufsession_.ModlGeneral.AskListCount(uf_list)
    return [nx.ufsession_.ModlGeneral.AskListItem(uf_list, index) for index in range(count)]


def _add_hole_group(groups: List[_FeatureGroup], feature: NXOpen.Features.Feature,
                    get_tool: NXOpen.Features.BooleanFeature, c_face: NXOpen.Face,
                    features: Sequence[NXOpen.Tag]) -> None:
    """TapAndReamNewMethod16/7/12/11/27/20/32/31 - one copy each in the C#, all the same."""
    for feat_tag in features:
        if feat_tag != feature.Tag:
            continue

        suppress_feat = _FeatureGroup(feature, get_tool, c_face)

        if len(groups) == 0:
            groups.append(suppress_feat)
            break

        # List.Find returns a default struct (null face) on a miss; Face references compared by tag here.
        if any(f.cylindrical_face is not None and f.cylindrical_face.Tag == c_face.Tag for f in groups):
            continue

        groups.append(suppress_feat)
        break


def _collect_hole_groups(colors: Sequence[int]) -> List[_FeatureGroup]:
    """
    The suppress/delete scans: TapAndReamNewMethod19/30 (taps, 181), 10/23 (reams, 42) and 15/35 (both). A
    HOLECHART face of an accepted color is grouped with its linked body when that linked body is one of the face's
    features, once per face.
    """
    groups: List[_FeatureGroup] = []

    for feature, get_tool in _linked_body_booleans():
        for b_body in get_tool.GetBodies():
            for c_face in _holechart_faces(b_body):
                if c_face.Color not in colors:
                    continue

                features = _face_feature_tags(c_face)
                _add_hole_group(groups, feature, get_tool, c_face, features)

    return groups


def _collect_move_groups() -> List[_FeatureGroup]:
    """
    TapAndReamNewMethod26/25/24: every linked body / boolean pair whose boolean has a HOLECHART cylinder, once per
    body of the boolean (the C# break leaves the face loop only).
    """
    move_features: List[_FeatureGroup] = []

    for feature, get_tool in _linked_body_booleans():
        for b_body in get_tool.GetBodies():
            for _c_face in _holechart_faces(b_body):
                move_features.append(_FeatureGroup(feature, get_tool, None))
                break

    return move_features


# ---------------------------------------------------------------------------------------------------
# Finishers
# ---------------------------------------------------------------------------------------------------

def _restore_original_work_part() -> None:
    """__work_part_ = originalWorkPart, with the C# static's capture-on-first-use (see the module docstring)."""
    global _original_work_part
    if _original_work_part is None:
        _original_work_part = nx.work_part()
    nx.set_work_part(_original_work_part)


def _linked_bodies_and_children(groups: Sequence[_FeatureGroup]) -> List[NXOpen.Features.Feature]:
    all_feats: List[NXOpen.Features.Feature] = []

    for f_group in groups:
        all_feats.append(f_group.linked_body)
        all_feats.extend(f_group.linked_body.GetChildren())

    return all_feats


def _suppress(suppress_features: Sequence[_FeatureGroup]) -> None:
    """TapAndReamNewMethod1/2/3 (identical), less their work part restore - the caller does it."""
    supp_all_feats = _linked_bodies_and_children(suppress_features)

    if len(supp_all_feats) > 0:
        nx.work_part().Features.SuppressFeatures(supp_all_feats)


def _delete(delete_features: Sequence[_FeatureGroup]) -> None:
    """TapAndReamNewMethod4/5/6 (identical), less their work part restore - the caller does it."""
    del_all_feats = _linked_bodies_and_children(delete_features)

    if len(del_all_feats) > 0:
        mark_id_delete = nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Invisible, "")
        nx.session_.UpdateManager.AddObjectsToDeleteList(del_all_feats)
        nx.session_.UpdateManager.DoUpdate(mark_id_delete)


def _move_to_end(all_features: Sequence[NXOpen.Features.Feature], last_feature: NXOpen.Features.Feature,
                 last_feature_time_stamp: int, move_features: Sequence[_FeatureGroup]) -> None:
    """TapAndReamNewMethod, less its work part restore - the caller does it. Raises on an empty move_features."""
    last_feature_group_time_stamp = move_features[len(move_features) - 1].boolean_feature.Timestamp

    if last_feature_time_stamp > last_feature_group_time_stamp:
        move_feat_list = nx.ufsession_.ModlGeneral.CreateList()

        for group in move_features:
            nx.ufsession_.ModlGeneral.PutListItem(move_feat_list, group.linked_body.Tag)
            nx.ufsession_.ModlGeneral.PutListItem(move_feat_list, group.boolean_feature.Tag)

        nx.ufsession_.Modeling.ReorderFeature(all_features[len(all_features) - 1].Tag, move_feat_list, _ReOrderAfter)

        last_feature.MakeCurrentFeature()


def _set_work_part_to(selected_comp: NXOpen.Assemblies.Component) -> None:
    """__work_part_ = selectedComp.__Prototype();"""
    nx.set_work_part(nx.prototype(selected_comp))


class TapAndReam:
    """Entry points, one per form button after its pick. Each prints any exception, as the handler's catch does."""

    @staticmethod
    def move_to_end(selected_comp: NXOpen.Assemblies.Component) -> None:
        """ButtonMoveToEnd_Click after the pick."""
        try:
            _set_work_part_to(selected_comp)
            all_features = list(nx.work_part().Features)
            last_feature = all_features[len(all_features) - 1]
            last_feature_time_stamp = all_features[len(all_features) - 1].Timestamp
            move_features = _collect_move_groups()
            _move_to_end(all_features, last_feature, last_feature_time_stamp, move_features)
            _restore_original_work_part()
        except Exception as ex:
            nx.print_exception(ex)

    @staticmethod
    def suppress_taps(selected_comp: NXOpen.Assemblies.Component) -> None:
        """ButtonSuppressTaps_Click after the pick."""
        TapAndReam._run(selected_comp, (_TapColor,), _suppress)

    @staticmethod
    def suppress_reams(selected_comp: NXOpen.Assemblies.Component) -> None:
        """ButtonSuppressReams_Click after the pick."""
        TapAndReam._run(selected_comp, (_ReamColor,), _suppress)

    @staticmethod
    def suppress_taps_reams(selected_comp: NXOpen.Assemblies.Component) -> None:
        """ButtonSuppressTapReam_Click after the pick."""
        TapAndReam._run(selected_comp, (_TapColor, _ReamColor), _suppress)

    @staticmethod
    def delete_taps(selected_comp: NXOpen.Assemblies.Component) -> None:
        """ButtonDeleteTaps_Click after the pick."""
        TapAndReam._run(selected_comp, (_TapColor,), _delete)

    @staticmethod
    def delete_reams(selected_comp: NXOpen.Assemblies.Component) -> None:
        """ButtonDeleteReams_Click after the pick."""
        TapAndReam._run(selected_comp, (_ReamColor,), _delete)

    @staticmethod
    def delete_taps_reams(selected_comp: NXOpen.Assemblies.Component) -> None:
        """ButtonDeleteTapsReams_Click after the pick."""
        TapAndReam._run(selected_comp, (_TapColor, _ReamColor), _delete)

    @staticmethod
    def _run(selected_comp: NXOpen.Assemblies.Component, colors: Sequence[int],
             finish: Callable[[Sequence[_FeatureGroup]], None]) -> None:
        try:
            _set_work_part_to(selected_comp)
            groups = _collect_hole_groups(colors)
            finish(groups)
            _restore_original_work_part()
        except Exception as ex:
            nx.print_exception(ex)


# ---------------------------------------------------------------------------------------------------
# Dialog
# ---------------------------------------------------------------------------------------------------

# The Action and Holes radio items, as in tools\make-dlx.py's TapAndReam entry.
ActionMoveToEnd = "Move Features to End"
ActionSuppress = "Suppress"
ActionDelete = "Delete"
HolesTaps = "Taps"
HolesReams = "Reams"
HolesBoth = "Taps and Reams"

_HoleColors = {HolesTaps: (_TapColor,), HolesReams: (_ReamColor,), HolesBoth: (_TapColor, _ReamColor)}

# The visible undo mark each form button set before its pick. The both-colors buttons used the taps' name.
_UndoNames = {
    (ActionSuppress, HolesTaps): "Suppress Taps",
    (ActionSuppress, HolesReams): "Suppress Reams",
    (ActionSuppress, HolesBoth): "Suppress Taps",
    (ActionDelete, HolesTaps): "Delete Taps",
    (ActionDelete, HolesReams): "Delete Reams",
    (ActionDelete, HolesBoth): "Delete Taps",
}


def _run_action(component: NXOpen.Assemblies.Component, action: str, holes: str) -> None:
    """
    One form button after its pick, from the dialog: the button's undo mark, the component's prototype as the work
    part, the scan and the finisher. The work part is put back afterwards (see the module docstring). Any exception
    is printed, as the handler's catch did.
    """
    try:
        undo_name = "ReOrder Feature" if action == ActionMoveToEnd else _UndoNames[(action, holes)]
        nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, undo_name)
        original_work_part = nx.work_part()
        try:
            _set_work_part_to(component)
            part_name = nx.work_part().Leaf

            if action == ActionMoveToEnd:
                all_features = list(nx.work_part().Features)
                move_features = _collect_move_groups()
                if not move_features:
                    nx.message_box(title_with_version("Tap and Ream"), NXOpen.NXMessageBox.DialogType.Information,
                                   "{} has no linked body with a HOLECHART boolean to move.".format(part_name))
                    return
                nx.syslog("TapAndReam: {} - moving {} linked body/boolean pair(s) to the end".format(
                    part_name, len(move_features)))
                last_feature = all_features[len(all_features) - 1]
                _move_to_end(all_features, last_feature, last_feature.Timestamp, move_features)
                return

            groups = _collect_hole_groups(_HoleColors[holes])
            nx.syslog("TapAndReam: {} - {} {} HOLECHART face(s) found".format(part_name, action.lower(), len(groups)))
            if action == ActionSuppress:
                _suppress(groups)
            else:
                _delete(groups)
        finally:
            nx.set_work_part(original_work_part)
    except Exception as ex:
        nx.print_exception(ex)


class _TapAndReamDialog(Dialog):
    dlx_name = "TapAndReam.dlx"

    def __init__(self, title: str) -> None:
        self.title = title
        super().__init__()

    def initialize(self) -> None:
        self.component_filter(self.block("component"))
        self.assembly_scope(self.block("component"))

    def shown(self) -> None:
        self._refresh()

    def update(self, block: NXOpen.BlockStyler.UIBlock) -> None:
        if block == self.block("action"):
            self._refresh()

    def enable_ok(self) -> bool:
        return len(self._components()) > 0

    def ok(self) -> bool:
        components = self._components()
        if not components:
            self.message("Select a component.", error=True)
            return False
        _run_action(components[0], self._action(), str(self.block("holes").ValueAsString))
        return True

    def _components(self) -> List[NXOpen.Assemblies.Component]:
        return components_of(self.selected(self.block("component")))

    def _action(self) -> str:
        return str(self.block("action").ValueAsString)

    def _refresh(self) -> None:
        """Move Features to End takes every HOLECHART boolean, whatever its color - no Holes choice."""
        self.block("holes").Show = self._action() != ActionMoveToEnd


def execute() -> None:
    title = title_with_version("Tap and Ream")
    try:
        _TapAndReamDialog(title).run()
    except NXOpen.NXException as ex:
        if ex.ErrorCode != _ErrorCannotLaunchDialog:
            raise
        nx.print_exception(ex)
        nx.show_error("NX would not open the {} dialog (error {} - it will not create a dialog from inside a "
                      "callback).\n\nTry running it from File -> Execute -> NX Open rather than from a menu or "
                      "toolbar button.".format(title, _ErrorCannotLaunchDialog))


def main() -> None:
    """The tap-and-ream UFunc - its menu button runs this file. An escaping exception is printed."""
    import usage_db

    with usage_db.run(ufunc_name):
        try:
            execute()
        except Exception as ex:
            nx.print_exception(ex)


if __name__ == "__main__":
    main()

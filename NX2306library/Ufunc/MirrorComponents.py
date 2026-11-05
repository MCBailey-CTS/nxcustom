"""
The mirror-components UFunc as a Block UI Styler dialog (MirrorComponents.dlx, tools\\make-dlx.py): a port of the C#
MirrorComponents form (src\\UFuncs\\MirrorComponents.cs) and the reflection passes behind its OK button
(src\\Static\\MirrorComponents.cs, the MirrorComponentsNewMethod* family). The menu button runs this file's main().
The form, its Static file and the feature-by-feature engine in src\\UFuncs\\MirrorComponents\\ are in git at the commit
before this file was added; Surface.cs stays there, because Globals.cs uses Surface.Plane.

The dialog:
  - Bodies       - solid bodies anywhere in the assembly (the C# "Select Components" pick, mask 70). Each picked body's
                   owning component is mirrored, once per part. With no component body picked, the work part itself is
                   mirrored (NewMethod20).
  - Mirror plane - a datum plane (MirrorComponentsSelectMirrorDatumPlane).
  - Mirror Copies / Detail # - copy each picked component's part to {job}-{op}-{Detail #} in the work part's folder
                   (counting up past existing files), add it to the work part where the original is, put it in the
                   work part's BODY reference sets, and mirror the copy instead of the original (CopyComponentToMirror).
OK mirrors and closes, Apply mirrors and keeps the dialog open with the picks cleared (the form stayed open and
ResetForm cleared it). One visible undo mark, "Mirror Components", covers the run.

What the reflection does to a part (the NewMethod9/12/14/15/23/27 passes, which differed only in how they found the
plane - see below):
  - The plane is taken into the part's own coordinates by wave-linking the datum plane into it with the component as
    the work component, then deleting the link (MirrorComponentsWaveLinkDatumPlane / NewMethod26). The display part
    itself (the work part at the top of the assembly) uses the picked plane as it is.
  - The part is displayed, then:
    - When it has a DYNAMIC BLOCK: each DYNAMIC BLOCK and each block named FEATURE BLOCK is edited to the mirror image
      of itself - origin mirrored, X along the mirrored Y, Y along the mirrored X, and its Length and Width formulas
      swapped (NewMethod1/2/3/6/8: SetOriginAndLengths(origin, Width, Length, Height) in the reflected WCS).
    - Curves on layers 1-20 and the datum planes of ABSOLUTE_DATUM_PLANE features on layers 1-20 are moved by the
      reflection (NewMethod11/22 + TransformObjects).
    - Each child component (the fasteners) is repositioned at its mirrored origin, X along its mirrored Y and Y along
      its mirrored X (NewMethod10/33).
    The mirrored part keeps its feature history; its solid comes out mirrored because the block it is built on does.

Differences from the C#:
  - The C# form could not run. Its Select Components button was wired to the empty ButtonSelectComponents_Click (the
    working handler, buttonSelectComponents_Click_1, was never hooked up), its bottom Ok button ran that empty pick and
    then OK with nothing picked, and _Runner had no mirror-components case, so a Release build could not start it.
  - Mirror208_3001, the feature-by-feature pass the C# ran on each copy after the reflection, is not ported. It
    suppressed every feature of both the original and the copy, then called MirrorChamfer (which throws
    "EXPECTED ERROR" on purpose) and MirrorBlock (whose face and edge matching throw NotImplementedException), so its
    only lasting effect was the suppressed features.
  - NX's Python UF binding has no uf5947 (UFTrns.TransformObjects). Curves and datum planes are moved with
    UF_MODL_transform_entities (Modl.TransformEntities, the documented replacement - it moves the objects' parents
    too); if a batch fails, each object is tried alone and the ones NX refuses are listed. The block and component
    frames are worked out directly instead of reflecting a temporary csys into the WCS and rotating it Y 180 / Z 90.
  - The WCS is left alone (the C# left it on the last mirrored frame).
  - The wave-linked passes (a component away from the absolute origin) mirrored the linked datum plane once per
    absolute datum plane in place of the absolute datum planes (NewMethod29/30). Every part now gets the absolute
    datum planes, as the at-origin passes did. The at-origin passes used the picked plane's coordinates as they were,
    which is wrong for a component at the origin but rotated; every component now goes through the wave link.
  - A part picked through two components is mirrored once (twice would put it back).
  - Mirror Copies with only work-part bodies picked says so; the C# fell through to mirroring the work part itself.
  - Detail # 100 works (FormatDetailNumber returned false for exactly 100 and kept the previous number).
  - The session load options are not changed (the form's Load set AsSaved / all components / interpart data on, for
    the rest of the session).
  - The update fail option (accept all) and the interrupt-update-on-error / warning preferences are put back afterwards.
    The C# put back only the two preferences.

Kept from the C#:
  - A component whose part's units differ from the display part's is skipped (now with a note in the listing window).
  - The copy is taken from the original's file on disk, so unsaved changes are not in it, and must land in the work
    part's folder; the new path is the original's with its last three characters before ".prt" replaced by the number.
  - The copy is added to the work part at the original's GetPosition, on its layer, named by the number.
  - Nothing is saved.

Bindings read off the NX2306 NXOpen_UF.pyd docstrings but not seen in NX:
  - Trns.CreateReflectionMatrix(plane) -> (matrix[12], status); Modeling.CreatePlane(origin, normal) -> tag.
  - Modl.TransformEntities(count, tags, matrix) takes a 16-element matrix (the reflection's 12 plus 0, 0, 0, 1).
  - Assem.RepositionInstance(instance, origin[3], csys[6]) - the X and Y axes; Assem.AskInstOfPartOcc(occ) -> instance.
  - Modeling.AskUpdateFailOption / SetUpdateFailOption with NXOpen.UF.Modl.UpdateOption.UpdateAcceptAll (looked up
    by name; when it is missing the option is left alone and the syslog says so).

**Never run in NX** (2026-10-30).
"""

from __future__ import annotations

import os
import shutil
import sys
from typing import Any, Iterable, List, Optional, Sequence, Set, Tuple, cast

# Session.Execute does not put the script's folder on sys.path, so the shared module would not import.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)
# The shared modules are in the python folder beside this file (src\UFuncs\python; deployed, Ufunc\python).
_shared_python = os.path.join(_here, "python")
if os.path.isdir(_shared_python) and _shared_python not in sys.path:
    sys.path.insert(1, _shared_python)

import NXOpen  # noqa: E402
import NXOpen.Assemblies  # noqa: E402
import NXOpen.BlockStyler  # noqa: E402
import NXOpen.Features  # noqa: E402
import NXOpen.UF  # noqa: E402

import tsg_nx as nx  # noqa: E402
from tsg_dialog import Dialog, title_with_version  # noqa: E402

ufunc_name = "mirror-components"

# NX will not create a Block Styler dialog from inside a callback (BillOfMaterial.execute handles it the same way).
_ErrorCannotLaunchDialog = 3520048

# Curves and datum planes on these layers are mirrored (MirrorComponentsGetCurves / NewMethod22: 0 < layer < 21).
_FirstLayer, _LastLayer = 1, 20

# The last Detail # (FormatDetailNumber: 0 < number < 991; the dialog's box starts at 1).
_LastDetail = 990

_DynamicBlockName = "DYNAMIC BLOCK"
_FeatureBlockName = "FEATURE BLOCK"

# UF_UI_SEL_FEATURE_SOLID_BODY
_SolidBodySubtype = 36


# ---------------------------------------------------------------------------------------------------
# Reflection math
# ---------------------------------------------------------------------------------------------------

class _Plane(object):
    """A mirror plane: a point on it and its unit normal (Surface.Plane)."""

    def __init__(self, origin: NXOpen.Point3d, normal: NXOpen.Vector3d) -> None:
        self.origin = origin
        self.normal = nx.unit(normal)

    def vector(self, v: NXOpen.Vector3d) -> NXOpen.Vector3d:
        """v - 2 (v . n) n"""
        n = self.normal
        d = 2.0 * (v.X * n.X + v.Y * n.Y + v.Z * n.Z)
        return NXOpen.Vector3d(v.X - d * n.X, v.Y - d * n.Y, v.Z - d * n.Z)

    def point(self, p: NXOpen.Point3d) -> NXOpen.Point3d:
        """p - 2 ((p - origin) . n) n"""
        n, o = self.normal, self.origin
        d = 2.0 * ((p.X - o.X) * n.X + (p.Y - o.Y) * n.Y + (p.Z - o.Z) * n.Z)
        return NXOpen.Point3d(p.X - d * n.X, p.Y - d * n.Y, p.Z - d * n.Z)

    def frame(self, origin: NXOpen.Point3d, x_axis: NXOpen.Vector3d,
              y_axis: NXOpen.Vector3d) -> Tuple[NXOpen.Point3d, NXOpen.Vector3d, NXOpen.Vector3d]:
        """
        The right-handed frame the C# ended on after reflecting a csys into the WCS and rotating it Y 180 / Z 90: the
        mirrored origin, X along the mirrored Y, Y along the mirrored X (so Z along the mirrored Z).
        """
        return self.point(origin), self.vector(y_axis), self.vector(x_axis)


def _reflection_matrix(plane: _Plane) -> List[float]:
    """UF_TRNS_create_reflection_matrix over a temporary plane, padded to the 16 values transform_entities takes."""
    o, n = plane.origin, plane.normal
    plane_tag = nx.ufsession_.Modeling.CreatePlane([o.X, o.Y, o.Z], [n.X, n.Y, n.Z])
    try:
        matrix, status = nx.ufsession_.Trns.CreateReflectionMatrix(plane_tag)
    finally:
        nx.ufsession_.Obj.DeleteObject(plane_tag)
    if status != 0:
        raise RuntimeError("UF_TRNS_create_reflection_matrix returned status {}.".format(status))
    values = [float(v) for v in matrix][:12]
    return values + [0.0, 0.0, 0.0, 1.0]


# ---------------------------------------------------------------------------------------------------
# One part
# ---------------------------------------------------------------------------------------------------

def _block_lengths(part: NXOpen.BasePart, block: NXOpen.Features.Block) -> Tuple[str, str, str]:
    """
    The block's Length (X), Width (Y) and Height formulas. The builder's Length/Width/Height come back None in Python,
    so the expressions come from UF_MODL_ask_block_parms, as BlankStation.py reads them.
    """
    parms = nx.ufsession_.ModlFeatures.AskBlockParms(block.Tag, 0)
    length, width, height = (part.Expressions.FindObject(parm.split("=", 1)[0].strip()) for parm in parms)
    return length.RightHandSide, width.RightHandSide, height.RightHandSide


def _mirror_block(part: NXOpen.BasePart, block: NXOpen.Features.Block, plane: _Plane) -> None:
    """NewMethod1/8: the block moved to its mirror image - mirrored frame, Length and Width formulas swapped."""
    length, width, height = _block_lengths(part, block)
    builder = part.Features.CreateBlockFeatureBuilder(block)
    try:
        x_axis, y_axis = builder.GetOrientation()
        origin, new_x, new_y = plane.frame(builder.Origin, x_axis, y_axis)
        builder.SetOrientation(new_x, new_y)
        builder.SetOriginAndLengths(origin, width, length, height)
        builder.Commit()
    finally:
        builder.Destroy()
    nx.ufsession_.Modeling.Update()


def _blocks_to_mirror(part: NXOpen.BasePart) -> List[NXOpen.Features.Block]:
    """Every DYNAMIC BLOCK (NewMethod2/4) and FEATURE BLOCK (NewMethod3/6) - only in a part with a DYNAMIC BLOCK."""
    blocks = [f for f in part.Features.GetFeatures() if isinstance(f, NXOpen.Features.Block)]
    if not any(b.Name == _DynamicBlockName for b in blocks):
        return []
    return [b for b in blocks if b.Name in (_DynamicBlockName, _FeatureBlockName)]


def _on_mirrored_layer(obj: NXOpen.DisplayableObject) -> bool:
    return _FirstLayer <= obj.Layer <= _LastLayer


def _objects_to_move(part: NXOpen.BasePart) -> List[NXOpen.DisplayableObject]:
    """MirrorComponentsGetCurves + NewMethod22: curves, and ABSOLUTE_DATUM_PLANE features' datum planes, on 1-20."""
    objects: List[NXOpen.DisplayableObject] = [c for c in cast(NXOpen.Part, part).Curves if _on_mirrored_layer(c)]
    for feature in part.Features.GetFeatures():
        if feature.FeatureType != "ABSOLUTE_DATUM_PLANE":
            continue
        for entity in feature.GetEntities():
            if isinstance(entity, NXOpen.DatumPlane) and _on_mirrored_layer(entity):
                objects.append(entity)
    return objects


def _move_objects(objects: Sequence[NXOpen.DisplayableObject], matrix: List[float]) -> None:
    """UF_MODL_transform_entities on the lot; when NX refuses the batch, one at a time, listing the ones it refuses."""
    if not objects:
        return
    try:
        nx.ufsession_.Modl.TransformEntities(len(objects), [o.Tag for o in objects], matrix)
        return
    except NXOpen.NXException as ex:
        nx.syslog("MirrorComponents: moving {} objects together failed ({}); trying them one at a time".format(
            len(objects), ex))
    for obj in objects:
        try:
            nx.ufsession_.Modl.TransformEntities(1, [obj.Tag], matrix)
        except NXOpen.NXException as ex:
            nx.print_("Could not mirror {} {} (layer {}): {}".format(
                type(obj).__name__, obj.JournalIdentifier, obj.Layer, ex))


def _reposition_children(part: NXOpen.BasePart, plane: _Plane) -> None:
    """NewMethod10/33: each child component moved to its mirrored frame."""
    for child in nx.children(part):
        try:
            position, orientation = child.GetPosition()
            origin, x_axis, y_axis = plane.frame(position, nx.axis_x(orientation), nx.axis_y(orientation))
            instance = nx.ufsession_.Assem.AskInstOfPartOcc(child.Tag)
            nx.ufsession_.Assem.RepositionInstance(
                instance, [origin.X, origin.Y, origin.Z],
                [x_axis.X, x_axis.Y, x_axis.Z, y_axis.X, y_axis.Y, y_axis.Z])
        except Exception as ex:
            nx.print_exception(ex, "Could not mirror the position of {} in {}".format(child.DisplayName, part.Leaf))


def _mirror_part(part: NXOpen.BasePart, plane: _Plane) -> None:
    """The reflection passes on one part, which must be the display and work part; plane is in its coordinates."""
    blocks = _blocks_to_mirror(part)
    for block in blocks:
        _mirror_block(part, block, plane)

    objects = _objects_to_move(part)
    _move_objects(objects, _reflection_matrix(plane))
    nx.ufsession_.Modeling.Update()

    _reposition_children(part, plane)
    nx.ufsession_.Modeling.Update()

    nx.syslog("MirrorComponents: {} - {} block(s), {} curve(s) / datum plane(s), {} child component(s)".format(
        part.Leaf, len(blocks), len(objects), len(nx.children(part))))


def _plane_in(component: Optional[NXOpen.Assemblies.Component], datum: NXOpen.DatumPlane) -> _Plane:
    """
    The datum plane in the component's part's coordinates: wave-linked into the part with the component as the work
    component, read, and the link deleted (MirrorComponentsWaveLinkDatumPlane / NewMethod14/15). None is the display
    part, where the picked plane is already in place.
    """
    if component is None:
        return _Plane(datum.Origin, datum.Normal)

    nx.set_work_component(component)
    part = nx.work_part()
    builder = part.BaseFeatures.CreateWaveLinkBuilder(None)
    try:
        builder.Type = NXOpen.Features.WaveLinkBuilder.Types.DatumLink
        datum_builder = builder.WaveDatumBuilder
        datum_builder.DisplayScale = 2.0
        datum_builder.Associative = True
        datum_builder.HideOriginal = False
        datum_builder.InheritDisplayProperties = False
        datum_builder.Datums.Add(datum)
        link = builder.CommitFeature()
    finally:
        builder.Destroy()

    try:
        linked = [e for e in link.GetEntities() if isinstance(e, NXOpen.DatumPlane)]
        if not linked:
            raise RuntimeError("The wave-linked mirror plane in {} has no datum plane.".format(part.Leaf))
        return _Plane(linked[0].Origin, linked[0].Normal)
    finally:
        nx.delete_objects([link])


def _mirror(targets: Sequence[Optional[NXOpen.Assemblies.Component]], datum: NXOpen.DatumPlane) -> int:
    """
    NewMethod17 / NewMethod20: each target's part mirrored in turn, displayed, then the display and work parts put back.
    None is the display part. A part reached through two targets is mirrored once. Returns the parts mirrored.
    """
    display = nx.display_part()
    done: Set[Any] = set()
    count = 0
    for component in targets:
        part = display if component is None else nx.prototype(component)
        if part.Tag in done:
            continue
        done.add(part.Tag)
        try:
            with nx.display_part_reset():
                if part.PartUnits != display.PartUnits:
                    nx.print_("{} is skipped: its units differ from {}'s.".format(part.Leaf, display.Leaf))
                    continue
                nx.prompt("Mirroring {} ({} of {})".format(part.Leaf, len(done), len(targets)))
                plane = _plane_in(component, datum)
                nx.set_display_part(part)
                nx.set_work_part(part)
                _mirror_part(part, plane)
                count += 1
        except Exception as ex:
            nx.print_exception(ex, "Could not mirror {}".format(part.Leaf))
    return count


# ---------------------------------------------------------------------------------------------------
# Mirror Copies
# ---------------------------------------------------------------------------------------------------

def _copy_path(source: str, number: int) -> str:
    """The original's path with its last three characters before ".prt" replaced by the number."""
    return "{}{:03d}.prt".format(source[:-7], number)


def _copy_component(component: NXOpen.Assemblies.Component,
                    number: int) -> Tuple[Optional[NXOpen.Assemblies.Component], int]:
    """
    CopyComponentToMirror: copies the component's part file to the first free number from `number` up, opens it, adds
    it to the work part at the original's position, layer and name = the number, and puts it in the work part's BODY
    reference sets. Returns the new component (None when it could not) and the next number to try.
    """
    work = nx.work_part()
    source = nx.prototype(component).FullPath

    path = _copy_path(source, number)
    while os.path.exists(path):
        number += 1
        if number > _LastDetail:
            nx.message_box("Mirror Components", NXOpen.NXMessageBox.DialogType.Error,
                           "No free detail number up to {} for {}.".format(_LastDetail, os.path.basename(source)))
            return None, number
        path = _copy_path(source, number)

    if os.path.normcase(os.path.dirname(work.FullPath)) != os.path.normcase(os.path.dirname(path)):
        nx.message_box("Error", NXOpen.NXMessageBox.DialogType.Error,
                       "The selected component is not from the work part directory.\nSave As before making a copy.")
        return None, number

    if not os.path.exists(source):
        nx.message_box("Error", NXOpen.NXMessageBox.DialogType.Error,
                       "Save the original file to the assembly before making a copy")
        return None, number

    shutil.copyfile(source, path)
    opened, load_status = nx.session_.Parts.OpenBase(path)
    if load_status is not None:
        load_status.Dispose()

    position, orientation = component.GetPosition()
    name = "{:03d}".format(number)
    copy = nx.add_component(work, opened, "BODY", name, position, orientation, component.Layer)

    for refset in work.GetAllReferenceSets():
        if refset.Name == "BODY":
            refset.AddObjectsToReferenceSet([copy])

    nx.print_("Copied {} to {}".format(os.path.basename(source), os.path.basename(path)))
    return copy, number + 1


def _copy_components(components: Sequence[NXOpen.Assemblies.Component],
                     first_number: int) -> List[NXOpen.Assemblies.Component]:
    """NewMethod: a copy of each component (by part), numbered from first_number."""
    copies: List[NXOpen.Assemblies.Component] = []
    number = first_number
    seen: Set[Any] = set()
    for index, component in enumerate(components):
        proto = nx.prototype(component)
        if proto.Tag in seen:
            continue
        seen.add(proto.Tag)
        nx.prompt("Copying: ({} of {})".format(index + 1, len(components)))
        try:
            copy, number = _copy_component(component, number)
        except Exception as ex:
            nx.print_exception(ex, "Could not copy {}".format(component.DisplayName))
            continue
        if copy is not None:
            copies.append(copy)
    return copies


# ---------------------------------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------------------------------

def _owning_components(bodies: Iterable[NXOpen.Body]) -> List[NXOpen.Assemblies.Component]:
    """The picked bodies' owning components, once each, in pick order."""
    return nx.distinct_by([b.OwningComponent for b in bodies if b.OwningComponent is not None], lambda c: c.Tag)


def _update_fail_accept_all() -> Optional[Any]:
    """UF_MODL_set_update_fail_option(accept all); returns the option to put back (None when it was not changed)."""
    accept_all = getattr(getattr(getattr(NXOpen.UF, "Modl", None), "UpdateOption", None), "UpdateAcceptAll", None)
    if accept_all is None:
        nx.syslog("MirrorComponents: NXOpen.UF.Modl.UpdateOption.UpdateAcceptAll not found; "
                  "update fail option unchanged")
        return None
    previous = nx.ufsession_.Modeling.AskUpdateFailOption()
    nx.ufsession_.Modeling.SetUpdateFailOption(accept_all)
    return previous


def run(bodies: Sequence[NXOpen.Body], datum: NXOpen.DatumPlane, mirror_copies: bool, first_number: int) -> None:
    """The OK button (buttonOk_Click_1) after its picks. Any exception is printed."""
    modeling = nx.session_.Preferences.Modeling
    interrupt_on_error = modeling.InterruptUpdateOnError
    interrupt_on_warning = modeling.InterruptUpdateOnWarning
    try:
        nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, "Mirror Components")
        modeling.InterruptUpdateOnError = False
        modeling.InterruptUpdateOnWarning = False
        previous_fail_option = _update_fail_accept_all()
        try:
            components = _owning_components(bodies)
            targets: List[Optional[NXOpen.Assemblies.Component]]
            if mirror_copies:
                if not components:
                    nx.message_box("Mirror Components", NXOpen.NXMessageBox.DialogType.Warning,
                                   "Mirror Copies copies components: pick bodies in components, not in the work part.")
                    nx.mark_cancelled("Mirror Copies with no component picked")
                    return
                targets = list(_copy_components(components, first_number))
            elif components:
                targets = list(components)
            else:
                # Only work-part bodies picked: the work part itself (NewMethod20). None when it is the display part.
                targets = [nx.session_.Parts.WorkComponent]

            if not targets:
                return

            with nx.suppress_display():
                count = _mirror(targets, datum)
            nx.print_("Mirrored {} part(s) through {}.".format(count, datum.JournalIdentifier))
        finally:
            if previous_fail_option is not None:
                nx.ufsession_.Modeling.SetUpdateFailOption(previous_fail_option)
    except Exception as ex:
        nx.print_exception(ex)
    finally:
        modeling.InterruptUpdateOnError = interrupt_on_error
        modeling.InterruptUpdateOnWarning = interrupt_on_warning


# ---------------------------------------------------------------------------------------------------
# Dialog
# ---------------------------------------------------------------------------------------------------

class _MirrorComponentsDialog(Dialog):
    dlx_name = "MirrorComponents.dlx"

    def __init__(self, title: str) -> None:
        self.title = title
        super().__init__()

    def initialize(self) -> None:
        bodies = self.block("bodies")
        bodies.SetSelectionFilter(NXOpen.Selection.SelectionAction.ClearAndEnableSpecific,
                                  [NXOpen.Selection.MaskTriple(NXOpen.UF.UFConstants.UF_solid_type, 0,
                                                               _SolidBodySubtype)])
        self.assembly_scope(bodies)

        plane = self.block("plane")
        plane.SetSelectionFilter(NXOpen.Selection.SelectionAction.ClearAndEnableSpecific,
                                 [NXOpen.Selection.MaskTriple(NXOpen.UF.UFConstants.UF_datum_plane_type, 0, 0)])
        self.assembly_scope(plane)

    def shown(self) -> None:
        self._refresh()

    def update(self, block: NXOpen.BlockStyler.UIBlock) -> None:
        if block == self.block("copies"):
            self._refresh()

    def enable_ok(self) -> bool:
        return len(self._bodies()) > 0 and self._datum() is not None

    def ok(self) -> bool:
        bodies, datum = self._bodies(), self._datum()
        # enable_ok greys OK out for these; they are a backstop.
        if not bodies or datum is None:
            self.message("Select the bodies and the mirror plane.", error=True)
            return False
        run(bodies, datum, bool(self.block("copies").Value), int(self.block("detail").Value))
        return True

    def apply(self) -> bool:
        if not self.ok():
            return False
        # ResetForm: the picks are cleared for the next run.
        self.block("bodies").SetSelectedObjects([])
        self.block("plane").SetSelectedObjects([])
        return True

    def _bodies(self) -> List[NXOpen.Body]:
        return [cast(NXOpen.Body, o) for o in self.selected(self.block("bodies")) if isinstance(o, NXOpen.Body)]

    def _datum(self) -> Optional[NXOpen.DatumPlane]:
        planes = [o for o in self.selected(self.block("plane")) if isinstance(o, NXOpen.DatumPlane)]
        return cast(NXOpen.DatumPlane, planes[0]) if planes else None

    def _refresh(self) -> None:
        """checkBoxMirrorCopies_CheckedChanged: Detail # only counts for Mirror Copies."""
        self.block("detail").Enable = bool(self.block("copies").Value)


def execute() -> None:
    title = title_with_version("Mirror Components")
    try:
        _MirrorComponentsDialog(title).run()
    except NXOpen.NXException as ex:
        if ex.ErrorCode != _ErrorCannotLaunchDialog:
            raise
        nx.print_exception(ex)
        nx.show_error("NX would not open the {} dialog (error {} - it will not create a dialog from inside a "
                      "callback).\n\nTry running it from File -> Execute -> NX Open rather than from a menu or "
                      "toolbar button.".format(title, _ErrorCannotLaunchDialog))


def main() -> None:
    """The mirror-components UFunc - its menu button runs this file. An escaping exception is printed."""
    import usage_db

    with usage_db.run(ufunc_name):
        try:
            execute()
        except Exception as ex:
            nx.print_exception(ex)


if __name__ == "__main__":
    main()

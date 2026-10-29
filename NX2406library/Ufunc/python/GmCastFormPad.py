"""
Python port of the gm-cast-form-pad UFunc (Merlin.StaticGmCastFormPad / Merlin.BuildGmCastFormPad,
src\\UFuncs\\Merlin.cs, region "Static Entry Points - GM Component / Split / Form Pad").
The C# wrapper was deleted 2026-10-22 (in git at 1cb53d8): the UFunc's menu button runs this file's main().

Run from an upper or lower station (uad/upd/ush/usp or lad/lsh/lsp as the work part). Select the part bodies; their
combined box, +4" on every side (rounded up to 1/8"), becomes an 8" block from Z -4 in the station, colored 13 with a
yellow (42) top face. It is promoted to {gm|cts}-cast-form-pad, re-based onto the block (the opposite corner for an
upper), and gets:
  - 5 guided retainers (the four box corners and the centre), the last one's prototype Save As'd as a job part;
  - 4 cast-in inserts on the box corners, on layer 96;
  - a SUBTOOL on layer 15 (hidden), the bottom face colored 42;
  - the GM POST CAST TEXT part imported at the centre, on layer 20 (POST, not PAD - kept from the C#);
  - 4 cast pad locators, one on each edge (Merlin.PlaceEdgeItems);
then each picked body's component has its UPR-3D / LWR-3D reference set linked in and subtracted from the pad.
DESCRIPTION / DETAIL NAME CAST FORM PAD, MATERIAL FILL IN, the AutoSize UDO switched off, and BODY set up in every
loaded ancestor assembly.

Two ways in:
  - File -> Execute -> NX Open on this file runs main() with is_gm = True, as the gm-cast-form-pad UFunc does.
  - Session.Execute("GmCastFormPad.py", "GmCastFormPad", "execute", is_gm) from C#.

Differences from the C#:
  - The bounding box is nx.body_box per body, combined. The C# builds five NXOpen.Points per body off an OrientedBox in
    the absolute csys and takes their min/max - the same box, without the temporary points.
  - The AutoSize UDO class can only be registered from C# (see tsg_nx.create_auto_size_udo). Run standalone in a
    session where TSG_Library never registered it, the pad gets no UDO and there is nothing to switch off - both print
    and carry on.
  - GFolder.create_or_null (print-only, result unused) is not ported.

The Merlin helpers DrawDie.py, PointComponent.py and GmCastTrimPad.py already port are imported from them rather than
copied.
"""

from __future__ import annotations

import datetime
import os
import sys
from typing import List, cast

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

import tsg_nx as nx  # noqa: E402
import PointComponent as merlin  # noqa: E402
import DrawDie as drawdie  # noqa: E402
import GmCastTrimPad as trimpad  # noqa: E402

# ---------------------------------------------------------------------------------------------------
# Constants (Merlin's, inches unless the name says otherwise)
# ---------------------------------------------------------------------------------------------------

# Block: the bodies' box plus this much on every side, 8" tall from Z -4.
FormPadGrow = 4.0
FormPadHeight = 8.0
FormPadBottomZ = -4.0
FormPadColor = 13

# The cast pad locators (PlaceEdgeItems arguments).
FormPadLocatorFrontBackNudge = 1.9 / 25.4
FormPadLocatorXEdgeInset = 62.2250 / 25.4
FormPadLocatorExtraZ = 6.350000014 / 25.4

_guidedRetainerZ = 2.9528 + 11 / 25.4
_castInInsertZ = 1.6535

# Guided-retainer / cast-in-insert Z offsets and orientation, per half.
_UpperZAdd = 8.03994 + (1 / 25.4) + -3.4652 + (1 / 25.4) + -(.00074 / 25.4) + ((1 - 0.998776) / 25.4)
_UpperTappedZ = 4.7717
_LowerZAdd = -3.3859 + -(1 / 25.4) + (.00074 / 25.4)
_LowerTappedZ = -0.0787

_gmGuidedRetainerPath = "G:\\0Library\\0Customer\\GM\\Smart GM Guided Retainer.prt"
_gmCastInInsertPath = "G:\\0Library\\0Customer\\GM\\GM M16 Cast-In Insert.prt"
_gmPostCastTextPath = "G:\\CTS\\junk\\blank-station-data\\GM POST CAST TEXT.prt"
_gmCastPadLocatorPath = "G:\\CTS\\junk\\blank-station-data\\GM CAST PAD LOCATOR.prt"
_ctsSmartKeyMetric = "G:\\0Library\\Keys\\Smart Key Metric.prt"
_ctsLiftLugMetric = "G:\\0Library\\LiftLugs\\Metric\\CastIn\\M16-J-449253.prt"
_ctsSmartSlGuidedKeeper = "G:\\0Library\\StandardLifters\\GuidedKeepers\\Smart SL Guided Keepers.prt"

_VectorZ = NXOpen.Vector3d(0.0, 0.0, 1.0)
_VectorZN = NXOpen.Vector3d(0.0, 0.0, -1.0)


class GmCastFormPad(object):

    @staticmethod
    def execute(is_gm: bool = True) -> None:
        """Merlin.StaticGmCastFormPad(is_gm) - the gm-cast-form-pad UFunc passes is_gm = True."""
        static_gm_cast_form_pad(is_gm)


def static_gm_cast_form_pad(is_gm: bool) -> None:
    """
    Merlin.StaticGmCastFormPad - TryBeginGmEntry (units gate, upper/lower from the work part, body pick, UPR-3D /
    LWR-3D, WCS to absolute), then the build.
    """
    ok, message = drawdie._check_info_units()
    if not ok:
        nx.show_error(message)
        return

    is_upper = trimpad._try_detect_is_upper()
    if is_upper is None:
        return

    label = "Gm Cast Form Pad"
    version = nx.assembly_file_version()
    bodies = drawdie._select_bodies("Select solid bodies for {}: {}".format(label, version),
                                    "{}: {}".format(label, version))
    if len(bodies) == 0:
        return

    refset_name = "UPR-3D" if is_upper else "LWR-3D"
    drawdie._set_wcs_to_absolute(nx.display_part())

    build_gm_cast_form_pad(is_gm, is_upper, bodies, refset_name)


def build_gm_cast_form_pad(is_gm: bool, is_upper: bool, bodies: List[NXOpen.Body], refset_name: str) -> None:
    """Merlin.BuildGmCastFormPad - the cast form pad over bodies, built into the work part's station."""
    top_level = nx.display_part()
    nx.set_display_part(nx.work_part())

    start = datetime.datetime.now()
    try:
        _build(is_gm, is_upper, bodies, refset_name, top_level)
    except Exception as ex:
        nx.print_exception(ex)
    finally:
        # Session.__UsingTimer prints the elapsed TimeSpan.
        nx.print_(drawdie._time_span(datetime.datetime.now() - start))


def _build(is_gm: bool, is_upper: bool, bodies: List[NXOpen.Body], refset_name: str,
           top_level: NXOpen.Part) -> None:
    if len(bodies) == 0:
        nx.print_("No bodies selected")
        return

    current_work = nx.work_part()
    box = nx.combine_boxes(nx.body_box(body) for body in bodies)

    length = box.MaxX - box.MinX
    width = box.MaxY - box.MinY

    xlength = nx.round_to_125(length) + FormPadGrow * 2
    ywidth = nx.round_to_125(width) + FormPadGrow * 2

    nx.display_part().Layers.WorkLayer = 1

    block_origin = NXOpen.Point3d(box.MinX - (xlength - length) / 2,
                                  box.MinY - (ywidth - width) / 2,
                                  FormPadBottomZ)

    block = drawdie._create_block_origin_and_lengths(block_origin, xlength, ywidth, FormPadHeight)
    block_body = block.GetBodies()[0]
    nx.set_color(block_body, FormPadColor)
    top_face = nx.planar_face_with_normal_or_null(block_body, _VectorZ)
    if top_face is None:
        raise RuntimeError("The form pad block has no +Z face")
    nx.set_color(top_face, 42)

    form_component = drawdie._create_new_component_core(
        "gm-cast-form-pad" if is_gm else "cts-cast-form-pad",
        [block_body],
        NXOpen.Assemblies.CreateNewComponentBuilder.ComponentOriginType.Absolute,
        NXOpen.Assemblies.CreateNewComponentBuilder.ComponentLayerOptionType.AsSpecified,
        original_objects_deleted=True,
        auto_size_udo=True)

    # Origin on the block's corner rather than the assembly's. Before the subtool below, so the extract is taken at
    # the final position. The block is built at the absolute orientation, so this is a pure translation.
    drawdie._rebase_block_to_part_origin(form_component, cast(NXOpen.Part, form_component.OwningPart),
                                         opposite_corner=is_upper)

    # Everything placed below sits inside the new part. The guided retainers and cast-in inserts measure from
    # `bounding`, re-read off the body just below. The cast text and the pad locators measured from the
    # assembly-space corner, so they now measure from the part origin.
    block_origin = NXOpen.Point3d(0.0, 0.0, 0.0)

    nx.setup_station_expressions(nx.work_part())
    bounding = nx.body_box(trimpad._single_solid_body_on_layer1(nx.display_part()))

    if is_upper:
        z_add = _UpperZAdd
        mat = drawdie._z_matrix(_VectorZ)
        tapped_z = _UpperTappedZ
    else:
        mat = drawdie._z_matrix(_VectorZN)
        z_add = _LowerZAdd
        tapped_z = _LowerTappedZ

    dx, dy, _dz = trimpad._distances(bounding)
    corners = [(0.0, 0.0), (dx, 0.0), (dx, dy), (0.0, dy)]

    guided_retainer_path = _gmGuidedRetainerPath if is_gm else _ctsSmartSlGuidedKeeper
    guided_retainers = [nx.add_component(nx.work_part(), guided_retainer_path, reference_set="BODY",
                                         origin=trimpad._from_min(bounding, x, y, _guidedRetainerZ + z_add),
                                         orientation=mat, layer=99)
                        for x, y in corners + [(dx / 2, dy / 2)]]

    # The last one placed, as the C# loop leaves it - they all share the one prototype anyway.
    nx.prototype(guided_retainers[-1]).SaveAs("{}\\{}-cast-form-pad-guided-retainer-{}.prt".format(
        os.path.dirname(nx.display_part().FullPath), "gm" if is_gm else "cts", merlin._random_file_token()))

    insert_orientation = drawdie._z_matrix(_VectorZ if not is_upper else _VectorZN)
    cast_in_insert_path = _gmCastInInsertPath if is_gm else _ctsLiftLugMetric
    for x, y in corners:
        nx.add_component(nx.work_part(), cast_in_insert_path, reference_set="BODY",
                         origin=trimpad._from_min(bounding, x, y, _castInInsertZ + tapped_z),
                         orientation=insert_orientation, layer=96)

    refset = nx.find_or_create_reference_set(nx.display_part(), "BODY")
    refset.AddObjectsToReferenceSet(list(nx.display_part().Bodies))
    new_part = nx.display_part()

    # Cast details are not resized - force the AutoSize UDO off (UDO + AUTO UPDATE attribute).
    drawdie._switch_auto_size_off(new_part)

    first_block = nx.first_block_feature(new_part)
    if first_block is None:
        raise RuntimeError("{} has no block feature".format(new_part.Leaf))
    first_block.SetName("DYNAMIC BLOCK")
    nx.set_attribute(new_part, "DESCRIPTION", "CAST FORM PAD")
    nx.set_attribute(new_part, "MATERIAL", "FILL IN")
    nx.set_attribute(new_part, "CSPC", "XXXX")
    nx.set_attribute(new_part, "GM Tool Number", "XX-XXXXX")
    new_part.Layers.WorkLayer = 15
    merlin._create_subtool(new_part)

    bottom_face = nx.planar_face_with_normal_or_null(trimpad._single_solid_body_on_layer1(nx.display_part()),
                                                     _VectorZN)
    if bottom_face is None:
        raise RuntimeError("{} has no -Z planar face".format(new_part.Leaf))
    nx.set_color(bottom_face, 42)
    nx.work_part().Layers.WorkLayer = 1
    trimpad._import_cast_text(nx.work_part(), _gmPostCastTextPath, xlength, ywidth, block_origin)

    wcs = nx.display_part().WCS
    current_wcs_fp = wcs.CoordinateSystem.Orientation.Element
    path = _gmCastPadLocatorPath if is_gm else _ctsSmartKeyMetric
    drawdie._place_edge_items(path, block_origin, xlength, ywidth, is_upper,
                              front_back_nudge=FormPadLocatorFrontBackNudge,
                              x_edge_inset=FormPadLocatorXEdgeInset,
                              extra_z=-FormPadLocatorExtraZ if is_upper else FormPadLocatorExtraZ,
                              layer=99)
    wcs.SetOriginAndMatrix(NXOpen.Point3d(0.0, 0.0, 0.0), current_wcs_fp)

    root = nx.root_component(nx.display_part())
    if root is not None:
        nx.find_or_create_reference_set(nx.display_part(), "BODY").AddObjectsToReferenceSet(list(root.GetChildren()))
    nx.find_or_create_reference_set(current_work, "BODY").AddObjectsToReferenceSet([form_component])
    nx.set_reference_set(form_component, "BODY")

    nx.set_display_part(top_level)
    nx.set_work_part(new_part)
    nx.create_auto_size_udo(nx.work_part())
    new_comp = nx.first_occurrence_in(new_part, nx.display_part())
    nx.set_reference_set(new_comp, "BODY")

    # Distinct, in pick order. A body picked outside any component has no component to subtract.
    selected_components: List[NXOpen.Assemblies.Component] = []
    for body in bodies:
        comp = body.OwningComponent
        if comp is not None and all(comp.Tag != seen.Tag for seen in selected_components):
            selected_components.append(comp)

    nx.set_work_part(new_part)
    new_part.Layers.SetState(1, NXOpen.Layer.State.WorkLayer)
    new_part.Layers.SetState(15, NXOpen.Layer.State.Hidden)

    for comp in selected_components:
        target = nx.dynamic_block(nx.work_part()).GetBodies()[0]

        if not nx.has_reference_set(nx.prototype(comp), refset_name):
            nx.print_("Component {} does not have reference set {}, skipping boolean".format(comp.DisplayName,
                                                                                             refset_name))
            continue

        nx.set_reference_set(comp, refset_name)
        try:
            linked = nx.create_linked_body(comp)
            nx.subtract(target, linked.GetBodies())
        except NXOpen.NXException as ex:
            if ex.ErrorCode != merlin.ErrorBooleanFailed:
                raise
            nx.print_("Failed to boolean {} with reference set {}".format(comp.DisplayName, refset_name))
            nx.print_exception(ex)
        nx.set_reference_set(comp, "BODY")

    nx.set_attribute(nx.prototype(form_component), "DETAIL NAME", "CAST FORM PAD")
    nx.set_reference_set(form_component, "BODY")
    # BODY as the used reference set in every ancestor assembly (station .. -000), not just the top-level context, so
    # each sub-assembly shows the pad when opened standalone.
    merlin._set_reference_set_in_ancestor_assemblies(new_comp)
    form_component.Unblank()
    nx.set_work_part(nx.display_part())


def main() -> None:
    """The gm-cast-form-pad UFunc - its menu button runs this file. An escaping exception is printed."""
    import usage_db
    from tsg_dialog import ask_is_gm

    with usage_db.run("gm-cast-form-pad"):
        try:
            # The Customer dialog stands in for the "Are you sure" box: GM builds with the GM parts, TSG throws.
            is_gm = ask_is_gm("Cast Form Pad")
            if is_gm is not None:
                GmCastFormPad.execute(is_gm)
        except Exception as ex:
            nx.print_exception(ex)


if __name__ == "__main__":
    main()

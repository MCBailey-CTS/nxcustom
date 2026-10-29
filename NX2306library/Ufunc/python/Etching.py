"""
The etching UFunc: Python only since 2026-10-29 (no C# class; the C# form, src\\UFuncs\\Etching.cs, and
src\\Static\\Etching.cs are in git before that date). No ribbon or menu button runs it yet. main() asks the "Are you
sure" box and runs the text pass below, which is unfinished (see further down).

The C# form had two buttons: Single Selection (an empty handler) and Smart Selection (AutoDetailCreateMaterialList,
which read the :COMPONENT_MATERIALS: list of the .ucf and threw it away). Neither did anything visible, so neither
is kept; the text pass, Static.Etching1, was called by nothing.

Ported from:
  - Static.Etching1                                   -> Etching.etching1
  - Static.AddFastenersSetWcsToWorkPart              -> _set_wcs_to_work_part
  - BasePart.__CreateTextFeature                      -> _create_text_feature (as in DetailNumberNote.py)
  - BasePart.__DynamicBlockOrNull / __HasDynamicBlock -> _dynamic_block_or_none
  - Block.__Origin / Block.__Orientation              -> _block_origin / _block_orientation
  - Face.__EdgePositions                              -> _edge_positions (as in DetailNumberNote.py)
  - Point3d / Vector3d.__MapCsysToCsys                -> _map_point_csys_to_csys / _map_vector_csys_to_csys
  - WCS.__Orientation                                 -> _wcs_orientation
  - GFolder.Create                                    -> _gfolder_create (only its validation; the result is unused)

This module has NEVER BEEN RUN IN NX.

The method cannot finish, and this port keeps that: for the first planar face of a dynamic-block component whose
every edge vertex sits at the WCS origin's Z, it creates the detail-name text feature and then throws
NotImplementedException (the material text, extrude and subtract are commented out in the C#). The exception is
caught and printed per component, so each qualifying component gets one text feature and one printed exception.

Differences from the C# / unconfirmed bindings:
  - Vector3d.__ToMatrix3x3(Vector3d) goes through UF_MTX3_initialize, which orthonormalizes; tsg_nx.matrix_from_axes
    does not. The block-builder and WCS axes are already orthonormal, so the result should be the same.
  - BlockFeatureBuilder.GetOrientation() and CartesianCoordinateSystem.GetDirections() are assumed to return their
    C# out pair as a tuple (PointComponent.py makes the same assumption for GetOrientation).
  - Session.Parts.WorkComponent, BasePart.CoordinateSystems.CreateCoordinateSystem(Point3d, Matrix3x3, bool) and
    NXObject.Prototype are taken from the C#; the pyd lists them, but their Python signatures are not confirmed.
  - The C# (Text) and (Face) casts are isinstance checks that raise TypeError.
"""

from __future__ import annotations

import os
import re
import sys
from typing import Any, List, Optional, cast

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
import NXOpen.GeometricUtilities  # noqa: E402

import tsg_nx as nx  # noqa: E402

# The text of a bare .NET NotImplementedException, so the listing window reads the same.
_NotImplementedMessage = "The method or operation is not implemented."


class Etching(object):

    @staticmethod
    def etching1() -> None:
        """Static.Etching1 - for every loaded component of the display assembly (distinct by display name) whose
        part has a DYNAMIC BLOCK: sets the WCS to the block, then for each planar face of the occurrence lying at
        the WCS origin's Z, writes the part's leaf as a text feature centred on the face - and throws (see the
        module docstring)."""
        root = cast(NXOpen.Assemblies.Component, nx.display_part().ComponentAssembly.RootComponent)

        components = nx.distinct_by([c for c in nx.descendants(root) if nx.is_loaded(c)], lambda c: c.DisplayName)

        for __c in components:
            try:
                __prototype = cast(NXOpen.Part, nx.prototype(__c))

                if _dynamic_block_or_none(__prototype) is None:
                    continue

                nx.set_work_part(__prototype)

                # The folder is unused; GFolder.Create only has to succeed.
                _gfolder_create(nx.work_part().FullPath)

                _set_wcs_to_work_part()

                # Session.__SetDisplayToWork (despite its name): work_ = disp, so the display part becomes the work part.
                nx.set_work_part(nx.display_part())

                expected_z = nx.display_part().WCS.CoordinateSystem.Origin.Z

                for __member in nx.members(__c):
                    if not isinstance(__member, NXOpen.Face):
                        continue

                    __face = __member

                    if not _is_planar(__face):
                        continue

                    __edge_positions: List[NXOpen.Point3d] = []

                    for __e in __face.GetEdges():
                        vert0, vert1 = __e.GetVertices()
                        __edge_positions.extend((vert0, vert1))

                    if not all(abs(expected_z - __pos.Z) < .001 for __pos in __edge_positions):
                        continue

                    with nx.display_part_reset():
                        nx.set_display_part(nx.prototype(__c))

                        _set_wcs_to_work_part()

                        __proto_face = _as_face(__face.Prototype)

                        z = _edge_positions(__proto_face)[0].Z

                        edge_pos = _edge_positions(__proto_face)

                        average_x = sum(p.X for p in edge_pos) / len(edge_pos)
                        average_y = sum(p.Y for p in edge_pos) / len(edge_pos)
                        # Unused, as in the C#.
                        _average_z = sum(p.Z for p in edge_pos) / len(edge_pos)

                        new_origin = NXOpen.Point3d(average_x, average_y, z)
                        new_ori = _wcs_orientation(nx.display_part().WCS)

                        detail_text_feature = _create_text_feature(
                            nx.display_part(),
                            "{}".format(nx.display_part().Leaf),
                            new_origin,
                            new_ori,
                            .900,
                            .400,
                            "Arial",
                            NXOpen.Features.TextBuilder.ScriptOptions.Oem)

                        if not isinstance(detail_text_feature, NXOpen.Features.Text):
                            raise TypeError("Unable to cast object of type '{}' to type 'NXOpen.Features.Text'."
                                            .format(type(detail_text_feature).__name__))

                        # Unused, as in the C#.
                        _materail_text_feature: Optional[NXOpen.Features.Text] = None

                        # The material text, the extrude of both texts and the subtract from the face's body are
                        # commented out in the C#; it throws here.
                        raise NotImplementedError(_NotImplementedMessage)
                # break;
            except Exception as ex:
                nx.print_exception(ex, __c.DisplayName)


def _as_face(obj: Any) -> NXOpen.Face:
    """The C# (Face) cast."""
    if not isinstance(obj, NXOpen.Face):
        raise TypeError("Unable to cast object of type '{}' to type 'NXOpen.Face'.".format(type(obj).__name__))
    return obj


def _is_planar(face: NXOpen.Face) -> bool:
    """Face.__IsPlanar"""
    return face.SolidFaceType == NXOpen.Face.FaceType.Planar


def _edge_positions(face: NXOpen.Face) -> List[NXOpen.Point3d]:
    """Face.__EdgePositions - both vertices of every edge, duplicates within .001 (per axis, strict) dropped."""
    kept: List[NXOpen.Point3d] = []

    for edge in face.GetEdges():
        point1, point2 = edge.GetVertices()

        for point in (point1, point2):
            if any(abs(k.X - point.X) < .001 and abs(k.Y - point.Y) < .001 and abs(k.Z - point.Z) < .001
                   for k in kept):
                continue

            kept.append(point)

    return kept


def _dynamic_block_or_none(part: NXOpen.BasePart) -> Optional[NXOpen.Features.Block]:
    """BasePart.__DynamicBlockOrNull - the Block feature named DYNAMIC BLOCK. SingleOrDefault, so two throw."""
    blocks = [f for f in part.Features.GetFeatures()
              if isinstance(f, NXOpen.Features.Block) and f.Name == "DYNAMIC BLOCK"]

    if len(blocks) > 1:
        raise RuntimeError("Sequence contains more than one matching element")

    return blocks[0] if blocks else None


def _block_origin(block: NXOpen.Features.Block) -> NXOpen.Point3d:
    """Block.__Origin - read off a BlockFeatureBuilder."""
    builder = block.OwningPart.Features.CreateBlockFeatureBuilder(block)
    try:
        return builder.Origin
    finally:
        builder.Destroy()


def _block_orientation(block: NXOpen.Features.Block) -> NXOpen.Matrix3x3:
    """Block.__Orientation - read off a BlockFeatureBuilder."""
    builder = block.OwningPart.Features.CreateBlockFeatureBuilder(block)
    try:
        x_axis, y_axis = builder.GetOrientation()
        return nx.matrix_from_axes(x_axis, y_axis)
    finally:
        builder.Destroy()


def _wcs_orientation(wcs: NXOpen.WCS) -> NXOpen.Matrix3x3:
    """WCS.__Orientation"""
    x_dir, y_dir = wcs.CoordinateSystem.GetDirections()
    return nx.matrix_from_axes(x_dir, y_dir)


def _map_point_csys_to_csys(input_coords: NXOpen.Point3d, input_csys: NXOpen.CartesianCoordinateSystem,
                            output_csys: NXOpen.CartesianCoordinateSystem) -> NXOpen.Point3d:
    """Point3d.__MapCsysToCsys"""
    origin = input_csys.Origin
    in_matrix = input_csys.Orientation.Element
    out_matrix = output_csys.Orientation.Element
    axes = (nx.axis_x(in_matrix), nx.axis_y(in_matrix), nx.axis_z(in_matrix))
    coords = (input_coords.X, input_coords.Y, input_coords.Z)
    position = [origin.X, origin.Y, origin.Z]

    for axis, value in zip(axes, coords):
        position[0] += axis.X * value
        position[1] += axis.Y * value
        position[2] += axis.Z * value

    vector = NXOpen.Vector3d(position[0] - output_csys.Origin.X,
                             position[1] - output_csys.Origin.Y,
                             position[2] - output_csys.Origin.Z)
    return NXOpen.Point3d(_dot(vector, nx.axis_x(out_matrix)),
                          _dot(vector, nx.axis_y(out_matrix)),
                          _dot(vector, nx.axis_z(out_matrix)))


def _map_vector_csys_to_csys(input_vector: NXOpen.Vector3d, input_csys: NXOpen.CartesianCoordinateSystem,
                             output_csys: NXOpen.CartesianCoordinateSystem) -> NXOpen.Vector3d:
    """Vector3d.__MapCsysToCsys"""
    in_matrix = input_csys.Orientation.Element
    out_matrix = output_csys.Orientation.Element
    axis_x = nx.axis_x(in_matrix)
    axis_y = nx.axis_y(in_matrix)
    axis_z = nx.axis_z(in_matrix)
    vector = NXOpen.Vector3d(
        input_vector.X * axis_x.X + input_vector.Y * axis_y.X + input_vector.Z * axis_z.X,
        input_vector.X * axis_x.Y + input_vector.Y * axis_y.Y + input_vector.Z * axis_z.Y,
        input_vector.X * axis_x.Z + input_vector.Y * axis_y.Z + input_vector.Z * axis_z.Z)
    return NXOpen.Vector3d(_dot(vector, nx.axis_x(out_matrix)),
                           _dot(vector, nx.axis_y(out_matrix)),
                           _dot(vector, nx.axis_z(out_matrix)))


def _dot(vector0: NXOpen.Vector3d, vector1: NXOpen.Vector3d) -> float:
    """Vector3d.__Multiply(Vector3d) - the dot product."""
    return vector0.X * vector1.X + vector0.Y * vector1.Y + vector0.Z * vector1.Z


def _set_wcs_to_work_part() -> None:
    """Static.AddFastenersSetWcsToWorkPart - puts the display part's WCS on the work part's DYNAMIC BLOCK, mapped through
    the work component when the work part is not the display part. The two csys it makes are temporary."""
    dynamic_block = _dynamic_block_or_none(nx.work_part())

    if dynamic_block is None:
        # BasePart.__DynamicBlock
        raise Exception("Could not find ")

    origin = _block_origin(dynamic_block)
    orientation = _block_orientation(dynamic_block)

    if nx.work_part().Tag == nx.display_part().Tag:
        nx.display_part().WCS.SetOriginAndMatrix(origin, orientation)
        return

    work_component = nx.session_.Parts.WorkComponent

    abs_csys = nx.display_part().CoordinateSystems.CreateCoordinateSystem(
        NXOpen.Point3d(0.0, 0.0, 0.0), nx.identity_matrix(), True)

    comp_csys = nx.display_part().CoordinateSystems.CreateCoordinateSystem(
        nx.component_origin(work_component),
        nx.component_orientation(work_component),
        True)

    new_origin = _map_point_csys_to_csys(origin, comp_csys, abs_csys)
    new_x_vec = _map_vector_csys_to_csys(nx.axis_x(nx.component_orientation(work_component)), comp_csys, abs_csys)
    new_y_vec = _map_vector_csys_to_csys(nx.axis_y(nx.component_orientation(work_component)), comp_csys, abs_csys)
    new_orientation = nx.matrix_from_axes(new_x_vec, new_y_vec)
    nx.display_part().WCS.SetOriginAndMatrix(new_origin, new_orientation)


def _create_text_feature(part: NXOpen.BasePart, note: str, origin: NXOpen.Point3d, orientation: NXOpen.Matrix3x3,
                         length: float, height: float, font: str,
                         script: Any) -> NXOpen.Features.Feature:
    """BasePart.__CreateTextFeature"""
    text_builder = part.Features.CreateTextBuilder(None)

    try:
        text_builder.PlanarFrame.AnchorLocation = \
            NXOpen.GeometricUtilities.RectangularFrameBuilder.AnchorLocationType.MiddleCenter
        text_builder.PlanarFrame.WScale = 100.0
        text_builder.PlanarFrame.Length.RightHandSide = nx.cs_double_str(length)
        text_builder.PlanarFrame.Height.RightHandSide = nx.cs_double_str(height)
        text_builder.PlanarFrame.WScale = 75.0
        text_builder.SelectFont(font, script)
        text_builder.TextString = note
        point2 = part.Points.CreatePoint(origin)
        csys = part.CoordinateSystems.CreateCoordinateSystem(origin, orientation, True)
        text_builder.PlanarFrame.CoordinateSystem = csys
        text_builder.PlanarFrame.UpdateOnCoordinateSystem()
        work_view = nx.session_.Parts.Work.ModelingViews.WorkView
        text_builder.PlanarFrame.AnchorLocator.SetValue(point2, work_view, origin)
        return cast(NXOpen.Features.Feature, text_builder.Commit())
    finally:
        text_builder.Destroy()


def _gfolder_create(job_folder: str) -> None:
    """GFolder.Create(string), validation only - raises where the C# throws; the folder itself is not needed."""
    split = job_folder.split("\\")

    if len(split) < 3:
        # C#: IndexOutOfRangeException(jobFolder)
        raise IndexError(job_folder)

    directory = "{}\\{}\\{}".format(split[0], split[1], split[2])

    if "\\cts\\" not in directory.lower():
        return

    # Not the C#: a job copied below the usual depth (G:\CTS\junk\Mark B\006073\006073-010\...) has no job number
    # in the third piece, so any deeper folder whose name starts with one will do.
    for leaf in [split[2]] + split[3:-1]:
        if re.match(r"^\s*[+-]?\d+\s*$", leaf) and -2147483648 <= int(leaf) <= 2147483647:
            return

        if re.match(r"^(?P<cts_number>\d{2,}) \([A-Z]+-[xX]+\)", leaf):
            return

        if re.match(r"^(?P<cts_number>\d{2,}) \([A-Za-z]+-(?P<customer_number>\d+)\)", leaf):
            return

        if re.match(r"^(?P<customer_number>\d{2,})", leaf):
            return

    raise ValueError("Could not make GFolder from '{}'".format(job_folder))


def main() -> None:
    """The etching UFunc (File -> Execute -> NX Open on this file): the confirm box, then the text pass."""
    import usage_db

    with usage_db.run("etching"):
        try:
            # No dialog of its own: ask before doing anything (a logged Question box).
            if nx.confirm_execute("etching"):
                Etching.etching1()
        except Exception as ex:
            nx.print_exception(ex)


if __name__ == "__main__":
    main()

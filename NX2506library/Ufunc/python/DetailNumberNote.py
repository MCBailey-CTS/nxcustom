"""
Python port of the NX work in the DetailNumberNote form (src\\UFuncs\\DetailNumberNote.cs), from the C# statics in
src\\Static\\DetailNumberNote.cs: the part of DetailNumberNoteMain1 after the tool pick, plus
DetailNumberNoteSimpleInterference, DetailNumberNoteTryCreateNote, DetailNumberNoteCreateNote0,
DetailNumberNoteGetDetailName, DetailNumberNoteModifyDisplay, DetailNumberNoteCreateOrientationFromZVector,
DetailNumberNoteSumEdgePositions and DetailNumberNoteRemoveParameters.

Wired (2026-10-21): DetailNumberNoteMain1 keeps its picks and the occurrence check in C# and calls
DetailNumberNote.create_notes in place of its tool loop. Never run in NX.

Not ported:
- The pickers (DetailNumberNoteSelectPlanarFace, DetailNumberNoteSelectToolComponents, and the unused
  DetailNumberNoteSelectSolidBodies / DetailNumberNoteSelectSolidBody): selection stays C#.
- The start of DetailNumberNoteMain1 - the target-face pick, the "Please select an occurrence face" check and the
  (unused) target_face_normal - because it sits between the two picks.
- DetailNumberNoteReadString/ReadInt/ReadDouble/ReadScriptOptions: no NX work, and nothing calls them (the form's
  constructor has the calls commented out).

The UFunc cannot finish today, and this port keeps that: DetailNumberNoteCreateNote0 ends in
`throw new NotImplementedException()` after building the note, and _create_note0 raises NotImplementedError at the
same point. (Face.__NormalVector in Globals.cs used to throw too; it now returns UF_MODL_ask_face_data's dir, and so
does _normal_vector.)

DetailNumberNoteMain1 calls
    PythonLibrary.Execute("DetailNumberNote.py", "DetailNumberNote", "create_notes",
        targetFace, selectedToolComponents.Cast<TaggedObject>().ToArray(),
        expectedTargetVector.X, expectedTargetVector.Y, expectedTargetVector.Z,
        length, height, font, script.ToString(), color, layer, referenceSet);
in place of its foreach loop. The script option goes by its enum name, since Session.Execute cannot pass an enum.

Differences from the C#:
- DisplayPartReset wraps only the loop here; the C# wraps the picks too. The picks do not change the display part.
- C#'s (Face) casts become an isinstance check that raises TypeError.
"""

from __future__ import annotations

import os
import sys
from typing import Any, Iterable, List, Optional, Sequence, cast

# Session.Execute does not put the script's folder on sys.path, so the shared module would not import.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

import NXOpen  # noqa: E402
import NXOpen.Assemblies  # noqa: E402
import NXOpen.Features  # noqa: E402
import NXOpen.GeometricAnalysis  # noqa: E402
import NXOpen.GeometricUtilities  # noqa: E402

import tsg_nx as nx  # noqa: E402

# uf_csys.h (NX2406\UGOPEN): UF_CSYS_ROOT_COORDS 1, UF_CSYS_ROOT_WCS_COORDS 3.
_UF_CSYS_ROOT_COORDS = 1
_UF_CSYS_ROOT_WCS_COORDS = 3

# UF_MODL_ask_face_data's type for a planar face.
_UF_MODL_PLANAR_FACE = 22

# The text of a bare .NET NotImplementedException, so the listing window reads the same.
_NotImplementedMessage = "The method or operation is not implemented."


def _as_face(obj: Any) -> NXOpen.Face:
    """The C# (Face) cast."""
    if not isinstance(obj, NXOpen.Face):
        raise TypeError("Unable to cast object of type '{}' to type 'NXOpen.Face'.".format(type(obj).__name__))
    return obj


def _is_planar(face: NXOpen.Face) -> bool:
    """Face.__IsPlanar"""
    return face.SolidFaceType == NXOpen.Face.FaceType.Planar


def _normal_vector(face: NXOpen.Face) -> NXOpen.Vector3d:
    """
    Face.__NormalVector - UF_MODL_ask_face_data's dir for a planar face (the surface normal; the face sense in
    normDir is ignored, as in the C#); raises for any other face type.
    """
    face_data = nx.ufsession_.Modeling.AskFaceData(face.Tag)
    face_type = face_data[0]
    direction = face_data[2]

    if face_type != _UF_MODL_PLANAR_FACE:
        raise RuntimeError("Cannot ask for the normal of a non planar face")

    return NXOpen.Vector3d(direction[0], direction[1], direction[2])


def _is_equal(vec0: NXOpen.Vector3d, vec1: NXOpen.Vector3d, tolerance: float = .001) -> bool:
    """Vector3d.__IsEqual - UF_VEC3_is_equal; any result but 0/1 is an error."""
    is_equal = nx.ufsession_.Vec3.IsEqual([vec0.X, vec0.Y, vec0.Z], [vec1.X, vec1.Y, vec1.Z], tolerance)

    if is_equal == 0:
        return False

    if is_equal == 1:
        return True

    # C#: throw NXException.Create(is_equal)
    raise RuntimeError("UF_VEC3_is_equal returned {}".format(is_equal))


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


def _map_acs_to_wcs(abs_coords: NXOpen.Point3d) -> NXOpen.Point3d:
    """Point3d.__MapAcsToWcs"""
    mapped = nx.ufsession_.Csys.MapPoint(_UF_CSYS_ROOT_COORDS, [abs_coords.X, abs_coords.Y, abs_coords.Z],
                                         _UF_CSYS_ROOT_WCS_COORDS)
    return NXOpen.Point3d(mapped[0], mapped[1], mapped[2])


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
        # CreateCoordinateSystem(origin, orientation, isTemporary) - the pyd lists this overload; whether it takes a
        # Matrix3x3 (as the C# does) rather than an NXMatrix is not confirmed.
        csys = part.CoordinateSystems.CreateCoordinateSystem(origin, orientation, True)
        text_builder.PlanarFrame.CoordinateSystem = csys
        text_builder.PlanarFrame.UpdateOnCoordinateSystem()
        work_view = nx.session_.Parts.Work.ModelingViews.WorkView
        text_builder.PlanarFrame.AnchorLocator.SetValue(point2, work_view, origin)
        # C#: (Text)textBuilder.Commit()
        return cast(NXOpen.Features.Feature, text_builder.Commit())
    finally:
        text_builder.Destroy()


def _simple_interference(part: NXOpen.Part, target_body: NXOpen.Body,
                         tool_body: NXOpen.Body) -> List[NXOpen.Face]:
    """Static.DetailNumberNoteSimpleInterference"""
    obj = part.AnalysisManager.CreateSimpleInterferenceObject()

    try:
        obj.FaceInterferenceType = NXOpen.GeometricAnalysis.SimpleInterference.FaceInterferenceMethod.AllPairs
        obj.InterferenceType = NXOpen.GeometricAnalysis.SimpleInterference.InterferenceMethod.InterferingFaces
        obj.FirstBody.Value = target_body
        obj.SecondBody.Value = tool_body
        obj.PerformCheck()
        result = obj.GetInterferenceResults()
        faces: List[Optional[NXOpen.Face]] = [None] * len(result)

        for i in range(0, len(result), 2):
            faces[i] = _as_face(result[i])
            # An odd result count fails here, as the C# does (IndexOutOfRangeException).
            faces[i + 1] = _as_face(result[i + 1])

        obj.Reset()
        return cast(List[NXOpen.Face], faces)
    finally:
        obj.Destroy()


def _get_detail_name(component: NXOpen.Assemblies.Component) -> str:
    """Static.DetailNumberNoteGetDetailName - the last three characters of the display name."""
    display_name = component.DisplayName

    length = len(display_name)

    if length < 3:
        # C# Substring(length - 3) throws ArgumentOutOfRangeException.
        raise ValueError("startIndex cannot be larger than length of string.")

    return display_name[length - 3:]


def _modify_display(displayable_objects: Sequence[NXOpen.DisplayableObject], color: int, layer: int) -> None:
    """Static.DetailNumberNoteModifyDisplay"""
    disp_mod = nx.session_.DisplayManager.NewDisplayModification()

    try:
        disp_mod.ApplyToAllFaces = True

        disp_mod.ApplyToOwningParts = False

        disp_mod.NewColor = color

        disp_mod.NewLayer = layer

        disp_mod.Apply(list(displayable_objects))
    finally:
        disp_mod.Dispose()


def _create_orientation_from_z_vector(vector: NXOpen.Vector3d) -> NXOpen.Matrix3x3:
    """Static.DetailNumberNoteCreateOrientationFromZVector - UF_MTX3_initialize_z, rows X and Y."""
    matrix = nx.ufsession_.Mtx3.InitializeZ([vector.X, vector.Y, vector.Z])
    x_vec = NXOpen.Vector3d(matrix[0], matrix[1], matrix[2])
    y_vec = NXOpen.Vector3d(matrix[3], matrix[4], matrix[5])
    return nx.matrix_from_axes(x_vec, y_vec)


def _sum_edge_positions(edge_positions: Iterable[NXOpen.Point3d]) -> List[float]:
    """Static.DetailNumberNoteSumEdgePositions"""
    x = 0.0
    y = 0.0
    z = 0.0

    for pos in edge_positions:
        x += pos.X
        y += pos.Y
        z += pos.Z

    return [x, y, z]


def _remove_parameters(part: NXOpen.Part, objects: Sequence[NXOpen.NXObject]) -> None:
    """Static.DetailNumberNoteRemoveParameters"""
    remove_parameters = part.Features.CreateRemoveParametersBuilder()

    try:
        remove_parameters.Objects.Add(list(objects))

        remove_parameters.Commit()
    finally:
        remove_parameters.Destroy()


def _create_note0(detail_number: str, target_face: NXOpen.Face, tool_face: NXOpen.Face, length: float,
                  height: float, font: str, script: Any, color: int, layer: int, reference_set: str) -> None:
    """Static.DetailNumberNoteCreateNote0 - builds the note, then raises NotImplementedError like the C#."""
    edge_positions = _edge_positions(tool_face)

    edge_sums = _sum_edge_positions(edge_positions)

    count = len(edge_positions)

    origin_in_absolute = NXOpen.Point3d(edge_sums[0] / count, edge_sums[1] / count, edge_sums[2] / count)

    comp_origin = nx.component_origin(target_face.OwningComponent)

    comp_orientation = nx.component_orientation(target_face.OwningComponent)

    nx.display_part().WCS.SetOriginAndMatrix(comp_origin, comp_orientation)

    origin_in_target = _map_acs_to_wcs(origin_in_absolute)

    face_vector = _normal_vector(target_face)

    orientation = _create_orientation_from_z_vector(face_vector)

    nx.set_display_part(cast(NXOpen.Part, _as_face(target_face.Prototype).OwningPart))

    text = _create_text_feature(nx.work_part(), detail_number, origin_in_target, orientation,
                                length,
                                height, font, script)

    splines: List[NXOpen.NXObject] = [e for e in text.GetEntities() if isinstance(e, NXOpen.Spline)]

    _remove_parameters(nx.work_part(), splines)

    _modify_display(cast(List[NXOpen.DisplayableObject], splines), color, layer)

    display = nx.display_part()

    existing = nx.find_reference_set_or_null(display, reference_set)

    if existing is not None:
        refset = existing
    else:
        refset = display.CreateReferenceSet()

        refset.SetName(reference_set)

    refset.AddObjectsToReferenceSet(splines)

    refset.AddObjectsToReferenceSet([_as_face(target_face.Prototype).GetBody()])

    raise NotImplementedError(_NotImplementedMessage)


def _try_create_note(detail: str, expected_target_vector: NXOpen.Vector3d, interfering_faces: Sequence[NXOpen.Face],
                     length: float, height: float, font: str, script: Any, color: int, layer: int,
                     reference_set: str) -> bool:
    """Static.DetailNumberNoteTryCreateNote"""
    for i in range(0, len(interfering_faces) - 1, 2):
        target_face = interfering_faces[i]
        tool_face = interfering_faces[i + 1]

        if not _is_planar(target_face):
            continue

        if not _is_planar(tool_face):
            continue

        target_vector = nx.unit(_normal_vector(target_face))
        tool_vector = nx.unit(_normal_vector(tool_face))

        if not _is_equal(target_vector, expected_target_vector):
            continue

        if not _is_equal(tool_vector, nx.negate(expected_target_vector)):
            continue

        _create_note0(detail, target_face, tool_face, length, height, font, script, color, layer, reference_set)
        return True

    return False


class DetailNumberNote(object):

    @staticmethod
    def create_notes(target_face: NXOpen.Face, tool_components: Sequence[NXOpen.Assemblies.Component],
                     expected_x: float, expected_y: float, expected_z: float,
                     length: float, height: float, font: str, script: str, color: int, layer: int,
                     reference_set: str) -> None:
        """
        The tool loop of Static.DetailNumberNoteMain1: for each tool, find the interference faces between the
        target face's body and the tool's layer-1 body, and note the tool's detail number on the face pair whose
        normals match the expected vector. script is a TextBuilder.ScriptOptions member name ("Western").
        """
        expected_target_vector = NXOpen.Vector3d(expected_x, expected_y, expected_z)
        script_option = getattr(NXOpen.Features.TextBuilder.ScriptOptions, script)

        with nx.display_part_reset():
            for tool in tool_components:
                bodies = [b for b in nx.members(tool)
                          if isinstance(b, NXOpen.Body) and cast(NXOpen.Body, b.Prototype).Layer == 1]

                if not bodies:
                    raise ValueError("Sequence contains no matching element")

                if len(bodies) > 1:
                    raise ValueError("Sequence contains more than one matching element")

                solid_body_layer_1_proto = bodies[0]

                interfering_faces = _simple_interference(nx.work_part(), target_face.GetBody(),
                                                         solid_body_layer_1_proto)

                detail = _get_detail_name(interfering_faces[1].OwningComponent)

                if _try_create_note(detail, expected_target_vector, interfering_faces,
                                    length, height, font, script_option, color, layer, reference_set):
                    solid_body_layer_1_proto.OwningComponent.Blank()

                    nx.print_("Created Note: {}".format(detail))

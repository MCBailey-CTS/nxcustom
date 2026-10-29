"""
The geometry design checks - ports of src\\UFuncs\\DesignCheck\\Validators\\CastingHalfMoons.cs, Dimensions.cs,
JigJacks.cs and ThirtyPoundCheck.cs over the design_check framework.

Ported from:
  - CastingHalfMoons (CastingMaterials, CheckMoons, Check, GetObjects) -> CastingHalfMoons (casting_materials,
    _check_moons, check, get_objects)
  - Dimensions                                  -> Dimensions
  - JigJacks (IsInchGrid, Check, GetObjects)    -> JigJacks (_is_inch_grid, check, get_objects)
  - ThirtyPoundCheck (MassInPounds, ...)        -> ThirtyPoundCheck (_mass_in_pounds, ...)
  - BasePart.__TreeNode / PartNode(part)        -> Item(part.Leaf, part)
  - Face.__NormalVector                         -> _normal_vector
  - Vector3d.__ToMatrix3x3 (from a Z axis)      -> _matrix_from_z
  - Vector3d._IsPerpendicularTo                 -> _is_perpendicular_to (UF Vec3.IsPerpendicular)
  - Point3d.__MapAcsToWcs                       -> _map_acs_to_wcs (UF Csys.MapPoint, root -> root WCS)
  - Edge.__StartPoint                           -> nx.edge_start_point
  - Component.__Origin                          -> nx.component_origin
  - Component._IsJckScrewTsg_                   -> nx.is_jck_screw_tsg(component.DisplayName)
  - BasePart.__Children                         -> nx.children
  - Point3d.__Distance                          -> nx.distance
  - BasePart.__SolidBodyLayer1OrNull            -> _solid_body_layer1_or_null

Differences from the C#:
  - None in behaviour intended. Kept from the C#, quirks included:
      * CastingHalfMoons fails when ANY half moon face IS planar (the message says "not a Planar Face"), so every
        face reaching the normal test is non-planar, and _normal_vector (Face.__NormalVector) raises "Cannot ask
        for the normal of a non planar face" - a part with four correctly named faces is counted as an error, never
        a pass. A HALFMOON1 / HALFMOON2 count other than 1 or 2 (0 included) reports "Found three faces named ...".
      * _check_moons moves the display part's WCS to the first face's first edge and leaves it there.
      * Dimensions asks UF View.AskViewDependentStatus and throws the answer away; the result is only
        "not IsRetained".
      * JigJacks' IsInchGrid never resets isInch, so one jack distance on the inch grid (a whole 1..71" or a
        sqrt(k^2 + m^2) diagonal, k, m in 1..71) passes the part. Two or more jacks with none on the grid fail with
        just the part node (no text under it), as in the C#.
  - Assumed NXOpen Python signatures (not in the stubs, so reached through Any):
      * ufsession_.View.AskViewDependentStatus(tag) returns (status, view name) - the C#'s two out parameters.
      * ufsession_.Vec3.IsPerpendicular(vec1, vec2, tolerance) returns the int (like Vec3.IsEqual in
        DetailNumberNote.py).
      * Part.Dimensions, Part.MeasureManager.NewMassProperties, MeasureBodies.AnalysisUnit / InformationUnit /
        Mass and Dimension.IsRetained - used as BillOfMaterial.py uses the measure ones.
  - The MeasureBodies is Dispose()d in a finally block in place of the C# using.

NEVER RUN IN NX. The C# design-check form and design-check-report stay until this is confirmed.
"""

from __future__ import annotations

import math
import os
import sys
from typing import Any, List, Optional, Sequence, Tuple, cast

# Session.Execute does not put the script's folder on sys.path, so the shared module would not import.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

import NXOpen  # noqa: E402

import tsg_nx as nx  # noqa: E402
from design_check import Check, Item, Result  # noqa: E402

# uf_csys.h
_UF_CSYS_ROOT_COORDS = 1
_UF_CSYS_ROOT_WCS_COORDS = 3

# UF_MODL_ask_face_data's type for a planar face.
_UF_MODL_PLANAR_FACE = 22


# ---------------------------------------------------------------------------------------------------
# Helpers (Globals.cs extensions with no tsg_nx port)
# ---------------------------------------------------------------------------------------------------

def _part_node(part: NXOpen.BasePart) -> Item:
    """BasePart.__TreeNode / PartNode: the part's Leaf, Tag = the part."""
    return Item(part.Leaf, part)


def _normal_vector(face: NXOpen.Face) -> NXOpen.Vector3d:
    """Face.__NormalVector - UF_MODL_ask_face_data's direction (not unitized); raises for a non planar face."""
    face_type, _point, direction, _box, _radius, _rad_data, _norm_dir = nx.ufsession_.Modeling.AskFaceData(face.Tag)
    if face_type != _UF_MODL_PLANAR_FACE:
        raise RuntimeError("Cannot ask for the normal of a non planar face")
    return NXOpen.Vector3d(direction[0], direction[1], direction[2])


def _cross(u: NXOpen.Vector3d, v: NXOpen.Vector3d) -> NXOpen.Vector3d:
    """Vector3d.__Cross"""
    return NXOpen.Vector3d(u.Y * v.Z - u.Z * v.Y, u.Z * v.X - u.X * v.Z, u.X * v.Y - u.Y * v.X)


def _matrix_from_z(axis_z: NXOpen.Vector3d) -> NXOpen.Matrix3x3:
    """Vector3d.__ToMatrix3x3 - an orthonormal matrix whose Z row is axis_z (unitized)."""
    u = NXOpen.Vector3d(0.0, 1.0, 0.0) if not abs(axis_z.X) < abs(axis_z.Y) else NXOpen.Vector3d(1.0, 0.0, 0.0)
    axis_z = nx.unit(axis_z)
    v = nx.unit(_cross(u, axis_z))
    w = nx.unit(_cross(axis_z, v))
    matrix = NXOpen.Matrix3x3()
    matrix.Xx, matrix.Xy, matrix.Xz = v.X, v.Y, v.Z
    matrix.Yx, matrix.Yy, matrix.Yz = w.X, w.Y, w.Z
    matrix.Zx, matrix.Zy, matrix.Zz = axis_z.X, axis_z.Y, axis_z.Z
    return matrix


def _is_perpendicular_to(vec1: NXOpen.Vector3d, vec2: NXOpen.Vector3d, tolerance: float = 0.0001) -> bool:
    """Vector3d._IsPerpendicularTo - UF_VEC3_is_perpendicular."""
    vec3 = cast(Any, nx.ufsession_).Vec3
    return int(vec3.IsPerpendicular([vec1.X, vec1.Y, vec1.Z], [vec2.X, vec2.Y, vec2.Z], tolerance)) == 1


def _map_acs_to_wcs(abs_coords: NXOpen.Point3d) -> NXOpen.Point3d:
    """Point3d.__MapAcsToWcs - UF_CSYS_map_point from the absolute csys to the WCS."""
    mapped = nx.ufsession_.Csys.MapPoint(_UF_CSYS_ROOT_COORDS, [abs_coords.X, abs_coords.Y, abs_coords.Z],
                                         _UF_CSYS_ROOT_WCS_COORDS)
    return NXOpen.Point3d(mapped[0], mapped[1], mapped[2])


def _solid_body_layer1_or_null(part: NXOpen.BasePart) -> Optional[NXOpen.Body]:
    """BasePart.__SolidBodyLayer1OrNull - the one non-occurrence solid body on layer 1, else None."""
    bodies = [body for body in cast(Any, part).Bodies
              if isinstance(body, NXOpen.Body) and not body.IsOccurrence and body.IsSolidBody and body.Layer == 1]
    return bodies[0] if len(bodies) == 1 else None


# ---------------------------------------------------------------------------------------------------
# CastingHalfMoons
# ---------------------------------------------------------------------------------------------------

class CastingHalfMoons(Check):
    """
    A casting (MATERIAL one of casting_materials) must have exactly four faces named HALFMOON*: two HALFMOON1 and
    two HALFMOON2, non planar, with normals perpendicular to absolute Z, each pair aligned.
    """

    assembly_part_only = False

    # sql
    casting_materials = [
        "GM190",
        "GM238",
        "GM241",
        "GM245",
        "GM246",
        "GM338",
        "S0050A",
        "S0030A",
        "G2500",
        "G3500",
        "D4512",
        "D5506",
        "D6510",
        "CARMO CAST",
        "GM68M",
        "S0030",
    ]

    @staticmethod
    def _check_moons(face1: NXOpen.Face, face2: NXOpen.Face) -> bool:
        """CheckMoons: the WCS on face1's first edge start, Z = face1's normal; face2's first edge start must map
        to Z 0 (within .0001). The WCS is left there."""
        nx.display_part().WCS.SetOriginAndMatrix(
            nx.edge_start_point(face1.GetEdges()[0]),
            _matrix_from_z(_normal_vector(face1)))

        return abs(_map_acs_to_wcs(nx.edge_start_point(face2.GetEdges()[0])).Z) < .0001

    def get_objects(self, part: NXOpen.Part) -> List[Any]:
        return [part]

    def check(self, obj: Any) -> Tuple[str, Optional[Item]]:
        part = cast(NXOpen.Part, obj)
        node = _part_node(part)

        if not nx.has_attribute(part, "MATERIAL"):
            node.add("Doesn't have MATERIAL attribute")
            return Result.Ignore, node

        material_value = nx.get_attribute(part, "MATERIAL")

        if all(val != material_value for val in self.casting_materials):
            node.add("Not a casting material: {}".format(material_value))
            return Result.Ignore, node

        # sql
        half_moon_const = "HALFMOON"

        all_half_moon_faces_in_part: List[NXOpen.Face] = [
            face
            for body in cast(Any, part).Bodies
            for face in body.GetFaces()
            if (face.Name or "").startswith(half_moon_const)]

        count = len(all_half_moon_faces_in_part)
        if count == 0:
            node.add("Could not find any named half moons.")
            return Result.Fail, node
        if count in (1, 2, 3):
            node.add("Only found {} face(s).".format(count))
            return Result.Fail, node
        if count != 4:
            node.add("Found too many half moon faces: {}.".format(count))
            return Result.Fail, node

        if any(face.SolidFaceType == NXOpen.Face.FaceType.Planar for face in all_half_moon_faces_in_part):
            node.add("Found at least one face named half moon that is not a Planar Face.")
            return Result.Fail, node

        half_moons1 = [face for face in all_half_moon_faces_in_part if face.Name == half_moon_const + "1"]
        half_moons2 = [face for face in all_half_moon_faces_in_part if face.Name == half_moon_const + "2"]

        # Checks to make sure that the program found 2 and only 2 faces named HALFMOON1.
        if len(half_moons1) != 2:
            node.add("Only found one face named {}1.".format(half_moon_const) if len(half_moons1) == 1
                     else "Found three faces named {}1.".format(half_moon_const))
            return Result.Fail, node

        # Checks to make sure that the program found 2 and only 2 faces named HALFMOON2.
        if len(half_moons2) != 2:
            node.add("Only found one face named {}2.".format(half_moon_const) if len(half_moons2) == 1
                     else "Found three faces named {}2.".format(half_moon_const))
            return Result.Fail, node

        # Checks to make sure that the normal of all the half moon faces is parallel to the absolute XY plane.
        z_axis = NXOpen.Vector3d(0.0, 0.0, 1.0)
        if any(not _is_perpendicular_to(_normal_vector(face), z_axis) for face in all_half_moon_faces_in_part):
            node.add("Found at least one half moon face whose normal isn't parallel to the absolute Z Axis of the "
                     "displayed snapPart.")
            return Result.Fail, node

        if not self._check_moons(half_moons1[0], half_moons1[1]):
            node.add("The half moon 1 faces are not aligned properly.")
            return Result.Fail, node

        if self._check_moons(half_moons2[0], half_moons2[1]):
            return Result.Pass, node

        node.add("The half moon 2 faces are not aligned properly.")
        return Result.Fail, node


# ---------------------------------------------------------------------------------------------------
# Dimensions
# ---------------------------------------------------------------------------------------------------

class Dimensions(Check):
    """Checks all the dimensions in an assembly are associative and up to date (fails a retained dimension)."""

    assembly_part_only = False

    def get_objects(self, part: NXOpen.Part) -> List[Any]:
        return list(cast(Any, part).Dimensions)

    def check(self, obj: Any) -> Tuple[str, Optional[Item]]:
        dimension = cast(Any, obj)
        node = Item(dimension.Name, dimension)

        # Gets the name of the drawing view that contains the "dimension".
        status = cast(Any, nx.ufsession_).View.AskViewDependentStatus(dimension.Tag)
        drawing_sheet_name = status[1] if isinstance(status, (tuple, list)) else ""

        # Some drawing sheets return a name with "@0" prepended; the C# replaces it and discards the result.
        _ = (drawing_sheet_name or "").replace("@0", "")

        return (Result.Pass if not dimension.IsRetained else Result.Fail), node


# ---------------------------------------------------------------------------------------------------
# JigJacks
# ---------------------------------------------------------------------------------------------------

class JigJacks(Check):
    """
    A part's unsuppressed, loaded -jck-screw-tsg children: none = ignored, one = fail, more = pass when the jacks
    sit on an inch grid from the first one.
    """

    assembly_part_only = False

    @staticmethod
    def _is_inch_grid(jj_point3d: Sequence[NXOpen.Point3d], tolerance: float = .0001) -> str:
        """IsInchGrid - isInch is never reset, so any one distance on the grid passes."""
        if len(jj_point3d) == 0:
            raise ValueError("Value does not fall within the expected range.")
        if len(jj_point3d) == 1:
            return Result.Pass

        is_inch = False
        max_size = 72
        base_location = jj_point3d[0]

        for i in range(1, len(jj_point3d)):
            distance1 = nx.distance(base_location, jj_point3d[i])

            for j in range(1, max_size):
                if abs(distance1 - j) < tolerance:
                    is_inch = True
                    break

            if is_inch:
                continue

            for k in range(1, max_size):
                for m in range(1, max_size):
                    distance2 = math.sqrt(float(k) ** 2 + float(m) ** 2)

                    if not abs(distance1 - distance2) < tolerance:
                        continue

                    is_inch = True
                    break

                if is_inch:
                    break

        return Result.Pass if is_inch else Result.Fail

    def get_objects(self, part: NXOpen.Part) -> List[Any]:
        return [part]

    def check(self, obj: Any) -> Tuple[str, Optional[Item]]:
        part = cast(NXOpen.Part, obj)
        node = _part_node(part)

        children_positions = [nx.component_origin(component)
                              for component in nx.children(part)
                              if not component.IsSuppressed
                              and nx.is_loaded(component)
                              and nx.is_jck_screw_tsg(component.DisplayName)]

        if len(children_positions) == 0:
            node.add("Part didn't contain any valid jig jacks.")
            return Result.Ignore, node
        if len(children_positions) == 1:
            node.add("Part contains only one valid jig jack.")
            return Result.Fail, node
        return self._is_inch_grid(children_positions), node


# ---------------------------------------------------------------------------------------------------
# ThirtyPoundCheck
# ---------------------------------------------------------------------------------------------------

class ThirtyPoundCheck(Check):
    """
    Fails a part whose layer 1 solid body weighs mass_limit_pounds or more, so a detail heavy enough to need lifting
    equipment is flagged before it reaches the floor. A part with no layer 1 solid body, or more than one, is not
    measured.
    """

    # Mass, in pounds, at or above which a body is reported.
    mass_limit_pounds = 30.0

    # Relative accuracy handed to the mass properties builder, matching the BOM export.
    mass_accuracy = 0.99

    assembly_part_only = False

    def get_objects(self, part: NXOpen.Part) -> List[Any]:
        body = _solid_body_layer1_or_null(part)
        return [] if body is None else [body]

    def check(self, obj: Any) -> Tuple[str, Optional[Item]]:
        body = cast(NXOpen.Body, obj)
        pounds = self._mass_in_pounds(body)

        node = Item("{:.2f} lb".format(pounds), body)

        return (Result.Fail if pounds >= self.mass_limit_pounds else Result.Pass), node

    @classmethod
    def _mass_in_pounds(cls, body: NXOpen.Body) -> float:
        """MassInPounds: the BOM export's unit array (index 2 PoundMass) from the body's own part, PoundInch."""
        part = cast(Any, body.OwningPart)

        mass_units = [part.UnitCollection.FindObject(name)
                      for name in ("SquareInch", "CubicInch", "PoundMass", "Inch", "PoundForce")]

        measure_bodies = part.MeasureManager.NewMassProperties(mass_units, cls.mass_accuracy, [body])

        try:
            measure_bodies.InformationUnit = cast(Any, NXOpen).MeasureBodies.AnalysisUnit.PoundInch
            return float(measure_bodies.Mass)
        finally:
            measure_bodies.Dispose()

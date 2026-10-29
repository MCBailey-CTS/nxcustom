"""
Pythonic wrappers over the NXOpen object model.

Each wrapper is named after the NXOpen type with a trailing underscore - Part_, Component_, Body_, Face_, Edge_,
Curve_/Line_/Arc_/Spline_, Point_, Expression_, ReferenceSet_, the features (Feature_, Block_, Extrude_,
ExtractFace_, BooleanFeature_, DatumCsys_, ...) - and holds the NX object it wraps:

    part = Part_(session.Parts.Display)
    part.nx          # the NXOpen.Part
    part.leaf        # NXOpen.Part.Leaf
    for body in part.solid_bodies:
        print(body.color, body.layer, body.box)

Properties and methods are the lower-case (snake_case) versions of the NXOpen members, plus Python ports of the
most-used extension methods in src\\Globals.cs (Component.__Prototype -> Component_.prototype,
BasePart.__DynamicBlock -> Part_.dynamic_block, Body.__Subtract -> Body_.subtract, ...); each one's docstring
names the member it stands for. Anything not wrapped is one `.nx` away.

wrap(obj) returns the most specific wrapper for any NX object (a Line comes back as a Line_), and every
collection a wrapper returns is a list of wrappers. Wrappers compare and hash by tag, so they work in sets and
as dict keys, and wrapping the same object twice gives two equal wrappers.

The value types are wrapped too, with arithmetic: Point3d_ - Point3d_ is a Vector3d_, Point3d_ + Vector3d_ a
Point3d_, Vector3d_ has dot/cross/unit/length, Matrix3x3_ has its axes. Wherever an NXOpen value is returned it
comes back wrapped; wherever one is taken, either form is accepted.
"""

from __future__ import annotations

import math
import os
from typing import Any, Callable, Dict, Generic, Iterable, Iterator, List, Optional, Sequence, Tuple, Type, \
    TypeVar, Union, cast, overload

import NXOpen
import NXOpen.Assemblies
import NXOpen.Features
import NXOpen.UF

import tsg_nx as nx

_TO = TypeVar("_TO", bound=NXOpen.TaggedObject)
_NO = TypeVar("_NO", bound=NXOpen.NXObject)
_DO = TypeVar("_DO", bound=NXOpen.DisplayableObject)
_CU = TypeVar("_CU", bound=NXOpen.Curve)
_CS = TypeVar("_CS", bound=NXOpen.CoordinateSystem)
_BP = TypeVar("_BP", bound=NXOpen.BasePart)
_FE = TypeVar("_FE", bound=NXOpen.Features.Feature)

# A position or direction taken as an argument: an NXOpen value, its wrapper, or three numbers.
PointLike = Union["Point3d_", NXOpen.Point3d, Sequence[float]]
VectorLike = Union["Vector3d_", NXOpen.Vector3d, Sequence[float]]

_TOLERANCE = .001


# ---------------------------------------------------------------------------------------------------------------
# Value types
# ---------------------------------------------------------------------------------------------------------------

class Point3d_(object):
    """NXOpen.Point3d, immutable, with arithmetic. Point - Point is a Vector3d_; Point +/- Vector a Point3d_."""

    __slots__ = ("x", "y", "z")

    def __init__(self, x: float = 0.0, y: float = 0.0, z: float = 0.0) -> None:
        object.__setattr__(self, "x", float(x))
        object.__setattr__(self, "y", float(y))
        object.__setattr__(self, "z", float(z))

    x: float
    y: float
    z: float

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError("Point3d_ is immutable - use with_x/with_y/with_z or arithmetic")

    @staticmethod
    def of(value: PointLike) -> Point3d_:
        """Any point-like value as a Point3d_."""
        if isinstance(value, Point3d_):
            return value
        if isinstance(value, NXOpen.Point3d):
            return Point3d_(value.X, value.Y, value.Z)
        x, y, z = value
        return Point3d_(x, y, z)

    @property
    def nx(self) -> NXOpen.Point3d:
        return NXOpen.Point3d(self.x, self.y, self.z)

    def __iter__(self) -> Iterator[float]:
        return iter((self.x, self.y, self.z))

    def __repr__(self) -> str:
        return "Point3d_({:g}, {:g}, {:g})".format(self.x, self.y, self.z)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, (Point3d_, NXOpen.Point3d, tuple, list)):
            return NotImplemented
        return self.is_equal_to(cast(PointLike, other))

    def __hash__(self) -> int:
        return hash((round(self.x, 3), round(self.y, 3), round(self.z, 3)))

    @overload
    def __sub__(self, other: Point3d_) -> Vector3d_: ...
    @overload
    def __sub__(self, other: Vector3d_) -> Point3d_: ...

    def __sub__(self, other: Union[Point3d_, Vector3d_]) -> Union[Vector3d_, Point3d_]:
        if isinstance(other, Vector3d_):
            return Point3d_(self.x - other.x, self.y - other.y, self.z - other.z)
        return Vector3d_(self.x - other.x, self.y - other.y, self.z - other.z)

    def __add__(self, other: Vector3d_) -> Point3d_:
        return Point3d_(self.x + other.x, self.y + other.y, self.z + other.z)

    def add(self, x: float = 0.0, y: float = 0.0, z: float = 0.0) -> Point3d_:
        """Point3d.__Add(x, y, z)"""
        return Point3d_(self.x + x, self.y + y, self.z + z)

    def add_x(self, x: float) -> Point3d_:
        """Point3d.__AddX"""
        return self.add(x=x)

    def add_y(self, y: float) -> Point3d_:
        """Point3d.__AddY"""
        return self.add(y=y)

    def add_z(self, z: float) -> Point3d_:
        """Point3d.__AddZ"""
        return self.add(z=z)

    def add_along(self, vector: VectorLike, distance: float) -> Point3d_:
        """Point3d.__Add(Vector3d, double) - this point moved distance along vector (not normalised)."""
        v = Vector3d_.of(vector)
        return Point3d_(self.x + v.x * distance, self.y + v.y * distance, self.z + v.z * distance)

    def with_x(self, x: float) -> Point3d_:
        return Point3d_(x, self.y, self.z)

    def with_y(self, y: float) -> Point3d_:
        return Point3d_(self.x, y, self.z)

    def with_z(self, z: float) -> Point3d_:
        return Point3d_(self.x, self.y, z)

    def distance(self, other: PointLike) -> float:
        """Point3d.__Distance"""
        return (Point3d_.of(other) - self).length

    def mid_point(self, other: PointLike) -> Point3d_:
        """Point3d.__MidPoint"""
        o = Point3d_.of(other)
        return Point3d_((self.x + o.x) / 2, (self.y + o.y) / 2, (self.z + o.z) / 2)

    def is_equal_to(self, other: PointLike, tolerance: float = _TOLERANCE) -> bool:
        """Point3d.__IsEqualTo - every coordinate within tolerance."""
        o = Point3d_.of(other)
        return abs(self.x - o.x) <= tolerance and abs(self.y - o.y) <= tolerance and abs(self.z - o.z) <= tolerance

    def to_vector(self) -> Vector3d_:
        """Point3d.__ToVector - the position vector from the origin."""
        return Vector3d_(self.x, self.y, self.z)


class Vector3d_(object):
    """NXOpen.Vector3d, immutable, with arithmetic: +, -, unary -, * and / by a number, dot, cross."""

    __slots__ = ("x", "y", "z")

    def __init__(self, x: float = 0.0, y: float = 0.0, z: float = 0.0) -> None:
        object.__setattr__(self, "x", float(x))
        object.__setattr__(self, "y", float(y))
        object.__setattr__(self, "z", float(z))

    x: float
    y: float
    z: float

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError("Vector3d_ is immutable")

    @staticmethod
    def of(value: VectorLike) -> Vector3d_:
        """Any vector-like value as a Vector3d_."""
        if isinstance(value, Vector3d_):
            return value
        if isinstance(value, NXOpen.Vector3d):
            return Vector3d_(value.X, value.Y, value.Z)
        x, y, z = value
        return Vector3d_(x, y, z)

    @staticmethod
    def axis_x() -> Vector3d_:
        """Session.__VectorX"""
        return Vector3d_(1.0, 0.0, 0.0)

    @staticmethod
    def axis_y() -> Vector3d_:
        """Session.__VectorY"""
        return Vector3d_(0.0, 1.0, 0.0)

    @staticmethod
    def axis_z() -> Vector3d_:
        """Session.__VectorZ"""
        return Vector3d_(0.0, 0.0, 1.0)

    @property
    def nx(self) -> NXOpen.Vector3d:
        return NXOpen.Vector3d(self.x, self.y, self.z)

    def __iter__(self) -> Iterator[float]:
        return iter((self.x, self.y, self.z))

    def __repr__(self) -> str:
        return "Vector3d_({:g}, {:g}, {:g})".format(self.x, self.y, self.z)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, (Vector3d_, NXOpen.Vector3d, tuple, list)):
            return NotImplemented
        o = Vector3d_.of(cast(VectorLike, other))
        return abs(self.x - o.x) <= _TOLERANCE and abs(self.y - o.y) <= _TOLERANCE and abs(self.z - o.z) <= _TOLERANCE

    def __hash__(self) -> int:
        return hash((round(self.x, 3), round(self.y, 3), round(self.z, 3)))

    def __add__(self, other: Vector3d_) -> Vector3d_:
        return Vector3d_(self.x + other.x, self.y + other.y, self.z + other.z)

    def __sub__(self, other: Vector3d_) -> Vector3d_:
        return Vector3d_(self.x - other.x, self.y - other.y, self.z - other.z)

    def __neg__(self) -> Vector3d_:
        """Vector3d.__Negate"""
        return Vector3d_(-self.x, -self.y, -self.z)

    def __mul__(self, scale: float) -> Vector3d_:
        return Vector3d_(self.x * scale, self.y * scale, self.z * scale)

    __rmul__ = __mul__

    def __truediv__(self, scale: float) -> Vector3d_:
        return Vector3d_(self.x / scale, self.y / scale, self.z / scale)

    @property
    def length(self) -> float:
        """Vector3d.__Norm"""
        return math.sqrt(self.x * self.x + self.y * self.y + self.z * self.z)

    def unit(self) -> Vector3d_:
        """Vector3d.__Unit"""
        return self / self.length

    def dot(self, other: VectorLike) -> float:
        """Vector3d.__Dot"""
        o = Vector3d_.of(other)
        return self.x * o.x + self.y * o.y + self.z * o.z

    def cross(self, other: VectorLike) -> Vector3d_:
        """Vector3d.__Cross"""
        o = Vector3d_.of(other)
        return Vector3d_(self.y * o.z - self.z * o.y, self.z * o.x - self.x * o.z, self.x * o.y - self.y * o.x)

    def angle(self, other: VectorLike) -> float:
        """Vector3d.__Angle - the angle to other in degrees (0..180)."""
        cosine = self.unit().dot(Vector3d_.of(other).unit())
        return math.degrees(math.acos(max(-1.0, min(1.0, cosine))))

    def is_parallel(self, other: VectorLike, tolerance: float = _TOLERANCE) -> bool:
        """Same or opposite direction."""
        return self.unit().cross(Vector3d_.of(other).unit()).length <= tolerance

    def is_same_direction(self, other: VectorLike, tolerance: float = _TOLERANCE) -> bool:
        """Vector3d.__Equals - the unit vectors match component by component."""
        return nx.vectors_equal(self.nx, Vector3d_.of(other).nx, tolerance)

    def to_point(self) -> Point3d_:
        return Point3d_(self.x, self.y, self.z)


class Matrix3x3_(object):
    """NXOpen.Matrix3x3: rows are the X, Y and Z axes."""

    __slots__ = ("_m",)

    def __init__(self, matrix: Optional[NXOpen.Matrix3x3] = None) -> None:
        self._m = matrix if matrix is not None else nx.identity_matrix()

    @staticmethod
    def identity() -> Matrix3x3_:
        """_Matrix3x3Identity"""
        return Matrix3x3_(nx.identity_matrix())

    @staticmethod
    def from_axes(x_axis: VectorLike, y_axis: VectorLike) -> Matrix3x3_:
        """Vector3d.__ToMatrix3x3(Vector3d) - rows X, Y and Z = X x Y."""
        return Matrix3x3_(nx.matrix_from_axes(Vector3d_.of(x_axis).nx, Vector3d_.of(y_axis).nx))

    @staticmethod
    def of(value: Union[Matrix3x3_, NXOpen.Matrix3x3]) -> Matrix3x3_:
        return value if isinstance(value, Matrix3x3_) else Matrix3x3_(value)

    @property
    def nx(self) -> NXOpen.Matrix3x3:
        return self._m

    @property
    def axis_x(self) -> Vector3d_:
        """Matrix3x3.__AxisX"""
        return Vector3d_(self._m.Xx, self._m.Xy, self._m.Xz)

    @property
    def axis_y(self) -> Vector3d_:
        """Matrix3x3.__AxisY"""
        return Vector3d_(self._m.Yx, self._m.Yy, self._m.Yz)

    @property
    def axis_z(self) -> Vector3d_:
        """Matrix3x3.__AxisZ"""
        return Vector3d_(self._m.Zx, self._m.Zy, self._m.Zz)

    @property
    def rows(self) -> Tuple[Tuple[float, float, float], ...]:
        m = self._m
        return ((m.Xx, m.Xy, m.Xz), (m.Yx, m.Yy, m.Yz), (m.Zx, m.Zy, m.Zz))

    def transpose(self) -> Matrix3x3_:
        """The inverse, for a rotation matrix."""
        (a, b, c), (d, e, f), (g, h, i) = self.rows
        m = NXOpen.Matrix3x3()
        m.Xx, m.Xy, m.Xz, m.Yx, m.Yy, m.Yz, m.Zx, m.Zy, m.Zz = a, d, g, b, e, h, c, f, i
        return Matrix3x3_(m)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, (Matrix3x3_, NXOpen.Matrix3x3)):
            return NotImplemented
        o = Matrix3x3_.of(other)
        return all(abs(p - q) <= _TOLERANCE for row, other_row in zip(self.rows, o.rows) for p, q in zip(row, other_row))

    def __hash__(self) -> int:
        return hash(tuple(round(v, 3) for row in self.rows for v in row))

    def __repr__(self) -> str:
        return "Matrix3x3_(x={}, y={}, z={})".format(tuple(self.axis_x), tuple(self.axis_y), tuple(self.axis_z))


def _point(value: PointLike) -> NXOpen.Point3d:
    return Point3d_.of(value).nx


def _vector(value: VectorLike) -> NXOpen.Vector3d:
    return Vector3d_.of(value).nx


# ---------------------------------------------------------------------------------------------------------------
# Wrapping
# ---------------------------------------------------------------------------------------------------------------

# NX class -> wrapper class, filled in by @_wraps. wrap() walks the object's MRO to the first registered class.
_REGISTRY: Dict[type, type] = {}

# Typed as the bare class, not Type[TaggedObject_[...]], so a decorated generic class stays unspecialized.
_C = TypeVar("_C", bound=type)


def _wraps(nx_type: type) -> Callable[[_C], _C]:
    def register(wrapper: _C) -> _C:
        _REGISTRY[nx_type] = wrapper
        return wrapper
    return register


@overload
def wrap(obj: None) -> None: ...
@overload
def wrap(obj: NXOpen.Part) -> Part_: ...
@overload
def wrap(obj: NXOpen.Assemblies.Component) -> Component_: ...
@overload
def wrap(obj: NXOpen.Body) -> Body_: ...
@overload
def wrap(obj: NXOpen.Face) -> Face_: ...
@overload
def wrap(obj: NXOpen.Edge) -> Edge_: ...
@overload
def wrap(obj: NXOpen.Line) -> Line_: ...
@overload
def wrap(obj: NXOpen.Arc) -> Arc_: ...
@overload
def wrap(obj: NXOpen.Curve) -> Curve_[NXOpen.Curve]: ...
@overload
def wrap(obj: NXOpen.Point) -> Point_: ...
@overload
def wrap(obj: NXOpen.Expression) -> Expression_: ...
@overload
def wrap(obj: NXOpen.ReferenceSet) -> ReferenceSet_: ...
@overload
def wrap(obj: NXOpen.Features.Block) -> Block_: ...
@overload
def wrap(obj: NXOpen.Features.Feature) -> Feature_[NXOpen.Features.Feature]: ...
@overload
def wrap(obj: NXOpen.DisplayableObject) -> DisplayableObject_[NXOpen.DisplayableObject]: ...
@overload
def wrap(obj: NXOpen.NXObject) -> NXObject_[NXOpen.NXObject]: ...
@overload
def wrap(obj: NXOpen.TaggedObject) -> TaggedObject_[NXOpen.TaggedObject]: ...


def wrap(obj: Optional[NXOpen.TaggedObject]) -> Optional[TaggedObject_[Any]]:
    """The most specific wrapper for obj (a Line wraps as a Line_, a Block feature as a Block_); None for None."""
    if obj is None:
        return None
    if isinstance(obj, TaggedObject_):
        return obj
    for cls in type(obj).__mro__:
        wrapper = _REGISTRY.get(cls)
        if wrapper is not None:
            return cast(TaggedObject_[Any], wrapper(obj))
    return TaggedObject_(obj)


def wrap_all(objects: Iterable[NXOpen.TaggedObject]) -> List[Any]:
    """[wrap(o) for o in objects]"""
    return [wrap(o) for o in objects]


def _unwrap(obj: Union[TaggedObject_[_TO], _TO]) -> _TO:
    return obj.nx if isinstance(obj, TaggedObject_) else obj


def display_part() -> Part_:
    """__display_part_"""
    return Part_(nx.display_part())


def work_part() -> Part_:
    """__work_part_"""
    return Part_(nx.work_part())


def from_tag(tag: int) -> TaggedObject_[Any]:
    """The wrapped object with this tag (TaggedObjectManager.GetTaggedObject)."""
    return wrap(NXOpen.TaggedObjectManager.GetTaggedObject(tag))


# ---------------------------------------------------------------------------------------------------------------
# Object hierarchy
# ---------------------------------------------------------------------------------------------------------------

@_wraps(NXOpen.TaggedObject)
class TaggedObject_(Generic[_TO]):
    """NXOpen.TaggedObject - the wrapped object is .nx; equality and hashing go by tag."""

    __slots__ = ("_nx",)

    _nx: _TO

    def __init__(self, nx_object: _TO) -> None:
        if nx_object is None:
            raise ValueError("{} cannot wrap None".format(type(self).__name__))
        self._nx = nx_object

    @property
    def nx(self) -> _TO:
        """The NXOpen object."""
        return self._nx

    @property
    def tag(self) -> int:
        return int(self._nx.Tag)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, TaggedObject_):
            return self.tag == other.tag
        if isinstance(other, NXOpen.TaggedObject):
            return self.tag == int(other.Tag)
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self.tag)

    def __repr__(self) -> str:
        return "{}({})".format(type(self).__name__, self._describe())

    def _describe(self) -> str:
        return "tag={}".format(self.tag)

    def delete(self) -> None:
        """TaggedObject.__Delete - through the update manager's delete list."""
        mark = nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Invisible, "Delete")
        nx.session_.UpdateManager.AddObjectsToDeleteList([self._nx])
        nx.session_.UpdateManager.DoUpdate(mark)
        nx.session_.DeleteUndoMark(mark, "")


@_wraps(NXOpen.NXObject)
class NXObject_(TaggedObject_[_NO]):
    """NXOpen.NXObject - name, ownership, occurrence/prototype and string user attributes."""

    __slots__ = ()

    def _describe(self) -> str:
        name = self.name
        return repr(name) if name else "tag={}".format(self.tag)

    @property
    def name(self) -> str:
        return self._nx.Name

    @name.setter
    def name(self, value: str) -> None:
        self._nx.SetName(value)

    @property
    def journal_identifier(self) -> str:
        return self._nx.JournalIdentifier

    @property
    def owning_part(self) -> Part_:
        """NXObject.__OwningPart"""
        return Part_(cast(NXOpen.Part, self._nx.OwningPart))

    @property
    def owning_component(self) -> Optional[Component_]:
        """The component this occurrence belongs to; None for a prototype."""
        return Component_(self._nx.OwningComponent) if self._nx.IsOccurrence else None

    @property
    def is_occurrence(self) -> bool:
        return self._nx.IsOccurrence

    @property
    def prototype(self) -> NXObject_[NXOpen.NXObject]:
        """NXObject.__Prototype - the prototype of an occurrence, or this object when it is not one."""
        proto = self._nx.Prototype if self._nx.IsOccurrence else None
        return cast(NXObject_[NXOpen.NXObject], wrap(proto)) if proto is not None else cast(NXObject_[NXOpen.NXObject], self)

    # --- attributes (string user attributes, as the C# __*Attribute helpers use them) ---

    def get_attribute(self, title: str) -> str:
        """NXObject.__GetAttribute - raises when the attribute is absent."""
        return nx.get_attribute(self._nx, title)

    def get_attribute_or(self, title: str, default: str = "") -> str:
        """NXObject.__TryGetAtt - the value, or default when the attribute is absent."""
        return self.get_attribute(title) if self.has_attribute(title) else default

    def set_attribute(self, title: str, value: str) -> None:
        """NXObject.__SetAttribute"""
        nx.set_attribute(self._nx, title, value)

    def has_attribute(self, title: str) -> bool:
        """NXObject.__HasAttribute"""
        return nx.has_attribute(self._nx, title)

    def delete_attribute(self, title: str) -> None:
        """NXObject.__DeleteAttribute"""
        self._nx.DeleteUserAttribute(NXOpen.NXObject.AttributeType.String, title, True, NXOpen.Update.Option.Now)

    @property
    def attributes(self) -> Dict[str, str]:
        """NXObject.__GetAttributes - every user attribute as title -> value string."""
        return {info.Title: self._nx.GetUserAttributeAsString(info.Title, info.Type, -1)
                for info in self._nx.GetUserAttributes()}


@_wraps(NXOpen.DisplayableObject)
class DisplayableObject_(NXObject_[_DO]):
    """NXOpen.DisplayableObject - color, layer, translucency, blanking and highlighting."""

    __slots__ = ()

    @property
    def color(self) -> int:
        """DisplayableObject.__Color()"""
        return self._nx.Color

    @color.setter
    def color(self, value: int) -> None:
        """DisplayableObject.__Color(int) - sets it and redisplays."""
        self._nx.Color = value
        self._nx.RedisplayObject()

    @property
    def layer(self) -> int:
        """DisplayableObject.__Layer()"""
        return self._nx.Layer

    @layer.setter
    def layer(self, value: int) -> None:
        """DisplayableObject.__Layer(int) - sets it and redisplays."""
        self._nx.Layer = value
        self._nx.RedisplayObject()

    def set_translucency(self, value: int) -> None:
        """DisplayableObject.__Translucency(int) - 0 (opaque) to 100, through a DisplayModification.

        A setter only: NX's Python binding has no way to read it back (UF_OBJ_ask_display_properties' struct has
        no translucency field there)."""
        modification = nx.session_.DisplayManager.NewDisplayModification()
        try:
            modification.ApplyToAllFaces = True
            modification.ApplyToOwningParts = False
            modification.NewTranslucency = value
            modification.Apply([self._nx])
        finally:
            modification.Dispose()

    @property
    def is_blanked(self) -> bool:
        return self._nx.IsBlanked

    def blank(self) -> None:
        self._nx.Blank()

    def unblank(self) -> None:
        self._nx.Unblank()

    def highlight(self) -> None:
        self._nx.Highlight()

    def unhighlight(self) -> None:
        self._nx.Unhighlight()

    def redisplay(self) -> None:
        """DisplayableObject.__RedisplayObject"""
        self._nx.RedisplayObject()


# ---------------------------------------------------------------------------------------------------------------
# Parts
# ---------------------------------------------------------------------------------------------------------------

@_wraps(NXOpen.BasePart)
class BasePart_(NXObject_[_BP]):
    """NXOpen.BasePart - file, units, features, expressions, reference sets and the assembly tree."""

    __slots__ = ()

    def _describe(self) -> str:
        return repr(self.leaf)

    # --- file ---

    @property
    def leaf(self) -> str:
        """NXOpen.BasePart.Leaf - the file name without folder or extension."""
        return self._nx.Leaf

    @property
    def full_path(self) -> str:
        return self._nx.FullPath

    @property
    def dir(self) -> str:
        """The folder the part is saved in. (BasePart.__Dir returns the *display* part's folder; this doesn't.)"""
        return os.path.dirname(self._nx.FullPath)

    @property
    def is_modified(self) -> bool:
        return self._nx.IsModified

    @property
    def is_inches(self) -> bool:
        return self._nx.PartUnits == NXOpen.BasePart.Units.Inches

    @property
    def is_millimeters(self) -> bool:
        return self._nx.PartUnits == NXOpen.BasePart.Units.Millimeters

    def save(self, save_components: bool = False) -> None:
        """BasePart.__Save"""
        status = self._nx.Save(
            NXOpen.BasePart.SaveComponents.TrueValue if save_components else NXOpen.BasePart.SaveComponents.FalseValue,
            NXOpen.BasePart.CloseAfterSave.FalseValue)
        status.Dispose()

    def close(self, whole_tree: bool = False) -> None:
        """Closes the part, modified or not."""
        self._nx.Close(
            NXOpen.BasePart.CloseWholeTree.TrueValue if whole_tree else NXOpen.BasePart.CloseWholeTree.FalseValue,
            NXOpen.BasePart.CloseModified.CloseModified, None)

    # --- display / work ---

    @property
    def is_display_part(self) -> bool:
        display = nx.session_.Parts.Display
        return display is not None and display.Tag == self._nx.Tag

    @property
    def is_work_part(self) -> bool:
        work = nx.session_.Parts.Work
        return work is not None and work.Tag == self._nx.Tag

    def make_display_part(self) -> None:
        """__display_part_ = part"""
        nx.set_display_part(self._nx)

    def make_work_part(self) -> None:
        """__work_part_ = part"""
        nx.set_work_part(self._nx)

    # --- features ---

    @property
    def features(self) -> List[Feature_[NXOpen.Features.Feature]]:
        return [cast(Feature_[NXOpen.Features.Feature], wrap(f)) for f in self._nx.Features.GetFeatures()]

    def features_of_type(self, feature_type: Type[_FE]) -> List[_FE]:
        """The part's features that are feature_type (an NXOpen.Features class), unwrapped."""
        return [f for f in self._nx.Features.GetFeatures() if isinstance(f, feature_type)]

    @property
    def dynamic_block(self) -> Block_:
        """BasePart.__DynamicBlock - the block feature named DYNAMIC BLOCK; raises when there is none."""
        return Block_(nx.dynamic_block(self._nx))

    @property
    def dynamic_block_or_none(self) -> Optional[Block_]:
        """BasePart.__DynamicBlockOrNull"""
        return self.dynamic_block if self.has_dynamic_block else None

    @property
    def has_dynamic_block(self) -> bool:
        """BasePart.__HasDynamicBlock"""
        return any(f.Name == "DYNAMIC BLOCK" for f in self.features_of_type(NXOpen.Features.Block))

    @property
    def absolute_datum_csys(self) -> DatumCsys_:
        """BasePart.__AbsoluteDatumCsys - the part's first datum csys feature."""
        csys = self.features_of_type(NXOpen.Features.DatumCsys)
        if not csys:
            raise RuntimeError("{} has no datum csys".format(self.leaf))
        return DatumCsys_(csys[0])

    # --- expressions ---

    @property
    def expressions(self) -> List[Expression_]:
        return [Expression_(e) for e in self._nx.Expressions]

    def find_expression(self, name: str) -> Expression_:
        """BasePart.__FindExpression - case-insensitive; raises when absent."""
        expression = self.find_expression_or_none(name)
        if expression is None:
            raise KeyError("No expression named {!r} in {}".format(name, self.leaf))
        return expression

    def find_expression_or_none(self, name: str) -> Optional[Expression_]:
        """BasePart.__FindExpressionOrNull"""
        expression = nx.find_expression_or_null(self._nx, name)
        return Expression_(expression) if expression is not None else None

    def create_expression(self, equation: str, units: Optional[str] = None) -> Expression_:
        """A number expression from "name=rhs", in units (a UnitCollection name: "Inch", "MilliMeter") or none."""
        unit = self._nx.UnitCollection.FindObject(units) if units else None
        return Expression_(self._nx.Expressions.CreateWithUnits(equation, unit))

    # --- reference sets ---

    @property
    def reference_sets(self) -> List[ReferenceSet_]:
        return [ReferenceSet_(r) for r in self._nx.GetAllReferenceSets()]

    @property
    def reference_set_names(self) -> List[str]:
        """Part.__GetAllReferenceSetNames"""
        return nx.reference_set_names(self._nx)

    def find_reference_set(self, name: str) -> ReferenceSet_:
        """BasePart.__FindReferenceSet - raises when absent."""
        refset = self.find_reference_set_or_none(name)
        if refset is None:
            raise KeyError("No reference set named {!r} in {}".format(name, self.leaf))
        return refset

    def find_reference_set_or_none(self, name: str) -> Optional[ReferenceSet_]:
        """BasePart.__FindReferenceSetOrNull"""
        refset = nx.find_reference_set_or_null(self._nx, name)
        return ReferenceSet_(refset) if refset is not None else None

    def has_reference_set(self, name: str) -> bool:
        """BasePart.__HasReferenceSet"""
        return nx.has_reference_set(self._nx, name)

    def find_or_create_reference_set(self, name: str) -> ReferenceSet_:
        """Merlin.FindOrCreateReferenceSet"""
        return ReferenceSet_(nx.find_or_create_reference_set(self._nx, name))

    # --- assembly ---

    @property
    def root_component(self) -> Optional[Component_]:
        """BasePart.__RootComponentOrNull - None for a piece part."""
        root = nx.root_component(self._nx)
        return Component_(root) if root is not None else None

    @property
    def is_assembly(self) -> bool:
        return self.root_component is not None

    @property
    def children(self) -> List[Component_]:
        """BasePart.__Children - the root component's direct children; [] for a piece part."""
        root = self.root_component
        return root.children if root is not None else []

    def descendants(self, include_root: bool = True, include_suppressed: bool = False,
                    include_unloaded: bool = False) -> List[Component_]:
        """Component.__Descendants of the root component; [] for a piece part."""
        root = self.root_component
        return root.descendants(include_root, include_suppressed, include_unloaded) if root is not None else []

    @property
    def descendant_parts(self) -> List[Part_]:
        """BasePart.__DescendantParts - this part and every loaded part under it, each once."""
        parts: Dict[int, Part_] = {self.tag: Part_(cast(NXOpen.Part, self._nx))}
        for component in self.descendants(include_root=False):
            proto = component.prototype_or_none
            if proto is not None:
                parts.setdefault(proto.tag, proto)
        return list(parts.values())

    def add_component(self, path_or_prototype: Union[str, BasePart_[Any], NXOpen.BasePart],
                      reference_set: str = "Entire Part", component_name: Optional[str] = None,
                      origin: Optional[PointLike] = None, orientation: Optional[Matrix3x3_] = None,
                      layer: int = 1) -> Component_:
        """BasePart.__AddComponent - a path is opened when it isn't loaded already."""
        proto = path_or_prototype.nx if isinstance(path_or_prototype, BasePart_) else path_or_prototype
        return Component_(nx.add_component(
            self._nx, proto, reference_set, component_name,
            _point(origin) if origin is not None else None,
            orientation.nx if orientation is not None else None,
            layer))

    def occurrences_in(self, assembly: Union[BasePart_[Any], NXOpen.BasePart]) -> List[Component_]:
        """Merlin.OccurrencesOfPartIn - every occurrence of this part anywhere inside assembly."""
        return [Component_(c) for c in nx.occurrences_of_part_in(_unwrap(assembly), self._nx)]

    def first_occurrence_in(self, assembly: Union[BasePart_[Any], NXOpen.BasePart]) -> Component_:
        """Part.__FirstOccurrenceIn"""
        return self.occurrences_in(assembly)[0]


@_wraps(NXOpen.Part)
class Part_(BasePart_[NXOpen.Part]):
    """NXOpen.Part - a BasePart_ plus its bodies, curves, points and datums."""

    __slots__ = ()

    @property
    def bodies(self) -> List[Body_]:
        return [Body_(b) for b in self._nx.Bodies]

    @property
    def solid_bodies(self) -> List[Body_]:
        return [b for b in self.bodies if b.is_solid]

    def solid_bodies_on_layer(self, layer: int) -> List[Body_]:
        return [b for b in self.solid_bodies if b.layer == layer]

    @property
    def single_solid_body_on_layer1(self) -> Body_:
        """BasePart.__SingleSolidBodyOnLayer1 - raises unless there is exactly one."""
        bodies = self.solid_bodies_on_layer(1)
        if len(bodies) != 1:
            raise RuntimeError("{} has {} solid bodies on layer 1, expected 1".format(self.leaf, len(bodies)))
        return bodies[0]

    @property
    def solid_body_on_layer1_or_none(self) -> Optional[Body_]:
        """BasePart.__SolidBodyLayer1OrNull - None unless there is exactly one."""
        bodies = self.solid_bodies_on_layer(1)
        return bodies[0] if len(bodies) == 1 else None

    @property
    def dynamic_block_body(self) -> Body_:
        """BasePart.__DynamicBlockBody"""
        return self.dynamic_block.bodies[0]

    @property
    def curves(self) -> List[Curve_[NXOpen.Curve]]:
        return [cast(Curve_[NXOpen.Curve], wrap(c)) for c in self._nx.Curves]

    @property
    def lines(self) -> List[Line_]:
        return [Line_(c) for c in self._nx.Curves if isinstance(c, NXOpen.Line)]

    @property
    def arcs(self) -> List[Arc_]:
        return [Arc_(c) for c in self._nx.Curves if isinstance(c, NXOpen.Arc)]

    @property
    def points(self) -> List[Point_]:
        return [Point_(p) for p in self._nx.Points]

    @property
    def datum_planes(self) -> List[DatumPlane_]:
        return [DatumPlane_(d) for d in self._nx.Datums if isinstance(d, NXOpen.DatumPlane)]

    @property
    def datum_axes(self) -> List[DatumAxis_]:
        return [DatumAxis_(d) for d in self._nx.Datums if isinstance(d, NXOpen.DatumAxis)]

    def create_point(self, point: PointLike) -> Point_:
        """BasePart.__CreatePoint"""
        return Point_(self._nx.Points.CreatePoint(_point(point)))

    @overload
    def create_line(self, start: PointLike, end: PointLike) -> Line_: ...
    @overload
    def create_line(self, x1: float, y1: float, z1: float, x2: float, y2: float, z2: float) -> Line_: ...

    def create_line(self, *args: Any, **kwargs: Any) -> Line_:
        """
        BasePart.__CreateLine - Curves.CreateLine from start to end, given as two points or as six numbers:
        create_line(x1, y1, z1, x2, y2, z2).
        """
        # Keyword arguments, by either overload's names, join the positional ones in order.
        for names in (("start", "end"), ("x1", "y1", "z1", "x2", "y2", "z2")):
            if any(name in kwargs for name in names):
                args += tuple(kwargs.pop(name) for name in names[len(args):] if name in kwargs)

        if kwargs:
            raise TypeError("create_line got unexpected keyword argument(s) {}".format(", ".join(kwargs)))

        if len(args) == 6:
            start, end = NXOpen.Point3d(*map(float, args[:3])), NXOpen.Point3d(*map(float, args[3:]))
        elif len(args) == 2:
            start, end = _point(args[0]), _point(args[1])
        else:
            raise TypeError("create_line takes two points or six numbers, got {} argument(s)".format(len(args)))

        return Line_(self._nx.Curves.CreateLine(start, end))

    def fit(self) -> None:
        """BasePart.__Fit - fits the work view."""
        self._nx.ModelingViews.WorkView.Fit()


# ---------------------------------------------------------------------------------------------------------------
# Assemblies
# ---------------------------------------------------------------------------------------------------------------

@_wraps(NXOpen.Assemblies.Component)
class Component_(DisplayableObject_[NXOpen.Assemblies.Component]):
    """NXOpen.Assemblies.Component - prototype, reference set, position and the assembly tree around it."""

    __slots__ = ()

    def _describe(self) -> str:
        return repr(self.display_name)

    @property
    def display_name(self) -> str:
        return self._nx.DisplayName

    @property
    def is_loaded(self) -> bool:
        """Component.__IsLoaded"""
        return nx.is_loaded(self._nx)

    @property
    def prototype(self) -> Part_:  # type: ignore[override]
        """Component.__Prototype - the part this component is an occurrence of; raises when it is not loaded."""
        if not self.is_loaded:
            raise RuntimeError("{} is not loaded".format(self.display_name))
        return Part_(cast(NXOpen.Part, self._nx.Prototype))

    @property
    def prototype_or_none(self) -> Optional[Part_]:
        return self.prototype if self.is_loaded else None

    @property
    def reference_set(self) -> str:
        return self._nx.ReferenceSet

    @reference_set.setter
    def reference_set(self, name: str) -> None:
        """Component.__ReferenceSet(string) - raises for a reference set the prototype doesn't have."""
        nx.set_reference_set(self._nx, name)

    @property
    def origin(self) -> Point3d_:
        """Component.__Origin"""
        return Point3d_.of(nx.component_origin(self._nx))

    @property
    def orientation(self) -> Matrix3x3_:
        """Component.__Orientation"""
        return Matrix3x3_(nx.component_orientation(self._nx))

    def move(self, translation: VectorLike = (0.0, 0.0, 0.0), rotation: Optional[Matrix3x3_] = None) -> None:
        """ComponentAssembly.MoveComponent in the owning assembly - by translation, then rotation (identity)."""
        self._nx.DirectOwner.MoveComponent(
            self._nx, _vector(translation), (rotation or Matrix3x3_.identity()).nx)

    # --- tree ---

    @property
    def parent(self) -> Optional[Component_]:
        parent = self._nx.Parent
        return Component_(parent) if parent is not None else None

    @property
    def is_root(self) -> bool:
        """Component.__IsRoot"""
        return self._nx.Parent is None

    @property
    def children(self) -> List[Component_]:
        return [Component_(c) for c in self._nx.GetChildren()]

    @property
    def is_leaf(self) -> bool:
        """Component.__IsLeaf - no children."""
        return len(self._nx.GetChildren()) == 0

    def descendants(self, include_root: bool = True, include_suppressed: bool = False,
                    include_unloaded: bool = False) -> List[Component_]:
        """Component.__Descendants - depth first, this component first."""
        return [Component_(c) for c in nx.descendants(self._nx, include_root, include_suppressed, include_unloaded)]

    @property
    def assembly_path(self) -> List[Component_]:
        """Component._AssemblyPath - the root first, this component last."""
        path: List[Component_] = []
        component: Optional[Component_] = self
        while component is not None:
            path.insert(0, component)
            component = component.parent
        return path

    @property
    def assembly_path_string(self) -> str:
        """Component.__AssemblyPathString - the display names root to here."""
        return " / ".join(c.display_name for c in self.assembly_path)

    @property
    def is_suppressed(self) -> bool:
        return self._nx.IsSuppressed

    def suppress(self) -> None:
        self._nx.Suppress()

    def unsuppress(self) -> None:
        self._nx.Unsuppress()

    # --- members ---

    @property
    def members(self) -> List[NXObject_[NXOpen.NXObject]]:
        """Component.__Members - every object in this occurrence."""
        return [cast(NXObject_[NXOpen.NXObject], wrap(m)) for m in nx.members(self._nx)]

    @property
    def solid_body_members(self) -> List[Body_]:
        """Component.__SolidBodyMembers"""
        return [Body_(b) for b in nx.solid_body_members(self._nx)]

    def find_occurrence(self, proto: Union[TaggedObject_[Any], NXOpen.TaggedObject]) -> Optional[NXObject_[Any]]:
        """Component.__FindOccurrence - proto's occurrence in this component; None when there is none."""
        found = self._nx.FindOccurrence(_unwrap(proto))
        return cast(Optional[NXObject_[Any]], wrap(found))

    # --- instance attributes ---

    def get_instance_attribute(self, title: str) -> str:
        """The string instance user attribute; raises when absent."""
        return self._nx.GetInstanceUserAttributeAsString(title, NXOpen.NXObject.AttributeType.String, -1)

    def set_instance_attribute(self, title: str, value: str) -> None:
        """Component.SetInstanceUserAttribute (string)"""
        self._nx.SetInstanceUserAttribute(title, -1, value, NXOpen.Update.Option.Now)

    def has_instance_attribute(self, title: str) -> bool:
        return self._nx.HasInstanceUserAttribute(title, NXOpen.NXObject.AttributeType.String, -1)

    def delete_instance_attribute(self, title: str) -> None:
        """Component.__DeleteInstanceUserAttribute"""
        self._nx.DeleteInstanceUserAttribute(NXOpen.NXObject.AttributeType.String, title, True, NXOpen.Update.Option.Now)

    # --- name predicates ---

    @property
    def is_shcs(self) -> bool:
        """Component.__IsShcs"""
        return nx.is_shcs(self.display_name)

    @property
    def is_dwl(self) -> bool:
        """Component.__IsDwl"""
        return nx.is_dwl(self.display_name)

    @property
    def is_jck_screw(self) -> bool:
        """Component.__IsJckScrew"""
        return nx.is_jck_screw(self.display_name)

    @property
    def is_jck_screw_tsg(self) -> bool:
        """Component.__IsJckScrewTsg"""
        return nx.is_jck_screw_tsg(self.display_name)

    @property
    def is_fastener(self) -> bool:
        """Component.__IsFastener - a SHCS, dowel or jack screw by name."""
        return self.is_shcs or self.is_dwl or self.is_jck_screw or self.is_jck_screw_tsg

    # --- wave links ---

    def create_linked_body(self) -> ExtractFace_:
        """Component.__CreateLinkedBody - one linked body of this component's solids, in the work part."""
        return ExtractFace_(cast(NXOpen.Features.ExtractFace, nx.create_linked_body(self._nx)))

    def create_linked_bodies(self) -> List[ExtractFace_]:
        """Component.__CreateLinkedBodies - one linked body per solid, in the work part."""
        return [ExtractFace_(f) for f in nx.create_linked_bodies(self._nx)]

    def set_as_work_component(self) -> None:
        """__work_component_ = component"""
        nx.set_work_component(self._nx)


# ---------------------------------------------------------------------------------------------------------------
# Solids
# ---------------------------------------------------------------------------------------------------------------

@_wraps(NXOpen.Body)
class Body_(DisplayableObject_[NXOpen.Body]):
    """NXOpen.Body - faces, edges, bounding box and booleans."""

    __slots__ = ()

    @property
    def is_solid(self) -> bool:
        return self._nx.IsSolidBody

    @property
    def is_sheet(self) -> bool:
        return self._nx.IsSheetBody

    @property
    def faces(self) -> List[Face_]:
        return [Face_(f) for f in self._nx.GetFaces()]

    @property
    def edges(self) -> List[Edge_]:
        return [Edge_(e) for e in self._nx.GetEdges()]

    @property
    def features(self) -> List[Feature_[NXOpen.Features.Feature]]:
        return [cast(Feature_[NXOpen.Features.Feature], wrap(f)) for f in self._nx.GetFeatures()]

    @property
    def box(self) -> nx.Box3d:
        """Body.__Box3d - the exact bounding box in absolute coordinates."""
        return nx.body_box(self._nx)

    @property
    def density(self) -> float:
        return self._nx.Density

    # --- faces by direction ---

    def faces_with_normal(self, normal: VectorLike) -> List[Face_]:
        """Body.__FacesWithVector - the planar faces whose normal is normal."""
        return [Face_(f) for f in nx.faces_with_vector(self._nx, _vector(normal))]

    def planar_face_with_normal_or_none(self, normal: VectorLike) -> Optional[Face_]:
        """Body.__PlanarFaceWithNormalOrNull"""
        face = nx.planar_face_with_normal_or_null(self._nx, _vector(normal))
        return Face_(face) if face is not None else None

    def single_face_with_normal(self, normal: VectorLike) -> Face_:
        """Body.__SinglePosZFace and friends - raises unless exactly one planar face has that normal."""
        faces = self.faces_with_normal(normal)
        if len(faces) != 1:
            raise RuntimeError("{} planar faces with normal {}, expected 1".format(len(faces), Vector3d_.of(normal)))
        return faces[0]

    @property
    def single_pos_z_face(self) -> Face_:
        """Body.__SinglePosZFace"""
        return self.single_face_with_normal((0.0, 0.0, 1.0))

    @property
    def single_neg_z_face(self) -> Face_:
        """Body.__SingleNegZFace"""
        return self.single_face_with_normal((0.0, 0.0, -1.0))

    @property
    def vertical_edges(self) -> List[Edge_]:
        """Body.__VerticalEdges - linear edges parallel to Z."""
        return [e for e in self.edges if e.is_linear and e.direction.is_parallel(Vector3d_.axis_z())]

    def horizontal_edges_at_z(self, z: float) -> List[Edge_]:
        """Body.__HorizontalEdgesAtZ - edges with both ends at z."""
        return [e for e in self.edges
                if abs(e.start_point.z - z) <= _TOLERANCE and abs(e.end_point.z - z) <= _TOLERANCE]

    # --- booleans ---

    def subtract(self, *tools: Union[Body_, NXOpen.Body]) -> BooleanFeature_:
        """Body.__Subtract - in the work part."""
        return BooleanFeature_(nx.subtract(self._nx, [_unwrap(t) for t in tools]))

    def unite(self, *tools: Union[Body_, NXOpen.Body]) -> BooleanFeature_:
        """Body.__Unite - in the work part."""
        return BooleanFeature_(nx.create_boolean(
            self._nx, [_unwrap(t) for t in tools], NXOpen.Features.Feature.BooleanType.Unite))

    def intersect(self, *tools: Union[Body_, NXOpen.Body]) -> BooleanFeature_:
        """Body.__Intersect - in the work part."""
        return BooleanFeature_(nx.create_boolean(
            self._nx, [_unwrap(t) for t in tools], NXOpen.Features.Feature.BooleanType.Intersect))

    def interferes_with(self, component: Union[Component_, NXOpen.Assemblies.Component]) -> bool:
        """Body.__InterferesWith(Component) - UF_MODL_check_interference against its solid bodies."""
        return nx.interferes_with(self._nx, _unwrap(component))


# UF_MODL_ask_face_data face types.
_UF_FACE_CYLINDRICAL = 16
_UF_FACE_CONICAL = 17
_UF_FACE_SPHERICAL = 18


@_wraps(NXOpen.Face)
class Face_(DisplayableObject_[NXOpen.Face]):
    """NXOpen.Face - type, normal, edges and owning body."""

    __slots__ = ()

    @property
    def face_type(self) -> NXOpen.Face.FaceType:
        return self._nx.SolidFaceType

    @property
    def is_planar(self) -> bool:
        """Face.__IsPlanar"""
        return self._nx.SolidFaceType == NXOpen.Face.FaceType.Planar

    @property
    def is_cylindrical(self) -> bool:
        return self._nx.SolidFaceType == NXOpen.Face.FaceType.Cylindrical

    @property
    def normal(self) -> Vector3d_:
        """Face.__Normal - the unit normal of a planar face; raises for any other face."""
        return Vector3d_.of(nx.face_normal(self._nx))

    @property
    def radius(self) -> float:
        """Face.__CylinderRadius - for a cylindrical, conical or spherical face (UF_MODL_ask_face_data)."""
        face_type, _point, _dir, _box, radius, _rad_data, _norm_dir = nx.ufsession_.Modeling.AskFaceData(self.tag)
        if face_type not in (_UF_FACE_CYLINDRICAL, _UF_FACE_CONICAL, _UF_FACE_SPHERICAL):
            raise RuntimeError("Face type {} has no radius".format(face_type))
        return float(radius)

    @property
    def edges(self) -> List[Edge_]:
        return [Edge_(e) for e in self._nx.GetEdges()]

    @property
    def body(self) -> Body_:
        return Body_(self._nx.GetBody())

    @property
    def edge_positions(self) -> List[Point3d_]:
        """Face.__EdgePositions - every edge's start and end, each once."""
        points: List[Point3d_] = []
        for edge in self.edges:
            for p in (edge.start_point, edge.end_point):
                if not any(p.is_equal_to(q) for q in points):
                    points.append(p)
        return points


@_wraps(NXOpen.Edge)
class Edge_(DisplayableObject_[NXOpen.Edge]):
    """NXOpen.Edge - end points, length, type and its faces/body."""

    __slots__ = ()

    @property
    def edge_type(self) -> NXOpen.Edge.EdgeType:
        return self._nx.SolidEdgeType

    @property
    def is_linear(self) -> bool:
        return self._nx.SolidEdgeType == NXOpen.Edge.EdgeType.Linear

    @property
    def is_circular(self) -> bool:
        return self._nx.SolidEdgeType == NXOpen.Edge.EdgeType.Circular

    @property
    def start_point(self) -> Point3d_:
        """Edge.__StartPoint - the first vertex."""
        return Point3d_.of(self._nx.GetVertices()[0])

    @property
    def end_point(self) -> Point3d_:
        """Edge.__EndPoint - the second vertex (the first again for a closed edge)."""
        return Point3d_.of(self._nx.GetVertices()[1])

    @property
    def mid_point(self) -> Point3d_:
        """Edge.__MidPoint - the point at the middle of the parameter range."""
        return Point3d_.of(nx.curve_mid_point(cast(NXOpen.Curve, self._nx)))

    @property
    def direction(self) -> Vector3d_:
        """Start to end, as a unit vector (meaningful for a linear edge)."""
        return (self.end_point - self.start_point).unit()

    @property
    def length(self) -> float:
        return self._nx.GetLength()

    def has_end_points(self, p1: PointLike, p2: PointLike) -> bool:
        """Edge.__HasEndPoints - its ends are p1 and p2, either way round."""
        a, b = Point3d_.of(p1), Point3d_.of(p2)
        s, e = self.start_point, self.end_point
        return (s.is_equal_to(a) and e.is_equal_to(b)) or (s.is_equal_to(b) and e.is_equal_to(a))

    @property
    def faces(self) -> List[Face_]:
        return [Face_(f) for f in self._nx.GetFaces()]

    @property
    def body(self) -> Body_:
        return Body_(self._nx.GetBody())

    def to_curve(self) -> Curve_[NXOpen.Curve]:
        """Edge.__ToCurve - a curve copied from the edge, in the work part."""
        return cast(Curve_[NXOpen.Curve], wrap(nx.edge_to_curve(self._nx)))


# ---------------------------------------------------------------------------------------------------------------
# Curves and points
# ---------------------------------------------------------------------------------------------------------------

@_wraps(NXOpen.Curve)
class Curve_(DisplayableObject_[_CU]):
    """NXOpen.Curve - length and evaluated points. Line_, Arc_ and Spline_ add their own members."""

    __slots__ = ()

    @property
    def length(self) -> float:
        return self._nx.GetLength()

    @property
    def is_reference(self) -> bool:
        return self._nx.IsReference

    def _evaluate(self, fraction: float) -> Point3d_:
        """The point at fraction (0..1) of the parameter range, through UF_EVAL."""
        evaluator = nx.ufsession_.Eval.Initialize2(self.tag)
        low, high = nx.ufsession_.Eval.AskLimits(evaluator)
        point = nx.ufsession_.Eval.EvaluateUnitVectors(evaluator, low + (high - low) * fraction)[0]
        return Point3d_(point[0], point[1], point[2])

    @property
    def start_point(self) -> Point3d_:
        """Curve.__StartPoint"""
        return self._evaluate(0.0)

    @property
    def end_point(self) -> Point3d_:
        """Curve.__EndPoint"""
        return self._evaluate(1.0)

    @property
    def mid_point(self) -> Point3d_:
        """Curve.__MidPoint"""
        return self._evaluate(0.5)

    def point_at(self, fraction: float) -> Point3d_:
        """Curve.__Position - the point at fraction (0..1) of the parameter range."""
        return self._evaluate(fraction)

    @property
    def is_closed(self) -> bool:
        """Curve.__IsClosed - start and end coincide."""
        return self.start_point.is_equal_to(self.end_point)


@_wraps(NXOpen.Line)
class Line_(Curve_[NXOpen.Line]):
    """NXOpen.Line"""

    __slots__ = ()

    @property
    def start_point(self) -> Point3d_:
        return Point3d_.of(self._nx.StartPoint)

    @start_point.setter
    def start_point(self, value: PointLike) -> None:
        self._nx.SetStartPoint(_point(value))

    @property
    def end_point(self) -> Point3d_:
        return Point3d_.of(self._nx.EndPoint)

    @end_point.setter
    def end_point(self, value: PointLike) -> None:
        self._nx.SetEndPoint(_point(value))

    def set_end_points(self, start: PointLike, end: PointLike) -> None:
        """Line.SetEndpoints"""
        self._nx.SetEndpoints(_point(start), _point(end))

    @property
    def direction(self) -> Vector3d_:
        """Line.__Vector - start to end, as a unit vector."""
        return (self.end_point - self.start_point).unit()

    @property
    def is_closed(self) -> bool:
        return False


@_wraps(NXOpen.Arc)
class Arc_(Curve_[NXOpen.Arc]):
    """NXOpen.Arc - centre, radius and angles (radians) in the arc's own orientation."""

    __slots__ = ()

    @property
    def center(self) -> Point3d_:
        """Arc.__CenterPoint"""
        return Point3d_.of(self._nx.CenterPoint)

    @property
    def radius(self) -> float:
        """Arc.__Radius"""
        return self._nx.Radius

    @radius.setter
    def radius(self, value: float) -> None:
        self._nx.SetRadius(value)

    @property
    def diameter(self) -> float:
        return self._nx.Radius * 2

    @property
    def start_angle(self) -> float:
        """Radians."""
        return self._nx.StartAngle

    @property
    def end_angle(self) -> float:
        """Arc.__EndAngle - radians."""
        return self._nx.EndAngle

    @property
    def sweep_angle(self) -> float:
        """end_angle - start_angle, radians."""
        return self._nx.EndAngle - self._nx.StartAngle

    @property
    def orientation(self) -> Matrix3x3_:
        """Arc.__Orientation"""
        return Matrix3x3_(self._nx.Matrix.Element)

    @property
    def normal(self) -> Vector3d_:
        """The axis the arc turns about (its orientation's Z)."""
        return self.orientation.axis_z

    @property
    def is_closed(self) -> bool:
        """Arc.__IsClosed - a full circle."""
        return abs(self.sweep_angle) >= 2 * math.pi - 1e-9


@_wraps(NXOpen.Spline)
class Spline_(Curve_[NXOpen.Spline]):
    """NXOpen.Spline"""

    __slots__ = ()


@_wraps(NXOpen.Point)
class Point_(DisplayableObject_[NXOpen.Point]):
    """NXOpen.Point - the point object (see Point3d_ for the value)."""

    __slots__ = ()

    @property
    def coordinates(self) -> Point3d_:
        return Point3d_.of(self._nx.Coordinates)

    @coordinates.setter
    def coordinates(self, value: PointLike) -> None:
        self._nx.SetCoordinates(_point(value))

    @property
    def x(self) -> float:
        return self._nx.Coordinates.X

    @property
    def y(self) -> float:
        return self._nx.Coordinates.Y

    @property
    def z(self) -> float:
        return self._nx.Coordinates.Z

    def move(self, vector: VectorLike, distance: float = 1.0) -> None:
        """Point.__Move - by vector * distance."""
        self.coordinates = self.coordinates.add_along(vector, distance)


# ---------------------------------------------------------------------------------------------------------------
# Coordinate systems and datums
# ---------------------------------------------------------------------------------------------------------------

@_wraps(NXOpen.CoordinateSystem)
class CoordinateSystem_(DisplayableObject_[_CS]):
    """NXOpen.CoordinateSystem - origin and axes."""

    __slots__ = ()

    @property
    def origin(self) -> Point3d_:
        """CoordinateSystem.__Origin"""
        return Point3d_.of(self._nx.Origin)

    @property
    def orientation(self) -> Matrix3x3_:
        """CoordinateSystem.__Orientation"""
        return Matrix3x3_(self._nx.Orientation.Element)

    @property
    def axis_x(self) -> Vector3d_:
        """CoordinateSystem.__AxisX"""
        return self.orientation.axis_x

    @property
    def axis_y(self) -> Vector3d_:
        """CoordinateSystem.__AxisY"""
        return self.orientation.axis_y

    @property
    def axis_z(self) -> Vector3d_:
        """CoordinateSystem.__AxisZ"""
        return self.orientation.axis_z

    def set_directions(self, x_axis: VectorLike, y_axis: VectorLike) -> None:
        """CoordinateSystem.__Orientation(Vector3d, Vector3d)"""
        self._nx.SetDirections(_vector(x_axis), _vector(y_axis))


@_wraps(NXOpen.CartesianCoordinateSystem)
class CartesianCoordinateSystem_(CoordinateSystem_[NXOpen.CartesianCoordinateSystem]):
    """NXOpen.CartesianCoordinateSystem"""

    __slots__ = ()


@_wraps(NXOpen.DatumPlane)
class DatumPlane_(DisplayableObject_[NXOpen.DatumPlane]):
    """NXOpen.DatumPlane - origin, normal and the feature that owns it."""

    __slots__ = ()

    @property
    def origin(self) -> Point3d_:
        return Point3d_.of(self._nx.Origin)

    @property
    def normal(self) -> Vector3d_:
        return Vector3d_.of(self._nx.Normal)

    @property
    def feature(self) -> Feature_[NXOpen.Features.Feature]:
        return cast(Feature_[NXOpen.Features.Feature], wrap(self._nx.Feature))


@_wraps(NXOpen.DatumAxis)
class DatumAxis_(DisplayableObject_[NXOpen.DatumAxis]):
    """NXOpen.DatumAxis - origin, direction and the feature that owns it."""

    __slots__ = ()

    @property
    def origin(self) -> Point3d_:
        """DatumAxis.__Origin"""
        return Point3d_.of(self._nx.Origin)

    @property
    def direction(self) -> Vector3d_:
        """DatumAxis.__Direction"""
        return Vector3d_.of(self._nx.Direction)

    @property
    def feature(self) -> Feature_[NXOpen.Features.Feature]:
        return cast(Feature_[NXOpen.Features.Feature], wrap(self._nx.Feature))


# ---------------------------------------------------------------------------------------------------------------
# Expressions and reference sets
# ---------------------------------------------------------------------------------------------------------------

@_wraps(NXOpen.Expression)
class Expression_(NXObject_[NXOpen.Expression]):
    """NXOpen.Expression - name, value and right-hand side."""

    __slots__ = ()

    def _describe(self) -> str:
        return "{} = {}".format(self.name, self.right_hand_side)

    @property
    def value(self) -> float:
        """The number value, in the expression's units."""
        return self._nx.Value

    @value.setter
    def value(self, value: float) -> None:
        self._nx.RightHandSide = nx.cs_double_str(value)

    @property
    def right_hand_side(self) -> str:
        return self._nx.RightHandSide

    @right_hand_side.setter
    def right_hand_side(self, value: str) -> None:
        self._nx.RightHandSide = value

    @property
    def equation(self) -> str:
        """name=rhs"""
        return self._nx.Equation

    @property
    def type(self) -> str:
        """"Number", "String", "Boolean", "Integer", "Point", "Vector", "List"."""
        return self._nx.Type

    @property
    def string_value(self) -> str:
        """For a String expression."""
        return self._nx.StringValue

    @property
    def units(self) -> Optional[str]:
        """The unit's name ("Inch", "MilliMeter", ...); None for a unitless expression."""
        unit = self._nx.Units
        return unit.Name if unit is not None else None

    @property
    def description(self) -> str:
        return self._nx.Description

    def rename(self, new_name: str) -> None:
        self._nx.OwningPart.Expressions.Rename(self._nx, new_name)


@_wraps(NXOpen.ReferenceSet)
class ReferenceSet_(DisplayableObject_[NXOpen.ReferenceSet]):
    """NXOpen.ReferenceSet - members, adding and removing."""

    __slots__ = ()

    @property
    def members(self) -> List[NXObject_[NXOpen.NXObject]]:
        """The objects directly in the reference set."""
        return [cast(NXObject_[NXOpen.NXObject], wrap(m)) for m in self._nx.AskAllDirectMembers()]

    def add(self, *objects: Union[NXObject_[Any], NXOpen.NXObject]) -> None:
        """ReferenceSet.AddObjectsToReferenceSet"""
        self._nx.AddObjectsToReferenceSet([_unwrap(o) for o in objects])

    def remove(self, *objects: Union[NXObject_[Any], NXOpen.NXObject]) -> None:
        """ReferenceSet.RemoveObjectsFromReferenceSet"""
        self._nx.RemoveObjectsFromReferenceSet([_unwrap(o) for o in objects])

    def __contains__(self, obj: object) -> bool:
        if not isinstance(obj, (TaggedObject_, NXOpen.TaggedObject)):
            return False
        tag = obj.tag if isinstance(obj, TaggedObject_) else int(obj.Tag)
        return any(int(m.Tag) == tag for m in self._nx.AskAllDirectMembers())

    def delete(self) -> None:
        """ReferenceSet.__Delete - BasePart.DeleteReferenceSet."""
        self._nx.OwningPart.DeleteReferenceSet(self._nx)


# ---------------------------------------------------------------------------------------------------------------
# Features
# ---------------------------------------------------------------------------------------------------------------

@_wraps(NXOpen.Features.Feature)
class Feature_(NXObject_[_FE]):
    """NXOpen.Features.Feature - type, bodies/faces/edges, parents/children, suppression."""

    __slots__ = ()

    def _describe(self) -> str:
        return repr(self.feature_name)

    @property
    def feature_type(self) -> str:
        """"BLOCK", "EXTRUDE", "LINKED_BODY", ..."""
        return self._nx.FeatureType

    @property
    def feature_name(self) -> str:
        """The name the part navigator shows ("Block(3)")."""
        return self._nx.GetFeatureName()

    @property
    def timestamp(self) -> int:
        return self._nx.Timestamp

    @property
    def bodies(self) -> List[Body_]:
        return [Body_(b) for b in self._nx.GetBodies()]

    @property
    def body(self) -> Body_:
        """The feature's single body; raises unless there is exactly one."""
        bodies = self.bodies
        if len(bodies) != 1:
            raise RuntimeError("{} has {} bodies, expected 1".format(self.feature_name, len(bodies)))
        return bodies[0]

    @property
    def faces(self) -> List[Face_]:
        return [Face_(f) for f in self._nx.GetFaces()]

    @property
    def edges(self) -> List[Edge_]:
        return [Edge_(e) for e in self._nx.GetEdges()]

    @property
    def entities(self) -> List[NXObject_[NXOpen.NXObject]]:
        return [cast(NXObject_[NXOpen.NXObject], wrap(e)) for e in self._nx.GetEntities()]

    @property
    def expressions(self) -> List[Expression_]:
        return [Expression_(e) for e in self._nx.GetExpressions()]

    @property
    def parents(self) -> List[Feature_[NXOpen.Features.Feature]]:
        return [cast(Feature_[NXOpen.Features.Feature], wrap(f)) for f in self._nx.GetParents()]

    @property
    def children(self) -> List[Feature_[NXOpen.Features.Feature]]:
        return [cast(Feature_[NXOpen.Features.Feature], wrap(f)) for f in self._nx.GetChildren()]

    @property
    def is_suppressed(self) -> bool:
        return self._nx.Suppressed

    def suppress(self) -> None:
        self._nx.Suppress()

    def unsuppress(self) -> None:
        self._nx.Unsuppress()

    def make_current(self) -> None:
        """Feature.MakeCurrentFeature"""
        self._nx.MakeCurrentFeature()

    def highlight(self) -> None:
        self._nx.Highlight()

    def unhighlight(self) -> None:
        self._nx.Unhighlight()

    def set_color(self, color: int) -> None:
        """Feature.__Color(int) - colors every body of the feature."""
        for body in self.bodies:
            body.color = color

    def set_layer(self, layer: int) -> None:
        """Feature.__Layer(int) - moves every body of the feature."""
        for body in self.bodies:
            body.layer = layer


@_wraps(NXOpen.Features.BodyFeature)
class BodyFeature_(Feature_[NXOpen.Features.BodyFeature]):
    """NXOpen.Features.BodyFeature"""

    __slots__ = ()


@_wraps(NXOpen.Features.Block)
class Block_(Feature_[NXOpen.Features.Block]):
    """NXOpen.Features.Block - size, origin and orientation, read through a BlockFeatureBuilder."""

    __slots__ = ()

    def _read(self) -> Tuple[Point3d_, float, float, float, Matrix3x3_]:
        builder = self._nx.OwningPart.Features.CreateBlockFeatureBuilder(self._nx)
        try:
            x_axis, y_axis = builder.GetOrientation()
            origin = Point3d_.of(builder.Origin)
        finally:
            builder.Destroy()

        # The builder's Length/Width/Height come back None in Python (the C# reads them there), so the size comes
        # from UF_MODL_ask_block_parms: the length, width and height expressions, as "p64=4.25" strings.
        part = self._nx.OwningPart
        length, width, height = (part.Expressions.FindObject(parm.split("=", 1)[0].strip()).Value
                                 for parm in nx.ufsession_.ModlFeatures.AskBlockParms(self.tag, 0))
        return origin, length, width, height, Matrix3x3_.from_axes(x_axis, y_axis)

    @property
    def origin(self) -> Point3d_:
        """Block.__Origin"""
        return self._read()[0]

    @property
    def length(self) -> float:
        """Block.__Length - along the block's X."""
        return self._read()[1]

    @property
    def width(self) -> float:
        """Block.__Width - along the block's Y."""
        return self._read()[2]

    @property
    def height(self) -> float:
        """Block.__Height - along the block's Z."""
        return self._read()[3]

    @property
    def size(self) -> Tuple[float, float, float]:
        """(length, width, height) in one builder round trip."""
        _origin, length, width, height, _orientation = self._read()
        return length, width, height

    @property
    def orientation(self) -> Matrix3x3_:
        """Block.__Orientation"""
        return self._read()[4]

    @property
    def is_dynamic_block(self) -> bool:
        return self.name == "DYNAMIC BLOCK"


@_wraps(NXOpen.Features.Extrude)
class Extrude_(Feature_[NXOpen.Features.Extrude]):
    """NXOpen.Features.Extrude"""

    __slots__ = ()


@_wraps(NXOpen.Features.BooleanFeature)
class BooleanFeature_(Feature_[NXOpen.Features.BooleanFeature]):
    """NXOpen.Features.BooleanFeature"""

    __slots__ = ()


@_wraps(NXOpen.Features.ExtractFace)
class ExtractFace_(Feature_[NXOpen.Features.ExtractFace]):
    """NXOpen.Features.ExtractFace - including the LINKED_BODY features wave links create."""

    __slots__ = ()

    @property
    def is_linked_body(self) -> bool:
        """ExtractFace.__IsLinkedBody"""
        return nx.is_linked_body(self._nx)

    @property
    def is_broken(self) -> bool:
        """ExtractFace.__IsBroken - the wave link has lost its source."""
        return nx.is_link_broken(self._nx)

    @property
    def xform_tag(self) -> int:
        """ExtractFace.__XFormTag"""
        return int(nx.xform_tag(self._nx))


@_wraps(NXOpen.Features.DatumCsys)
class DatumCsys_(Feature_[NXOpen.Features.DatumCsys]):
    """NXOpen.Features.DatumCsys - its csys, three planes and three axes."""

    __slots__ = ()

    @property
    def csys(self) -> CartesianCoordinateSystem_:
        found = [e for e in self._nx.GetEntities() if isinstance(e, NXOpen.CartesianCoordinateSystem)]
        return CartesianCoordinateSystem_(found[0])

    @property
    def origin(self) -> Point3d_:
        return self.csys.origin

    @property
    def orientation(self) -> Matrix3x3_:
        return self.csys.orientation

    @property
    def datum_planes(self) -> List[DatumPlane_]:
        return [DatumPlane_(e) for e in self._nx.GetEntities() if isinstance(e, NXOpen.DatumPlane)]

    @property
    def datum_axes(self) -> List[DatumAxis_]:
        return [DatumAxis_(e) for e in self._nx.GetEntities() if isinstance(e, NXOpen.DatumAxis)]

    def _plane_normal_to(self, axis: Vector3d_) -> DatumPlane_:
        for plane in self.datum_planes:
            if plane.normal.is_parallel(axis):
                return plane
        raise RuntimeError("{} has no datum plane normal to {}".format(self.feature_name, axis))

    @property
    def plane_xy(self) -> DatumPlane_:
        """DatumCsys.__DatumPlaneXY"""
        return self._plane_normal_to(self.orientation.axis_z)

    @property
    def plane_xz(self) -> DatumPlane_:
        """DatumCsys.__DatumPlaneXZ"""
        return self._plane_normal_to(self.orientation.axis_y)

    @property
    def plane_yz(self) -> DatumPlane_:
        """DatumCsys.__DatumPlaneYZ"""
        return self._plane_normal_to(self.orientation.axis_x)


@_wraps(NXOpen.Features.DatumPlaneFeature)
class DatumPlaneFeature_(Feature_[NXOpen.Features.DatumPlaneFeature]):
    """NXOpen.Features.DatumPlaneFeature"""

    __slots__ = ()

    @property
    def datum_plane(self) -> DatumPlane_:
        return DatumPlane_(cast(NXOpen.DatumPlane, self._nx.GetEntities()[0]))


@_wraps(NXOpen.Features.DatumAxisFeature)
class DatumAxisFeature_(Feature_[NXOpen.Features.DatumAxisFeature]):
    """NXOpen.Features.DatumAxisFeature"""

    __slots__ = ()

    @property
    def datum_axis(self) -> DatumAxis_:
        return DatumAxis_(cast(NXOpen.DatumAxis, self._nx.GetEntities()[0]))


@_wraps(NXOpen.Features.PointFeature)
class PointFeature_(Feature_[NXOpen.Features.PointFeature]):
    """NXOpen.Features.PointFeature"""

    __slots__ = ()

    @property
    def point(self) -> Point_:
        """PointFeature.__Point"""
        return Point_(cast(NXOpen.Point, self._nx.GetEntities()[0]))


@_wraps(NXOpen.Features.EdgeBlend)
class EdgeBlend_(Feature_[NXOpen.Features.EdgeBlend]):
    """NXOpen.Features.EdgeBlend"""

    __slots__ = ()


@_wraps(NXOpen.Features.Chamfer)
class Chamfer_(Feature_[NXOpen.Features.Chamfer]):
    """NXOpen.Features.Chamfer"""

    __slots__ = ()


@_wraps(NXOpen.Features.OffsetFace)
class OffsetFace_(Feature_[NXOpen.Features.OffsetFace]):
    """NXOpen.Features.OffsetFace"""

    __slots__ = ()


@_wraps(NXOpen.Features.CompositeCurve)
class CompositeCurve_(Feature_[NXOpen.Features.CompositeCurve]):
    """NXOpen.Features.CompositeCurve - including linked curves."""

    __slots__ = ()

    @property
    def curves(self) -> List[Curve_[NXOpen.Curve]]:
        return [cast(Curve_[NXOpen.Curve], wrap(e)) for e in self._nx.GetEntities() if isinstance(e, NXOpen.Curve)]

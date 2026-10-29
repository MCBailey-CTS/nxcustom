"""
Python port of the BURNOUT sheet builder from the CreateBurnout form (src\\UFuncs\\CreateBurnout.cs), from the C#
statics in src\\Static\\CreateBurnout.cs: CreateBurnoutSheet, CreateBurnoutSetAnnotationPreferences and
CreateBurnoutSetViewPreferences.
The C# wrapper was deleted 2026-10-22 (in git at f32694f): the UFunc's menu button runs this file's main().

Wired (2026-10-20): the create-burnout UFunc runs CreateBurnout.execute, which replaces the WinForms form with a
modal dialog (CreateBurnout.dlx, built by tools\make-dlx.py) and then does what ButtonSelect_Click did - the
component pick or the whole assembly, the burnout-material filter, then the BURNOUT sheets created or deleted, all
inside a display_part_reset (the builder changes the display part per part and does not restore it). Never run in
NX yet.

Kept quirks of the C#: the six attribute flags are declared once, outside the per-part loop, so a part passes
the attribute check on attributes found on an earlier part; and a part that still fails it returns from the
whole method, skipping the remaining parts and the final listing.
"""

from __future__ import annotations

import os
import sys
from typing import List, Sequence, cast

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
import NXOpen.Annotations  # noqa: E402
import NXOpen.Drawings  # noqa: E402
import NXOpen.Layer  # noqa: E402
import NXOpen.Preferences  # noqa: E402
import NXOpen.UF  # noqa: E402

import tsg_nx as nx  # noqa: E402
from tsg_dialog import Dialog, components_of  # noqa: E402

# NXOpen.UF.UFConstants.UF_drawing_type (uf_object_types.h).
_UF_drawing_type = 62

# NXException.ErrorCode from Expressions.FindObject when the name does not exist.
_ErrorExpressionNotFound = 3520016

# The note on the burnout sheet - the C# builds the same six lines three times.
_NoteLines = (
    "<W@SHOP> JOB NO.: <W@JOB NUMBER>",
    "QTY: <W@QTY>",
    "DET #: <W@DETAIL NUMBER>",
    "MATL: <W@MATERIAL>",
    "SIZE: <W@DESCRIPTION>",
    "SEND ALL SLUGS TO <W@SHOP>",
)


def _has_expression(part: NXOpen.BasePart, expression_name: str) -> bool:
    """BasePart.__HasExpression - Expressions.FindObject, false on error 3520016 only."""
    try:
        part.Expressions.FindObject(expression_name)
        return True
    except NXOpen.NXException as ex:
        if ex.ErrorCode == _ErrorExpressionNotFound:
            return False
        raise


def _has_drawing_sheet(part: NXOpen.BasePart, drawing_sheet_name: str) -> bool:
    """BasePart.__HasDrawingSheet(string) - ordinal (case-sensitive) name match."""
    return any(sheet.Name == drawing_sheet_name for sheet in cast(NXOpen.Part, part).DrawingSheets)


def _new_lettering(size: float, cfw: NXOpen.Annotations.TextCfw) -> NXOpen.Annotations.Lettering:
    """One of the four identical Lettering initializers in CreateBurnoutSetAnnotationPreferences."""
    lettering = NXOpen.Annotations.Lettering()
    lettering.Size = size
    lettering.CharacterSpaceFactor = 0.9
    lettering.AspectRatio = 0.65
    lettering.LineSpaceFactor = 1.0
    lettering.Cfw = cfw
    lettering.Italic = False
    return lettering


def _thin_line_cfw() -> NXOpen.Annotations.LineCfw:
    """new LineCfw(7, ObjectFont.Solid, LineWidth.Thin) - the positional struct constructor is assumed to match."""
    return NXOpen.Annotations.LineCfw(7, NXOpen.DisplayableObject.ObjectFont.Solid,
                                      NXOpen.Annotations.LineWidth.Thin)


def _set_annotation_preferences() -> None:
    """Static.CreateBurnoutSetAnnotationPreferences."""
    work = nx.work_part()
    lettering_preferences1 = work.Annotations.Preferences.GetLetteringPreferences()

    # sql
    cfw = NXOpen.Annotations.TextCfw()
    cfw.Color = 7
    cfw.Font = 1
    cfw.Width = NXOpen.Annotations.LineWidth.Thin

    lettering_preferences1.SetDimensionText(_new_lettering(0.5, cfw))
    lettering_preferences1.SetAppendedText(_new_lettering(0.5, cfw))
    lettering_preferences1.SetToleranceText(_new_lettering(0.125, cfw))
    lettering_preferences1.SetGeneralText(_new_lettering(0.5, cfw))

    work.Annotations.Preferences.SetLetteringPreferences(lettering_preferences1)

    lettering_preferences1.Dispose()

    # sql
    line_and_arrow_preferences1 = work.Annotations.Preferences.GetLineAndArrowPreferences()
    line_and_arrow_preferences1.SetFirstExtensionLineCfw(_thin_line_cfw())
    line_and_arrow_preferences1.SetFirstArrowheadCfw(_thin_line_cfw())
    line_and_arrow_preferences1.SetFirstArrowLineCfw(_thin_line_cfw())
    line_and_arrow_preferences1.SetSecondExtensionLineCfw(_thin_line_cfw())
    line_and_arrow_preferences1.SetSecondArrowheadCfw(_thin_line_cfw())
    line_and_arrow_preferences1.SetSecondArrowLineCfw(_thin_line_cfw())

    work.Annotations.Preferences.SetLineAndArrowPreferences(line_and_arrow_preferences1)

    line_and_arrow_preferences1.Dispose()

    dimension_preferences1 = work.Annotations.Preferences.GetDimensionPreferences()
    dimension_preferences1.TextPlacement = NXOpen.Annotations.TextPlacement.Automatic
    dimension_preferences1.TrimDimensionLineStyle = NXOpen.Annotations.TrimDimensionLineStyle.Trim
    work.Annotations.Preferences.SetDimensionPreferences(dimension_preferences1)
    dimension_preferences1.Dispose()

    # Struct and enum names read from NXOpen_UF.pyd (NXOpen.UF.Drf.UnitsFormatPreferences, C enum member names);
    # not yet seen in NX.
    drf = NXOpen.UF.Drf
    units_format_preferences1 = drf.UnitsFormatPreferences()
    units_format_preferences1.DimensionLinearUnits = drf.LinearUnits.INCHES
    units_format_preferences1.LinearFractionType = drf.FractionType.DECIMAL
    units_format_preferences1.DecimalPointCharacter = drf.DecimalPointCharacter.DECIMAL_POINT_PERIOD
    units_format_preferences1.DisplayTrailingZeros = True
    units_format_preferences1.DimensionTolerancePlacement = drf.TolerancePlacement.TOLERANCE_AFTER_DIMENSION
    units_format_preferences1.DimensionAngularFormat = drf.AngularUnits.FRACTIONAL_DEGREES
    units_format_preferences1.DimAngularFormatTolerance = drf.AngularUnits.FRACTIONAL_DEGREES
    units_format_preferences1.AngularSuppressZeros = drf.AngularSuppressZeros.ANG_DISPLAY_ZEROS
    units_format_preferences1.DualDimensionFormat = drf.DualDimensionFormat.NO_DUAL_DIMENSION
    units_format_preferences1.DualDimensionUnits = drf.LinearUnits.INCHES
    units_format_preferences1.DualFractionType = drf.FractionType.DECIMAL
    units_format_preferences1.DualConvertTolerance = True
    nx.ufsession_.Drf.SetUnitsFormatPreferences(units_format_preferences1)


def _set_view_preferences() -> None:
    """Static.CreateBurnoutSetViewPreferences."""
    work = nx.work_part()
    work.ViewPreferences.HiddenLines.HiddenlineColor = 0
    work.ViewPreferences.HiddenLines.HiddenlineFont = NXOpen.Preferences.Font.Dashed
    work.ViewPreferences.VisibleLines.VisibleColor = 0
    work.ViewPreferences.VisibleLines.VisibleWidth = NXOpen.Preferences.Width.Original
    work.ViewPreferences.SmoothEdges.SmoothEdgeColor = 0
    work.ViewPreferences.SmoothEdges.SmoothEdgeFont = NXOpen.Preferences.Font.Invisible
    work.ViewPreferences.SmoothEdges.SmoothEdgeWidth = NXOpen.Preferences.Width.Original
    work.ViewPreferences.General.AutomaticAnchorPoint = False
    work.ViewPreferences.General.Centerlines = False
    work.Preferences.ColorSettingVisualization.MonochromeDisplay = False


def _create_burnout_drawing(comp: NXOpen.Part) -> bool:
    """
    The per-part body of Static.CreateBurnoutSheet after its attribute check, from SetDisplayPart on. Returns
    False where the C# `continue`s (the sheet already exists).
    """
    nx.ufsession_.Part.SetDisplayPart(comp.Tag)
    nx.display_part().WCS.SetOriginAndMatrix(NXOpen.Point3d(0.0, 0.0, 0.0), nx.identity_matrix())

    # CreateOrNull burnout drawing sheet
    is_burnout = _has_drawing_sheet(nx.display_part(), "BURNOUT")

    if is_burnout:
        nx.print_("Burnout drawing already exists " + comp.Leaf)
        return False

    work = nx.work_part()
    work.DraftingDrawingSheets.InsertSheet(
        "BURNOUT",
        NXOpen.Drawings.DrawingSheet.Unit.Inches,
        150.0,
        250.0,
        1.0,
        1.0,
        NXOpen.Drawings.DrawingSheet.ProjectionAngleType.ThirdAngle)

    # UF_OBJ_cycle_by_name_and_type: the C# ref param comes back as the return value (checked in the pyd).
    burnout_dwg = nx.ufsession_.Obj.CycleByNameAndType(
        nx.display_part().Tag,
        "BURNOUT",
        _UF_drawing_type,
        False,
        0)  # Tag.Null - tsg_nx.cycle_objs_in_part starts its UF cycle the same way

    current_dwg = nx.ufsession_.Draw.AskCurrentDrawing()

    dwg_name = nx.ufsession_.Obj.AskName(current_dwg)

    if dwg_name != "BURNOUT":
        nx.ufsession_.Draw.OpenDrawing(burnout_dwg)

    # Set lettering and view preferences
    _set_annotation_preferences()
    _set_view_preferences()
    nx.ufsession_.Draw.SetBorderDisplay(False)

    # Import plan view
    base_view_builder1 = work.DraftingViews.CreateBaseViewBuilder(None)

    is_plan = False

    for m_view in work.ModelingViews:
        if m_view.Name.upper() != "PLAN":
            continue

        is_plan = True
        base_view_builder1.SelectModelView.SelectedView = m_view

    if not is_plan:
        for m_view in work.ModelingViews:
            if m_view.Name.upper() == "TOP":
                base_view_builder1.SelectModelView.SelectedView = m_view

    # sql
    point1 = NXOpen.Point3d(125.0, 75.0, 0.0)
    base_view_builder1.Placement.Placement.SetValue(None, work.Views.WorkView, point1)

    nx_object1 = base_view_builder1.Commit()

    base_view_builder1.Destroy()

    # Set layers visible in view

    nx.display_part().Layers.SetState(100, NXOpen.Layer.State.WorkLayer)

    imported_view_obj = cast(NXOpen.View, nx_object1)

    # C# new StateInfo[256]: every entry default (Layer 0, State 0) until the loop fills 0..254 - the last
    # entry is left at its default, as in the C#.
    layer_visible_in_view: List[NXOpen.Layer.StateInfo] = [NXOpen.Layer.StateInfo() for _ in range(256)]

    for i in range(len(layer_visible_in_view) - 1):
        layer_visible_in_view[i].Layer = i + 1
        layer_visible_in_view[i].State = NXOpen.Layer.State.Hidden

    layer_visible_in_view[99].Layer = 100
    layer_visible_in_view[99].State = NXOpen.Layer.State.Visible

    work.Layers.SetObjectsVisibilityOnLayer(imported_view_obj, layer_visible_in_view, True)

    drafting_views = list(work.DraftingViews)
    work.DraftingViews.UpdateViews(drafting_views)

    # Add annotation note

    mark_id3 = nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Invisible, "CreateOrNull Annotation")

    lettering_preferences2 = work.Annotations.Preferences.GetLetteringPreferences()

    user_symbol_preferences2 = work.Annotations.NewUserSymbolPreferences(
        NXOpen.Annotations.UserSymbolPreferences.SizeType.ScaleAspectRatio, 1.0, 1.0)

    # sql
    origin2 = NXOpen.Point3d(0.0, 0.0, 0.0)
    note1 = work.Annotations.CreateNote(list(_NoteLines), origin2,
                                        NXOpen.AxisOrientation.Horizontal,
                                        lettering_preferences2,
                                        user_symbol_preferences2)

    note1.SetText(list(_NoteLines))
    origin3 = NXOpen.Point3d(125.0, 100.0, 0.0)
    note1.AnnotationOrigin = origin3

    nx.session_.UpdateManager.DoUpdate(mark_id3)

    mark_id4 = nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Invisible, "CreateOrNull Annotation")

    origin4 = NXOpen.Point3d(125.0, 100.0, 0.0)
    note2 = work.Annotations.CreateNote(list(_NoteLines), origin4,
                                        NXOpen.AxisOrientation.Horizontal,
                                        lettering_preferences2,
                                        user_symbol_preferences2)

    lettering_preferences2.Dispose()
    user_symbol_preferences2.Dispose()

    nx.session_.UpdateManager.AddToDeleteList(note2)

    nx.session_.UpdateManager.DoUpdate(mark_id4)

    nx.session_.DeleteUndoMark(mark_id3, "CreateOrNull Annotation")

    nx.session_.DeleteUndoMark(mark_id4, "CreateOrNull Annotation")

    # sql
    display = nx.display_part()
    display.Layers.SetState(1, NXOpen.Layer.State.WorkLayer)
    display.Layers.SetState(100, NXOpen.Layer.State.Selectable)
    display.Layers.SetState(200, NXOpen.Layer.State.Selectable)
    display.Layers.SetState(230, NXOpen.Layer.State.Selectable)
    return True


class CreateBurnout(object):

    @staticmethod
    def execute() -> None:
        """create-burnout: the dialog, then create or delete the BURNOUT sheets."""
        _run()

    @staticmethod
    def create_burnout_sheet(parts: Sequence[NXOpen.Part]) -> None:
        """
        Static.CreateBurnoutSheet: for each burnout part with ADDX/ADDY/ADDZ expressions and the six title-block
        attributes, adds a BURNOUT drawing sheet with the PLAN (else TOP) view showing layer 100 and the
        shop/job/qty note; then lists every part passed in. Leaves the last part displayed.
        """
        nx_comp_list = list(parts or [])

        nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, "CreateOrNull Burnout")

        if len(nx_comp_list) == 0:
            nx.print_("")
            nx.print_("There are no burnouts in this assembly")
            return

        # Declared once, outside the loop, exactly as the C# does.
        is_job_number = False
        is_qty = False
        is_detail_number = False
        is_material = False
        is_description = False
        is_shop = False

        for comp in nx_comp_list:
            try:
                if not _has_expression(comp, "ADDX"):
                    nx.print_("Part {} does not have a expression ADDX".format(comp.Leaf))
                    continue

                if not _has_expression(comp, "ADDY"):
                    nx.print_("Part {} does not have a expression ADDY".format(comp.Leaf))
                    continue

                if not _has_expression(comp, "ADDZ"):
                    nx.print_("Part {} does not have a expression ADDZ".format(comp.Leaf))
                    continue

                for attr_burn in comp.GetUserAttributes():
                    title = attr_burn.Title.upper()

                    if title == "JOB NUMBER":
                        if nx.get_attribute(comp, attr_burn.Title) != "":
                            is_job_number = True
                    elif title == "QTY":
                        if nx.get_attribute(comp, attr_burn.Title) != "":
                            is_qty = True
                    elif title == "DETAIL NUMBER":
                        if nx.get_attribute(comp, attr_burn.Title) != "":
                            is_detail_number = True
                    elif title == "MATERIAL":
                        if nx.get_attribute(comp, attr_burn.Title) != "":
                            is_material = True
                    elif title == "DESCRIPTION":
                        if nx.get_attribute(comp, attr_burn.Title) != "":
                            is_description = True
                    elif title == "SHOP":
                        if nx.get_attribute(comp, attr_burn.Title) != "":
                            is_shop = True

                if (not is_job_number or not is_qty or not is_detail_number or not is_material
                        or not is_description or not is_shop):
                    if not is_description:
                        nx.print_("Attribute Error {}: DESCRIPTION".format(comp.Leaf))

                    if not is_detail_number:
                        nx.print_("Attribute Error {}: DETAIL NUMBER".format(comp.Leaf))

                    if not is_job_number:
                        nx.print_("Attribute Error {}: JOB NUMBER".format(comp.Leaf))

                    if not is_material:
                        nx.print_("Attribute Error {}: MATERIAL".format(comp.Leaf))

                    if not is_qty:
                        nx.print_("Attribute Error {}: QTY".format(comp.Leaf))

                    if not is_shop:
                        nx.print_("Attribute Error {}: SHOP".format(comp.Leaf))

                    # The C# returns here - the rest of the parts and the final listing are skipped.
                    return

                _create_burnout_drawing(comp)
            except Exception as ex:
                nx.print_exception(ex, comp.Leaf)

        burnout_list = "".join("{}\n".format(comp.Leaf) for comp in nx_comp_list)
        nx.print_("")
        nx.print_("==================================================================================")
        nx.print_("List of all burnout components:")
        nx.print_("==================================================================================")
        nx.print_("")
        nx.print_(burnout_list)
        nx.print_("")
        nx.print_("==================================================================================")


# ---------------------------------------------------------------------------------------------------
# The create-burnout UFunc: a modal dialog (CreateBurnout.dlx) in place of the WinForms form
# ---------------------------------------------------------------------------------------------------

# The materials the form treats as burnouts, compared upper-cased.
_BurnoutMaterials = ("HRS PLT", "4140 PLT", "4140 PH PLT")


class _CreateBurnoutDialog(Dialog):
    """
    The form's two group boxes as two radio enums: Options (Create Burnouts / Delete Burnouts - the form's two
    mutually exclusive checkboxes) and Selection (Select / Select All - its two buttons). The component picker
    shows only for Select. OK does what pressing the button did.
    """

    dlx_name = "CreateBurnout.dlx"
    title = "Create Burnout"

    def __init__(self) -> None:
        super().__init__()
        self.create = True
        self.select_all = False
        self.components: List[NXOpen.Assemblies.Component] = []

    def initialize(self) -> None:
        self.component_filter(self.block("components"))
        self._show_picker()

    def update(self, block: NXOpen.BlockStyler.UIBlock) -> None:
        if block == self.block("scope"):
            self._show_picker()

    def ok(self) -> bool:
        self.create = self.block("action").ValueAsString == "Create Burnouts"
        self.select_all = self.block("scope").ValueAsString == "Select All"
        self.components = components_of(self.selected(self.block("components")))

        if not self.select_all and not self.components:
            self.message("Select the components, or choose Select All.")
            return False

        return True

    def _show_picker(self) -> None:
        self.block("components").Show = self.block("scope").ValueAsString != "Select All"


def _burnout_parts(components: Sequence[NXOpen.Assemblies.Component]) -> List[NXOpen.Part]:
    """The distinct prototype parts of components whose MATERIAL is one of the burnout materials."""
    parts: List[NXOpen.Part] = []
    seen = set()

    for component in components:
        proto = component.Prototype
        if not isinstance(proto, NXOpen.Part) or proto.Tag in seen:
            continue
        seen.add(proto.Tag)

        if not nx.has_attribute(proto, "MATERIAL"):
            continue

        if nx.get_attribute(proto, "MATERIAL").upper() in _BurnoutMaterials:
            parts.append(proto)

    return parts


def _delete_burnout_sheets(parts: Sequence[NXOpen.Part]) -> None:
    """The form's Delete Burnouts pass: every drawing sheet named BURNOUT in each part."""
    for part in parts:
        sheets = [sheet for sheet in part.DrawingSheets if sheet.Name == "BURNOUT"]
        if sheets:
            with nx.do_update():
                nx.session_.UpdateManager.AddObjectsToDeleteList(sheets)


def _run() -> None:
    """CreateBurnout.ButtonSelect_Click, behind the dialog."""
    if nx.display_part() is None:
        nx.print_("There is no displayed part loaded")
        return

    dialog = _CreateBurnoutDialog()

    if not dialog.run():
        return

    with nx.display_part_reset():
        try:
            if dialog.select_all:
                root = nx.root_component(nx.display_part())
                components = [] if root is None else [c for c in nx.descendants(root) if not c.IsSuppressed]
            else:
                components = dialog.components

            parts = _burnout_parts(components)

            if dialog.create:
                CreateBurnout.create_burnout_sheet(parts)
            else:
                _delete_burnout_sheets(parts)
        except Exception as ex:
            nx.print_exception(ex)



def main() -> None:
    """The create-burnout UFunc - its menu button runs this file. An escaping exception is printed."""
    import usage_db

    with usage_db.run("create-burnout"):
        try:
            _run()
        except Exception as ex:
            nx.print_exception(ex)


if __name__ == "__main__":
    main()

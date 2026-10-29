"""
Python port of AssemblyWavelink (src\\UFuncs\\AssemblyWavelink.cs): WaveLinkFasteners, WavelinkSubtool and
WaveLinkBoolean.

Called from the AssemblyWavelink form through Session.Execute - see PythonLibrary.cs. The form and the
selection (including the boolean's reference-set dialog) stay C#; everything after the picks runs here. The
buttons call the C# methods today; the form's *Python wrappers call these instead.
"""

import os
import sys

# Session.Execute does not put the script's folder on sys.path, so the shared module would not import.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

import NXOpen  # noqa: E402
import NXOpen.Features  # noqa: E402
import NXOpen.Layer  # noqa: E402

import tsg_nx as nx  # noqa: E402

# Static.SubToolRefSetNames - matched against the upper-cased reference set name.
_SubToolRefSetNames = ("SUB_TOOL", "SUB-TOOL", "SUBTOOL")

# Layer the linked bodies are created on.
_LinkedBodyLayer = 96


def _linked_body_name(linked, reference_set, owner):
    """Static.LinkedBodyName"""
    if owner is None:
        return "{}, {}".format(linked.DisplayName, reference_set)
    return "{}, {}, {}".format(linked.DisplayName, reference_set, owner.DisplayName)


class AssemblyWavelink(object):

    @staticmethod
    def wave_link_fasteners(undo_name, blank_tools, shcs_ref_set, dwl_ref_set, jck_ref_set, targets, tools):
        """
        Subtracts each tool component's fasteners from every target body. Mirrors the part of the C#
        WaveLinkFasteners that runs after selection; see its doc comment for the rules.

        targets and tools are picked in C# (SelectFastenerTargetsAndTools) and passed in as TaggedObject
        arrays. Session.Execute cannot pass null, so an empty string means "no reference set" for the three
        refset arguments.
        """
        shcs_ref_set = shcs_ref_set or None
        dwl_ref_set = dwl_ref_set or None
        jck_ref_set = jck_ref_set or None
        targets = list(targets or [])
        tools = list(tools or [])

        if not targets or not tools:
            return

        nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, undo_name)

        with nx.display_part_reset():
            try:
                with nx.suppress_display():
                    for target in targets:
                        for tool in tools:
                            with nx.display_part_reset(), nx.reset_work_layer():
                                try:
                                    _subtract_tool_fasteners(
                                        target, tool, shcs_ref_set, dwl_ref_set, jck_ref_set)

                                    if nx.work_part().Layers.WorkLayer != 96:
                                        nx.work_part().Layers.SetState(96, NXOpen.Layer.State.Selectable)

                                    if blank_tools:
                                        tool.Blank()
                                except Exception as ex:
                                    nx.print_exception(ex)

                nx.work_part().Layers.SetState(1, NXOpen.Layer.State.WorkLayer)
            except Exception as ex:
                nx.print_exception(ex)

    @staticmethod
    def wave_link_subtool(undo_name, target, tools):
        """
        AssemblyWavelink.WavelinkSubtool, after the picks. Subtracts each tool's sub tool geometry from the one
        target body: the tool is switched to whichever SUB_TOOL / SUB-TOOL / SUBTOOL reference set it publishes,
        linked into the target's part and subtracted, then put back on its own reference set. A tool with none
        or several of those, or that does not interfere, is reported and stepped over.

        As in the C#, any other failure ends the run (it is caught outside the tool loop).
        """
        tools = list(tools or [])

        if target is None or not tools:
            return

        nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, undo_name)

        with nx.display_part_reset():
            try:
                current = nx.display_part().Layers.WorkLayer

                try:
                    nx.set_work_component(target.OwningComponent)
                    nx.display_part().Layers.SetState(_LinkedBodyLayer, NXOpen.Layer.State.WorkLayer)

                    for tool in tools:
                        # ReferenceSetReset
                        original_ref_set = tool.ReferenceSet
                        try:
                            _subtract_sub_tool(target, tool)
                        finally:
                            nx.set_reference_set(tool, original_ref_set)
                            tool.RedisplayObject()
                finally:
                    nx.display_part().Layers.SetState(current, NXOpen.Layer.State.WorkLayer)

                    if nx.work_part().Layers.WorkLayer != _LinkedBodyLayer:
                        nx.work_part().Layers.SetState(_LinkedBodyLayer, NXOpen.Layer.State.Selectable)
            except Exception as ex:
                nx.print_exception(ex)

        nx.work_part().Layers.SetState(1, NXOpen.Layer.State.WorkLayer)

    @staticmethod
    def wave_link_boolean(blank_tools, boolean_type, reference_set, targets, tools):
        """
        Static.WaveLinkBoolean, after the picks and the reference-set dialog. Links every tool,
        through reference_set, into every target's part (one LINKED_BODY per solid body) and applies the
        boolean to each link. boolean_type is the Feature.BooleanType member name - "Subtract", "Unite",
        "Intersect", or "Create", which links only.

        As in the C#, a failure inside one link prints and moves on; a failure to make the links ends the run.
        """
        targets = list(targets or [])
        tools = list(tools or [])

        if not targets or not tools or not reference_set:
            return

        link_only = boolean_type == "Create"
        operation = getattr(NXOpen.Features.Feature.BooleanType, boolean_type)

        nx.session_.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, "Assembly Wavelink")

        with nx.display_part_reset():
            try:
                for target in targets:
                    for tool in tools:
                        with nx.display_part_reset():
                            nx.set_work_component(target.OwningComponent)
                            nx.display_part().Layers.SetState(_LinkedBodyLayer, NXOpen.Layer.State.WorkLayer)

                            current_ref_set = tool.ReferenceSet
                            nx.set_reference_set(tool, reference_set)

                            try:
                                for ext in nx.create_linked_bodies(tool):
                                    try:
                                        ext.SetName(_linked_body_name(tool, reference_set, tool.Parent))
                                        nx.print_("//////////////////")
                                        nx.print_("Created {} in {}".format(ext.GetFeatureName(), ext.OwningPart.Leaf))

                                        if link_only:
                                            continue

                                        boolean_feature = nx.create_boolean(target, ext.GetBodies(), operation)
                                        nx.print_("Created {} in {}".format(
                                            boolean_feature.GetFeatureName(), ext.OwningPart.Leaf))
                                    except NXOpen.NXException as ex:
                                        if ex.ErrorCode == nx.ErrorNoInterference:
                                            nx.print_("Error occurred when trying to subtract {}, no interference."
                                                      .format(tool.DisplayName))
                                        else:
                                            nx.print_exception(ex)
                                    except Exception as ex:
                                        nx.print_exception(ex)
                            finally:
                                nx.set_reference_set(tool, current_ref_set)

                            if nx.work_part().Layers.WorkLayer != _LinkedBodyLayer:
                                nx.work_part().Layers.SetState(_LinkedBodyLayer, NXOpen.Layer.State.Selectable)

                nx.work_part().Layers.SetState(1, NXOpen.Layer.State.WorkLayer)

                if blank_tools:
                    for tool in tools:
                        tool.Blank()
            except Exception as ex:
                nx.print_exception(ex)


def _subtract_sub_tool(target, tool):
    """The body of the WavelinkSubtool tool loop."""
    matches = [r for r in nx.prototype(tool).GetAllReferenceSets() if r.Name.upper() in _SubToolRefSetNames]

    # SingleOrDefault: several is the InvalidOperationException the C# catches.
    if len(matches) > 1:
        nx.print_("Found more than one sub tool reference set for {} - {} - {}".format(
            tool.DisplayName, tool.Name, tool.Tag))
        return

    if not matches:
        nx.print_("Didn't find any sub tool reference sets for {} - {} - {}".format(
            tool.DisplayName, tool.Name, tool.Tag))
        return

    reference_set = matches[0].Name
    nx.set_reference_set(tool, reference_set)
    linked_body = nx.create_linked_body(tool)
    # The tool is what gets linked here, so its own parent is the owner field.
    linked_body.SetName(_linked_body_name(tool, reference_set, tool.Parent))
    nx.print_("//////////////////")
    nx.print_("Created {} in {}".format(linked_body.GetFeatureName(), linked_body.OwningPart.Leaf))

    try:
        boolean_feature = nx.subtract(target, linked_body.GetBodies())
    except NXOpen.NXException as ex:
        if ex.ErrorCode != nx.ErrorNoInterference:
            raise
        nx.print_("Error occurred when trying to subtract {}, no interference.".format(tool.DisplayName))
        return

    nx.print_("Created {} in {}".format(boolean_feature.GetFeatureName(), linked_body.OwningPart.Leaf))


def _subtract_tool_fasteners(target, tool, shcs_ref_set, dwl_ref_set, jck_ref_set):
    nx.set_work_component(target.OwningComponent)
    nx.display_part().Layers.SetState(96, NXOpen.Layer.State.WorkLayer)

    ref_sets = [r for r in (shcs_ref_set, dwl_ref_set) if r]

    for child in tool.GetChildren():
        try:
            if not nx.is_loaded(child):
                nx.print_("Child fastener {} was not loaded.".format(child.DisplayName))
                continue

            if child.IsSuppressed:
                continue

            original_ref_set = child.ReferenceSet
            proto_child = nx.proto_child_comp(child)

            if proto_child.Layer != nx.LayerFastener and proto_child.Layer != 90:
                continue

            try:
                # Intersect keeps the prototype's order, like LINQ's Intersect.
                names = [n for n in nx.reference_set_names(proto_child.Prototype) if n in ref_sets]
                names = list(dict.fromkeys(names))

                if len(names) == 0:
                    # Same grouping as the C#: the last clause is (jck and tsg) or plain jck.
                    if ((shcs_ref_set is not None and nx.is_shcs(child.DisplayName))
                            or (dwl_ref_set is not None and nx.is_dwl(child.DisplayName))
                            or (jck_ref_set is not None and nx.is_jck_screw_tsg(child.DisplayName))
                            or nx.is_jck_screw(child.DisplayName)):
                        nx.print_("Coulnd't find any valid ref sets for {}".format(child.DisplayName))
                    continue

                if len(names) > 1:
                    nx.print_("Found more than one valid ref set for {}".format(child.DisplayName))
                    continue

                nx.set_reference_set(child, names[0])

                if not nx.interferes_with(target, child):
                    nx.print_("Could not subtract fastener {}, no interference.".format(child.DisplayName))
                    continue

                ext = nx.create_linked_body(child)
                ext.SetName(_linked_body_name(child, names[0], tool))
                nx.print_("//////////////////")
                nx.print_("Created {} in {}".format(ext.GetFeatureName(), ext.OwningPart.Leaf))
                boolean_feature = nx.subtract(target, ext.GetBodies())
                nx.print_("Created {} in {}".format(boolean_feature.GetFeatureName(), ext.OwningPart.Leaf))
                nx.set_reference_set(child, original_ref_set)
            except Exception as ex:
                nx.print_exception(ex, child.DisplayName)
        except Exception as ex:
            nx.print_exception(ex)

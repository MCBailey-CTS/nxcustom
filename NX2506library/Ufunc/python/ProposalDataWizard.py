"""
Python port of the NX work in the ProposalDataWizard form (src\\UFuncs\\ProposalDataWizard.cs), whose static
methods now live in src\\Static\\ProposalDataWizard.cs (partial class Static):

- ProposalDataWizardFindMasters(simulation, mathdataType)      -> ProposalDataWizard.find_masters
- ProposalDataWizardGetProposalLevel(folder)                    -> ProposalDataWizard.get_proposal_level
- ProposalDataWizardStep(partPath, stepPath, wait)              -> ProposalDataWizard.step
- ProposalDataWizardCreateStpFile(partToExport)                 -> ProposalDataWizard.create_stp_file
- ProposalDataWizardWavelink(master, simulationBody)            -> ProposalDataWizard.wavelink
- ProposalDataWizardConstructProposalFilePath(master, dataLevel, pLevel)
                                                                -> ProposalDataWizard.construct_proposal_file_path
- ProposalDataWizardGetPartNumber(displayName)                  -> ProposalDataWizard.get_part_number
- ProposalDataWizardCreateProposalComponent(proposalBody, newPartPath)
                                                                -> ProposalDataWizard.create_proposal_component
- ProposalDataWizardCreateMasterReferenceSet(masterPart, name, objects)
                                                                -> ProposalDataWizard.create_master_reference_set
- ProposalDataWizardCreateProposalReferenceSet(proposalPart, name, objects)
                                                                -> ProposalDataWizard.create_proposal_reference_set
- GFolder.create_or_null(Part) / DirMathData, Extensions.TodaysDate,
  BasePart.__FindReferenceSet                                   -> _GFolder, _todays_date, _find_reference_set

**Wired (2026-10-21): find_masters (through find_master_tags) and get_proposal_level.** The form's FindMasters /
GetProposalLevel helpers call them in place of the C# ProposalDataWizardFindMasters / GetProposalLevel, which are
commented out in src\\Static\\ProposalDataWizard.cs. Nothing calls the other ports: their only caller would be
ProposalDataWizardCreateData, which throws (see below), so their C# stays live and unused. **Never run in NX.**

Not ported, deliberately:
- ProposalDataWizardCreateData: its body is commented out and it throws NotImplementedException, so the
  Create button does nothing but print that exception. There is no work to port; the commented-out body is the
  pipeline the methods above would be chained into if it is ever revived.
- The form itself: SetRevisionLevel and Reset (they fill the form's text boxes and list box), the hover/click
  handlers (the body pick stays C#), the ListItem struct and the MathdataType/DataLevelType1 enums.

Parameters that cannot cross Session.Execute are passed as plain values instead:
- find_masters takes the MathdataType as its enum name ("Master" / "History"), the way
  AssemblyWavelink.wave_link_boolean takes the boolean type.
- get_proposal_level takes the GFolder's DirMathData string, not the GFolder.
- The two reference-set builders take the C# params array as a sequence.
PythonLibrary.Execute returns Session.Execute's result as an object, so the string-returning methods can hand
their value back; whether a list of components (find_masters) or a feature/component comes back is unconfirmed,
so the form calls find_master_tags, which returns the tags as a comma-separated string. The form's calls:
    PythonLibrary.Execute("ProposalDataWizard.py", "ProposalDataWizard", "find_master_tags",
        (Part)disp, mathdataType.ToString());
    PythonLibrary.Execute("ProposalDataWizard.py", "ProposalDataWizard",
        "get_proposal_level", folder.DirMathData);

Differences from the C# / unconfirmed bindings:
- ufsession_.So.CreateXformAssyCtxt and ufsession_.Wave.CreateLinkedBody return their C# out tag (signatures
  read from NXOpen_UF.pyd; not in python\\stubs yet, so mypy reports them).
- StepCreator.ExportFrom, ObjectTypes (ObjectTypeSelector.Curves/Surfaces/Solids), LayerMask and FileSaveFlag
  and Session.SetUndoMarkName exist in NXOpen.pyd but not in the stubs. The C# casts ints to the enums:
  ExportAsOption 1 = Ap214, ExportFromOption 1 = ExistingPart (DisplayPart, ExistingPart in the pyd's order),
  MarkVisibility 0 = Invisible / 1 = Visible (assumed .NET order: Invisible, Visible, AnyVisibility).
- .NET exception messages are reproduced as the C# ArgumentException family formats them on .NET Framework
  ("...\\r\\nParameter name: x"); the exception type printed is the Python one.
- Directory.GetDirectories(..., AllDirectories) is os.walk, which does not follow directory symlinks/junctions.
"""

from __future__ import annotations

import datetime
import os
import re
import sys
from typing import List, Optional, Sequence, cast

# Session.Execute does not put the script's folder on sys.path, so the shared module would not import.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

import NXOpen  # noqa: E402
import NXOpen.Assemblies  # noqa: E402
import NXOpen.Features  # noqa: E402
import NXOpen.Layer  # noqa: E402

import tsg_nx as nx  # noqa: E402

# Static.ProposalDataWizardProposalRegex / ProposalDataWizardPartNumberWithDateRegex
# (.NET named groups (?<x>) are (?P<x>) in Python).
# sql
# The regular expression to match the proposal folders.
_ProposalRegex = r"^[0-9]{4}-[0-9]{2}-[0-9]{2}-p(?P<proposalLevel>[0-9]+)(?:-proposal-data)*$"

# The regular expression to match the part number with a trailing date.
_PartNumberWithDateRegex = \
    r"^(TSG|R)\d+([ps][0-9]+)?[-\s_](?P<partNumber>.+)[-\s_][0-9]{4}[-\s_][0-9]{1,2}[-\s_][0-9]{1,2}.*$"

# Extensions.RegexMaster / RegexHistory
_RegexMaster = r"^(?P<customerNum>\d+)-Master$"
_RegexHistory = r"^(?P<customerNum>\d+)-History$"

# Extensions.RefsetEntirePart / RefsetEmpty
_RefsetEntirePart = "Entire Part"
_RefsetEmpty = "Empty"

_StepSettingsFile = "U:\\nxFiles\\Step Translator\\214ug.def"

# NXOpen.Tag.Null
_NullTag = 0


class ProposalDataWizard(object):

    @staticmethod
    def find_masters(simulation: NXOpen.Part, mathdata_type: str) -> List[NXOpen.Assemblies.Component]:
        """
        Static.ProposalDataWizardFindMasters - the display part's Master (or History) children, each made
        selectable (unless its layer is the work layer) and unblanked. mathdata_type is "Master" or "History".
        """
        components: List[NXOpen.Assemblies.Component] = []

        regex_string = _RegexHistory if mathdata_type == "History" else _RegexMaster

        for child in nx.children(simulation):
            if re.search(regex_string, child.DisplayName):
                if simulation.Layers.GetState(child.Layer) != NXOpen.Layer.State.WorkLayer:
                    simulation.Layers.SetState(child.Layer, NXOpen.Layer.State.Selectable)

                # Un-blanks the master.
                child.Unblank()

                components.append(child)

        return components

    @staticmethod
    def find_master_tags(simulation: NXOpen.Part, mathdata_type: str) -> str:
        """
        find_masters for the C# form: the masters' tags as one comma-separated string ("" for none), since whether
        a list of components survives Session.Execute's return is unconfirmed. The form turns each back into its
        Component.
        """
        return ",".join(str(int(master.Tag)) for master in ProposalDataWizard.find_masters(simulation, mathdata_type))

    @staticmethod
    def get_proposal_level(dir_math_data: str) -> str:
        """Static.ProposalDataWizardGetProposalLevel - "p" + (highest proposal folder under Math Data + 1)."""
        # Gets all the directories that are below the math data folder.
        directories = _get_directories_recursive(dir_math_data)

        # Represents the highest proposal level found.
        # The default is 1.
        current_proposal_level = 0

        # Iterate through the {directories}.
        for directory in directories:
            # Gets the name of the {directory}.
            directory_name = _file_name_without_extension(directory)

            # Matches the {directoryName}.
            match = re.match(_ProposalRegex, directory_name)

            # If the {match} is not successful, then we can continue.
            if not match:
                continue

            # Gets the proposal level from the directory.
            proposal_level = int(match.group("proposalLevel"))

            # If the {proposalLevel} is greater than the {currentProposalLevel}, then we can set the
            # {currentProposalLevel} to the {proposalLevel}.
            if current_proposal_level < proposal_level:
                current_proposal_level = proposal_level

        return "p{}".format(current_proposal_level + 1)

    @staticmethod
    def step(part_path: str, step_path: str, wait: bool) -> None:
        """Static.ProposalDataWizardStep - STEP export of the part file on disk with the 214ug settings."""
        try:
            if part_path is None:
                raise ValueError("Value cannot be null.\r\nParameter name: partPath")

            if step_path is None:
                raise ValueError("Value cannot be null.\r\nParameter name: stepPath")

            if not os.path.isfile(part_path):
                raise ValueError("Path to part does not exist.\r\nParameter name: partPath")

            if os.path.isfile(step_path):
                raise ValueError("Path for Step file already exists.\r\nParameter name: stepPath")

            session = nx.session_
            undo_mark_id1 = session.SetUndoMark(NXOpen.Session.MarkVisibility.Invisible, "Start")  # (0)
            step_creator = session.DexManager.CreateStepCreator()
            step_creator.ExportAs = NXOpen.StepCreator.ExportAsOption.Ap214  # (1)
            step_creator.ExportFrom = NXOpen.StepCreator.ExportFromOption.ExistingPart  # (1)
            step_creator.ObjectTypes.Solids = True
            step_creator.InputFile = part_path
            step_creator.OutputFile = step_path
            session.SetUndoMarkName(undo_mark_id1, "Export to STEP Options Dialog")
            step_creator.SettingsFile = _StepSettingsFile
            step_creator.ObjectTypes.Curves = True
            step_creator.ObjectTypes.Surfaces = True
            step_creator.ObjectTypes.Solids = True
            session.DeleteUndoMark(
                session.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, "Export to STEP Options"), None)
            undo_mark_id2 = session.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, "Export to STEP Options")
            step_creator.FileSaveFlag = False
            step_creator.ProcessHoldFlag = wait
            step_creator.LayerMask = "1-256"
            step_creator.Commit()
            session.DeleteUndoMark(undo_mark_id2, None)

            if wait:
                nx.print_("Successfully created \"{}\".".format(step_path) if os.path.isfile(step_path)
                          else "Unsuccessfully created \"{}\".".format(step_path))
        except Exception as ex:
            nx.print_exception(ex, "Error when creating Step file for " + str(part_path))

    @staticmethod
    def create_stp_file(part_to_export: str) -> None:
        """
        Static.ProposalDataWizardCreateStpFile - STEP next to the part (same name, .stp), then deletes every
        .log and .def file in that folder.
        """
        # todo

        out_put_path = _change_extension(part_to_export, "stp")

        ProposalDataWizard.step(part_to_export, out_put_path, True)

        directory_name = os.path.dirname(out_put_path)

        if not directory_name:
            return

        for path in _get_files(directory_name):
            if path.endswith(".log") or path.endswith(".def"):
                os.remove(path)

    @staticmethod
    def wavelink(master: NXOpen.Assemblies.Component,
                 simulation_body: NXOpen.Body) -> NXOpen.Features.ExtractFace:
        """
        Static.ProposalDataWizardWavelink - links the simulation body into the master's prototype (assembly
        context xform), then makes the display part the work part again.
        """
        try:
            master_prototype = nx.prototype(master)

            xform = nx.ufsession_.So.CreateXformAssyCtxt(master_prototype.Tag, _NullTag, master.Tag)

            linked_feature = nx.ufsession_.Wave.CreateLinkedBody(simulation_body.Tag, xform, master_prototype.Tag,
                                                                  False)

            nx.ufsession_.Modeling.Update()

            return cast(NXOpen.Features.ExtractFace, nx.tagged_object(linked_feature))
        finally:
            # Restores the display part to be the work part as well.
            nx.set_work_part(nx.display_part())

    @staticmethod
    def construct_proposal_file_path(master: NXOpen.Assemblies.Component, data_level: str, p_level: str) -> str:
        """Static.ProposalDataWizardConstructProposalFilePath - where the proposal part for the master goes."""
        prototype = master.Prototype

        # If the {master} is not loaded, then we need to throw.
        if not isinstance(prototype, NXOpen.Part):
            raise ValueError("The master must be loaded.\r\nParameter name: master")

        # The {master} cannot be set to neither "Entire Part" nor "Empty" reference set.
        if master.ReferenceSet == _RefsetEntirePart or master.ReferenceSet == _RefsetEmpty:
            raise ValueError(
                "The master cannot be set to the \"Entire Part\" nor \"Empty\" reference set.\r\n"
                "Parameter name: master")

        # Get the name of the reference set that the {master} is currently set to.
        reference_set_title = master.ReferenceSet

        # Gets the reference set from the {prototype}.
        reference_set = _find_reference_set(prototype, reference_set_title)

        # Gets the objects from the {referenceSet} that are components.
        components_in_reference_set = [obj for obj in reference_set.AskAllDirectMembers()
                                       if isinstance(obj, NXOpen.Assemblies.Component)]

        # Gets the GFolder that the {master} sits in.
        folder = _GFolder.create_or_null(prototype.FullPath)

        if folder is None:
            raise FileNotFoundError("Master did not reside within a GFolder.")

        # If {componentsInReferenceSet} doesn't have a length of 1, then we need to throw.
        if len(components_in_reference_set) != 1:
            raise ValueError(
                "The reference set \"{}\" in the master doesn't contain exactly one component.\r\n"
                "Parameter name: master".format(reference_set_title))

        # Gets the component that is a descendant of the {master}.
        descendant_of_master = components_in_reference_set[0]

        # Gets the display name of the {descendantOfMaster}.
        display_name = descendant_of_master.DisplayName

        # Gets the part number from the {displayName}.
        part_number = ProposalDataWizard.get_part_number(display_name)

        revised_part_number = "{}{}-{}-{}".format(data_level, p_level, part_number, _todays_date())

        if os.path.isdir("{}\\Proposal".format(folder.DirMathData)):
            return "{}\\Proposal\\{}-{}\\{}.prt".format(folder.DirMathData, _todays_date(), p_level,
                                                       revised_part_number)

        master_directory = os.path.dirname(prototype.FullPath)

        file_path = "{}\\{}-{}\\{}-proposal-data.prt".format(master_directory, _todays_date(), p_level,
                                                             revised_part_number)

        return file_path

    @staticmethod
    def get_part_number(display_name: str) -> str:
        """Static.ProposalDataWizardGetPartNumber - the part number between the TSG/R level and the date."""
        match = re.match(_PartNumberWithDateRegex, display_name)

        if not match:
            # C#: InvalidOperationException
            raise RuntimeError(
                "The display name {} did not match the part number regex.\n".format(display_name) +
                "It must start with (TSG\\R)### and end with a date in the form of YYYY-MM-DD.\n")

        return match.group("partNumber")

    @staticmethod
    def create_proposal_component(proposal_body: NXOpen.Body,
                                  new_part_path: str) -> NXOpen.Assemblies.Component:
        """
        Static.ProposalDataWizardCreateProposalComponent - promotes the body into a new blank-template part at
        new_part_path, on layer 60, absolute origin.
        """
        work = nx.work_part()
        file_new1 = nx.session_.Parts.FileNew()
        # C#: (Part.Units)__work_part_.PartUnits
        file_new1.Units = (NXOpen.Part.Units.Millimeters if work.PartUnits == NXOpen.BasePart.Units.Millimeters
                           else NXOpen.Part.Units.Inches)
        directory_name = os.path.dirname(new_part_path)
        if not directory_name:
            # C#: Path.GetDirectoryName(newPartPath) ?? throw new DirectoryNotFoundException()
            raise FileNotFoundError()

        if not os.path.isdir(directory_name):
            os.makedirs(directory_name)

        file_new1.NewFileName = new_part_path

        # Revision 1.2 - 2017 - 08 - 29
        file_new1.UseBlankTemplate = True
        create_new_component_builder1 = work.AssemblyManager.CreateNewComponentBuilder()
        create_new_component_builder1.ReferenceSet = \
            NXOpen.Assemblies.CreateNewComponentBuilder.ComponentReferenceSetType.Other
        create_new_component_builder1.LayerOption = \
            NXOpen.Assemblies.CreateNewComponentBuilder.ComponentLayerOptionType.AsSpecified
        create_new_component_builder1.NewComponentName = _file_name_without_extension(new_part_path)
        create_new_component_builder1.LayerNumber = 60
        create_new_component_builder1.ComponentOrigin = \
            NXOpen.Assemblies.CreateNewComponentBuilder.ComponentOriginType.Absolute
        create_new_component_builder1.ObjectForNewComponent.Add(proposal_body)
        create_new_component_builder1.NewFile = file_new1
        # Like the C#, the builder is not destroyed when Commit throws.
        create_new_component_builder1.Commit()
        ject = create_new_component_builder1.GetObject()
        create_new_component_builder1.Destroy()
        return cast(NXOpen.Assemblies.Component, ject)

    @staticmethod
    def create_master_reference_set(master_part: NXOpen.Part, reference_set_name: str,
                                    objects_to_add: Sequence[NXOpen.NXObject]) -> NXOpen.ReferenceSet:
        """Static.ProposalDataWizardCreateMasterReferenceSet - a new named reference set holding the objects."""
        # Creates a reference set derived from the prototype of the {master}.
        master_reference_set = master_part.CreateReferenceSet()

        # Sets the name of the {masterReferenceSet} to be the display name of the {proposalComponent}.
        master_reference_set.SetName(reference_set_name)

        # Adds the {proposalComponent} to the {masterReferenceSet}.
        master_reference_set.AddObjectsToReferenceSet(list(objects_to_add))

        return master_reference_set

    @staticmethod
    def create_proposal_reference_set(proposal_part: NXOpen.Part, reference_set_name: str,
                                      objects_to_add: Sequence[NXOpen.NXObject]) -> NXOpen.ReferenceSet:
        """
        Static.ProposalDataWizardCreateProposalReferenceSet - deletes any reference set of that name, then
        creates it afresh holding the objects.
        """
        # Attempts to get the BODY reference set from the {proposalPrototype}.
        temp_body_reference_set = nx.find_reference_set_or_null(proposal_part, reference_set_name)

        # If thw {tempBodyReferenceSet} is not null, then we can delete it.
        if temp_body_reference_set is not None:
            # ReferenceSet.__Delete
            temp_body_reference_set.OwningPart.DeleteReferenceSet(temp_body_reference_set)

        # Creates a reference set derived from the {proposalPrototype}.
        proposal_reference_set = proposal_part.CreateReferenceSet()

        # Names the {proposalReferenceSet} to {referenceSetName}.
        proposal_reference_set.SetName(reference_set_name)

        # Adds the {bodyInProposalPrototype} to the {proposalReferenceSet}.
        proposal_reference_set.AddObjectsToReferenceSet(list(objects_to_add))

        return proposal_reference_set


# ---------------------------------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------------------------------

def _find_reference_set(part: NXOpen.BasePart, refset_title: str) -> NXOpen.ReferenceSet:
    """BasePart.__FindReferenceSet - throws when the part has no reference set of that name."""
    refset = nx.find_reference_set_or_null(part, refset_title)
    if refset is None:
        raise Exception("Could not find reference set with title \"{}\" in part \"{}\".".format(
            refset_title, part.Leaf))
    return refset


def _get_directories_recursive(directory: str) -> List[str]:
    """Directory.GetDirectories(directory, "*", SearchOption.AllDirectories) - throws when it is missing."""
    if not os.path.isdir(directory):
        # C#: DirectoryNotFoundException
        raise FileNotFoundError("Could not find a part of the path '{}'.".format(directory))
    found: List[str] = []
    for root, dir_names, _ in os.walk(directory):
        for dir_name in dir_names:
            found.append(os.path.join(root, dir_name))
    return found


def _get_files(directory: str) -> List[str]:
    """Directory.GetFiles(directory) - the folder's files (not recursive), as full paths."""
    return [os.path.join(directory, name) for name in os.listdir(directory)
            if os.path.isfile(os.path.join(directory, name))]


def _file_name_without_extension(path: str) -> str:
    """Path.GetFileNameWithoutExtension - the leaf up to its last '.', even for a leading dot."""
    name = os.path.basename(path)
    index = name.rfind(".")
    return name[:index] if index >= 0 else name


def _change_extension(path: str, extension: str) -> str:
    """Path.ChangeExtension(path, extension) - replaces (or appends) the leaf's extension."""
    name = os.path.basename(path)
    index = name.rfind(".")
    stem = path[:len(path) - len(name) + index] if index >= 0 else path
    return "{}.{}".format(stem, extension)


def _todays_date() -> str:
    """Extensions.TodaysDate - yyyy-MM-dd."""
    today = datetime.date.today()
    return "{}-{:02d}-{:02d}".format(today.year, today.month, today.day)


class _GFolder(object):
    """GFolder (src\\Utilities\\GFolder.cs) - only the members ProposalDataWizard reads."""

    def __init__(self, dir_job: str, customer_number: str) -> None:
        self.DirJob = dir_job
        self.CustomerNumber = customer_number

    @property
    def DirMathData(self) -> str:
        """GFolder.DirMathData"""
        return "{}\\Math Data".format(self.DirJob)

    @staticmethod
    def create(job_folder: str) -> "_GFolder":
        """GFolder.Create(string)"""
        split = job_folder.split("\\")

        if len(split) < 3:
            # C#: IndexOutOfRangeException(jobFolder)
            raise IndexError(job_folder)

        directory = "{}\\{}\\{}".format(split[0], split[1], split[2])
        number = _GFolder._job_number(directory, split[2])
        if number:
            return _GFolder(directory, number)

        # Not the C#: a job copied below the usual depth (G:\CTS\junk\Mark B\006073\006073-010\...) has no job
        # number in the third piece, so the job folder is the first deeper folder whose name starts with one.
        for i in range(3, len(split) - 1):
            deeper = "\\".join(split[:i + 1])
            number = _GFolder._job_number(deeper, split[i])
            if number:
                return _GFolder(deeper, number)

        if "\\cts\\" not in directory.lower():
            return _GFolder(directory, "")

        raise ValueError("Could not make GFolder from '{}'".format(job_folder))

    @staticmethod
    def _job_number(directory: str, leaf: str) -> Optional[str]:
        """GFolder.Create's rules for the job folder `directory` named `leaf`: its customer number, or None."""
        if "\\cts\\" not in directory.lower():
            match0 = re.match(r"^(?P<num_0>\d{2,})", leaf)
            return match0.group("num_0") if match0 else None

        if _int_try_parse(leaf):
            return leaf

        match = re.match(r"^(?P<cts_number>\d{2,}) \([A-Z]+-[xX]+\)", leaf)
        if match:
            return match.group("cts_number")

        match = re.match(r"^(?P<cts_number>\d{2,}) \([A-Za-z]+-(?P<customer_number>\d+)\)", leaf)
        if match:
            return match.group("customer_number")

        match = re.match(r"^(?P<customer_number>\d{2,})", leaf)
        if match:
            return match.group("customer_number")

        return None

    @staticmethod
    def create_or_null(work_part_path: str) -> Optional["_GFolder"]:
        """GFolder.create_or_null(Part) - prints the exception and returns None."""
        try:
            return _GFolder.create(work_part_path)
        except Exception as ex:
            nx.print_exception(ex, "Exception caught for GFolder '{}'".format(work_part_path))
            return None


def _int_try_parse(text: str) -> bool:
    """int.TryParse(string, out _) with the default NumberStyles.Integer: optional surrounding whitespace, an
    optional sign, digits, and the value must fit in an Int32."""
    match = re.match(r"^\s*([+-]?\d+)\s*$", text)
    if match is None:
        return False
    try:
        value = int(match.group(1))
    except ValueError:
        return False
    return -2147483648 <= value <= 2147483647

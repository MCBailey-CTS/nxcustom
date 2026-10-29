"""
Python port of the static methods behind the UpsizeDownsizeFasteners form (src\\UFuncs\\UpsizeDownsizeFasteners.cs),
which now live in src\\Static\\UpsizeDownsizeFasteners.cs:

- UpsizeDownsizeLoadShcs                            -> UpsizeDownsizeFasteners.load_shcs
- UpsizeDownsizeCreateUpDownPairsDiameterLengths    -> _create_up_down_pairs_diameter_lengths
- UpsizeDownsizeCreateUpDownPairs                   -> _create_up_down_pairs

**Not wired** - btnSelectDetails_Click still calls the C#. **Never run in NX.**

None of this touches NX: it scans the G:\\0Library fastener folders and the preferred-diameter lists and pairs
each fastener with its next size down and up. It is ported anyway because it is the whole of what the UFunc
does today (the per-detail loop after the selection in btnSelectDetails_Click is empty and unreachable).

Like the C#, load_shcs builds three maps (all / TSG preferred / GM preferred) and only writes the TSG one, to
stdout (Console.WriteLine in the C#). Under NX, stdout may land in the syslog or the listing window rather than
nowhere - not checked.

Differences from the C#:
- Directory.GetFiles(..., AllDirectories) is mimicked with os.walk: a folder's files (sorted case-insensitively,
  as NTFS returns them) before its subfolders, depth first. The diameter neighbours in
  _create_up_down_pairs_diameter_lengths follow that first-seen order, so the order matters.
- The "*.prt" / "*-screw.prt" patterns are matched with fnmatch, case-insensitively. .NET's 3-character-extension
  quirk (where "*.prt" would also match "x.prtx") is not reproduced.
"""

from __future__ import annotations

import fnmatch
import os
import re
from typing import Dict, Iterator, List, Optional, Tuple

# No NXOpen and no tsg_nx: nothing here touches NX, so there is no sys.path insert either.

_PreferredDiametersPath = r"U:\nxFiles\UfuncFiles\AddFastenersPreferredDiameters.txt"
_PreferredGmDiametersPath = r"U:\nxFiles\UfuncFiles\AddFastenersPreferredDiametersGm.txt"

# fastener path -> [down, up]; either entry may be None at the end of a run (CreateUpDownPairs).
_Pair = Tuple[str, List[Optional[str]]]


def _cs_int_parse(text: str) -> int:
    """int.Parse - unlike Python's int(), rejects '_' digit separators."""
    if not re.fullmatch(r"\s*[+-]?[0-9]+\s*", text):
        raise ValueError("Input string was not in a correct format.")
    return int(text)


def _get_files(directory: str, pattern: str, all_directories: bool) -> List[str]:
    """Directory.GetFiles(directory, pattern, TopDirectoryOnly / AllDirectories) - see the module docstring."""
    if not os.path.isdir(directory):
        # Directory.GetFiles throws DirectoryNotFoundException.
        raise FileNotFoundError("Could not find a part of the path '{}'.".format(directory))

    files: List[str] = []
    pattern = pattern.lower()

    for root, dirs, names in os.walk(directory):
        dirs.sort(key=str.upper)
        files.extend(os.path.join(root, name) for name in sorted(names, key=str.upper)
                     if fnmatch.fnmatchcase(name.lower(), pattern))
        if not all_directories:
            break

    return files


def _read_all_lines(path: str) -> List[str]:
    """File.ReadAllLines"""
    with open(path, encoding="utf-8-sig") as f:
        return f.read().splitlines()


def _sorted_jacks(directory: str, pattern: str, suffix: str) -> List[str]:
    """The OrderBy(int.Parse(file name minus suffix, '_' removed)) the C# applies to each jack folder."""
    return sorted(_get_files(directory, pattern, False),
                  key=lambda s: _cs_int_parse(os.path.basename(s).replace(suffix, "").replace("_", "")))


def _create_up_down_pairs_diameter_lengths(fasteners: List[str]) -> Iterator[_Pair]:
    """
    Static.UpsizeDownsizeCreateUpDownPairsDiameterLengths - pairs each {dia}-shcs/dwl-{length} with the
    previous/next diameter (in first-seen order) at the nearest length at-or-below / at-or-above.
    A generator, like the C# iterator, so nothing throws until it is enumerated.
    """
    d: Dict[int, Dict[int, str]] = {}

    for path in fasteners:
        leaf = (os.path.splitext(os.path.basename(path))[0]
                .replace("-shcs-", "-")
                .replace("-dwl-", "-")
                .replace("mm", "")
                .replace("-2x", ""))

        split = leaf.split("-")

        diameter = _cs_int_parse(split[0])
        length = _cs_int_parse(split[1])

        if diameter not in d:
            d[diameter] = {}

        d[diameter][length] = path

    diameters = list(d.keys())

    for diameter in d.keys():
        index = diameters.index(diameter)

        down_diameter = diameter
        up_diameter = diameter

        # looking down
        if index > 0:
            down_diameter = diameters[index - 1]

        # looking up
        if index < len(diameters) - 1:
            up_diameter = diameters[index + 1]

        for length in d[diameter].keys():
            down_lengths_keys = list(reversed(list(d[down_diameter].keys())))
            up_lengths_keys = list(d[up_diameter].keys())
            # FirstOrDefault on an int sequence -> 0 when nothing matches.
            down_length = next((ln for ln in down_lengths_keys if ln <= length), 0)
            up_length = next((ln for ln in up_lengths_keys if ln >= length), 0)

            if down_length == 0:
                down_length = down_lengths_keys[0]

            if up_length == 0:
                up_length = up_lengths_keys[-1]

            yield (d[diameter][length], [d[down_diameter][down_length], d[up_diameter][up_length]])


def _create_up_down_pairs(fasteners: List[str]) -> Iterator[_Pair]:
    """Static.UpsizeDownsizeCreateUpDownPairs - neighbours in list order; None past either end."""
    for i in range(len(fasteners)):
        if i == 0:
            # Raises IndexError for a one-item list, as the C# fasteners[i + 1] does.
            yield (fasteners[i], [None, fasteners[i + 1]])
            continue

        if i == len(fasteners) - 1:
            yield (fasteners[i], [fasteners[i - 1], None])
            continue

        yield (fasteners[i], [fasteners[i - 1], fasteners[i + 1]])


def _add_all(target: Dict[str, List[Optional[str]]], pairs: Iterator[_Pair]) -> None:
    """Dictionary.Add per pair - raises on a duplicate key like the C# ArgumentException."""
    for key, value in pairs:
        if key in target:
            raise KeyError("An item with the same key has already been added.")
        target[key] = value


class UpsizeDownsizeFasteners(object):

    @staticmethod
    def load_shcs() -> None:
        """Static.UpsizeDownsizeLoadShcs"""
        english_shcs = _get_files("G:\\0Library\\Fasteners\\English\\SocketHeadCapScrews", "*.prt", True)
        english_shcs_2x = _get_files("G:\\0Library\\Fasteners\\English\\SocketHeadCapScrews-2x", "*.prt", True)
        english_dowels = _get_files("G:\\0Library\\Fasteners\\English\\Dowels", "*.prt", False)

        english_jig_jacks = _sorted_jacks("G:\\0Library\\Fasteners\\English\\JackScrews", "*-screw-tsg.prt",
                                          "-jck-screw-tsg.prt")

        english_jack_screws = _sorted_jacks("G:\\0Library\\Fasteners\\English\\JackScrews", "*-screw.prt",
                                            "-jck-screw.prt")

        metric_shcs = _get_files("G:\\0Library\\Fasteners\\Metric\\SocketHeadCapScrews", "*.prt", True)
        metric_shcs_2x = _get_files("G:\\0Library\\Fasteners\\Metric\\SocketHeadCapScrews-2x", "*.prt", True)
        metric_dowels = _get_files("G:\\0Library\\Fasteners\\Metric\\Dowels", "*.prt", False)
        metric_jig_jacks = _sorted_jacks("G:\\0Library\\Fasteners\\Metric\\JackScrews", "*-screw-tsg.prt",
                                         "mm-jck-screw-tsg.prt")

        metric_jack_screws = _sorted_jacks("G:\\0Library\\Fasteners\\Metric\\JackScrews", "*-screw.prt",
                                           "mm-jck-screw.prt")

        preferred = _read_all_lines(_PreferredDiametersPath)
        preferred_gm = _read_all_lines(_PreferredGmDiametersPath)

        english_shcs_tsg = [s for s in preferred if "mm" not in s and "-2x" not in s]
        english_shcs_tsg_2x = [s for s in preferred if "mm" not in s and "-2x" in s]
        metric_shcs_tsg = [s for s in preferred if "mm" in s and "-2x" not in s]
        metric_shcs_tsg_2x = [s for s in preferred if "mm" in s and "-2x" in s]

        english_shcs_gm = [s for s in preferred_gm if "mm" not in s and "-2x" not in s]
        english_shcs_gm_2x = [s for s in preferred_gm if "mm" not in s and "-2x" in s]
        metric_shcs_gm = [s for s in preferred_gm if "mm" in s and "-2x" not in s]
        metric_shcs_gm_2x = [s for s in preferred_gm if "mm" in s and "-2x" in s]

        dict_all: Dict[str, List[Optional[str]]] = {}
        dict_tsg: Dict[str, List[Optional[str]]] = {}
        dict_gm: Dict[str, List[Optional[str]]] = {}

        _add_all(dict_all, _create_up_down_pairs(english_jig_jacks))
        _add_all(dict_all, _create_up_down_pairs(english_jack_screws))
        _add_all(dict_all, _create_up_down_pairs(metric_jig_jacks))
        _add_all(dict_all, _create_up_down_pairs(metric_jack_screws))
        _add_all(dict_all, _create_up_down_pairs_diameter_lengths(english_dowels))
        _add_all(dict_all, _create_up_down_pairs_diameter_lengths(metric_dowels))

        for key in dict_all.keys():
            dict_gm[key] = dict_all[key]
            dict_tsg[key] = dict_all[key]

        _add_all(dict_all, _create_up_down_pairs_diameter_lengths(english_shcs))
        _add_all(dict_all, _create_up_down_pairs_diameter_lengths(metric_shcs))
        _add_all(dict_all, _create_up_down_pairs_diameter_lengths(english_shcs_2x))
        _add_all(dict_all, _create_up_down_pairs_diameter_lengths(metric_shcs_2x))

        _add_all(dict_tsg, _create_up_down_pairs_diameter_lengths(english_shcs_tsg))
        _add_all(dict_tsg, _create_up_down_pairs_diameter_lengths(metric_shcs_tsg))
        _add_all(dict_tsg, _create_up_down_pairs_diameter_lengths(english_shcs_tsg_2x))
        _add_all(dict_tsg, _create_up_down_pairs_diameter_lengths(metric_shcs_tsg_2x))

        _add_all(dict_gm, _create_up_down_pairs_diameter_lengths(english_shcs_gm))
        _add_all(dict_gm, _create_up_down_pairs_diameter_lengths(metric_shcs_gm))
        _add_all(dict_gm, _create_up_down_pairs_diameter_lengths(english_shcs_gm_2x))
        _add_all(dict_gm, _create_up_down_pairs_diameter_lengths(metric_shcs_gm_2x))

        for key in dict_tsg.keys():
            # Console.WriteLine("\t" + null) prints a bare tab; str(None) would print "None".
            print(key)
            print("\t" + (dict_tsg[key][0] or ""))
            print("\t" + (dict_tsg[key][1] or ""))


def main() -> None:
    """Standalone entry (File -> Execute -> NX Open) - prints the fastener library dictionary, as load_shcs does."""
    UpsizeDownsizeFasteners.load_shcs()


if __name__ == "__main__":
    main()

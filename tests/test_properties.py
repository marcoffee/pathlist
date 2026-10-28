from __future__ import annotations

import os
import unittest
from typing import Final, List


if os.name != "posix":
    raise unittest.SkipTest("the tests assume posix paths")

try:
    from hypothesis import given, settings
    from hypothesis import strategies as st

except ImportError:
    raise unittest.SkipTest("hypothesis is not installed") from None

from test_pathlist import _ARGPARSE_ERROR, _DOUBLE_SLASH_IS_ROOT, _PathlistTestCase


# no `o`, so a random option can never abbreviate --output and write files outside the test
_ALPHABET: Final = "ab/. -é"
_DOUBLE_SLASH_CHOICES: Final = ("auto", "root", "keep")

# every option but --output, which would write files where the generated text points, plus the
# --double-slashes values, which the alphabet cannot spell
_TOKENS: Final = (
    "-e", "--exclude", "-s", "--separator", "--input-separator", "--output-separator",
    "--double-slashes", "-d", "--dedup", "--dedup-abs", "--abs", "--rel", "--resolve-symlinks",
    "--no-remove-empty", "--no-trim-paths", "--", "-h", *_DOUBLE_SLASH_CHOICES,
)

_entry = st.text(alphabet=_ALPHABET, max_size=128)
_option_value = _entry.filter(lambda text: not text.startswith("-"))
_entries = st.lists(_entry, max_size=128)
_excludes = st.lists(_option_value, min_size=1, max_size=16)
_double_slash_choice = st.sampled_from(_DOUBLE_SLASH_CHOICES)
_argv = st.lists(st.one_of(st.sampled_from(_TOKENS), st.text(alphabet=_ALPHABET)), max_size=64)

_property_settings = settings(deadline=None, max_examples=256)

def _folds (mode: str) -> bool:
    """
    Tells whether a --double-slashes mode folds a leading `//` into `/` on the running system.

    :param mode: The --double-slashes value.

    :return: Whether `//` is folded.
    """
    return (mode == "root") or ((mode == "auto") and _DOUBLE_SLASH_IS_ROOT)

def _location (path: str, folds: bool) -> str:
    """
    Normalizes `path` to the location it names.

    :param path: The path.
    :param folds: Whether a leading `//` names the root, POSIX leaving it implementation-defined.

    :return: The normalized path.
    """
    normalized = os.path.normpath(path)

    if folds and normalized.startswith("//"):
        return normalized[1 :]

    return normalized

def _normpath (path: str, folds: bool) -> str:
    """
    Normalizes `path` the way pathlist compares entries.

    :param path: The entry.
    :param folds: Whether a leading `//` names the root.

    :return: The location the entry names, or `""` for an empty one.
    """
    return "" if (path == "") else _location(path, folds)

def _kept (entries: List[str]) -> List[str]:
    """
    Applies the default trimming and empty-entry removal to `entries`.

    :param entries: The raw entries.

    :return: The entries pathlist keeps by default.
    """
    return [entry.strip() for entry in entries if (entry.strip() != "")]

class TestProperties (_PathlistTestCase):
    @_property_settings
    @given(entries=_entries)
    def test_default_keeps_entries (self, entries: List[str]) -> None:
        """
        Without options, the output is the trimmed, non-empty entries in their input order.
        """
        self.assertEqual(self.output("--", ":".join(entries)), ":".join(_kept(entries)))

    @_property_settings
    @given(entries=_entries, excludes=_excludes, mode=_double_slash_choice)
    def test_exclude (self, entries: List[str], excludes: List[str], mode: str) -> None:
        """
        -e removes exactly the entries whose normalized form matches an excluded path.
        """
        excluded = {_normpath(exclude, _folds(mode)) for exclude in excludes}

        expected = [
            entry
            for entry in _kept(entries)
            if (_normpath(entry, _folds(mode)) not in excluded)
        ]

        self.assertEqual(
            self.output("-e", *excludes, "--double-slashes", mode, "--", ":".join(entries)),
            ":".join(expected),
        )

    @_property_settings
    @given(entries=_entries, mode=_double_slash_choice)
    def test_dedup (self, entries: List[str], mode: str) -> None:
        """
        -d keeps the first entry of each normalized form, in input order.
        """
        seen = set()
        expected = []

        for entry in _kept(entries):
            if (key := _normpath(entry, _folds(mode))) not in seen:
                seen.add(key)
                expected.append(entry)

        self.assertEqual(
            self.output("-d", "--double-slashes", mode, "--", ":".join(entries)),
            ":".join(expected),
        )

    @_property_settings
    @given(entries=_entries, mode=_double_slash_choice)
    def test_dedup_idempotent (self, entries: List[str], mode: str) -> None:
        """
        Deduplicating an already deduplicated list changes nothing.
        """
        once = self.output("-d", "--double-slashes", mode, "--", ":".join(entries))

        self.assertEqual(self.output("-d", "--double-slashes", mode, "--", once), once)

    @_property_settings
    @given(entries=_entries, mode=_double_slash_choice)
    def test_abs (self, entries: List[str], mode: str) -> None:
        """
        --abs makes every entry absolute, pointing at the same place as its input entry.
        """
        output = self.output(
            "--abs", "--double-slashes", mode, "--", ":".join(entries), cwd=self.tmp_path,
        )

        expected = [os.path.join(self.tmp_path, entry) for entry in _kept(entries)]

        self.assertEqual(
            [_location(entry, _folds(mode)) for entry in output.split(":") if (entry != "")],
            [_location(entry, _folds(mode)) for entry in expected],
        )

    @_property_settings
    @given(entries=_entries, start=_option_value)
    def test_rel (self, entries: List[str], start: str) -> None:
        """
        --rel entries joined onto the start directory point at the same place as their inputs.
        """
        start_path = os.path.join(self.tmp_path, start)
        output = self.output("--rel", start_path, "--", ":".join(entries), cwd=self.tmp_path)
        expected = [os.path.join(self.tmp_path, entry) for entry in _kept(entries)]

        # a relative path cannot name a `//` root, so --rel always folds it, whatever the mode
        self.assertEqual(
            [
                _location(os.path.join(start_path, entry), folds=True)
                for entry in output.split(":")
                if (entry != "")
            ],
            [_location(entry, folds=True) for entry in expected],
        )

    @_property_settings
    @given(argv=_argv)
    def test_any_arguments (self, argv: List[str]) -> None:
        """
        Any combination of arguments either succeeds or is refused by argparse, never crashing.
        """
        result = self.run_script(*argv, cwd=self.tmp_path)

        self.assertIn(result.returncode, (0, _ARGPARSE_ERROR), result.stderr)

if __name__ == "__main__":
    unittest.main()

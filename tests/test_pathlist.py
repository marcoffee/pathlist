from __future__ import annotations

import io
import os
import runpy
import subprocess
import sys
import tempfile
import unittest
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Final, NamedTuple, Sequence, Tuple
from unittest import mock


if os.name != "posix":
    raise unittest.SkipTest("the tests assume posix paths")

_SCRIPT: Final = Path(__file__).resolve().parent.parent / "pathlist"
_ARGPARSE_ERROR: Final = 2

def _double_slash_is_root () -> bool:
    """
    Asks the system whether a leading `//` names the root, independently of the script, since this
    is the fact `--double-slashes auto` is specified against.

    :return: Whether `//` and `/` are the same directory, `False` when it cannot be told.
    """
    try:
        return os.path.samefile("/", "//")

    except OSError:
        return False

_DOUBLE_SLASH_IS_ROOT: Final = _double_slash_is_root()

# (id, arguments, output when `//` is the root, output when it is not)
_DOUBLE_SLASH_CASES: Final[tuple[tuple[str, tuple[str, ...], str, str], ...]] = (
    ("exclude-input", ("//a:/b", "-e", "/a"), "/b", "//a:/b"),
    ("exclude-value", ("/a:/b", "-e", "//a"), "/b", "/a:/b"),
    ("dedup", ("//a:/a", "-d"), "//a", "//a:/a"),
    ("dedup-abs", ("//a:/a", "--dedup-abs"), "//a", "//a:/a"),
    ("abs", ("//usr/lib", "--abs"), "/usr/lib", "//usr/lib"),
    ("rel", ("//a:/usr/b", "--rel", "/usr"), "../a:b", "//a:b"),
    ("rel-from-double-slash", ("//a/x:/b", "--rel", "//a"), "x:../b", "x:/b"),
    ("rel-exclude", ("//a:/usr/b", "--rel", "/usr", "-e", "//a"), "b", "b"),
    ("rel-dedup-abs", ("//a:/usr/b://a/", "--rel", "/usr", "--dedup-abs"), "../a:b", "//a:b"),
    ("abs-resolve-symlinks", ("//usr/lib", "--abs", "--resolve-symlinks"), "/usr/lib", "//usr/lib"),
    (
        "dedup-abs-resolve-symlinks",
        ("//usr/lib:/usr/lib", "--dedup-abs", "--resolve-symlinks"),
        "//usr/lib",
        "//usr/lib:/usr/lib",
    ),
)

# (id, arguments, expected output)
_Case = Tuple[str, Tuple[str, ...], str]

_README_CASES: Final[tuple[_Case, ...]] = (
    ("remove-a-directory", ("/a:/opt/old/lib:/b", "-e", "/opt/old/lib"), "/a:/b"),
    (
        "prepend-dedup",
        ("/home/user/.local/bin", "/usr/bin:/home/user/.local/bin:/bin", "-d"),
        "/home/user/.local/bin:/usr/bin:/bin",
    ),
    ("append-to-empty", ("", "/opt/new/lib/pkgconfig"), "/opt/new/lib/pkgconfig"),
    (
        "append",
        ("/usr/lib:/usr/local/lib/pkgconfig", "/opt/new/lib/pkgconfig"),
        "/usr/lib:/usr/local/lib/pkgconfig:/opt/new/lib/pkgconfig",
    ),
    ("relative-to", ("/usr/lib", "/usr/local/lib", "--rel", "/usr"), "lib:local/lib"),
    ("space-separator", ("/a:/b", "--output-separator", " "), "/a /b"),
    ("linebreak-separator", ("/a:/b:/c", "--output-separator", "\n"), "/a\n/b\n/c"),
)

_JOIN_CASES: Final[tuple[_Case, ...]] = (
    ("empty", ("",), ""),
    ("single-path", ("/a",), "/a"),
    ("concatenated-in-order", ("/a", "/b:/c", "/d"), "/a:/b:/c:/d"),
    ("flag-between-inputs", ("/a:/b", "-d", "/c", "/a"), "/a:/b:/c"),
    ("leading-dash-after-double-dash", ("--", "-a:/b"), "-a:/b"),
)

_EXCLUDE_CASES: Final[tuple[_Case, ...]] = (
    ("trailing-slash-in-input", ("/a:/b/:/c", "-e", "/b"), "/a:/c"),
    ("trailing-slash-in-exclude", ("/a:/b:/c", "-e", "/b/"), "/a:/c"),
    ("normalized", ("/a:/x/../b:/c", "-e", "/b"), "/a:/c"),
    ("several", ("/a:/b:/c", "-e", "/a", "/c"), "/b"),
    ("absent", ("/a:/b", "-e", "/z"), "/a:/b"),
    ("every-occurrence", ("/a:/b", "/a", "-e", "/a"), "/b"),
)

_DEDUP_CASES: Final[tuple[_Case, ...]] = (
    ("first-occurrence-wins", ("/a:/b:/a", "-d"), "/a:/b"),
    ("trailing-slash", ("/a:/a/:/b", "-d"), "/a:/b"),
    ("normalized", ("/a:/x/../a", "-d"), "/a"),
)

class _Result (NamedTuple):
    returncode: int
    stdout: str
    stderr: str

class _PathlistTestCase (unittest.TestCase):
    def setUp (self) -> None:
        """
        Creates a temporary directory, removed after the test.
        """
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        self.tmp_path = Path(tmp_dir.name).resolve()

    def run_script (self, *args: str, cwd: Path | None = None) -> _Result:
        """
        Runs the pathlist script in-process, as `__main__`.

        :param args: The command line arguments.
        :param cwd: The working directory during the run (default: the current one).

        :return: The exit code and the captured standard output and error.
        """
        stdout = io.StringIO()
        stderr = io.StringIO()
        previous_cwd = os.getcwd()
        returncode = 0

        if cwd is not None:
            os.chdir(cwd)

        try:
            # a parenthesized multi-item `with` only parses from python 3.10
            with ExitStack() as stack:
                stack.enter_context(mock.patch.object(sys, "argv", [str(_SCRIPT), *args]))
                stack.enter_context(redirect_stdout(stdout))
                stack.enter_context(redirect_stderr(stderr))
                runpy.run_path(str(_SCRIPT), run_name="__main__")

        except SystemExit as exc:
            returncode = 0 if (exc.code is None) else int(exc.code)

        finally:
            os.chdir(previous_cwd)

        return _Result(returncode=returncode, stdout=stdout.getvalue(), stderr=stderr.getvalue())

    def output (self, *args: str, cwd: Path | None = None) -> str:
        """
        Runs the pathlist script and returns its output, failing when it exits non-zero.

        :param args: The command line arguments.
        :param cwd: The working directory during the run (default: the current one).

        :return: The standard output.
        """
        result = self.run_script(*args, cwd=cwd)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def check_cases (self, cases: Sequence[_Case]) -> None:
        """
        Checks each case as its own subtest, so every failing case is reported.

        :param cases: The (id, arguments, expected output) cases.
        """
        for case_id, args, expected in cases:
            with self.subTest(case=case_id):
                self.assertEqual(self.output(*args), expected)

    def make_symlink (self) -> None:
        """
        Creates the `real` directory and a `link` symlink to it inside the temporary directory.
        """
        (self.tmp_path / "real").mkdir()
        (self.tmp_path / "link").symlink_to(self.tmp_path / "real")

class TestStandalone (unittest.TestCase):
    def test_runs_as_script (self) -> None:
        """
        The file runs on its own interpreter, outside the test process.
        """
        process = subprocess.run(
            (sys.executable, str(_SCRIPT), "/a:/b:/c", "-e", "/b"),
            capture_output=True,
            check=False,
            text=True,
        )

        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(process.stdout, "/a:/c")

    def test_help (self) -> None:
        """
        --help exits successfully and names the program after the file.
        """
        process = subprocess.run(
            (sys.executable, str(_SCRIPT), "--help"),
            capture_output=True,
            check=False,
            text=True,
        )

        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertTrue(process.stdout.startswith("usage: pathlist "))

class TestReadme (_PathlistTestCase):
    def test_examples (self) -> None:
        """
        Every README example prints the output the README documents.
        """
        self.check_cases(_README_CASES)

    def test_inputs_last (self) -> None:
        """
        Options placed before `--` apply to the inputs placed after it.
        """
        self.assertEqual(self.output("-e", "/b", "--", "/a:/b", "/c"), "/a:/c")

class TestInputs (_PathlistTestCase):
    def test_join (self) -> None:
        """
        pathlist splits each input on the separator and joins all of them in order.
        """
        self.check_cases(_JOIN_CASES)

    def test_missing_input (self) -> None:
        """
        pathlist refuses a call without inputs.
        """
        self.assertEqual(self.run_script("-d").returncode, _ARGPARSE_ERROR)

    def test_exclude_swallows_trailing_input (self) -> None:
        """
        An input placed right after `-e` is taken as an exclude, leaving no inputs.
        """
        self.assertEqual(self.run_script("-e", "/b", "/a:/b").returncode, _ARGPARSE_ERROR)

class TestEmptyAndTrim (_PathlistTestCase):
    def test_empty_entries_removed (self) -> None:
        """
        Empty entries are dropped by default.
        """
        self.assertEqual(self.output("::/a::/b:"), "/a:/b")

    def test_empty_entries_kept (self) -> None:
        """
        --no-remove-empty keeps empty entries empty, never turning them into `.`.
        """
        self.assertEqual(self.output("/a::/b", "--no-remove-empty"), "/a::/b")

    def test_entries_trimmed (self) -> None:
        """
        Surrounding whitespace is stripped from every entry by default.
        """
        self.assertEqual(self.output(" /a : /b "), "/a:/b")

    def test_entries_not_trimmed (self) -> None:
        """
        --no-trim-paths keeps the whitespace around each entry.
        """
        self.assertEqual(self.output(" /a : /b ", "--no-trim-paths"), " /a : /b ")

    def test_blank_entry_removed_after_trim (self) -> None:
        """
        An entry holding only whitespace is empty once trimmed, so it is dropped.
        """
        self.assertEqual(self.output("/a:  :/b"), "/a:/b")

class TestSeparators (_PathlistTestCase):
    def test_separator (self) -> None:
        """
        -s sets both the input and the output separator.
        """
        self.assertEqual(self.output("/a;/b", "/c", "-s", ";"), "/a;/b;/c")

    def test_input_separator (self) -> None:
        """
        --input-separator overrides -s for splitting only.
        """
        self.assertEqual(self.output("/a,/b", "--input-separator", ","), "/a:/b")

    def test_output_separator (self) -> None:
        """
        --output-separator overrides -s for joining only.
        """
        self.assertEqual(self.output("/a;/b", "-s", ";", "--output-separator", ","), "/a,/b")

    def test_empty_input_separator (self) -> None:
        """
        An empty input separator is refused, since the input cannot be split on it.
        """
        result = self.run_script("/a", "--input-separator", "")

        self.assertEqual(result.returncode, _ARGPARSE_ERROR)
        self.assertIn("input separator cannot be empty", result.stderr)

    def test_empty_output_separator (self) -> None:
        """
        An empty output separator concatenates the entries.
        """
        self.assertEqual(self.output("/a:/b", "--output-separator", ""), "/a/b")

class TestExclude (_PathlistTestCase):
    def test_exclude (self) -> None:
        """
        -e removes every entry equal to an excluded path after normalization.
        """
        self.check_cases(_EXCLUDE_CASES)

    def test_output_keeps_spelling (self) -> None:
        """
        Entries that are not excluded are printed as written, not normalized.
        """
        self.assertEqual(self.output("/a/:./b:/c", "-e", "/c"), "/a/:./b")

    def test_exclude_empty (self) -> None:
        """
        Excluding the empty string removes the empty entries kept by --no-remove-empty.
        """
        self.assertEqual(self.output("/a::/b", "--no-remove-empty", "-e", ""), "/a:/b")

class TestDedup (_PathlistTestCase):
    def test_dedup (self) -> None:
        """
        -d keeps the first occurrence of each entry, comparing them after normalization.
        """
        self.check_cases(_DEDUP_CASES)

    def test_no_dedup_by_default (self) -> None:
        """
        Duplicates are kept unless deduplication is requested.
        """
        self.assertEqual(self.output("/a:/b:/a"), "/a:/b:/a")

    def test_dedup_abs_relative_and_absolute (self) -> None:
        """
        --dedup-abs treats a relative entry and its absolute form as the same path.
        """
        self.assertEqual(
            self.output(f"lib:{self.tmp_path}/lib", "--dedup-abs", cwd=self.tmp_path),
            "lib",
        )

    def test_dedup_abs_keeps_symlink (self) -> None:
        """
        --dedup-abs keeps a symlink and its target apart unless --resolve-symlinks is given.
        """
        self.make_symlink()

        self.assertEqual(
            self.output(f"{self.tmp_path}/link:{self.tmp_path}/real", "--dedup-abs"),
            f"{self.tmp_path}/link:{self.tmp_path}/real",
        )

    def test_dedup_abs_resolves_symlink (self) -> None:
        """
        --dedup-abs --resolve-symlinks treats a symlink and its target as the same path, without
        converting the entries it keeps.
        """
        self.make_symlink()

        self.assertEqual(
            self.output("link:real", "--dedup-abs", "--resolve-symlinks", cwd=self.tmp_path),
            "link",
        )

    def test_dedup_abs_resolves_symlink_with_abs (self) -> None:
        """
        --abs --dedup-abs --resolve-symlinks merges a symlink into its resolved target.
        """
        self.make_symlink()

        self.assertEqual(
            self.output(
                f"{self.tmp_path}/link:{self.tmp_path}/real",
                "--abs", "--dedup-abs", "--resolve-symlinks",
            ),
            f"{self.tmp_path}/real",
        )

    def test_dedup_abs_keeps_empty_apart (self) -> None:
        """
        --dedup-abs never merges an empty entry with the working directory.
        """
        self.assertEqual(
            self.output(".::", "--dedup-abs", "--no-remove-empty", cwd=self.tmp_path),
            ".:",
        )

    def test_dedup_abs_after_exclude (self) -> None:
        """
        -e is applied before --dedup-abs, so excluding a path never removes a symlink to it that
        the exclude alone would keep.
        """
        self.make_symlink()

        self.assertEqual(
            self.output(
                "real:link", "--dedup-abs", "--resolve-symlinks", "-e", "real", cwd=self.tmp_path,
            ),
            "link",
        )

    def test_dedup_abs_with_abs (self) -> None:
        """
        --dedup-abs still deduplicates when --abs already made the entries absolute.
        """
        self.assertEqual(
            self.output(f"lib:{self.tmp_path}/lib", "--abs", "--dedup-abs", cwd=self.tmp_path),
            f"{self.tmp_path}/lib",
        )

class TestAbsolute (_PathlistTestCase):
    def test_abs (self) -> None:
        """
        --abs makes relative entries absolute against the working directory.
        """
        self.assertEqual(
            self.output("lib:/usr/lib", "--abs", cwd=self.tmp_path),
            f"{self.tmp_path}/lib:/usr/lib",
        )

    def test_abs_resolves_parent_of_symlink (self) -> None:
        """
        --abs --resolve-symlinks resolves a symlink before the `..` after it, as the kernel does,
        instead of cancelling both lexically.
        """
        (self.tmp_path / "real" / "sub").mkdir(parents=True)
        (self.tmp_path / "link").symlink_to(self.tmp_path / "real" / "sub")

        self.assertEqual(
            self.output("link/..", "--abs", "--resolve-symlinks", cwd=self.tmp_path),
            f"{self.tmp_path}/real",
        )

    def test_abs_keeps_symlinks (self) -> None:
        """
        --abs keeps symlinks unless --resolve-symlinks is given.
        """
        self.make_symlink()

        self.assertEqual(self.output("link", "--abs", cwd=self.tmp_path), f"{self.tmp_path}/link")

    def test_abs_resolves_symlinks (self) -> None:
        """
        --abs --resolve-symlinks replaces symlinks with their targets.
        """
        self.make_symlink()

        self.assertEqual(
            self.output("link", "--abs", "--resolve-symlinks", cwd=self.tmp_path),
            f"{self.tmp_path}/real",
        )

    def test_resolve_symlinks_alone (self) -> None:
        """
        --resolve-symlinks is refused without --abs, --rel or --dedup-abs, which it would not
        affect.
        """
        result = self.run_script("/a", "--resolve-symlinks")

        self.assertEqual(result.returncode, _ARGPARSE_ERROR)
        self.assertIn("--resolve-symlinks requires", result.stderr)

    def test_abs_keeps_empty (self) -> None:
        """
        --abs leaves empty entries empty instead of turning them into the working directory.
        """
        self.assertEqual(self.output("/a::/b", "--abs", "--no-remove-empty"), "/a::/b")

    def test_abs_exclude (self) -> None:
        """
        --abs makes excludes absolute too, so a relative exclude matches its absolute entry.
        """
        self.assertEqual(
            self.output(f"{self.tmp_path}/lib:/usr/lib", "--abs", "-e", "lib", cwd=self.tmp_path),
            "/usr/lib",
        )

class TestRelative (_PathlistTestCase):
    def test_rel_default_start (self) -> None:
        """
        A bare --rel makes entries relative to the working directory.
        """
        self.assertEqual(self.output(f"{self.tmp_path}/lib", "--rel", cwd=self.tmp_path), "lib")

    def test_rel_walks_up (self) -> None:
        """
        --rel climbs with `..` for entries outside the start directory.
        """
        self.assertEqual(self.output("/usr/lib", "--rel", "/usr/local"), "../lib")

    def test_rel_relative_entry (self) -> None:
        """
        --rel resolves relative entries against the working directory first.
        """
        (self.tmp_path / "sub").mkdir()

        self.assertEqual(
            self.output("lib", "--rel", str(self.tmp_path / "sub"), cwd=self.tmp_path),
            "../lib",
        )

    def test_rel_resolves_symlinks (self) -> None:
        """
        --rel --resolve-symlinks resolves the entries and the start alike, so no spurious `..`.
        """
        self.make_symlink()

        self.assertEqual(
            self.output(
                f"{self.tmp_path}/link/lib", "--rel", f"{self.tmp_path}/link", "--resolve-symlinks",
            ),
            "lib",
        )

    def test_rel_keeps_duplicates (self) -> None:
        """
        --rel alone keeps duplicates, since deduplication is only done when requested.
        """
        self.assertEqual(self.output("/usr/a:/usr/a", "--rel", "/usr"), "a:a")

    def test_rel_dedup (self) -> None:
        """
        --rel -d removes the duplicates left after making the entries relative.
        """
        self.assertEqual(self.output("/usr/a:/usr/a/", "--rel", "/usr", "-d"), "a")

    def test_rel_dedup_abs_symlink (self) -> None:
        """
        --rel --dedup-abs --resolve-symlinks merges a symlink under the start directory into its
        target, even when the working directory is elsewhere.
        """
        (self.tmp_path / "cwd").mkdir()
        self.make_symlink()

        self.assertEqual(
            self.output(
                f"{self.tmp_path}/link:{self.tmp_path}/real",
                "--rel", str(self.tmp_path),
                "--dedup-abs",
                "--resolve-symlinks",
                cwd=(self.tmp_path / "cwd"),
            ),
            "real",
        )

    def test_rel_dedup_abs_keeps_empty_apart (self) -> None:
        """
        --rel --dedup-abs never merges an empty entry with the start directory.
        """
        self.assertEqual(
            self.output("/usr::/usr/a", "--rel", "/usr", "--dedup-abs", "--no-remove-empty"),
            ".::a",
        )

    def test_rel_dedup_abs_ignores_cwd (self) -> None:
        """
        --rel --dedup-abs --resolve-symlinks resolves the entries against the start directory, so
        a symlink in the working directory never merges two distinct paths.
        """
        (self.tmp_path / "base" / "a").mkdir(parents=True)
        (self.tmp_path / "base" / "c").mkdir()
        (self.tmp_path / "cwd" / "a").mkdir(parents=True)
        (self.tmp_path / "cwd" / "c").symlink_to(self.tmp_path / "cwd" / "a")

        self.assertEqual(
            self.output(
                f"{self.tmp_path}/base/a:{self.tmp_path}/base/c",
                "--rel", str(self.tmp_path / "base"),
                "--dedup-abs",
                "--resolve-symlinks",
                cwd=(self.tmp_path / "cwd"),
            ),
            "a:c",
        )

    def test_rel_keeps_empty (self) -> None:
        """
        --rel leaves empty entries empty.
        """
        self.assertEqual(
            self.output("/usr/a::/usr/b", "--rel", "/usr", "--no-remove-empty"),
            "a::b",
        )

    def test_rel_exclude (self) -> None:
        """
        --rel makes excludes relative too, so an absolute exclude matches its relative entry.
        """
        self.assertEqual(self.output("/usr/lib:/usr/bin", "--rel", "/usr", "-e", "/usr/lib"), "bin")

    def test_rel_empty_start (self) -> None:
        """
        An empty --rel start directory is refused.
        """
        result = self.run_script("/a", "--rel", "")

        self.assertEqual(result.returncode, _ARGPARSE_ERROR)
        self.assertIn("--rel option requires a non-empty argument", result.stderr)

    def test_abs_and_rel (self) -> None:
        """
        --abs and --rel cannot be combined.
        """
        result = self.run_script("/a", "--abs", "--rel")

        self.assertEqual(result.returncode, _ARGPARSE_ERROR)
        self.assertIn("--abs and --rel", result.stderr)

class TestOutput (_PathlistTestCase):
    def test_stdout_without_newline (self) -> None:
        """
        The list is printed with no trailing newline.
        """
        self.assertEqual(self.output("/a:/b"), "/a:/b")

    def test_output_file (self) -> None:
        """
        -o writes the list to a file, with no trailing newline, and prints nothing.
        """
        target = self.tmp_path / "out.txt"

        self.assertEqual(self.output("/a:/b", "-o", str(target)), "")
        self.assertEqual(target.read_text(encoding="utf-8"), "/a:/b")

class TestDoubleSlash (_PathlistTestCase):
    def check_double_slash (self, mode_args: tuple[str, ...], is_root: bool) -> None:
        """
        Checks every `//` case under the given --double-slashes arguments.

        :param mode_args: The --double-slashes arguments, empty for the default.
        :param is_root: Whether the outputs should treat a leading `//` as the root.
        """
        for case_id, args, root_output, other_output in _DOUBLE_SLASH_CASES:
            with self.subTest(case=case_id):
                self.assertEqual(
                    self.output(*args, *mode_args),
                    root_output if is_root else other_output,
                )

    def test_root (self) -> None:
        """
        --double-slashes root folds a leading `//` into `/`.
        """
        self.check_double_slash(("--double-slashes", "root"), is_root=True)

    def test_keep (self) -> None:
        """
        --double-slashes keep keeps a leading `//` apart from `/`.
        """
        self.check_double_slash(("--double-slashes", "keep"), is_root=False)

    def test_auto (self) -> None:
        """
        --double-slashes auto folds a leading `//` exactly when the system treats it as the root.
        """
        self.check_double_slash(("--double-slashes", "auto"), is_root=_DOUBLE_SLASH_IS_ROOT)

    def test_default_is_auto (self) -> None:
        """
        Without --double-slashes, a leading `//` is handled as with auto.
        """
        self.check_double_slash((), is_root=_DOUBLE_SLASH_IS_ROOT)

    def test_invalid_mode (self) -> None:
        """
        An unknown --double-slashes value is refused.
        """
        self.assertEqual(
            self.run_script("/a", "--double-slashes", "fold").returncode,
            _ARGPARSE_ERROR,
        )

if __name__ == "__main__":
    unittest.main()

"""A pathspec silently disables rename detection: the old path stops matching,
so renames come back as add+delete with no warning. That failure produced a
wrong intermediate answer during the prototype work, which is why it is
asserted rather than remembered.
"""
import pathlib, re

ROOT = pathlib.Path(__file__).resolve().parent.parent
SOURCES = ["pairup.py", "scope.py", "gen2.py"]
DIFF_CALL = re.compile(r'\["git",\s*"diff".*?\]', re.S)


def test_rename_diffs_carry_no_pathspec():
    calls = 0
    for name in SOURCES:
        for call in DIFF_CALL.findall((ROOT / name).read_text()):
            calls += 1
            assert "-M" in call, f"{name}: rename detection missing in {call}"
            assert "-l50000" in call, f"{name}: rename limit missing in {call}"
            assert '"--"' not in call, f"{name}: pathspec separator in {call}"
    assert calls, "found no git diff invocations to check -- did they move?"

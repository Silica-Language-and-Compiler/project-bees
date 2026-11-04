#!/usr/bin/env python3
"""Tests for tools/check_lowering_choices.py. Run: python3 tools/test_check_lowering_choices.py
(Python 3, standard library only; no trial leaf is needed because the checker does not touch Silica.)"""
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import check_lowering_choices as C  # noqa: E402

EXAMPLE = os.path.join(ROOT, "contract", "conformance", "lowering-choices.example")


def example_text():
    with open(EXAMPLE) as fh:
        return fh.read()


def replace_line(text, prefix, new):
    out = []
    for line in text.split("\n"):
        out.append(new if line.startswith(prefix) else line)
    return "\n".join(out)


def messages(text):
    return [m for _, m in C.check(text)]


class CheckLoweringChoices(unittest.TestCase):
    def test_example_is_valid(self):
        self.assertEqual(C.check(example_text()), [])

    def test_template_is_valid(self):
        self.assertEqual(C.check(C.template()), [])

    def test_every_requirement_is_required(self):
        for rid in C.REQUIREMENTS:
            text = "\n".join(l for l in example_text().split("\n") if not l.startswith(rid + " "))
            self.assertTrue(any(f"missing entry for {rid}" in m for m in messages(text)), rid)

    def test_header_lines(self):
        text = example_text().replace("lowering-choices 1", "lowering-choices 2", 1)
        self.assertTrue(any("first line" in m for m in messages(text)))
        text = "\n".join(l for l in example_text().split("\n") if not l.startswith("compiler "))
        self.assertTrue(any("missing `compiler`" in m for m in messages(text)))
        self.assertTrue(any("empty" in m for m in messages("")))

    def test_unknown_id_and_duplicate(self):
        self.assertTrue(any("unknown requirement id A9.9" in m for m in messages(example_text() + "A9.9 x\n")))
        self.assertTrue(any("listed twice" in m for m in messages(example_text() + "A4.3 uniform-shape\n")))

    def test_bad_choice(self):
        text = replace_line(example_text(), "A5.4", "A5.4 swallow")
        self.assertTrue(any("`swallow` is not a choice" in m for m in messages(text)))

    def test_note_required_for_other_and_not_applicable(self):
        text = replace_line(example_text(), "A5.5", "A5.5 other")
        self.assertTrue(any("needs a note" in m for m in messages(text)))
        text = replace_line(example_text(), "A5.5", "A5.5 other -- built on a library of our own")
        self.assertEqual(C.check(text), [])

    def test_keys(self):
        text = replace_line(example_text(), "A3.2", "A3.2 lowered release=keep_last_message")
        self.assertTrue(any("`reserve` is required" in m for m in messages(text)))
        text = replace_line(example_text(), "A3.2", "A3.2 lowered reserve=big release=keep_last_message")
        self.assertTrue(any("non-negative integer" in m for m in messages(text)))
        text = replace_line(example_text(), "A3.2", "A3.2 lowered reserve=1 release=forever")
        self.assertTrue(any("must be one of" in m for m in messages(text)))
        text = replace_line(example_text(), "A4.3", "A4.3 one-per-shape colour=red")
        self.assertTrue(any("unknown key `colour`" in m for m in messages(text)))
        text = replace_line(example_text(), "A4.4", "A4.4 chosen restart=temporary strategy=one_for_one restart=permanent")
        self.assertTrue(any("given twice" in m for m in messages(text)))

    def test_cli_exit_codes(self):
        script = os.path.join(HERE, "check_lowering_choices.py")
        ok = subprocess.run([sys.executable, script, EXAMPLE], capture_output=True, text=True)
        self.assertEqual(ok.returncode, 0, ok.stderr)
        with tempfile.NamedTemporaryFile("w", suffix=".choices", delete=False) as fh:
            fh.write(replace_line(example_text(), "A5.4", "A5.4 swallow"))
            path = fh.name
        try:
            bad = subprocess.run([sys.executable, script, path], capture_output=True, text=True)
        finally:
            os.unlink(path)
        self.assertEqual(bad.returncode, 1)
        self.assertIn(":", bad.stderr)
        self.assertEqual(subprocess.run([sys.executable, script, "/nonexistent.choices"], capture_output=True).returncode, 1)


if __name__ == "__main__":
    unittest.main(verbosity=1)

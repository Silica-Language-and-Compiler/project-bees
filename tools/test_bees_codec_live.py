#!/usr/bin/env python3
"""Tests of tools/bees_codec_live.py's normalising (what the goldens of trials/c1_codec_live hold) and of its check for a
machine without stock Erlang. No process is started."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bees_codec_live as L  # noqa: E402


class Norm(unittest.TestCase):
    def test_bees_lines(self):
        lines = ["[bees audit] frame dropped, not a name this node serves rex -1",
                 "[bees audit] frame dropped, not a name this node serves global_name_server -1",
                 "bees: sen[silica] root actor exited (no supervisor)",
                 "ding",
                 "[silica] root actor exited (no supervisor)",
                 "at 0x00000001045fc000 here",
                 "[bees audit] net ticks seen (1 yes, 0 no) - 1",
                 "[bees audit] frames dropped - 17"]
        self.assertEqual(L.norm_bees(lines, 0),
                         ["[bees audit] frame dropped, not a name this node serves global_name_server -1",
                          "[bees audit] frame dropped, not a name this node serves rex -1",
                          "bees: sending",
                          "at 0xADDR here",
                          "[bees audit] net ticks seen (1 yes, 0 no) - N",
                          "[bees audit] frames dropped - 17",
                          "exit=0"])

    def test_single_drop_is_left_alone(self):
        lines = ["a", "[bees audit] frame dropped, not a name this node serves rex -1", "b"]
        self.assertEqual(L.norm_bees(lines, 3)[:-1], lines)
        self.assertEqual(L.norm_bees(lines, 3)[-1], "exit=3")

    def test_stock_lines(self):
        lines = ["stock: done", "=ERROR REPORT==== 18-Nov-2026::10:00:00.000000 ===", "  ** Connection attempt from <0.91.0> refused", "noise"]
        self.assertEqual(L.norm_stock(lines, 0), ["stock: done", "** Connection attempt from <PID> refused", "exit=0"])


class Tools(unittest.TestCase):
    def test_port_is_the_tables(self):
        self.assertEqual(L.EPMD_PORT, "24190")

    def test_missing(self):
        with mock.patch.object(L.shutil, "which", lambda t: None if t == "erlc" else "/x/" + t):
            self.assertEqual(L.missing_tools(), ["erlc"])
        with mock.patch.object(L.shutil, "which", lambda t: "/x/" + t):
            self.assertEqual(L.missing_tools(), [])


if __name__ == "__main__":
    unittest.main()

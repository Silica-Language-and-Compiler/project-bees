#!/usr/bin/env python3
"""Tests of the N5 (TRUST sessions, B2) generator and configuration changes: the record macros of a `.silica.in` source
(tools/bees_trust_mux_gen.py expand), the generated tables (bees_trust_slots), when a node multiplexes (trust.session written, or
the one switch bees_conf.SESSION_DEFAULT_ON), what bees_trust_conf says about the session, and that a node which does not
multiplex gets exactly the root unit it got before N5.

    python3 tools/test_bees_trust_mux.py
"""
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bees_conf as C  # noqa: E402
import bees_config_trust as B  # noqa: E402
import bees_trust_gen as G  # noqa: E402
import bees_trust_mux_gen as M  # noqa: E402

TRUST = """[{mode, trust}, {trust, [{port, 47501}, {listen_address, "127.0.0.1"}, {plaintext_test_only, true}%s]}]."""


def slurp(p):
    with open(p) as f:
        return f.read()


class Macros(unittest.TestCase):
    SRC = "//@type S = a: int64, c: dangerous_actor_ref, b: boolean\n//@type V = a: int64, b: boolean\n"

    def test_type(self):
        self.assertIn("fn f(st: { a: int64, c: dangerous_actor_ref, b: boolean }) -> { a: int64, b: boolean } {",
                      M.expand(self.SRC + "fn f(st: @{S}) -> @{V} {"))

    def test_copy_and_overrides(self):
        self.assertIn("x <- { a: st.a, b: st.b };", M.expand(self.SRC + "x <- @{V st};"))
        self.assertIn("{ a: st.a + 1, b: case p of { true -> f(1, 2); false -> st.b } }",
                      M.expand(self.SRC + "@{V st | b: case p of { true -> f(1, 2); false -> st.b }, a: st.a + 1}"))

    def test_merge(self):
        self.assertIn("{ a: v.a, c: st.c, b: true }", M.expand(self.SRC + "@{S st + V v | b: true}"))

    def test_unknown_field_and_type(self):
        with self.assertRaises(SystemExit):
            M.expand(self.SRC + "@{V st | zz: 1}")
        with self.assertRaises(SystemExit):
            M.expand(self.SRC + "@{W st}")

    def test_the_template_expands_completely(self):
        out = M.expand(slurp(M.TEMPLATE))
        self.assertNotIn("@{", out)
        self.assertIn("module dangerous_bees_trust_mux;", out)


class Units(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.d)

    def test_tables_are_sized_by_max_inflight(self):
        for n in (1, 3, 64):
            M.gen_slots(self.d, n)
            s = slurp(os.path.join(self.d, "bees_trust_slots.silica"))
            self.assertIn(f", c{n - 1}: int64", s)
            self.assertNotIn(f", c{n}: int64", s)
            self.assertIn(f", q{n - 1}: int64", s)
            self.assertNotIn(f", q{n}: int64", s)
            # a cast's req_id names the row after the last one
            self.assertIn(f"false -> {n} }}, seq1)", s)
            for name in ("msup/2", "sup_start/1", "mpend/2", "pend_start/4", "mmet/2", "met_start/0"):
                self.assertIn(f"export {name};", s)

    def test_the_client_stops_at_its_own_max_calls(self):
        # the pending table puts no request on a session after the client's own session.max_calls (nothing learned from the server)
        M.gen_slots(self.d, 2)
        s = slurp(os.path.join(self.d, "bees_trust_slots.silica"))
        self.assertIn("lim: boolean <- sent and isgo == false and seq1 >= bees_trust_conf@session_max_calls();", s)
        self.assertIn("drain: boolean <- (k == 1023 or lim) and st.phase == 2;", s)

    def test_every_metric_of_the_design_is_printed(self):
        M.gen_slots(self.d, 2)
        s = slurp(os.path.join(self.d, "bees_trust_slots.silica"))
        for name in ("trust_sessions_started_total", "trust_sessions_active", "trust_duplicates_total", "trust_client_cancels_total",
                     "trust_protocol_close_total", "trust_resume_reads_total", "trust_session_age_ms_sum", "trust_session_age_ms_count",
                     "trust_result_latency_ms_sum", "trust_result_latency_ms_count", "trust_paused_duration_ms_sum",
                     "trust_paused_duration_ms_count"):
            self.assertIn(name, s)
        for reason in ("limit_reached", "shutdown", "deny", "protocol"):
            self.assertIn('trust_goaway_total{reason=\\"%s\\"}' % reason, s)
            self.assertIn('trust_sessions_ended_total{reason=\\"%s\\"}' % reason, s)

    def test_generate_and_remove(self):
        M.generate(self.d, 2)
        names = sorted(os.listdir(self.d))
        self.assertEqual(names, ["bees_trust_mux.atoms", "bees_trust_mux_frame.silica", "bees_trust_slots.silica",
                                 "dangerous_bees_trust_mux.silica"])
        self.assertTrue(os.path.isfile(os.path.join(self.d, "bees_trust_mux_frame.silica")), "the link must resolve")
        M.remove(self.d)
        self.assertEqual(os.listdir(self.d), [])


class Config(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.on = C.SESSION_DEFAULT_ON

    def tearDown(self):
        C.SESSION_DEFAULT_ON = self.on
        shutil.rmtree(self.d)

    def conf(self, extra):
        p = os.path.join(self.d, "bees.config")
        with open(p, "w") as f:
            f.write(TRUST % extra)
        v, notes, err = B.run(p)
        self.assertIsNone(err)
        out = os.path.join(self.d, "lib")
        B.gen(out, v, notes, err)
        return v, slurp(os.path.join(out, "bees_trust_conf.silica")), p

    def test_the_switch_is_off_in_the_tree(self):
        # the owner's ruling on N5 Q1 is that it becomes True; it is flipped with the re-recording of the existing goldens
        self.assertIs(C.SESSION_DEFAULT_ON, False)

    def test_no_session_key_is_b1_while_the_switch_is_off(self):
        C.SESSION_DEFAULT_ON = False
        v, text, _ = self.conf("")
        self.assertFalse(v["session_set"])
        self.assertEqual(v["session"], {k: d for k, (_, d) in C.SESSION_OPTS.items()})
        self.assertIn("fn mux() -> boolean { false }", text)
        self.assertIn("fn session_single() -> boolean { true }", text)
        self.assertIn("one request per connection (B1)", text)

    def test_no_session_key_multiplexes_with_the_defaults_when_the_switch_is_on(self):
        C.SESSION_DEFAULT_ON = True
        v, text, _ = self.conf("")
        self.assertTrue(v["session_set"])
        self.assertIn("fn mux() -> boolean { true }", text)
        self.assertIn("fn session_single() -> boolean { false }", text)
        self.assertIn("sessions (B2): max_inflight 8, max_calls 100, max_age_ms 60000, idle_ms 5000, drain_ms 1000", text)

    def test_session_written(self):
        v, text, _ = self.conf(", {session, #{max_inflight => 2, max_calls => 8, idle_ms => 600, drain_ms => 1000}}, {session_slots_max, 5}, {acceptors, 4}")
        self.assertIn("fn mux() -> boolean { true }", text)
        self.assertIn("fn session_single() -> boolean { false }", text)
        self.assertIn("fn session_max_inflight() -> int64 { 2 }", text)
        self.assertIn("fn session_max_calls() -> int64 { 8 }", text)
        self.assertIn("fn session_max_age_ms() -> uint64 { 60000 }", text)
        self.assertIn("fn session_idle_ns() -> int64 { 600000000 }", text)
        self.assertIn("fn session_idle_tick_ms() -> uint64 { 60 }", text)
        # the effective drain is min(drain_ms, idle_ms)
        self.assertIn("fn session_drain_ms() -> uint64 { 600 }", text)
        self.assertIn("fn session_drain() -> int64 { 600 }", text)
        self.assertIn("fn session_slots_max() -> int64 { 5 }", text)
        self.assertIn("sessions (B2): max_inflight 2, max_calls 8, max_age_ms 60000, idle_ms 600, drain_ms 600, session_slots_max 5", text)
        self.assertIn("acceptors 4 is validated and not used", text)

    def test_limits_of_one_keep_a_node_at_one_request_per_connection(self):
        for on in (False, True):
            C.SESSION_DEFAULT_ON = on
            v, text, _ = self.conf(", {session, #{max_inflight => 1, max_calls => 1}}")
            self.assertIn("fn mux() -> boolean { true }", text)
            self.assertIn("fn session_single() -> boolean { true }", text)
            self.assertIn("one request per connection (B1)", text)
            self.assertNotIn("sessions (B2)", text)

    def test_the_idle_tick_is_never_below_ten_ms(self):
        _, text, _ = self.conf(", {session, #{idle_ms => 100, max_age_ms => 1000}}")
        self.assertIn("fn session_idle_tick_ms() -> uint64 { 10 }", text)

    def test_mfa_step_writes_and_removes_the_session_units(self):
        _, _, p = self.conf(", {session, #{max_inflight => 3}}")
        out = os.path.join(self.d, "lib")
        G.mux_units(out, p)
        self.assertIn(", c2: int64", slurp(os.path.join(out, "bees_trust_slots.silica")))
        self.assertTrue(os.path.isfile(os.path.join(out, "dangerous_bees_trust_mux.silica")))
        C.SESSION_DEFAULT_ON = False
        _, _, p = self.conf("")
        G.mux_units(out, p)
        self.assertFalse(os.path.exists(os.path.join(out, "bees_trust_slots.silica")))
        self.assertFalse(os.path.lexists(os.path.join(out, "bees_trust_mux.atoms")))

    def root_unit(self, extra):
        _, _, _ = self.conf(extra)
        role = os.path.join(self.d, "x.role")
        with open(role, "w") as f:
            f.write("fn main() -> int64 { 0 }\n")
        out = os.path.join(self.d, "dangerous_x.silica")
        G.gen_edge("dangerous_x", out, [role])
        return slurp(out)

    def test_root_unit_of_a_node_that_does_not_multiplex_is_what_it_was(self):
        C.SESSION_DEFAULT_ON = False
        text = self.root_unit("")
        want = ("// Generated by tools/bees_trust_gen.py from src/shim/bees_tcp_edge.part, src/shim/bees_trust_node.part, "
                "bees_trust_link_plain.part and x.role. Do not edit.\n"
                + "".join(f"use {u};\n" for u in G.HEADER_USES) + "module dangerous_x;\n\n"
                + slurp(G.TCP_PART) + "\n" + slurp(G.LINK_PLAIN) + "\n" + slurp(G.NODE_PART) + "\nfn main() -> int64 { 0 }\n")
        self.assertEqual(text, want)

    def test_root_unit_of_a_session_node(self):
        text = self.root_unit(", {session, #{max_inflight => 2}}")
        for u in G.MUX_USES:
            self.assertIn(f"use {u};\n", text)
        for fn in G.MUX_RENAMES:
            self.assertEqual(text.count(f"\nfn {fn}("), 1, f"{fn} is defined once, by bees_trust_mux.part")
            self.assertEqual(text.count(f"\nfn {fn}_b1("), 1, f"the node part's {fn} is kept as {fn}_b1")
        self.assertIn("fn trpc_close(addr: string) -> atom", text)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Tests of the Python TEMPUS extension's node parts, against what the Silica library was shown to do.

    python3 example_tempus_clients/python/test_bees_tempus_node.py      (from the BEES root directory)

  the stores      bees_tempus_view.py and bees_tempus_store.py take the place of the two independent models
                  (tools/bees_tempus_view_model.py, tools/bees_tempus_store_model.py) in the tools' own tests, which
                  compute every line of trials/t0_tempus_view and trials/t1_tempus_store again and compare it with
                  those trials' recorded outputs. So the extension's stores are compared, line for line, with what
                  the Silica view and store printed.
  the clock       every line of trials/t0_tempus_clock's recorded output is computed again with clock_back and
                  clock_turn of bees_tempus_node.py from the readings the line itself names.
  admission       every case of trials/t4_tempus_admission (tools/bees_tempus_fixtures.py) gets the verdict and the
                  reason text the Silica node printed; the order of an advert's checks; the tempus whitelist rule.
  configuration   the refusals of tools/test_bees_tempus_conf.py, with the same words, and the boot refusals of
                  trials/c4_tempus_boot.
  the codec       what the extension must refuse; the node's structure check.
  replies         a reply must be the reply of its request, and its entries must verify.
  a node          in this process, with a clock, timers and a random source the test steps by hand.

The keys, certificates and tokens are TEST ONLY (bees_tempus_testing.py and the certificates of
tools/bees_tempus_certs.py).
"""
import glob
import os
import random
import shutil
import sys
import tempfile
import time
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(HERE, "lib"))      # the extension
sys.path.insert(0, os.path.join(HERE, "testing"))  # TEST ONLY: its test support
sys.path.insert(0, os.path.join(ROOT, "tools"))
import bees_tempus_admission as adm  # noqa: E402
import bees_tempus_codec as codec  # noqa: E402
import bees_tempus_config as config  # noqa: E402
import bees_tempus_node as node  # noqa: E402
import bees_tempus_peer as peer  # noqa: E402
import bees_tempus_store as store  # noqa: E402
import bees_tempus_testing as t  # noqa: E402
import bees_tempus_view as view  # noqa: E402

CERTS = os.path.join(ROOT, "trials", "t5_tempus_tls", "certs")
A = codec.Atom


def golden_lines(leaf, pattern):
    paths = sorted(glob.glob(os.path.join(ROOT, "trials", leaf, pattern)))
    out = []
    for p in paths:
        with open(p) as f:
            out.append((p, [ln.rstrip("\n") for ln in f if ln.strip()]))
    return out


# ---------------------------------------------------------------- the stores
def tools_tests_with_the_extension():
    """the tools' own view and store tests, with the extension's modules in the place of the two models"""
    saved = dict((k, sys.modules.get(k)) for k in ("bees_tempus_view_model", "bees_tempus_store_model",
                                                   "test_bees_tempus_view", "test_bees_tempus_store"))
    for k in saved:
        sys.modules.pop(k, None)
    sys.modules["bees_tempus_view_model"] = view
    fake = types.ModuleType("bees_tempus_store_model")
    fake.Store = store.Store
    sys.modules["bees_tempus_store_model"] = fake
    try:
        import test_bees_tempus_store as ts
        import test_bees_tempus_view as tv
        assert tv.m is view and ts.view is view and ts.Store is store.Store
        suite = unittest.TestSuite()
        suite.addTests(unittest.defaultTestLoader.loadTestsFromModule(tv))
        suite.addTests(unittest.defaultTestLoader.loadTestsFromModule(ts))
        return suite
    finally:
        for k, v in saved.items():
            sys.modules.pop(k, None)
            if v is not None:
                sys.modules[k] = v


def random_entries(rng, names, most):
    picked = rng.sample(names, rng.randint(0, min(most, len(names))))
    return [(n, "d-" + n, rng.randint(0, 40)) for n in picked]


def view_rules_against_the_model(case):
    """the same random inputs to the extension's view rules and to the independent model of tools/"""
    import bees_tempus_view_model as model
    rng = random.Random(7)
    names = ["p%02d" % i for i in range(12)]
    for _ in range(400):
        mine, other = random_entries(rng, names, 8), random_entries(rng, names, 6)
        draws = [rng.randint(0, 1000) for _ in range(9)]
        cap, count = rng.randint(1, 8), rng.randint(1, 5)
        case.assertEqual(view.age_all(mine), model.age_all(mine))
        case.assertEqual(view.merge(mine, other, "p00", cap), model.merge(mine, other, "p00", cap))
        case.assertEqual(view.prefer_sent(other, mine), model.prefer_sent(other, mine))
        case.assertEqual(view.backfill(mine, other, cap), model.backfill(mine, other, cap))
        case.assertEqual(view.sample(mine, count, draws), model.sample(mine, count, draws))
        case.assertEqual(view.reply_select(mine, count, "p01", draws), model.reply_select(mine, count, "p01", draws))
        if mine:
            case.assertEqual(view.select(mine, count, draws), model.select(mine, count, draws))


def store_steps_against_the_model(case):
    """the same 600 random steps to the extension's Store and to the independent model of tools/, for a store of the
    node's own type and for one that is not: the same answer and the same view after every step"""
    import bees_tempus_store_model as store_model
    import bees_tempus_view_model as view_model
    rng = random.Random(11)
    names = ["p%02d" % i for i in range(10)]
    for own in (True, False):
        mine = store.Store("me", "d-me", own, 5, 3)
        model = store_model.Store("me", "d-me", own, 5, 3)
        for step in range(600):
            draws = [rng.randint(0, 1000) for _ in range(5)]
            what = rng.choice(("tick", "tick", "reply", "failed", "request", "sample", "insert", "drop"))
            if what == "tick":
                mine.tick_draws, model.tick_draws = list(draws), list(draws)
                case.assertEqual(mine.tick(), model.tick())
            elif what == "reply":
                received = random_entries(rng, names + ["me"], 4)
                mine.reply(received)
                model.reply(received)
            elif what == "failed":
                mine.failed()
                model.failed()
            elif what == "request":
                received = random_entries(rng, names + ["me"], 4)
                mine.reply_draws, model.reply_draws = list(draws), list(draws)
                case.assertEqual(mine.request("p03", received), model.request("p03", received))
            elif what == "sample":
                n = rng.randint(1, 5)
                mine.reply_draws, model.reply_draws = list(draws), list(draws)
                case.assertEqual(mine.sample(n), model.sample(n))
            elif what == "insert":
                for x in random_entries(rng, names, 1):
                    mine.insert(x)
                    model.insert(x)
            else:
                name = rng.choice(names)
                mine.drop(name)
                model.drop(name)
            case.assertEqual(mine.view, model.view, "step %d, %s" % (step, what))
            case.assertTrue(view_model.valid(mine.view, "me", 5))


class Stores(unittest.TestCase):
    def test_the_silica_goldens_of_t0_and_t1(self):
        # Beside the goldens: the extension's rules against the two independent models, on random inputs. These two
        # comparisons are made inside this test, and not as tests of their own, because the trial
        # trials/c7_tempus_node_python records one line for each test of this file.
        view_rules_against_the_model(self)
        store_steps_against_the_model(self)
        suite = tools_tests_with_the_extension()
        self.assertGreaterEqual(suite.countTestCases(), 12)
        result = unittest.TestResult()
        suite.run(result)
        self.assertEqual((result.failures, result.errors), ([], []))
        self.assertEqual(result.testsRun - len(result.skipped), suite.countTestCases() - len(result.skipped))
        self.assertTrue(golden_lines("t0_tempus_view", "view.*.scout") and golden_lines("t1_tempus_store", "steps.*.scout"))

    def test_a_missing_or_negative_draw_counts_as_zero(self):
        v = [("a", "", 5), ("b", "", 5), ("c", "", 1)]
        self.assertEqual(view.select(v, 3, [])[1][0], "a")
        self.assertEqual(view.select(v, 3, [-4])[1][0], "a")
        self.assertEqual(view.select(v, 3, [1])[1][0], "b")


# ---------------------------------------------------------------- the clock
BACK = {"follow": 1, "hold": 2, "stop": 3}
ACT = {0: "not earlier", 1: "earlier, followed", 2: "earlier, held", 3: "earlier, the node stops"}
STATE = {0: "no reading yet", 3: "no reading yet, application told", 1: "good", 2: "paused, waits for the clock",
         6: "goes on with its last reading", 5: "holds its time", 4: "stopped"}
SAY = {0: "nothing", 1: "first reading: one line, listen", 2: "no time at start: one line, application told",
       3: "no time, pause: one line, application told", 4: "no time, continue: one line, application told",
       6: "step back followed: one line", 7: "step back, hold begins: one line", 8: "the held time is reached: one line",
       9: "step back above the limit: one line, application told, stop"}


def accepts(state):
    if state in (0, 3):
        return "does not listen yet"
    closes = node.clock_closes(state)
    if closes:
        return "closes accepted connections (role %d, %s)" % ({"clock_refused": 4, "clock_stopped": 5}[closes], closes)
    return "accepts"


def clock_lines(golden):
    """every line of the t0_tempus_clock golden, computed again from the readings each line names"""
    out, mode, now, state = [], None, 0, 0
    for ln in golden:
        if ln.startswith("part ") or ln.startswith("exit="):
            out.append(ln)
        elif ln.startswith("clock_back "):
            words = ln.replace(",", "").split()
            mode = (words[1], int(words[3]) if words[2] == "limit" else 0, words[-1])
            now, state = 0, 0
            out.append(ln)
        elif ln.startswith("  reading "):
            said = ln[len("  reading "):].split(" -> ")[0]
            n = None if said == "no time" else int(said)
            now, state, say, again = node.clock_turn(state, now, n, mode[0], mode[1], mode[2])
            out.append("  reading %s -> time %d; %s; %s; %s; does: %s%s" % (
                said, now, STATE[state], "ticks" if node.clock_ticks(state) else "no ticks", accepts(state),
                "read again: one line; then " if again else "", SAY[say]))
        else:
            head, rest = ln.split(": time ")
            words = head.split()
            last, n = int(rest.split(",")[0]), int(rest.split("reading ")[1].split(" ")[0])
            got, act = node.clock_back(last, n, words[0], int(words[2]) if len(words) == 3 else 0)
            out.append("%s: time %d, reading %d -> time %d, %s" % (head, last, n, got, ACT[act]))
    return out


class Clock(unittest.TestCase):
    def test_every_line_of_the_silica_golden(self):
        goldens = golden_lines("t0_tempus_clock", "clock.*.scout")
        self.assertTrue(goldens)
        for path, lines in goldens:
            self.assertGreater(len(lines), 60, path)
            self.assertEqual(clock_lines(lines), lines, path)

    def test_the_system_clock_is_whole_seconds_and_present(self):
        now = node.SystemClock().read()
        self.assertIsInstance(now, int)
        self.assertLess(abs(now - time.time()), 2)


# ---------------------------------------------------------------- admission
class Admission(unittest.TestCase):
    def setUp(self):
        import bees_tempus_fixtures as fx
        self.fx = fx
        self.v = adm.Verifier(fx.PRODUCER_PUB, fx.KID, fx.NOW, fx.SKEW, [])

    def verdict(self, case):
        fx = self.fx
        try:
            if case["kind"] == 1:
                d = codec.descriptor(case["id"], case["pub"], fx.ADDR, case["token"])
                self.v.check_entry(d, {v: k for k, v in fx.STORE.items()}[case["want"]])
            else:
                self.v.check_proof(case["pub"], case["nonce"], case["token"], case["sig"])
        except codec.Refused as why:
            return str(why)
        return ""

    def test_every_case_of_t4_with_the_silica_reason(self):
        cases = [c for c in self.fx.cases() if c["kind"] in (1, 2)]
        self.assertGreaterEqual(len(cases), 19)
        want = {"the proof of possession does not verify": "the signature does not verify"}
        for case in cases:
            got = self.verdict(case)
            self.assertEqual(want.get(got, got), case["expect"], case["name"])
        # and the recorded output of the Silica trial says the same, line for line
        for path, lines in golden_lines("t4_tempus_admission", "dangerous_admit.*.scout"):
            by = dict(ln.split(": ", 1) for ln in lines if ": " in ln)
            for case in cases:
                got = self.verdict(case)
                got = want.get(got, got)
                self.assertEqual(by[case["name"]], "admitted" if got == "" else "refused: " + got, path)

    def test_the_node_signs_as_the_fixture(self):
        fx = self.fx
        case = [c for c in fx.cases() if c["kind"] == 3][0]
        me = t.Identity(case["pub"], case["token"], fx.ADDR)
        self.assertEqual(me.prove(case["nonce"]), case["sig"])

    def advert(self, typ="tempus_edge", **kw):
        return t.fixture_identity(64, typ, 1000, 2000, addr="127.0.0.1:1", **kw)

    def refusal(self, v, d, cert_pub, cert_fp=b"f" * 64):
        with self.assertRaises(codec.Refused) as e:
            v.check_advert(d, cert_pub, cert_fp)
        return e.exception.event, str(e.exception)

    def test_the_order_of_an_adverts_checks(self):
        v = adm.Verifier(self.fx.PRODUCER_PUB, "k1", 1500, 10, [])
        good = self.advert()
        self.assertEqual(v.check_advert(good.descriptor(), good.pub, b"f" * 64)[0]["typ"], "tempus_edge")
        other = bytes(32)
        # the binding is judged before anything of the token: an expired token under another kid, by a key that is
        # not the producer's, presented under another certificate, is a binding refusal
        worst = self.advert(kid="k0", producer=t.fixture_key(96)).descriptor()
        self.assertEqual(self.refusal(v, worst, other),
                         ("binding_refused", "the advert's pub is not the key of the peer's TLS certificate"))
        # then the kid, before the time
        old = t.fixture_identity(64, "tempus_edge", 1000, 1400, addr="127.0.0.1:1", kid="k0", producer=t.fixture_key(96))
        self.assertEqual(self.refusal(v, old.descriptor(), old.pub), ("key_rotated", "key_rotated"))
        # then the time, before sub
        late = t.fixture_identity(64, "tempus_edge", 1000, 1400, addr="127.0.0.1:1", sub=bytes(32))
        self.assertEqual(self.refusal(v, late.descriptor(), late.pub), ("admission_refused", "the token has expired"))
        sub = self.advert(sub=bytes(32))
        self.assertEqual(self.refusal(v, sub.descriptor(), sub.pub), ("admission_refused", "sub is not the peer's key"))
        # then the whitelist, before the two key operations
        forged = self.advert("tempus_sentinel", producer=t.fixture_key(96))
        self.assertEqual(self.refusal(v, forged.descriptor(), forged.pub)[0], "whitelist_reject")
        d = dict(good.descriptor())
        d[A("id")] = bytes(64)
        self.assertEqual(self.refusal(v, d, good.pub), ("admission_refused", "id is not the SHA-512 of pub"))
        forged = self.advert(producer=t.fixture_key(96))
        self.assertEqual(self.refusal(v, forged.descriptor(), forged.pub), ("admission_refused", "the signature does not verify"))

    def test_the_tempus_whitelist_rule_both_ways(self):
        fp = b"w" * 64
        v = adm.Verifier(self.fx.PRODUCER_PUB, "k1", 1500, 10, [b"x" * 64, fp])
        edge, sentinel, bridge = self.advert(), self.advert("tempus_sentinel"), self.advert("tempus_bridge")
        self.assertEqual(v.check_advert(edge.descriptor(), edge.pub, b"n" * 64)[1], -1)
        self.assertEqual(v.check_advert(sentinel.descriptor(), sentinel.pub, fp)[1], 1)
        self.assertEqual(v.check_advert(bridge.descriptor(), bridge.pub, fp)[1], 1)
        self.assertEqual(self.refusal(v, sentinel.descriptor(), sentinel.pub, b"n" * 64), (
            "whitelist_reject", "a tempus_bridge or tempus_sentinel token under a certificate that is not in the tempus whitelist"))
        self.assertEqual(self.refusal(v, edge.descriptor(), edge.pub, fp), (
            "whitelist_reject", "a certificate of the tempus whitelist with a token whose typ is not tempus_bridge or tempus_sentinel"))
        # an empty whitelist accepts no bridge and no sentinel
        none = adm.Verifier(self.fx.PRODUCER_PUB, "k1", 1500, 10, [])
        self.assertEqual(self.refusal(none, sentinel.descriptor(), sentinel.pub, fp)[0], "whitelist_reject")

    def test_a_fingerprint_names_a_certificate_not_a_key(self):
        key = t.fixture_key(64)
        one = adm.fingerprint(adm.certificate_der(t.certificate_pem(key, "one", 1)))
        two = adm.fingerprint(adm.certificate_der(t.certificate_pem(key, "two", 2)))
        self.assertEqual(len(one), 64)
        self.assertNotEqual(one, two)


# ---------------------------------------------------------------- configuration
def values(**kw):
    v = {"role": "edge", "listen_address": "127.0.0.1", "port": 24300,
         "sentinels": [("127.0.0.1", 24310, "sentinel.pem")],
         "edge": {"capacity": 4, "shuffle_length": 3, "tick_ms": 1000},
         "bridge": {"capacity": 4, "shuffle_length": 2, "tick_ms": 1000},
         "sentinel": {"capacity": 4, "shuffle_length": 2, "tick_ms": 1000},
         "producer_key": ("k1", "00" * 32),
         "identity_keyfile": os.path.join(CERTS, "other-key.pem"), "identity_certfile": os.path.join(CERTS, "other.pem"),
         "whitelist_cert_dir": WHITELIST,
         "shuffle_timeout_ms": 2000, "inflight_max": 4, "clock_skew_ms": 10000,
         "clock_back": "follow", "clock_fail": "pause", "clock_read_ms": 1000,
         "join_retry_initial_ms": 200, "join_retry_max_ms": 800}
    for k, val in kw.items():
        if val is None:
            v.pop(k, None)
        else:
            v[k] = val
    return v


WHITELIST = None


def setUpModule():
    global WHITELIST
    WHITELIST = tempfile.mkdtemp(prefix="bees_tempus_whitelist_")
    for name in ("sentinel", "bridge"):
        shutil.copy(os.path.join(CERTS, name + ".pem"), WHITELIST)


def tearDownModule():
    shutil.rmtree(WHITELIST)


class Configuration(unittest.TestCase):
    def refused(self, part, **kw):
        with self.assertRaises(config.ConfigRefused) as e:
            config.node_config(values(**kw))
        self.assertIn(part, str(e.exception))

    def edge(self, **kw):
        z = {"capacity": 4, "shuffle_length": 3, "tick_ms": 1000}
        z.update(kw)
        return z

    def test_a_good_configuration(self):
        c = config.node_config(values())
        self.assertEqual((c.role, c.typ, c.port, c.clock_skew_s), ("edge", "tempus_edge", 24300, 10))
        self.assertEqual(c.stores["tempus_edge"], {"capacity": 4, "shuffle_length": 3, "tick_ms": 1000})
        self.assertEqual(c.sentinels, [("127.0.0.1:24310", "sentinel.pem")])
        self.assertEqual(c.whitelist_names, ["bridge.pem", "sentinel.pem"])
        self.assertEqual([len(f) for f in c.whitelist], [64, 64])
        self.assertIsNone(c.clock_back_limit_s)

    def test_the_refusals_of_the_silica_configuration_in_the_same_words(self):
        # tools/test_bees_tempus_conf.py: test_bounds, test_sentinels, test_section_and_mode_agree
        self.refused("257 is above 256", edge=self.edge(capacity=257))
        self.refused("above the capacity 4", edge=self.edge(shuffle_length=5))
        self.refused("32 bytes", producer_key=("k1", "00" * 31))
        self.refused("below join_retry_initial_ms", join_retry_max_ms=150)
        self.refused("required unless the node is the first sentinel", sentinels=None)
        self.assertEqual(config.node_config(values(role="sentinel", sentinels=None)).sentinels, [])
        self.refused("bridge needs mode tempus-trust", role="bridge")
        # test_control_test_only_is_no_key_any_more
        for value in (True, False):
            self.refused("tempus.control_test_only: no such key any more", control_test_only=value)
        # test_clock_choices_have_no_default, _closed_sets, _limit_only_under_stop, _read_bounds
        self.refused("tempus.clock_back: required (no default)", clock_back=None)
        self.refused("tempus.clock_fail: required (no default)", clock_fail=None)
        self.refused("tempus.clock_read_ms: required (no default)", clock_read_ms=None)
        self.refused("tempus.clock_back_limit_s: required when clock_back is stop", clock_back="stop")
        self.refused("expected one of follow, hold, stop", clock_back="ignore")
        self.refused("expected one of follow, hold, stop", clock_back=1)
        self.refused("expected one of continue, pause", clock_fail="stop")
        self.refused("expected one of continue, pause", clock_fail=True)
        for back in ("follow", "hold"):
            self.refused("remove clock_back_limit_s", clock_back=back, clock_back_limit_s=30)
        for limit in (0, 86400):
            self.assertEqual(config.node_config(values(clock_back="stop", clock_back_limit_s=limit)).clock_back_limit_s, limit)
        for limit in (-1, 86401, "none"):
            self.refused("clock_back_limit_s", clock_back="stop", clock_back_limit_s=limit)
        for ms in (100, 60000):
            self.assertEqual(config.node_config(values(clock_read_ms=ms)).clock_read_ms, ms)
        self.refused("clock_read_ms", clock_read_ms=99)
        self.refused("clock_read_ms", clock_read_ms=60001)

    def test_every_required_key_and_every_bound(self):
        for key in config.REQUIRED:
            self.refused("tempus.%s: required (no default)" % key, **{key: None})
        for name, lo, hi in config.INTS:
            if name == "join_retry_max_ms":
                continue
            self.refused("%d is below %d" % (lo - 1, lo), **{name: lo - 1})
            self.refused("%d is above %d" % (hi + 1, hi), **{name: hi + 1})
            self.refused("expected an integer", **{name: "7"})
        for name, lo, hi in config.STORE:
            self.refused("is below %d" % lo, edge=self.edge(**{name: lo - 1}))
            self.refused("is above %d" % hi, bridge=self.edge(**{name: hi + 1}))
        self.refused("tempus.sentinel.tick_ms: required (no default)", sentinel={"capacity": 4, "shuffle_length": 2})
        self.refused("unknown key", colour="blue")
        self.refused("the kid is not 1 to 64 bytes", producer_key=("", "00" * 32))
        self.refused("names no certificate of the tempus whitelist", sentinels=[("127.0.0.1", 1, "nobody.pem")])
        self.refused("1 to 16", sentinels=[])
        self.refused("is not an IPv4 literal", sentinels=[("sentinel.example", 1, "sentinel.pem")])
        self.refused("not read by the Python extension", whitelist_file="whitelist.config")
        self.refused("only none", edge_spec="any")

    def boot(self, token, **kw):
        lines = []
        with self.assertRaises(node.BootRefused) as e:
            node.Node(config.node_config(values(**kw)), token=token, address="127.0.0.1:24300", on_event=lambda e: None,
                      log=lines.append)
        self.assertEqual(lines, ["tempus: boot refused: " + str(e.exception)])
        return str(e.exception)

    def test_the_boot_refusals_of_c4(self):
        golden = [ln for _p, lines in golden_lines("c4_tempus_boot", "dangerous_*.macos_applesilicon.scout") for ln in lines]
        pub = t._raw_public(t.fixture_key(64))
        tok = lambda **kw: t.make_token(t.fixture_key(0), "k1", kw.get("sub", pub), kw.get("typ", "tempus_edge"), 1000, 2000)  # noqa: E731
        # the node's token: the same words as the Silica node's boot check
        why = self.boot(tok(typ="tempus_sentinel"))
        self.assertEqual(why, "the node's token is for another peer type than the node's")
        self.assertIn("tempus: boot refused: " + why, golden)
        self.assertEqual(self.boot(tok(sub=bytes(32))), "the node's token names another key")
        self.assertTrue(self.boot(tok()[:-1]).startswith("the node's token does not read: "))
        # the other cases of c4 are values of the configuration here, refused before any node exists
        self.assertIn("tempus: boot refused: tempus_edge: capacity is not 1 to 256", golden)
        self.refused("tempus.edge.capacity", edge=self.edge(capacity=0))
        self.assertIn("tempus: boot refused: tempus_edge: shuffle_length is not 1 to 64 and at most the capacity", golden)
        self.refused("tempus.edge.shuffle_length", edge=self.edge(shuffle_length=5))
        self.assertIn("tempus: boot refused: the producer key is not a kid of 1 to 64 bytes and a 32-byte key", golden)
        self.refused("tempus.producer_key", producer_key=("k1", b"short"))
        self.assertIn("tempus: boot refused: clock_back is not follow (1), hold (2) or stop (3)", golden)
        self.refused("tempus.clock_back", clock_back="4")
        # an identity whose certificate is over another key
        self.assertIn("could not be loaded", self.boot(tok(), identity_certfile=os.path.join(CERTS, "node.pem")))


# ---------------------------------------------------------------- the codec
class Codec(unittest.TestCase):
    def test_an_atom_that_is_not_utf8_is_refused_not_raised(self):
        for body in (b"\x83\x74\x00\x00\x00\x01\x77\x01\xff\x61\x01", b"\x83\x74\x00\x00\x00\x01\x76\x00\x02\xc3\x28\x61\x01",
                     b"\x83\x74\x00\x00\x00\x01\x77\x01t\x77\x02\xff\xfe"):
            with self.assertRaises(codec.Refused):
                codec.etf_decode(body)
            with self.assertRaises(codec.Refused):
                codec.read_body(body, 3)
            self.assertEqual(codec.read_any(body)[0], "undecoded")
            self.assertEqual(codec.structure_reason(body), "unknown_atom")

    def test_the_test_frames_are_frames_of_no_kind(self):
        for body in (t.tick("tempus_edge"), t.clock(1500), t.clock(1500, 100, 1600)):
            with self.assertRaisesRegex(codec.Refused, "unknown kind"):
                codec.read_body(body, 3)
            self.assertEqual(codec.structure_reason(body), "unknown_atom")
            self.assertEqual(codec.kind_of(body), "")
        self.assertNotIn("tick", codec.KINDS)
        self.assertNotIn("clock", codec.KINDS)
        for name in ("tick", "clock", "make_token", "token_payload", "fixture_key", "Misbehaviour"):
            for module in (codec, adm, peer, node, config, store, view):
                self.assertFalse(hasattr(module, name), "%s.%s" % (module.__name__, name))

    def test_no_extension_module_imports_the_test_support(self):
        # the seven modules, and the driver application, which is a program an application's author copies from
        for path in [m.__file__ for m in (codec, adm, peer, node, config, store, view)] + \
                [os.path.join(HERE, "driver", "tempus_peer.py")]:
            module = types.SimpleNamespace(__name__=os.path.basename(path))
            with open(path) as f:
                text = f.read()
            self.assertNotIn("import bees_tempus_testing", text, module.__name__)
            self.assertNotIn("from bees_tempus_testing", text, module.__name__)
            self.assertNotIn("bees_tempus_client", text.replace("test_bees_tempus_client", ""), module.__name__)

    def test_the_nodes_structure_check(self):
        good = codec.sample("tempus_edge", 2)
        self.assertEqual((codec.structure_reason(good), codec.kind_of(good)), ("", "sample"))
        self.assertEqual(codec.structure_reason(b""), "truncated")
        self.assertEqual(codec.structure_reason(b"\x82" + good[1:]), "bad_version")
        self.assertEqual(codec.structure_reason(good + b"\x00"), "trailing_bytes")
        self.assertEqual(codec.structure_reason(good[:-1]), "truncated")
        self.assertEqual(codec.structure_reason(b"\x83\x6c\x00\x00\x00\x00\x6a"), "bad_tag")
        twice = b"\x83\x74\x00\x00\x00\x02" + b"\x77\x01t\x77\x06sample" * 2
        self.assertEqual(codec.structure_reason(twice), "duplicate_field")
        deep = codec.etf_encode({A("t"): [[[[[[1]]]]]]})
        self.assertEqual(codec.structure_reason(deep), "too_deep")
        self.assertEqual(codec.structure_reason(b"\x83\x74\x00\x00\x00\x11"), "too_long")
        self.assertEqual(codec.kind_of(codec.call_frame("r", "erlang", "ok", [1])), "call")
        hello = codec.etf_encode({A("t"): A("hello")})
        self.assertEqual((codec.structure_reason(hello), codec.kind_of(hello)), ("", "hello"))
        # a call naming an atom the node does not hold is refused for that atom, before its kind is looked at
        self.assertEqual(codec.structure_reason(codec.call_frame("r", "lists", "reverse", [1])), "unknown_atom")
        # the atoms held are exactly those of the Silica node's two atom files, src/tempus/bees_tempus.atoms and
        # src/trust/bees_trust.atoms (asserted here, and not as a test of its own, because the trial
        # trials/c7_tempus_node_python records one line for each test of this file)
        held = set()
        for name in ("src/tempus/bees_tempus.atoms", "src/trust/bees_trust.atoms"):
            with open(os.path.join(ROOT, name)) as f:
                for ln in f:
                    held.update(ln.split("#")[0].split())
        self.assertEqual(set(codec.NODE_ATOMS), held)
        self.assertEqual(len(held), 68)


# ---------------------------------------------------------------- replies
class Replies(unittest.TestCase):
    def setUp(self):
        self.v = adm.Verifier(t._raw_public(t.fixture_key(0)), "k1", 1500, 10, [])
        self.x = t.fixture_identity(64, "tempus_edge", 1000, 2000, addr="127.0.0.1:1")
        self.y = t.fixture_identity(96, "tempus_edge", 1000, 2000, addr="127.0.0.1:2")
        self.z = t.fixture_identity(128, "tempus_edge", 1000, 2000, addr="127.0.0.1:3")

    def refused(self, part, request, reply, count=3):
        with self.assertRaises(codec.Refused) as e:
            peer.check_reply(self.v, request, reply, count)
        self.assertIn(part, str(e.exception))

    def test_a_reply_must_be_the_reply_of_its_request(self):
        x, y, z = self.x, self.y, self.z
        smp, shf = codec.sample("tempus_edge", 2), codec.shuffle("tempus_edge", [x.entry(0)])
        self.assertEqual(peer.check_reply(self.v, smp, codec.sample_reply("tempus_edge", [y.entry(1)]), 3)[0], "sample_reply")
        self.assertEqual(peer.check_reply(self.v, shf, codec.shuffle_reply("tempus_edge", [y.entry(1), z.entry(2)]), 3)[0], "shuffle_reply")
        self.refused("not the reply of the request", smp, codec.shuffle_reply("tempus_edge", []))
        self.refused("not the reply of the request", shf, codec.sample_reply("tempus_edge", []))
        self.refused("not the reply of the request", smp, codec.done())
        self.refused("another store", smp, codec.sample_reply("tempus_bridge", []))
        self.refused("more entries than were asked for", smp, codec.sample_reply("tempus_edge", [x.entry(0), y.entry(0), z.entry(0)]))
        self.refused("more entries than the shuffle length", shf, codec.shuffle_reply("tempus_edge", [x.entry(0), y.entry(0), z.entry(0)]), 2)
        result = lambda rid: codec.etf_encode({A("t"): A("result"), A("ver"): 1, A("req_id"): rid, A("value"): 5})  # noqa: E731
        call = codec.call_frame(b"r1", "m", "f", [1])
        self.assertEqual(peer.check_reply(self.v, call, result(b"r1"), 3)[1]["value"], 5)
        self.refused("another req_id", call, result(b"zz"))
        self.refused("no reply", codec.call_frame(b"r1", "m", "f", [1], kind="cast"), result(b"r1"))

    def test_every_entry_of_a_reply_is_verified(self):
        smp = codec.sample("tempus_edge", 3)
        forged = t.fixture_identity(96, "tempus_edge", 1000, 2000, addr="127.0.0.1:2", producer=t.fixture_key(96))
        self.refused("entry 1: the signature does not verify", smp, codec.sample_reply("tempus_edge", [self.x.entry(0), forged.entry(0)]))
        expired = t.fixture_identity(96, "tempus_edge", 1000, 1400, addr="127.0.0.1:2")
        self.refused("entry 0: the token has expired", smp, codec.sample_reply("tempus_edge", [expired.entry(0)]))
        bridge = t.fixture_identity(96, "tempus_bridge", 1000, 2000, addr="127.0.0.1:2")
        self.refused("entry 0: typ is not the store's type", smp, codec.sample_reply("tempus_edge", [bridge.entry(0)]))


# ---------------------------------------------------------------- a node, stepped by hand
class Stepped:
    def __init__(self, role, name, port, typ, sentinels=None, random=None, clock=1500, **kw):
        self.lines, self.events = [], []
        self.clock, self.timers = t.TestClock(clock), t.TestTimers()
        conf = config.node_config(values(role=role, port=port, sentinels=sentinels,
                                         identity_keyfile=os.path.join(CERTS, name + "-key.pem"),
                                         identity_certfile=os.path.join(CERTS, name + ".pem"),
                                         producer_key=("k1", t._raw_public(t.fixture_key(0))), **kw))
        import bees_tempus_certs as certs
        token = t.make_token(t.fixture_key(0), "k1", certs.public_bytes(name), typ, 1000, 2000)
        self.node = node.Node(conf, token=token, address="127.0.0.1:%d" % port, on_event=self.events.append,
                              log=self.lines.append, clock=self.clock, timers=self.timers,
                              random=random or t.TestRandom())

    def wait(self, text, seconds=10.0):
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            if any(text in ln for ln in list(self.lines)):
                return
            time.sleep(0.01)
        raise AssertionError("no line with %r in:\n%s" % (text, "\n".join(self.lines)))

    def settle(self):
        self.node.peers("tempus_edge")           # an answer from the node's thread: everything posted before is done


class ANode(unittest.TestCase):
    def setUp(self):
        self.nodes = []

    def tearDown(self):
        for n in self.nodes:
            n.node.stop()

    def start(self, *a, **kw):
        n = Stepped(*a, **kw)
        self.nodes.append(n)
        n.node.start()
        return n

    def port(self):
        import socket
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        p = s.getsockname()[1]
        s.close()
        return p

    def test_join_shuffle_and_what_the_stores_hold(self):
        ps, pa, pb = self.port(), self.port(), self.port()
        s = self.start("sentinel", "sentinel", ps, "tempus_sentinel")
        s.wait("join: no sentinel is configured")
        sent = [("127.0.0.1", ps, "sentinel.pem")]
        a = self.start("edge", "other", pa, "tempus_edge", sent)
        a.wait("join: done")
        # a tick that finds the view empty asks a sentinel again; the sentinel's answer names the asker itself (it
        # joined before), and an entry for the node itself never enters its view
        self.assertTrue(a.timers.fire("tick tempus_edge"))
        a.wait("tick tempus_edge: the view is empty")
        a.wait("join: the sentinel answered for tempus_edge d4")
        b = self.start("edge", "node", pb, "tempus_edge", sent)
        b.wait("join: done")
        ida, idb, ids = a.node.identity.peer_id, b.node.identity.peer_id, s.node.identity.peer_id
        # the sentinel holds both joiners; the second joiner was answered with the first and never with itself; each
        # joiner keeps the sentinel it joined through (ruling NQ-12)
        self.assertEqual([e[0] for e in s.node.peers("tempus_edge")], [idb, ida])
        self.assertEqual(a.node.peers("tempus_edge"), [])
        self.assertEqual([(e[0], e[2]) for e in b.node.peers("tempus_edge")], [(ida, 0)])
        self.assertEqual([(e[0], e[2]) for e in a.node.peers("tempus_sentinel")], [(ids, 0)])
        self.assertEqual(s.node.peers("tempus_sentinel"), [])
        # B's tick: the partner is A, the buffer B's own entry at age 0; A answers from its empty view and now holds B
        self.assertTrue(b.timers.fire("tick tempus_edge"))
        b.wait("tick tempus_edge: shuffle merged")
        self.assertEqual([(e[0], e[2]) for e in a.node.peers("tempus_edge")], [(idb, 0)])
        self.assertEqual(b.node.peers("tempus_edge"), [])
        # a store that is not of the node's own type: the partner that answered re-enters at age 0 (ruling NQ-15)
        self.assertTrue(s.timers.fire("tick tempus_edge"))
        s.wait("tick tempus_edge: shuffle merged")
        self.assertEqual(len(s.node.peers("tempus_edge")), 2)
        self.assertIn("view", [e.name for e in b.events])

    def test_no_draws_no_choice(self):
        p = self.port()
        s = self.start("sentinel", "sentinel", p, "tempus_sentinel", random=t.TestRandom(fails=True))
        s.wait("join: no sentinel is configured")
        self.assertTrue(s.timers.fire("tick tempus_edge"))
        s.wait("tick tempus_edge: skipped (no draws)")
        me = t.fixture_identity(64, "tempus_edge", 1000, 2000, addr="127.0.0.1:1")
        v = t.Verifier(t._raw_public(t.fixture_key(0)), "k1", 1500, 10)
        out = t.dial("127.0.0.1:%d" % p, me, v, t.sample("tempus_edge", 1), timeout=3.0)
        # no nonce can be made either: the connection is closed, and the line says whose fault it is
        self.assertEqual(out.what, "closed")
        s.wait("[tempus audit] internal_error peer=- random bytes refused a1")

    def test_a_listen_address_in_use_is_said(self):
        import socket
        busy = socket.socket()
        busy.bind(("127.0.0.1", 0))
        busy.listen(1)
        try:
            s = self.start("sentinel", "sentinel", busy.getsockname()[1], "tempus_sentinel")
            s.wait("the listening link has gone down")
            s.settle()
            self.assertEqual([e.name for e in s.events], ["listen_failed"])
        finally:
            busy.close()

    def test_no_reading_at_start(self):
        s = self.start("sentinel", "sentinel", self.port(), "tempus_sentinel", clock=None)
        s.wait("clock: the system clock could not be read: the node has not started")
        s.settle()
        self.assertEqual([e.name for e in s.events], ["clock_unreadable"])
        self.assertFalse(any("listening" in ln for ln in s.lines))
        s.clock.value = 1500
        self.assertTrue(s.timers.fire("clock"))
        s.wait("listening on")
        self.assertEqual(s.lines[1], "clock: the system clock is read")


if __name__ == "__main__":
    unittest.main()

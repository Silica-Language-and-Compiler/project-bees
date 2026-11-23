#!/usr/bin/env python3
"""Walk the trial of the Rust TEMPUS client against real bridges (trials/c17_tempus_bridge_rust).

    walk.py LEAF_DIR PATH_OF_tempus-client

Node T (TRUST) and the bridges B1 and B2 are started as tools/bees_tempus_trial.py starts them. The Rust client is used
through its command line only (example_tempus_clients/rust): `listen` processes that stay up and one `dial` process per
request, with the classes of trials/c14_tempus_rust/client_walk.py. Every line the Rust client prints is checked here (a
failed check fails the trial) and written to rust.sout, which is compared with its golden. The Rust client sends no
test-only frame: the ticks and clock readings that drive the bridges, which are test programs, are sent here with the
Python test support. What a client cannot see is in the nodes' own outputs. COVERAGE.md says which row of the
behaviour list (design 16.2) each step shows.

  A  B2 joins through the Rust client listening as its sentinel, and asks it again when a store is empty
  B  a bridge learns another through the Rust client listening with a bridge token; an application gets a bridge
  C  calls and a cast: answered by the bridge, answered through the TRUST node, a function that fails, a call that
     takes longer than the bridge's bound
  D  the whitelist rule for a bridge certificate, at the client and at the bridge
  E  what the bridge refuses of an edge, until its score is above the limit and a good request is refused too
  F  the bridge's bound on one peer's requests in flight, and the node's bound on accepted connections
  G  the TRUST side refuses the bridge's request; the TRUST side is unreachable
  H  a bridge is lost
(The rows of the behaviour list that need no bridge and that the first Rust trial does not show are walked in
trials/c15_tempus_node_rust, steps K1 to K15, against Silica nodes that are not bridges.)
Keys, certificates and tokens are TEST ONLY, from fixed seeds. Ports come from tools/trial_ports.py.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.join(HERE, "..", "..", "tools")
sys.path.insert(0, TOOLS)
sys.path.insert(0, os.path.join(HERE, "..", "..", "example_tempus_clients", "python"))  # the Python test support
import bees_tempus_client as c  # noqa: E402
import trial_ports  # noqa: E402
sys.path.insert(0, os.path.join(HERE, "..", "c14_tempus_rust"))            # the class that runs the Rust command line
from client_walk import Rust, id8, seed  # noqa: E402
from bees_tempus_trial import CERTS, Node, check, quiet  # noqa: E402

BASE = trial_ports.TABLE["c17_tempus_bridge_rust"][0]
T_ADDR, B1, B2, SS_ADDR, E_ADDR, XB_ADDR, _B1T, _B2T, DEAD = ("127.0.0.1:%d" % (BASE + k) for k in range(9))
A = c.Atom


def pem(name):
    return os.path.join(CERTS, name + ".pem")


def main(argv):
    if len(argv) != 3:
        print(__doc__)
        return 2
    leaf, exe = os.path.abspath(argv[1]), os.path.abspath(argv[2])
    sw = Rust(exe, os.path.join(leaf, "rust.sout"))
    nodes = {}
    now = ["--now", "1500"]
    b1id, b2id = id8(160), id8(176)
    E = ["--seed", seed(64), "--addr", E_ADDR, "--test-token", "tempus_edge:1000:3000"]

    def edge(first):
        return ["--seed", seed(first), "--addr", DEAD, "--test-token", "tempus_edge:1000:3000"]

    XB = ["--seed", seed(224), "--addr", XB_ADDR, "--test-token", "tempus_bridge:1000:3000", "--cert", pem("x4")]
    SS = ["--seed", seed(128), "--addr", SS_ADDR, "--test-token", "tempus_sentinel:1000:3000", "--cert", pem("sentinel")]
    v = c.Verifier(c._raw_public(c.fixture_key(0)), "k1", 1500, 10)
    ticker = c.fixture_identity(32, "tempus_edge", 1000, 5000, addr=DEAD)      # the trial tool's own peer, for the test-only frames
    p1, p2 = " peer=%s typ=tempus_bridge" % b1id, " peer=%s typ=tempus_bridge" % b2id

    def test_frame(addr, body, verifier=v):
        out = c.dial(addr, ticker, verifier, body)
        check(out.what == "reply" and out.kind == "done", "a test-only frame to %s (the trial tool's own): %s" % (addr, out.line()))

    def call(label, addr, who, words, want, **kw):
        line = sw.dial(label, addr, who, kw.pop("clock", now), words, want, **kw)
        quiet()
        return line

    def result(value, peer):
        return "reply result req_id=31 value=%d ver=1%s" % (value, peer)

    def raw(body):
        return ["raw", body.hex()]

    try:
        # ---------------- A: B2 joins through the Rust client
        sw.say("# A: bridge B2 joins through the Rust client, which listens as its sentinel")
        ls = sw.listen("A0 the Rust client listens as the sentinel", SS_ADDR, SS, now)
        t = nodes["t"] = Node(os.path.join(leaf, "nodes", "t"), "dangerous_t")
        t.wait(r"listening on 127\.0\.0\.1")
        n1 = nodes["b1"] = Node(os.path.join(leaf, "nodes", "b1"), "dangerous_b1")
        n1.wait(r"^join: no sentinel is configured$")
        n2 = nodes["b2"] = Node(os.path.join(leaf, "nodes", "b2"), "dangerous_b2")
        n2.wait(r"^join: done$")
        quiet()
        served = "served sample n=%d store=%s sent=reply" + p2
        ls.next("A1 B2's join, edge store", served % (3, "tempus_edge"))
        ls.next("A1 B2's join, bridge store", served % (2, "tempus_bridge"))
        ls.next("A1 B2's join, sentinel store", served % (2, "tempus_sentinel"))
        test_frame(B2, c.tick("tempus_edge"))
        n2.wait(r"^tick tempus_edge: the view is empty$")
        ls.next("A2 a tick finds B2's edge store empty: B2 asks its sentinel again", served % (3, "tempus_edge"))
        n2.wait(r"^join: the sentinel answered for tempus_edge")
        quiet()

        # ---------------- B: bridges learn each other; an application gets a bridge
        sw.say("# B: bridge B1 learns bridge B2 through the Rust client, which listens with a bridge token")
        lb = sw.listen("B0 the Rust client listens as a bridge", XB_ADDR, XB, now, length=2,
                       entries=["tempus_bridge=0:176:tempus_bridge:1000:3000:" + B2])
        call("B1 as that bridge: shuffle tempus_bridge, its own entry at age 0", B1, XB, ["shuffle", "tempus_bridge"],
             "reply shuffle_reply entries=[] store=tempus_bridge" + p1, length=2)
        test_frame(B1, c.tick("tempus_bridge"))
        lb.next("B2 B1's tick: B1 shuffles its bridge store with the Rust client, its own entry at age 0",
                "served shuffle entries=[0:%s] store=tempus_bridge sent=reply%s" % (b1id, p1))
        n1.wait(r"^tick tempus_bridge: shuffle merged$")
        quiet()
        call("B3 an edge asks B1 for bridges: B1 holds B2, the entry the Rust client answered with", B1, E, ["sample", "tempus_bridge", "2"],
             "reply sample_reply entries=[0:%s] store=tempus_bridge%s" % (b2id, p1), length=2)
        call("B4 the application picks that bridge, B2, and calls it: demo:add(2, 40)", B2, E, ["call", "demo", "add", "2", "40"], result(42, p2))
        lb.stop()

        # ---------------- C: calls and a cast
        sw.say("# C: calls and a cast, as an edge")
        call("C1 call demo:add(2, 40) on B1", B1, E, ["call", "demo", "add", "2", "40"], result(42, p1))
        call("C2 call demo:onward(20, 22) on B1: the bridge's application calls demo:add on the TRUST node", B1, E,
             ["call", "demo", "onward", "20", "22"], result(42, p1))
        call("C3 the same through B2", B2, E, ["call", "demo", "onward", "20", "22"], result(42, p2))
        call("C4 cast demo:note(7) on B1: a cast has no reply", B1, E, ["cast", "demo", "note", "7"], "closed at=reply" + p1)
        check("[bridge] note got 7" in n1.text(), "C4: the cast did not run on B1")
        call("C5 call demo:crash(1): the function fails, and the client is told nothing", B1, E, ["call", "demo", "crash", "1"], "closed at=reply" + p1)
        call("C6 call demo:slow(1): longer than the bridge's call timeout", B1, E, ["call", "demo", "slow", "1"], "closed at=reply" + p1, timeout="8")
        call("C7 call demo:add(2, 3) afterwards", B1, E, ["call", "demo", "add", "2", "3"], result(5, p1))

        # ---------------- D: the whitelist rule
        sw.say("# D: the whitelist rule for a bridge certificate")
        smp = ["sample", "tempus_edge", "1"]
        call("D1 the client's whitelist holds B1's TEMPUS certificate", B1, E, smp, lambda ln: ln.startswith("reply sample_reply "),
             more=["--whitelist-cert", pem("bridge")])
        call("D2 the client's whitelist holds another certificate only: the client refuses the bridge", B1, E, smp,
             'refused at=advert peer=%s reason="the certificate of a tempus_bridge is not in the whitelist"' % b1id,
             more=["--whitelist-cert", pem("sentinel")])
        call("D3 the client shows a bridge token under a certificate B1 does not list: B1 refuses it", B1,
             ["--seed", seed(64), "--addr", E_ADDR, "--test-token", "tempus_bridge:1000:3000"], smp, "closed at=challenge" + p1)
        n1.wait(r"whitelist_reject peer=\S+ a tempus_bridge or tempus_sentinel token under a certificate that is not in the tempus whitelist")
        call("D4 the client shows a certificate B1 lists with an edge token: B1 refuses it", B1,
             ["--seed", seed(224), "--addr", E_ADDR, "--test-token", "tempus_edge:1000:3000", "--cert", pem("x4")], smp, "closed at=challenge" + p1)
        n1.wait(r"whitelist_reject peer=\S+ a certificate of the tempus whitelist with a token whose typ is not")

        # ---------------- E: refusals, and the score
        sw.say("# E: what B1 refuses of an edge; each refusal raises that edge's score, and above the limit a good request is refused")
        Q = edge(96)
        gone = "closed at=reply" + p1
        call("E1 a function of a forbidden module: erlang:apply", B1, Q, ["call", "erlang", "apply"], gone)
        call("E2 a function the edge is not permitted: demo:secret", B1, Q, ["call", "demo", "secret"], gone)
        call("E3 a request that says three arguments and carries two", B1, Q, raw(c.call_frame("1", "demo", "add", [2, 3], arity=3)), gone)
        call("E4 a request that says no argument and carries two", B1, Q, raw(c.call_frame("1", "demo", "add", [2, 3], arity=0)), gone)
        call("E5 a function that fails", B1, Q, ["call", "demo", "crash", "1"], gone)
        call("E6 a function of a forbidden module again", B1, Q, ["call", "erlang", "apply"], gone)
        call("E7 a good request, demo:add(2, 3): refused, the score is above the limit", B1, Q, ["call", "demo", "add", "2", "3"], gone)
        n1.wait(r"bridge_refused peer=\S+ score \d+ is above the limit 5")
        call("E8 another edge is served", B1, E, ["call", "demo", "add", "2", "3"], result(5, p1))

        # ---------------- F: requests in flight
        sw.say("# F: the bridge's bound of 2 requests in flight for one peer, and the node's bound of 4 accepted connections")
        F, G = edge(112), edge(208)
        held = []

        def hold(who):
            held.append(subprocess.Popen([exe, "dial", B1] + who + sw.checks(now, timeout="8") + ["call", "demo", "hold", "1"],
                                         stdout=subprocess.PIPE, text=True))
            n1.wait(r"bridge_admitted peer=\S+ call demo:hold/1")
            quiet(0.3)

        hold(F)
        hold(F)
        call("F1 two calls of one edge are held by the bridge's application; its third request is refused", B1, F,
             ["call", "demo", "add", "2", "3"], gone)
        n1.wait(r"bridge_inflight peer=\S+ the peer's requests in flight are at their bound")
        hold(G)
        hold(G)
        call("F2 four connections are in hand (inflight_max): a fifth is closed at once after its handshake", B1, E,
             ["call", "demo", "add", "2", "3"], "closed at=advert")
        n1.wait(r"inflight_refused peer=- more accepted connections than inflight_max: closed at once")
        for k, h in enumerate(held, start=1):
            line = h.communicate(timeout=30)[0].strip()
            sw.say("F3 held call %d, closed by the bridge at its call timeout -> %s" % (k, line))
            check(line == gone, "F3: a held call ended as: " + line)
        quiet(1.0)
        call("F4 afterwards the edge is served again", B1, E, ["call", "demo", "add", "2", "3"], result(5, p1))

        # ---------------- G: the TRUST side
        sw.say("# G: the TRUST side refuses the bridge, and then is not there")
        call("G1 call demo:bad on B2: its application calls a function the TRUST node does not permit the bridge", B2, E,
             ["call", "demo", "bad"], "closed at=reply" + p2)
        call("G2 call demo:onward(20, 22) on B2 afterwards", B2, E, ["call", "demo", "onward", "20", "22"], result(42, p2))
        nodes.pop("t").stop()
        call("G3 the TRUST node has stopped: demo:onward on B2 is closed with no reply", B2, E, ["call", "demo", "onward", "20", "22"],
             "closed at=reply" + p2, timeout="8")
        call("G4 a function the bridge runs itself is still answered", B2, E, ["call", "demo", "add", "2", "40"], result(42, p2))

        # ---------------- H: a bridge is lost
        sw.say("# H: bridge B2 is stopped")
        nodes.pop("b2").stop()
        ls.stop()
        call("H1 a call to B2", B2, E, ["call", "demo", "add", "2", "40"], "unreachable at=tls")
        test_frame(B1, c.tick("tempus_bridge"))
        n1.wait(r"^tick tempus_bridge: shuffle failed$")
        quiet()
        call("H2 B1's tick dialed B2 and failed: B1 holds no bridge any more", B1, E, ["sample", "tempus_bridge", "2"],
             "reply sample_reply entries=[] store=tempus_bridge" + p1, length=2)
        call("H3 a call through B1 is answered", B1, E, ["call", "demo", "add", "2", "40"], result(42, p1))

    finally:
        for node in list(nodes.values()):
            node.stop()
        sw.close()
    print("[c17] the Rust client's steps against the bridges passed")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

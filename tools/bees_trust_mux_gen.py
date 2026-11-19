#!/usr/bin/env python3
"""bees_trust_mux_gen: the generators of a TRUST session node's units (N5, B2: windowed multiplexing;
development-plan/spikes/N5-multiplexing.md). Called by tools/bees_trust_gen.py (its `mfa` step, when the node's bees.config
multiplexes); it can also be run by hand:

    bees_trust_mux_gen.py OUT_DIR BEES_CONFIG      write the session units of that node into OUT_DIR (its lib/)

Written into OUT_DIR:
    bees_trust_slots.silica            generated: the per-connection supervisor `msup` (the table of requests in work: a req_id
                                       as three words, a sequence number, flags, the start time; refuses a duplicate req_id,
                                       starts one worker per request, arms the call timer), the client's pending table `mpend`
                                       (who waits for which result) and the metrics actor `mmet`. Their tables are records of
                                       scalars sized by trust.session.max_inflight, because an actor that lives as long as a
                                       session may hold no heap value (SD-35).
    dangerous_bees_trust_mux.silica    src/trust/dangerous_bees_trust_mux.silica.in with its record macros expanded (expand())
    bees_trust_mux_frame.silica, bees_trust_mux.atoms    links to src/trust (the pure frame unit and the session atoms)

Record macros of a `.silica.in` source (Silica has no record update and no type names):
    //@type NAME = field: type, ...     defines NAME (the line is kept as a comment)
    @{NAME}                             the record type
    @{NAME x | f: e, ...}               a record of that type, every field from x.f except the ones given
    @{NAME x + OTHER y | f: e, ...}     the same, with the fields that OTHER has taken from y
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "src", "trust")
TEMPLATE = os.path.join(SRC, "dangerous_bees_trust_mux.silica.in")
LINKS = ("bees_trust_mux_frame.silica", "bees_trust_mux.atoms")

# the metrics of the multiplexing design ("Observability"), in the order of mmet's counters; the index is what the session
# actors cast. Histograms are count and sum (N5 Q10); the counts of the three histograms are other counters (see DERIVED).
METRICS = [
    "trust_sessions_started_total", "trust_sessions_active",
    'trust_sessions_ended_total{reason="limit_reached"}', 'trust_sessions_ended_total{reason="shutdown"}',
    'trust_sessions_ended_total{reason="deny"}', 'trust_sessions_ended_total{reason="protocol"}',
    'trust_sessions_ended_total{reason="client_cancel"}', 'trust_sessions_ended_total{reason="other"}',
    'trust_goaway_total{reason="limit_reached"}', 'trust_goaway_total{reason="shutdown"}',
    'trust_goaway_total{reason="deny"}', 'trust_goaway_total{reason="protocol"}',
    'trust_requests_total{type="call",outcome="ok"}', 'trust_requests_total{type="call",outcome="error"}',
    'trust_requests_total{type="cast",outcome="ok"}', 'trust_requests_total{type="cast",outcome="error"}',
    'trust_requests_refused_total{reason="draining"}', 'trust_requests_refused_total{reason="duplicate"}',
    'trust_requests_refused_total{reason="malformed"}', 'trust_requests_refused_total{reason="max_inflight"}',
    "trust_duplicates_total", "trust_client_cancels_total", 'trust_worker_crashes_total{class="error"}',
    "trust_protocol_close_total", "trust_resume_reads_total",
    "(unused)", "trust_session_age_ms_sum", "(unused)", "trust_result_latency_ms_sum", "(unused)", "trust_paused_duration_ms_sum",
]
# sums whose value is wall-clock time: printed as the name and the value, so a trial can mask them
TIME_SUMS = (26, 28, 30)


def split_top(s):
    """split on commas outside (), [] and {}"""
    out, depth, cur = [], 0, ""
    for ch in s:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur)
    return out


def expand(text):
    """expand the record macros of a .silica.in source"""
    types = {}
    for m in re.finditer(r"^//@type (\w+) = (.*)$", text, re.M):
        fields = []
        for part in split_top(m.group(2)):
            name, typ = part.split(":", 1)
            fields.append((name.strip(), typ.strip()))
        types[m.group(1)] = fields
    out, i = [], 0
    while True:
        j = text.find("@{", i)
        if j < 0:
            out.append(text[i:])
            break
        out.append(text[i:j])
        depth, k = 1, j + 2
        while depth:
            if text[k] == "{":
                depth += 1
            elif text[k] == "}":
                depth -= 1
            k += 1
        body = text[j + 2:k - 1]
        head, _, over = body.partition("|")
        overrides = {}
        for part in split_top(over):
            name, val = part.split(":", 1)
            overrides[name.strip()] = val.strip()
        hm = re.fullmatch(r"\s*(\w+)(?:\s+(\w+)(?:\s*\+\s*(\w+)\s+(\w+))?)?\s*", head)
        if not hm or hm.group(1) not in types:
            raise SystemExit(f"bees_trust_mux_gen: cannot read the macro @{{{body}}}")
        name, base, other, obase = hm.groups()
        fields = types[name]
        if base is None:
            out.append("{ " + ", ".join(f"{f}: {t}" for f, t in fields) + " }")
        else:
            unknown = set(overrides) - {f for f, _ in fields}
            if unknown:
                raise SystemExit(f"bees_trust_mux_gen: @{{{body}}}: {name} has no field {sorted(unknown)}")
            ofields = {f for f, _ in types[other]} if other else set()
            parts = []
            for f, _ in fields:
                if f in overrides:
                    parts.append(f"{f}: {overrides[f]}")
                elif f in ofields:
                    parts.append(f"{f}: {obase}.{f}")
                else:
                    parts.append(f"{f}: {base}.{f}")
            out.append("{ " + ", ".join(parts) + " }")
        i = k
    return "".join(out)


M5 = "(:bees, int64, string, string, int64)"
WHO = "(:who, int64, atom, atom, int64, string, actor_ref, int64)"
POL = "stack_policy(0, :keep_last_message), state_policy(:keep_state_area)"


def chain(n, cond, default):
    e = default
    for i in reversed(range(n)):
        e = f"case {cond(i)} of {{ true -> {i}; false -> {e} }}"
    return e


def pick(n, field, default):
    return "case i of { " + " ".join(f"{i} -> st.{field}{i};" for i in range(n)) + f" _: int64 -> {default} }}"


def gen_sup(n):
    st = "{ conn: actor_ref, n: int64, seq: int64, det: boolean, " + ", ".join(
        f"a{i}: int64, b{i}: int64, c{i}: int64, m{i}: int64, t{i}: int64" for i in range(n)) + " }"
    L = []
    L.append("// ---- msup: the per-connection supervisor (a plain behaviour with a table; N5 Q11). Messages (:bees, k, s1, s2, n):")
    L.append("//   1, 2   admit a call / a cast: s1 the args span, s2 the req_id, n the MFA table slot. Answer to the connection:")
    L.append("//          (:bees, 30, req_id, \"\", kind) in work, or (:bees, 31, req_id, \"\", 0 a duplicate req_id in work | 2 no free row)")
    L.append("//   5      the call timer: s1 the req_id, n the admission's sequence number; the connection gets (:bees, 33, req_id, \"\", 0)")
    L.append("//   9      a worker's answer (bees_trust_work@twork): passed on as (:bees, 9, s1, req_id, code + 10 * cast + 100 * timed_out")
    L.append("//          + 1000 * duration_ms); the row is free again")
    L.append("//   40     detach: the connection is closing; it gets (:bees, 41, \"\", \"\", in_work) as the LAST message from here, results")
    L.append("//          are dropped from then on, and the supervisor ends when its last worker has answered")
    L.append("// A row: a, b, c the req_id as words (c is never 0 for a row in use), m = 4 * sequence + 2 * cast + timed_out, t the start time.")
    L.append(f"fn sup_k(msg: {M5}) -> int64 {{ case msg of {{ (:bees, k: int64, _a: string, _b: string, _n: int64) -> k }} }}")
    L.append(f"fn sup_s1(msg: {M5}) -> string {{ case msg of {{ (:bees, _k: int64, a: string, _b: string, _n: int64) -> a }} }}")
    L.append(f"fn sup_s2(msg: {M5}) -> string {{ case msg of {{ (:bees, _k: int64, _a: string, b: string, _n: int64) -> b }} }}")
    L.append(f"fn sup_n(msg: {M5}) -> int64 {{ case msg of {{ (:bees, _k: int64, _a: string, _b: string, n: int64) -> n }} }}")
    L.append(f"fn sup_find(st: {st}, a: int64, b: int64, c: int64) -> int64 {{ {chain(n, lambda i: f'st.c{i} == c and st.a{i} == a and st.b{i} == b', '0 - 1')} }}")
    L.append(f"fn sup_free(st: {st}) -> int64 {{ {chain(n, lambda i: f'st.c{i} == 0', '0 - 1')} }}")
    L.append(f"fn sup_m(st: {st}, i: int64) -> int64 {{ {pick(n, 'm', '0')} }}")
    L.append(f"fn sup_t(st: {st}, i: int64) -> int64 {{ {pick(n, 't', '0')} }}")
    L.append("fn sup_arm(me: actor_ref, rid: string, seq: int64) -> boolean {")
    L.append("    sequence proc[concurrency]")
    L.append("        t: timer_ref <- send_after(bees_trust_conf@call_timeout_ms(), me, (:bees, 5, rid, \"\", seq) impl ActorMessage {})")
    L.append("    produces pure true end")
    L.append("}")
    L.append("fn sup_run(me: actor_ref, slot: int64, args: string, rid: string, k: int64, seq: int64) -> boolean {")
    L.append("    sequence proc[concurrency]")
    L.append(f"        w: actor_ref <- spawn(0, bees_trust_work@twork, {POL});")
    L.append("        ok: boolean <- cast(w, (slot, args, rid, me) impl ActorMessage {});")
    L.append("        _: boolean <- case k == 1 of { true -> sup_arm(me, rid, seq); false -> true }")
    L.append("    produces pure ok end")
    L.append("}")
    L.append("fn sup_to(conn: actor_ref, k: int64, s1: string, s2: string, n: int64) -> boolean {")
    L.append("    sequence proc[concurrency]")
    L.append("        ok: boolean <- cast(conn, (:bees, k, s1, s2, n) impl ActorMessage {})")
    L.append("    produces pure ok end")
    L.append("}")
    L.append(f"fn msup(msg: {M5}, st: {st}) -> (:no_reply, {st}) {{")
    L.append("    sequence proc[concurrency]")
    L.append("        me: actor_ref <- self();")
    L.append("        k: int64 <- sup_k(msg);")
    L.append("        s1: string <- sup_s1(msg);")
    L.append("        s2: string <- sup_s2(msg);")
    L.append("        n: int64 <- sup_n(msg);")
    L.append("        rid: string <- case k == 5 of { true -> s1; false -> s2 };")
    L.append("        a: int64 <- bees_trust_mux_frame@id_a(rid);")
    L.append("        b: int64 <- bees_trust_mux_frame@id_b(rid);")
    L.append("        c: int64 <- bees_trust_mux_frame@id_c(rid);")
    L.append("        hit: int64 <- case k == 40 of { true -> 0 - 1; false -> sup_find(st, a, b, c) };")
    L.append("        free: int64 <- sup_free(st);")
    L.append("        now: int64 <- monotonic_time();")
    L.append("        req: boolean <- (k == 1 or k == 2) and st.det == false;")
    L.append("        put: int64 <- case req and hit < 0 of { true -> free; false -> 0 - 1 };")
    L.append("        seq1: int64 <- st.seq + 1;")
    L.append("        hm: int64 <- sup_m(st, hit);")
    L.append("        _: boolean <- case put >= 0 of { true -> sup_run(me, n, s1, rid, k, seq1); false -> true };")
    L.append("        _: boolean <- case req of {")
    L.append("            true -> case put >= 0 of { true -> sup_to(st.conn, 30, rid, \"\", k); false -> sup_to(st.conn, 31, rid, \"\", case hit >= 0 of { true -> 0; false -> 2 }) };")
    L.append("            false -> true")
    L.append("        };")
    L.append("        mark: int64 <- case k == 5 and hit >= 0 and hm / 4 == n and hm % 2 == 0 of { true -> hit; false -> 0 - 1 };")
    L.append("        _: boolean <- case mark >= 0 and st.det == false of { true -> sup_to(st.conn, 33, rid, \"\", 0); false -> true };")
    L.append("        clr: int64 <- case k == 9 of { true -> hit; false -> 0 - 1 };")
    L.append("        dur: int64 <- (now - sup_t(st, hit)) / 1000000;")
    L.append("        fwd: int64 <- n + 10 * ((hm / 2) % 2) + 100 * (hm % 2) + 1000 * dur;")
    L.append("        _: boolean <- case clr >= 0 and st.det == false of { true -> sup_to(st.conn, 9, s1, rid, fwd); false -> true };")
    L.append("        n1: int64 <- st.n + case put >= 0 of { true -> 1; false -> 0 } - case clr >= 0 of { true -> 1; false -> 0 };")
    L.append("        det1: boolean <- st.det or k == 40;")
    L.append("        _: boolean <- case k == 40 and st.det == false of { true -> sup_to(st.conn, 41, \"\", \"\", st.n); false -> true };")
    L.append("        m1: int64 <- 4 * seq1 + case k == 2 of { true -> 2; false -> 0 };")
    L.append("        _: atom <- case det1 and n1 == 0 of { true -> stop_self(:normal); false -> :ok }")
    L.append("    produces pure (:no_reply, {")
    L.append("        conn: st.conn, n: n1, seq: case put >= 0 of { true -> seq1; false -> st.seq }, det: det1,")
    rows = []
    for i in range(n):
        rows.append(f"        a{i}: case put == {i} of {{ true -> a; false -> case clr == {i} of {{ true -> 0; false -> st.a{i} }} }}, "
                    f"b{i}: case put == {i} of {{ true -> b; false -> case clr == {i} of {{ true -> 0; false -> st.b{i} }} }}, "
                    f"c{i}: case put == {i} of {{ true -> c; false -> case clr == {i} of {{ true -> 0; false -> st.c{i} }} }}, "
                    f"m{i}: case put == {i} of {{ true -> m1; false -> case clr == {i} of {{ true -> 0; false -> case mark == {i} of {{ true -> st.m{i} + 1; false -> st.m{i} }} }} }}, "
                    f"t{i}: case put == {i} of {{ true -> now; false -> st.t{i} }}")
    L.append(",\n".join(rows) + " }) end")
    L.append("}")
    zero = ", ".join(f"a{i}: 0, b{i}: 0, c{i}: 0, m{i}: 0, t{i}: 0" for i in range(n))
    L.append("// a new supervisor for the connection actor conn")
    L.append("fn sup_start(conn: actor_ref) -> actor_ref {")
    L.append("    sequence proc[concurrency]")
    L.append(f"        s: actor_ref <- spawn({{ conn: conn, n: 0, seq: 0, det: false, {zero} }}, msup, {POL})")
    L.append("    produces pure s end")
    L.append("}")
    return L


def gen_pend(n):
    st = ("{ tx: actor_ref, srv: int64, gen: int64, phase: int64, told: boolean, acked: boolean, txdone: boolean, seq: int64, fk: int64, fm: atom, ff: atom, "
          "fa: int64, fargs: string, fwho: actor_ref, freq: int64, "
          + ", ".join(f"w{i}: actor_ref, r{i}: int64, q{i}: int64" for i in range(n)) + " }")
    PM = f"{WHO} | {M5}"
    L = []
    L.append("// ---- mpend: a client connection's pending table and request entry. Messages:")
    L.append("//   (:who, k, m, f, arity, args, reply_to, req)   k 1 a call, 2 a cast (from the server's manager, on an acknowledged session);")
    L.append("//                                  30 close the session (trpc_close); 120 the manager's answer to `gone`: nothing more comes from it")
    L.append("//   (:bees, k, s1, s2, n) from the connection actor and timers:")
    L.append("//     21 the handshake frames are written: send the first request   22 the server acknowledged: a session (the manager is told)")
    L.append("//     2 a result (s1 req_id, s2 the value span)   23 goaway limit_reached or shutdown: take no more (the manager is told `gone`)")
    L.append("//     24 the connection ended (n = status + 100 * link_down): every waiting call is answered with the status, the send actor ended")
    L.append("//     5 a call's timer (s1 req_id): answered timeout")
    L.append("// Phases: 0 not yet sent   1 the first request is sent   2 a session   3 draining or closing   4 ended, waiting for the manager.")
    L.append("// A request it cannot take goes back to the manager: 10 + kind when the session is ending (a new connection), 20 + kind when the")
    L.append("// table is full (its own connection, B1). A row: w who to answer, r its request number, q the req_id's sequence number (0 free).")
    L.append("// The req_id is 14 bytes: the row and the sequence number (bees_trust_mux_frame@id_make). A cast takes no row.")
    acc = [("pk", "int64", "k", "1000 + k2"), ("pm", "atom", "m", "bees_atoms@a_error()"), ("pf", "atom", "f", "bees_atoms@a_error()"),
           ("pa", "int64", "a", "n"), ("pargs", "string", "s", "s1"), ("preq", "int64", "r", "0"), ("ps2", "string", '""', "s2")]
    for name, typ, wv, bv in acc:
        L.append(f"fn {name}(msg: {PM}) -> {typ} {{ case msg of {{ (:who, k: int64, m: atom, f: atom, a: int64, s: string, _w: actor_ref, r: int64) -> {wv}; "
                 f"(:bees, k2: int64, s1: string, s2: string, n: int64) -> {bv} }} }}")
    L.append(f"fn pwho(msg: {PM}, me: actor_ref) -> actor_ref {{ case msg of {{ (:who, _k: int64, _m: atom, _f: atom, _a: int64, _s: string, w: actor_ref, _r: int64) -> w; "
             f"(:bees, _k2: int64, _s1: string, _s2: string, _n: int64) -> me }} }}")
    L.append(f"fn pend_free(st: {st}) -> int64 {{ {chain(n, lambda i: f'st.q{i} == 0', '0 - 1')} }}")
    L.append(f"fn pend_q(st: {st}, i: int64) -> int64 {{ {pick(n, 'q', '0 - 1')} }}")
    L.append(f"fn pend_r(st: {st}, i: int64) -> int64 {{ {pick(n, 'r', '0')} }}")
    L.append(f"fn pend_w(st: {st}, i: int64, me: actor_ref) -> actor_ref {{ case i of {{ " + " ".join(f"{i} -> st.w{i};" for i in range(n)) + " _: int64 -> me } }")
    L.append("fn pend_answer(who: actor_ref, req: int64, what: atom, value: string) -> boolean {")
    L.append("    sequence proc[concurrency]")
    L.append("        m: { req: int64, what: atom, value: string } <- { req: req, what: what, value: value };")
    L.append("        ok: boolean <- cast(who, m impl ActorMessage {})")
    L.append("    produces pure ok end")
    L.append("}")
    L.append("fn pend_tx(tx: actor_ref, kind: int64, s1: string, s2: string, m: atom, f: atom, n: int64) -> boolean {")
    L.append("    sequence proc[concurrency]")
    L.append("        ok: boolean <- cast(tx, (:bees, kind, s1, s2, m, f, n) impl ActorMessage {})")
    L.append("    produces pure ok end")
    L.append("}")
    L.append("fn pend_mgr(srv: int64, k: int64, m: atom, f: atom, a: int64, args: string, who: actor_ref, req: int64) -> boolean {")
    L.append("    sequence proc[concurrency]")
    L.append("        ok: boolean <- cast_registered(bees_trust_conf@mgr_name(srv), (:who, k, m, f, a, args, who, req) impl ActorMessage {})")
    L.append("    produces pure ok end")
    L.append("}")
    L.append("fn pend_arm(me: actor_ref, rid: string) -> boolean {")
    L.append("    sequence proc[concurrency]")
    L.append("        t: timer_ref <- send_after(bees_trust_conf@call_timeout_ms(), me, (:bees, 5, rid, \"\", 0) impl ActorMessage {})")
    L.append("    produces pure true end")
    L.append("}")
    L.append(f"fn pend_flush(st: {st}, what: atom) -> boolean {{")
    L.append("    sequence")
    for i in range(n):
        L.append(f"        _: boolean <- case st.q{i} != 0 of {{ true -> pend_answer(st.w{i}, st.r{i}, what, \"\"); false -> true }};")
    L.append("        ok: boolean <- true")
    L.append("    produces pure ok end")
    L.append("}")
    L.append(f"fn mpend(msg: {PM}, st: {st}) -> (:no_reply, {st}) {{")
    L.append("    sequence proc[concurrency%s]" % (", device_io" if os.environ.get("BEES_MUX_DEBUG") else ""))
    L.append("        me: actor_ref <- self();")
    L.append("        k: int64 <- pk(msg);")
    if os.environ.get("BEES_MUX_DEBUG"):
        L.append("        _: atom <- println(concat(concat(\"[mpend] k=\", bees_trust_frame@int_text(k)), concat(\" phase=\", bees_trust_frame@int_text(st.phase))));")
    L.append("        isreq: boolean <- k == 1 or k == 2;")
    L.append("        isgo: boolean <- k == 1021 and st.phase == 0;")
    L.append("        rk: int64 <- case isgo of { true -> st.fk; false -> k };")
    L.append("        rm: atom <- case isgo of { true -> st.fm; false -> pm(msg) };")
    L.append("        rf: atom <- case isgo of { true -> st.ff; false -> pf(msg) };")
    L.append("        ra: int64 <- case isgo of { true -> st.fa; false -> pa(msg) };")
    L.append("        rargs: string <- case isgo of { true -> st.fargs; false -> pargs(msg) };")
    L.append("        rwho: actor_ref <- case isgo of { true -> st.fwho; false -> pwho(msg, me) };")
    L.append("        rreq: int64 <- case isgo of { true -> st.freq; false -> preq(msg) };")
    L.append("        can: boolean <- isgo or (isreq and st.phase == 2);")
    L.append("        free: int64 <- pend_free(st);")
    L.append("        put: int64 <- case can and rk == 1 of { true -> free; false -> 0 - 1 };")
    L.append("        sent: boolean <- can and (rk == 2 or put >= 0);")
    L.append("        seq1: int64 <- st.seq + 1;")
    L.append(f"        rid: string <- bees_trust_mux_frame@id_make(case put >= 0 of {{ true -> put; false -> {n} }}, seq1);")
    if os.environ.get("BEES_MUX_DEBUG"):
        L.append("        _: atom <- println(concat(concat(\"[mpend] put=\", bees_trust_frame@int_text(put)), concat(concat(\" rk=\", bees_trust_frame@int_text(rk)), concat(\" ridlen=\", bees_trust_frame@int_text(length_bytes(rid))))));")
    L.append("        _: boolean <- case sent of { true -> pend_tx(st.tx, case rk == 1 of { true -> 7; false -> 8 }, rid, rargs, rm, rf, ra); false -> true };")
    L.append("        _: boolean <- case put >= 0 of { true -> pend_arm(me, rid); false -> true };")
    L.append("        _: boolean <- case sent and rk == 2 of { true -> pend_answer(rwho, rreq, bees_atoms@a_cast(), \"\"); false -> true };")
    L.append("        // not taken: the table is full (its own connection), or the session is not one (any more): a new connection")
    L.append("        _: boolean <- case can and rk == 1 and put < 0 of { true -> pend_mgr(st.srv, 20 + rk, rm, rf, ra, rargs, rwho, rreq); false -> true };")
    L.append("        _: boolean <- case isreq and st.phase != 2 of { true -> pend_mgr(st.srv, 10 + rk, rm, rf, ra, rargs, rwho, rreq); false -> true };")
    L.append("        // a result, or a call's timer: the row named by the req_id, if it still holds that sequence number")
    L.append("        s1: string <- pargs(msg);")
    L.append("        hs: int64 <- case k == 1002 or k == 1005 of { true -> bees_trust_mux_frame@id_slot(s1); false -> 0 - 1 };")
    L.append("        hq: int64 <- bees_trust_mux_frame@id_seq(s1);")
    L.append("        clr: int64 <- case hs >= 0 and hq > 0 and pend_q(st, hs) == hq of { true -> hs; false -> 0 - 1 };")
    L.append("        val: string <- ps2(msg);")
    L.append("        cw: actor_ref <- pend_w(st, clr, me);")
    L.append("        _: boolean <- case clr >= 0 of { true -> pend_answer(cw, pend_r(st, clr), case k == 1002 of { true -> bees_atoms@a_ok(); false -> bees_atoms@a_timeout() }, case k == 1002 of { true -> val; false -> \"\" }); false -> true };")
    L.append("        // the server acknowledged the offer: the manager may route requests here")
    L.append("        act: boolean <- k == 1022 and st.phase == 1;")
    L.append("        _: boolean <- case act of { true -> pend_mgr(st.srv, 100, bees_atoms@a_error(), bees_atoms@a_error(), 0, \"\", me, st.gen); false -> true };")
    L.append("        // the end: by the connection (24), or asked by trpc_close (30: the send actor closes the carrier, the server sees a")
    L.append("        // client close, which cancels the session; every waiting call is answered `closed`)")
    L.append("        ended: boolean <- k == 1024 and st.phase != 4;")
    L.append("        closing: boolean <- k == 30 and (st.phase == 1 or st.phase == 2 or st.phase == 3) and st.txdone == false;")
    L.append("        status: int64 <- pa(msg) % 100;")
    L.append("        what: atom <- bees_trust_mux_frame@status_atom(case closing of { true -> 1; false -> status });")
    L.append("        _: boolean <- case ended or closing of { true -> pend_flush(st, what); false -> true };")
    L.append("        _: boolean <- case ended and st.phase == 0 and st.fk != 0 of { true -> pend_answer(st.fwho, st.freq, what, \"\"); false -> true };")
    L.append("        _: boolean <- case closing of { true -> pend_tx(st.tx, 3, \"\", \"\", bees_atoms@a_error(), bees_atoms@a_error(), 0); false -> true };")
    L.append("        _: boolean <- case ended and st.txdone == false of { true -> pend_tx(st.tx, case pa(msg) >= 100 of { true -> 10; false -> 3 }, \"\", \"\", bees_atoms@a_error(), bees_atoms@a_error(), 0); false -> true };")
    L.append("        // the client's own window: after session.max_calls requests on a session it puts no more on it (the next one opens a")
    L.append("        // new connection). A server with the same max_calls sends its goaway at that request, and nothing was written")
    L.append("        // behind it; without this, the calls written behind a window's last request end `closed` (they are never re-sent,")
    L.append("        // N5 Q5). The server tells the client nothing: the number is the client's own configuration.")
    L.append("        lim: boolean <- sent and isgo == false and seq1 >= bees_trust_conf@session_max_calls();")
    L.append("        drain: boolean <- (k == 1023 or lim) and st.phase == 2;")
    L.append("        tell: boolean <- (ended or closing or drain) and st.told == false;")
    L.append("        _: boolean <- case tell of { true -> pend_mgr(st.srv, 110, bees_atoms@a_error(), bees_atoms@a_error(), 0, \"\", me, st.gen); false -> true };")
    L.append("        acked1: boolean <- st.acked or k == 120;")
    L.append("        phase1: int64 <- case ended of { true -> 4; false -> case closing or drain of { true -> 3; false -> case act of { true -> 2; false -> case isgo of { true -> 1; false -> st.phase } } } };")
    L.append("        wipe: boolean <- ended or closing;")
    L.append("        _: atom <- case phase1 == 4 and acked1 of { true -> stop_self(:normal); false -> :ok }")
    L.append("    produces pure (:no_reply, {")
    L.append("        tx: st.tx, srv: st.srv, gen: st.gen, phase: phase1, told: st.told or tell, acked: acked1, txdone: st.txdone or closing or ended,")
    L.append("        seq: case sent of { true -> seq1; false -> st.seq }, fk: st.fk, fm: st.fm, ff: st.ff, fa: st.fa, fargs: st.fargs, fwho: st.fwho, freq: st.freq,")
    rows = []
    for i in range(n):
        rows.append(f"        w{i}: case put == {i} of {{ true -> rwho; false -> st.w{i} }}, r{i}: case put == {i} of {{ true -> rreq; false -> st.r{i} }}, "
                    f"q{i}: case put == {i} of {{ true -> seq1; false -> case wipe or clr == {i} of {{ true -> 0; false -> st.q{i} }} }}")
    L.append(",\n".join(rows) + " }) end")
    L.append("}")
    zero = ", ".join(f"w{i}: tx, r{i}: 0, q{i}: 0" for i in range(n))
    L.append("// the pending table of a new client connection to pinned server srv (the manager's session number gen), holding the")
    L.append("// connection's first request until the handshake frames are written")
    L.append(f"fn pend_start(tx: actor_ref, srv: int64, gen: int64, first: {WHO}) -> actor_ref {{")
    L.append("    sequence proc[concurrency]")
    L.append("        p: actor_ref <- case first of {")
    L.append("            (:who, k: int64, m: atom, f: atom, a: int64, args: string, who: actor_ref, req: int64) ->")
    L.append(f"                spawn({{ tx: tx, srv: srv, gen: gen, phase: 0, told: false, acked: false, txdone: false, seq: 0, fk: k % 10, fm: m, ff: f, fa: a, fargs: args, fwho: who, freq: req, {zero} }}, mpend, {POL})")
    L.append("        }")
    L.append("    produces pure p end")
    L.append("}")
    return L


def gen_met():
    n = len(METRICS)
    st = "{ " + ", ".join(f"v{i}: int64" for i in range(n)) + " }"
    L = []
    L.append("// ---- mmet: the node's session metrics (registered as bees_trust_metrics). (:bees, i, \"\", \"\", d) adds d to counter i;")
    L.append("// (:bees, 100, \"\", \"\", 0) prints them all, one `[trust metrics] name value` line each; (:bees, 101, ...) prints them 200 ms")
    L.append("// later (for a caller whose own request is still being finished: two actors printing at once can mix their lines).")
    L.append("// Histograms are count and sum (N5 Q10).")
    L.append("fn met_line(name: string, v: int64) -> atom {")
    L.append("    sequence proc[device_io]")
    L.append("        _: atom <- println(concat(concat(\"[trust metrics] \", name), concat(\" \", bees_trust_frame@int_text(v))))")
    L.append("    produces pure :ok end")
    L.append("}")
    L.append(f"fn met_dump(st: {st}) -> atom {{")
    L.append("    sequence")
    for i, name in enumerate(METRICS):
        if name != "(unused)":
            L.append(f"        _: atom <- met_line({chr(34)}{name.replace(chr(34), chr(92) + chr(34))}{chr(34)}, st.v{i});")
    L.append("        _: atom <- met_line(\"trust_session_age_ms_count\", st.v2 + st.v3 + st.v4 + st.v5 + st.v6 + st.v7);")
    L.append("        _: atom <- met_line(\"trust_result_latency_ms_count\", st.v12 + st.v13 + st.v14 + st.v15);")
    L.append("        _: atom <- met_line(\"trust_paused_duration_ms_count\", st.v24)")
    L.append("    produces pure :ok end")
    L.append("}")
    L.append("fn met_later(me: actor_ref) -> boolean {")
    L.append("    sequence proc[concurrency]")
    L.append("        t: timer_ref <- send_after(200, me, (:bees, 100, \"\", \"\", 0) impl ActorMessage {})")
    L.append("    produces pure true end")
    L.append("}")
    L.append(f"fn mmet(msg: {M5}, st: {st}) -> (:no_reply, {st}) {{")
    L.append("    sequence proc[concurrency]")
    L.append("        me: actor_ref <- self();")
    L.append("        i: int64 <- sup_k(msg);")
    L.append("        d: int64 <- sup_n(msg);")
    L.append("        _: boolean <- case i == 101 of { true -> met_later(me); false -> true };")
    L.append("        _: atom <- case i == 100 of { true -> met_dump(st); false -> :ok }")
    L.append("    produces pure (:no_reply, { " + ", ".join(f"v{j}: st.v{j} + case i == {j} of {{ true -> d; false -> 0 }}" for j in range(n)) + " }) end")
    L.append("}")
    L.append("fn met_start() -> actor_ref {")
    L.append("    sequence proc[concurrency]")
    L.append(f"        p: actor_ref <- spawn_registered({{ {', '.join(f'v{j}: 0' for j in range(n))} }}, mmet, bees_atoms@a_bees_trust_metrics(), {POL})")
    L.append("    produces pure p end")
    L.append("}")
    return L


def gen_slots(out_dir, n):
    L = ["// Generated by tools/bees_trust_mux_gen.py for trust.session.max_inflight = %d. Do not edit. The tables of a TRUST session node" % n,
         "// (N5, B2; development-plan/spikes/N5-multiplexing.md section 4): records of scalars, because an actor that lives as long as",
         "// a session may hold no heap value (SD-35).",
         "module bees_trust_slots;", "use bees_atoms;", "use bees_trust_frame;", "use bees_trust_mux_frame;", "use bees_trust_conf;",
         "use bees_trust_work;", "", "export msup/2;", "export sup_start/1;", "export mpend/2;", "export pend_start/4;", "export mmet/2;",
         "export met_start/0;", ""]
    L += gen_sup(n) + [""] + gen_pend(n) + [""] + gen_met() + [""]
    with open(os.path.join(out_dir, "bees_trust_slots.silica"), "w") as fh:
        fh.write("\n".join(L))


def generate(out_dir, max_inflight):
    os.makedirs(out_dir, exist_ok=True)
    gen_slots(out_dir, max_inflight)
    text = expand(open(TEMPLATE).read())
    with open(os.path.join(out_dir, "dangerous_bees_trust_mux.silica"), "w") as fh:
        fh.write("// Generated by tools/bees_trust_mux_gen.py from src/trust/dangerous_bees_trust_mux.silica.in. Do not edit.\n" + text)
    for name in LINKS:
        dst = os.path.join(out_dir, name)
        if not os.path.lexists(dst):
            os.symlink(os.path.relpath(os.path.realpath(os.path.join(SRC, name)), os.path.realpath(out_dir)), dst)


def remove(out_dir):
    """a node that does not multiplex has none of the session units"""
    for name in ("bees_trust_slots.silica", "dangerous_bees_trust_mux.silica") + LINKS:
        p = os.path.join(out_dir, name)
        if os.path.lexists(p):
            os.remove(p)


def main(argv):
    if len(argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    sys.path.insert(0, HERE)
    import bees_conf as C
    t = C.validate(argv[2], None)["trust"]
    generate(argv[1], t["session"]["max_inflight"])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

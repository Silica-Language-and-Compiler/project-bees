# Spike S14: Host-Name Resolution for the Transport

**STATED GOAL (D42, user ruling 2026-11-12, kept 2026-11-17): host-name resolution is to move fully to Silica.** The system resolver
(`getaddrinfo` behind one FFI worker) is an interim. It is to be **replaced by a Silica implementation** of name resolution, with no C
of BEES's own, and the contract of section 3 stays so that nothing that calls it changes. Silica must offer first: **dialing IPv6
literals** (silica-defects.md SR-2: `silica_sockets_tcp_connect` parses with `inet_pton(AF_INET, ...)` and the carrier splits
`"host:port"` at the first `:`), and **a resolver-capable transport** (a `(:udp)` carrier a DNS stub client can speak over, which must also
read `/etc/hosts` and the system's resolver configuration, or a resolver in the language's standard library; section 9).

**Status (2026-11-17): folded into the N1 resolver; one resolver, built and tested.** BEES had two resolvers, this spike's step 1
(`dangerous_bees_dns`, built 2026-11-12, never wired into a node) and the N1 resolver (`dangerous_bees_resolve`, live in the node edges).
The user ruled (Option 1) that the N1 one is the one and everything of this spike's behaviour is folded into it. **What is built:**

| Section | Where it is now |
| --- | --- |
| 3 the contract | `dangerous_bees_resolve@rslv` (a cast-only one-shot FFI worker, `src/shim/dangerous_bees_resolve.silica`; C: `native/src/silica_bees_resolve.c`, `getaddrinfo`, `AF_UNSPEC` so that a name with only AAAA records is told apart from a name that does not exist). In: `(host, reply_to, tag)`. Out: `(:bees, tag, etf)` with the tag echoed; the ETF binary's text is `ok <a.b.c.d>[,...] <n6>` or `err <reason>`, reason one of **nxdomain, no_address, temporary, bad_name, failed** (a NUL in the name is bad_name). The worker ends after its one answer. The answer is FFI-derived and tainted (SD-24): the owner de-taints it with `decode((:etf), ...)` in a produces-pure block (the S14 draft cast a tainted string tuple directly), which is why the text rides in an ETF binary |
| 3 one lookup per resolver, the owner holds the budget | `net_resolve` (`src/shim/bees_resolve_edge.part`) spawns a worker per lookup and an owner `rdial`, and starts a timer of the node's dial budget `open_ms` (not TRUST's `dns_total_timeout_ms`, which has no node using it). When the timer fires first: `dns_error timeout`, nothing is dialled |
| 3 the tag echo | `rdial` accepts only an answer whose tag is its own and only while its budget is not spent; any other answer is dropped with the line `late answer dropped, tag T`. The tag is the dial attempt number plus 1 |
| 5 checking the answer | `bees_addr` (now `src/shim/bees_addr.silica`, pure; the ONE filter): parse as strict dotted quads, drop `0.0.0.0/8`, `255.255.255.255`, `224.0.0.0/4`, `240.0.0.0/4`, drop repeats **before** the loopback rule, and the loopback rule (a loopback-only setting refuses a name that resolves to any address outside `127.0.0.0/8`: `dns_error not_loopback`, nothing dialled); an answer with nothing usable is `dns_error no_usable_address`. Applied by `rdial` to every answer of the dial path |
| 4 try each address | in turn, one per dial attempt: attempt `k` takes the `(k mod n)`th screened address, on a fresh carrier with fresh `tx`, proxies and `conn` (the redial actor already builds all of them anew). **Built only that far**; see "What is left" below |
| 7 IPv6 | the config reader refuses an IPv6 literal in `listen_address` and in a peer's `host` as "not built yet" with the SR-2 reason (`tools/bees_conf.py`, unit-tested); `net_resolve` refuses an IPv6 literal at run time (`dns_error not_built_yet`); a name with only AAAA answers is `no_address` |
| 2 constraint SD-40 | the C entry takes the host as a pointer and length bound first, and the worker binds the host to a name before the foreign call (SD-40 workaround, silica-defects.md; unchanged) |
| the loopback rule at the reader | unchanged: `beam.auth none` and `trust.plaintext_test_only` accept only `localhost` or a loopback literal as a host at build time (bees-config-file.md rule 9); at run time the rule above holds for the address `localhost` resolves to |

Retired: `native/src/silica_bees_dns.c` and its wrapper entries (`bees_dns_resolve`, `bees_dns_take`), `src/inter_nodal/dangerous_bees_dns.silica`
and `src/inter_nodal/bees_dns.atoms`. Kept and moved: `bees_addr` (to `src/shim`, with `count_of`, `nth_of` and the `ans_*` parsers
added). The D30 atoms: nothing of the resolver's reasons crosses a unit as an atom (the reasons are text inside the ETF answer, validated by
`bees_addr@ans_reason`), so no resolver manifest is needed. Trials: `trials/name_resolution` (the pure checks and the worker's answers)
and `trials/n1_addr` (`name`, `dns_error`, and the cases that need the resolver's test stub: `order`, `slow_lookup`, `not_loopback`).

**What is left (precisely).** (a) Section 4's dial actor `dlr` is **not** built as written, because it cannot be made sound with this
code: a dialed carrier's owner is fixed by its `(:open, owner, address)`, so `conn` must own it from the start and `tx` and `conn`
are spawned with it (SD-39); "start the link actors only after one attempt is up" works for `lsn` only because an accepted carrier waits
for an adopting `(:open, owner, "")`. What is built instead: each dial attempt is a whole new link (the redial actor's own design), and
the next address is taken at the next attempt. So the next address is tried after the connect budget and the redial back-off
(`redial_initial_ms`), not 250 ms later, and only for a peer with redial on; a peer with redial off tries the first address once. There
is no staggered parallel attempt and no `closing every other carrier`. (b) A node that cannot be a dialer at all for want of a first
attempt (a lookup that failed, `dns_error ...`) is still not retried, as before. (c) TRUST: no TRUST node dials a name today (its
peers are pinned addresses); the resolver edge is part of the BEAM-mode and M3 node edges only. A TRUST dial by name will use the same
`net_resolve` and filter. (d) The boot-time `listen_address` match against an interface address (section 4 table) and the TRUST pin
keys (section 6) are not built. (e) The 2 s per-name-server budget cannot be enforced through `getaddrinfo`.

**The sections below are the design as written on 2026-11-12;** where they say `dangerous_bees_dns`, `bees_dns_edge.part` or `dlr`, read the
table above.

---

## 1. Why it is needed

- `bees.config` allows a host name wherever it takes an address: `listen_address` in both modes, and each peer's `host`
  ([../bees-config-file.md](../bees-config-file.md) section 5). TRUST's discovery is "explicit `host:port`; DNS A/AAAA only; no EPMD"
  ([../inter-nodal-modes.md](../inter-nodal-modes.md) section 2), with a DNS budget of 2 s per name server and 5 s in total (section 3.8).
- **The language's carrier takes only an IPv4 literal.** `silica_sockets_tcp_connect` and the listener entries parse the host with
  `inet_pton(AF_INET, ...)` (`compiler/stdlib/net/silica_sockets.c` in the Silica tree), so a name or an IPv6 literal ends with
  `EINVAL`. Addresses are `"a.b.c.d:port"`, `"listen:port"`, `"listen:a.b.c.d:port"` and `"listen:any:port"`
  (`dangerous_tcp_carrier.silica`, header comment). Silica is not changed from BEES (silica-defects rule); resolution therefore
  happens in BEES **before** `(:open, owner, address)` is cast, and the carrier and BEES's existing transport behaviours (`tx`,
  `conn`, `lsn` in `dangerous_bees_net`) stay as they are.

## 2. Constraints from the current code

| Constraint | Source | Consequence |
| --- | --- | --- |
| A function of a `dangerous_` unit may be called only inside an FFI worker (E4042) | 2026-11-10 port, [../silica-transport-alignment.md](../silica-transport-alignment.md) | The resolver is an **actor** spawned from the node edge, as `carrier_new()` spawns the carrier; it is spoken to by messages |
| `tx` and `conn` never change carrier (SD-39) | same | Each connect attempt uses a **fresh carrier**; the link actors are spawned only after one attempt is up (the `lsn` pattern) |
| The carrier connects or fails at once; no retry, no idle timeout | same, table row "no idle timeout" | Retry across addresses and the connect budget are BEES's |
| FFI results are untrusted | [../inter-nodal-modes.md](../inter-nodal-modes.md) section 1.2 (re-creation) | The resolver's answer is parsed and checked in pure code before use (section 5) |
| Anything that could differ between languages belongs to the compilers | BEES language-variance rule | BEES provides the resolver actor and the dial path only; `inet:getaddrs` and its equivalents in other languages are each compiler's |

## 3. The resolver actor (interim: the system resolver)

**Unit:** `dangerous_bees_dns`, behaviour `resolver`, an FFI worker installed with `spawn_dangerous` by a `resolver_new()` in a new
edge part (`src/shim/bees_dns_edge.part`), pasted into the node's root unit beside `bees_tcp_edge.part`.

**Contract** (tagged tuples, as the carrier contract is):

| Direction | Message | Meaning |
| --- | --- | --- |
| in | `(:resolve, owner, host, tag)` | look up `host` (a `string`); `tag` (an `int64`) is echoed so the owner can drop a late answer |
| out | `(:resolved, tag, addrs)` | `addrs`: the IPv4 addresses as one `string`, dotted quads separated by `,`, in the order the system returned them |
| out | `(:resolve_failed, tag, reason)` | `reason` is one of `:nxdomain`, `:no_address` (the name exists but has no A record), `:temporary` (`EAI_AGAIN`), `:bad_name`, `:failed` |

**C side:** one entry in `native/src/silica_bees_native.c` (and its wrapper in `silica_bees_native_wrapper.meta`) that calls
`getaddrinfo(host, NULL, hints, ...)` with `ai_family = AF_INET`, `ai_socktype = SOCK_STREAM`, `ai_flags = AI_ADDRCONFIG`, and returns
the addresses as a byte result, following the pointer-plus-length shape of `silica_sockets_bytes`. On macOS `getaddrinfo` goes through
the system resolver, so it honours `/etc/hosts`, `.local` names (mDNS) and per-domain resolvers such as a VPN's split DNS.

**One lookup per resolver.** `getaddrinfo` has no per-call timeout and blocks its thread (a dangerous actor is its own thread). The
owner therefore spawns a resolver per lookup, enforces the budget itself (section 4) and ignores an answer whose `tag` it has
abandoned; the resolver ends after its one answer. A lookup the system is slow to fail keeps its thread until the system gives up;
that is the interim's known cost, recorded for the replacement (section 9). The 2 s per-name-server figure of TRUST cannot be
enforced through `getaddrinfo`; only the 5 s total is.

**IPv4 only.** The resolver asks for `AF_INET` because the carrier can dial nothing else (section 7).

## 4. The dial actor `dlr`

A dialing node today runs `net_dial` (`src/shim/bees_node_edge.part`): spawn `tx` and `conn` on one carrier, then open it with
`bees_peers@link_address()`. With names, `net_dial` instead spawns a dial actor `dangerous_bees_net@dlr`, the mirror of `lsn`:

1. If the peer's host is a dotted quad, skip to step 3 with that one address.
2. Spawn a resolver, cast `(:resolve, self, host, tag)`, start a timer for `dns_total_timeout_ms` (default 5000). On `:resolve_failed`
   or the timer, the dial fails with reason `{:dns, reason}` (or `{:dns, :timeout}`), reported as a link failure is today.
3. Validate the addresses (section 5). None left: the dial fails with `{:dns, :no_usable_address}`.
4. For each address in order, `carrier_new()` and open it with `"a.b.c.d:port"`, starting the next attempt 250 ms after the previous
   one (TRUST's connect stagger, inter-nodal-modes 3.8) unless one is already up. Each attempt has the 3 s connect budget.
5. On the first `:link_up`, spawn `tx` and `conn` on **that** carrier (as `lsn` does for an accepted peer, so SD-39 holds), hand them
   the link, and close every other attempt's carrier. If every attempt fails, the dial fails with the last reason.

`tx` and `conn` are unchanged: they still receive one connected carrier and never replace it.

**EPMD (BEAM mode, N2).** When a peer's `port` is `epmd`, the same resolved addresses serve both steps: `PORT_PLEASE2` to
`a.b.c.d:epmd_port`, then the dial to `a.b.c.d:<port EPMD answered>` on the **same** address, as OTP does. The resolver's output is
therefore a list of addresses, and the port of each `(ip, port)` attempt comes from the configuration or from EPMD.

**When lookups happen.**

| Name | When resolved | Use |
| --- | --- | --- |
| `listen_address` (either mode) | once, at boot (validation's "resolvable at boot") | must equal an IPv4 address of one of the host's interfaces; opened as `"listen:a.b.c.d:port"` (or `"listen:port"` for 127.0.0.1). No match is a boot error |
| a configured peer's `host` | on every dial, including each reconnect | no cache: `getaddrinfo` does not report a record's TTL, and a reconnect then follows a DNS change |
| TRUST `trpc:call(Host, Port, ...)` | on every call that opens a connection | as for a peer |

## 5. Checking the answer (pure code)

The resolver's `addrs` is FFI output: untrusted. In the `sequence` of a `produces pure` block, `dlr` (and the boot check):

1. splits on `,` and parses each part as exactly four decimal fields of 0 to 255, no leading `+`, no empty field; anything else is
   dropped and counted;
2. drops `0.0.0.0/8`, `255.255.255.255`, `224.0.0.0/4` (multicast) and `240.0.0.0/4`;
3. drops duplicates, keeping the first;
4. **applies the loopback-only rules to the resolved address, never to the name.** `beam.auth none` and `trust.plaintext_test_only`
   require a loopback address (bees-config-file.md section 4, rule 9); a name passes only if **every address dialled** is in
   `127.0.0.0/8`. A name that resolves elsewhere (including a DNS rebinding) is refused with `{:dns, :not_loopback}`, not dialled.

## 6. TRUST certificate pinning (ruled 2026-11-12)

The peer's fingerprint is pinned "for the address being dialled" (inter-nodal-modes 3.3). **Keyed by the name when a name is used;
keyed by the IP when it is not.**

- `trpc:call("billing.example", ...)` and a peer configured with `{host, "billing.example"}` look up the pin under
  `"billing.example"`, whatever address the name resolved to, so a DNS change does not break the pin and a different address
  serving the same certificate still matches.
- `trpc:call("10.0.0.8", ...)` and `{host, "10.0.0.8"}` look it up under `"10.0.0.8"`.
- A name and the address it resolves to are **different keys**: a pin stored for `"10.0.0.8"` does not satisfy a dial to
  `"billing.example"`, nor the reverse.
- Name keys are compared case-insensitively, with one trailing `.` removed (DNS names are case-insensitive; `example.` and `example`
  are the same name).

## 7. IPv6 (ruled 2026-11-12: "not built yet")

The language's carrier dials and listens on IPv4 only (section 1). Until it supports IPv6:

- an IPv6 literal in `listen_address` or a peer's `host` is a **"not built yet" boot error** (bees-config-file.md rule 9), never
  ignored and never rewritten to an IPv4 address;
- the resolver asks for A records only, so a name with only AAAA records fails with `:no_address`;
- a `trpc:call` with an IPv6 literal fails with `{:dns, :not_built_yet}`.

This is a limitation of the language's carrier, not a defect, and is not worked around in BEES. When the carrier gains IPv6, the
resolver asks for both families, `dlr` interleaves them (IPv6 first, as RFC 8305 does), and this section is removed.

## 8. Rulings (user, 2026-11-12)

| # | Question | Ruling |
| --- | --- | --- |
| 1 | System resolver or BEES's own DNS client | "start with system resolvers and include a stated goal for later that they be replaced by silica implementations" |
| 2 | IPv6 while the carrier is IPv4-only | "'not built yet'" |
| 3 | TRUST pin key | "keyed by name when name is used. Keyed by ip when it is not." |

## 9. The later Silica implementation (the stated goal)

The interim's C entry is to be replaced by name resolution written in Silica, so that BEES carries no resolver C of its own. What it
should give that the interim does not:

- TRUST's 2 s per-name-server and 5 s total budgets enforced exactly, and no thread held by a slow lookup;
- the record TTL, so a resolved address can be cached for its lifetime;
- A and AAAA together once the carrier has IPv6;
- the same contract as section 3, so `dlr` does not change.

Two routes, to be chosen when the replacement is taken up: a DNS stub client in Silica over the language's `(:udp)` carrier (it must
then also read `/etc/hosts` and the system's resolver configuration, and decide what to do about `.local` names and per-domain
resolvers that `getaddrinfo` handles today); or a resolver provided by the language's standard library, if Silica adds one. Either is
a request to, or a choice within, the language, not a change BEES makes to Silica.

## 10. What the spike checks when it runs

1. A two-node trial (as M4) with the dialing node's peer written as `localhost`, and as a name in `/etc/hosts` that maps to
   `127.0.0.1`: the link comes up and the goldens equal M4's.
2. A name that does not exist: the dial fails with `{:dns, :nxdomain}` within the budget, and the node reports it.
3. A name that resolves to a non-loopback address under `auth none`: refused with `{:dns, :not_loopback}`, nothing dialled.
4. Two addresses for one name, the first refusing connections: the second attempt starts 250 ms later and carries the link; the first
   attempt's carrier is closed; `tx` and `conn` are spawned once.
5. An IPv6 literal in the config: boot fails with the "not built yet" message.
6. The pin-key rules of section 6, once TRUST pinning exists (N3/N4).
7. A slow lookup (a test resolver entry that sleeps past the budget): the dial fails at 5 s and the late answer is dropped by its tag.

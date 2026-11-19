# N2T: TLS for BEAM-mode links, compatible with stock Erlang's `inet_tls_dist`

**Status: design written 2026-11-18, before the code; the build status is the last section.** Milestone N2T puts BEAM-mode
links (the Erlang distribution protocol of N2, N2b, N2c) inside TLS, so that a BEES node and a stock Erlang node started with
`erl -proto_dist inet_tls` interoperate and BEES-to-BEES BEAM links can be encrypted. Plaintext BEAM mode (`{transport, tcp}`)
stays and is what every earlier trial uses. TRUST is untouched: TRUST's trust rules (D43 pins, D44 per-peer classical) do
**not** apply here, and nothing below changes them.

The questions of section 7 were **ruled by the owner on 2026-11-18** (through the coordinator: "accept the N2T agent's
suggestions", with Q4 read as "build RSA" and Q8 as "no default"); the text below is the design as ruled and built.

## 1. What stock Erlang requires

The installed Erlang is OTP 28 (erts 15.0, `ssl` 11.2, linked with OpenSSL 3.6.2). Two sources are kept apart:
**observed** means run on this Mac on 2026-11-18 against that `erl` (two `erl` nodes, `openssl s_client`, a Python probe
and a ClientHello capture, all on 127.0.0.1 with a private EPMD); **source** means read in the installed
`lib/ssl-11.2/src/inet_tls_dist.erl`; **documentation** means Erlang's guide "Using TLS for Erlang Distribution", cited
from memory because nothing may be fetched and the installed OTP carries no documentation files (so those lines are the
least certain and none of the build depends on one alone).

| # | Fact | How known |
| --- | --- | --- |
| 1 | `-proto_dist inet_tls` with **no** TLS options does not work: a ping between two such nodes answers `pang` (a server needs a certificate). | observed |
| 2 | Options come from `-ssl_dist_optfile FILE` (a term `[{server, Opts}, {client, Opts}]`) or from `-ssl_dist_opt server_X V client_X V` flags; only the names in `ssl_option/2` are accepted on the command line (`certfile`, `cacertfile`, `keyfile`, `password`, `verify`, `verify_fun`, `crl_check`, `crl_cache`, `reuse_sessions`, `secure_renegotiate`, `depth`, `hibernate_after`, `ciphers`, `versions`, `ktls`, and for a server `dhfile`, `fail_if_no_peer_cert`). | source; the optfile observed |
| 3 | **The TLS version defaults to TLS 1.2 ONLY.** `dist_defaults/1` adds `{versions, ['tlsv1.2']}` whenever the options name no `versions`. With the usual optfile (certfile, keyfile, cacertfile, verify) an `openssl s_client` that offers 1.3 and 1.2 is answered with **TLSv1.2, ECDHE-ECDSA-AES256-GCM-SHA384**; a client that offers only TLS 1.3 is refused (`insufficient security`, the node logs `no_suitable_ciphers`). The node's own ClientHello then carries no `supported_versions` at all. | source and observed |
| 4 | With `{versions, ['tlsv1.3']}` in both halves of the optfile the node speaks **TLS 1.3**: two `erl` nodes ping (`pong`); its ClientHello offers `supported_versions` 1.3 only, suites `TLS_AES_256_GCM_SHA384, TLS_AES_128_GCM_SHA256, TLS_CHACHA20_POLY1305_SHA256, TLS_AES_128_CCM_SHA256, TLS_AES_128_CCM_8_SHA256`, groups `x25519, x448, secp521r1, secp384r1, secp256r1` and three brainpool curves, **one key share: X25519**, and signature algorithms that include `ed25519`, `ecdsa_secp256r1_sha256` and the RSA-PSS family. | observed |
| 5 | **No X25519MLKEM768.** `ssl:groups()` of ssl 11.2 has no hybrid or ML-KEM group. A client offering only X25519MLKEM768 is refused (`insufficient security`); a client offering `X25519MLKEM768:X25519` is answered a HelloRetryRequest and the handshake completes on **X25519** (TLS 1.3). So the TRUST profile (hybrid only) cannot reach a stock OTP 28 node. | observed |
| 6 | **No ALPN.** The ClientHello has no `application_layer_protocol_negotiation` extension, and a server that is offered one selects none (`No ALPN negotiated`). | observed |
| 7 | **SNI and the host name check.** A dialing node sends `server_name` = the host part of the node name it dials (`localhost` for `x@localhost`) (`{server_name_indication, Host}` in `do_setup`), and with `{verify, verify_peer}` it checks the server certificate against that name: a server whose certificate names `otherhost` is refused with `{bad_cert, hostname_check_failed}` and the ping answers `pang`. | source and observed |
| 8 | **Client verification is off unless asked for.** The `ssl` defaults apply: a client defaults to `verify_peer` (OTP 26 and later) and so needs `cacertfile` (an optfile with only a server half: `pang`); a server defaults to `verify_none` and asks for no client certificate. A cluster that wants mutual TLS writes `{verify, verify_peer}, {fail_if_no_peer_cert, true}` in the server half: then a client with no certificate is refused (`certificate required` in 1.3, `handshake failure` in 1.2), one of another CA with `unknown ca`, an expired one with `certificate expired`. | observed (defaults also documentation) |
| 9 | **A server does not check the client certificate's name by default.** A client whose certificate names `otherhost` is accepted (`pong`). The optional `{verify_fun, {inet_tls_dist, verify_client, []}}` (with `net_kernel:allow/1`) compares the certificate's host names with the allowed nodes' hosts and the peer's address. | observed; the option from source |
| 10 | **In TLS 1.3 a refused client certificate reaches the client after its own handshake has finished** (the server's alert arrives on the first read), so a dialing node sees "established" and then a fatal alert. | observed (`s_client` with the wrong-CA and the expired certificate) |
| 11 | **EPMD is unchanged and plaintext.** A TLS node registers with ALIVE2 as before (`erl_epmd:names` lists it; protocol byte and versions as for TCP) and the port it registers is the TLS listener's; a dialing node looks the port up with PORT_PLEASE2 and then opens TLS to it. `net_kernel:nodes_info/0` shows the link's protocol as `tls`. | observed (documentation says the same) |
| 12 | **The distribution handshake inside TLS is NOT byte-for-byte the plaintext one: every handshake message has a 4-byte length, not a 2-byte length.** `inet_tls_dist` opens the connection with `{packet, 4}` from the start (plaintext `inet_tcp_dist` uses `{packet, 2}` until the handshake is done), and its `f_send` is `ssl:send`. Observed: over TLS a name message `N` framed with 2 bytes is never answered; framed with 4 bytes it is answered `00 00 00 03 's' 'o' 'k'`. The message bodies (`N`, `s`, `N`, `r`, `a`, flags, challenge and digest) are the same, and after the handshake the 4-byte framing, the ticks (a zero length) and the control messages are the same as plaintext. | source and observed |
| 13 | Certificates: Ed25519 and ECDSA P-256 certificates (issued by a small test CA) are accepted by the installed `erl` in TLS 1.3. | observed |
| 14 | A plaintext distribution handshake sent to a TLS listener is answered with a fatal TLS alert (`unexpected message`, the node logs `{unsupported_record_type, 0}`) and the connection is closed. | observed |
| 15 | kTLS (`{ktls, true}`) is an optional kernel offload of the same TLS stream; it does not change the wire. Session tickets are off by default. | source |

## 2. The design in one paragraph

A node's whole BEAM-mode transport is chosen by one existing option, `beam.transport` (`tcp` or `tls`). With `tls`, a new
actor, the **BEAM TLS link** (`src/inter_nodal/dangerous_beam_tls.silica`, a fork of TRUST's `dangerous_bees_tls` without
pins, fingerprints or whitelist), sits between the language's `(:tcp)` carrier and the N2 connection actors. Upward it
speaks the carrier contract message for message, so `conn`, `tx`, `lsn`, `slot`, `epm` and the redial actor are unchanged
except for one thing: the handshake framing (fact 12), which `conn` and its assembler choose from `beam_conf@tls()`. The
engine is the one TRUST uses (`native/tls/silica_bees_tls.c`, OpenSSL at least 4.1.0, D40), with a **new profile, number 16,** added
beside TRUST (0) and TEMPUS (1) (not 2: TEMPUS's self-test opens profile 2 to show that a profile that does not exist is
refused, and that stays true). EPMD carriers stay plaintext. A plaintext node does not use the TLS units at all and links
no OpenSSL: the edge generator pastes a two-function part that either wraps a carrier in a TLS link (a node that uses
`dangerous_beam_tls`) or returns it untouched.

```
 conn / tx / lsn (dangerous_beam_net, unchanged contract)
      |  (:open) (:tx) (:credit) :close      ^ (:link_up) (:rx) (:tx_credit) (:link_down) (:accepted)
 btls (link) + btlsw (writer)   or   btlsl (listener: wraps each accepted carrier in a role-2 btls)
      |  ciphertext only
 the language's (:tcp) carrier
```

## 3. Configuration (bees.config, section `beam`)

Every option is stated here with its type, whether it has a default, and its bounds. Nothing is defaulted silently.

| Option | Type | Default | Rule |
| --- | --- | --- | --- |
| `transport` | `tcp` or `tls` | **none: required** (ruled 2026-11-18, Q8: D25's default `tls` is withdrawn; until N2T `tls` was refused as "not built yet") | `tls`: every link of the node, dialed or accepted, is TLS; `tcp`: none is. There is no per-peer or per-listener mixing (section 4). |
| `tls_opts` | list of `{certfile, S}`, `{keyfile, S}`, `{cacertfile, S}` | **none: required** when `transport` is `tls`; **refused** when it is `tcp` (a stray option, the stricter rule) | All three keys are required, no other key is accepted, no key twice. `certfile`: this node's certificate (PEM; the chain file may carry intermediates after it), presented when it dials and when it listens. `keyfile`: its private key (PEM), not readable or writable by group or others (rule 8). `cacertfile`: the trust anchors (PEM), the ONLY anchors: no system store, no default paths. Paths are relative to the file's directory; each must exist and be a readable regular file (rule 8). The names are Erlang's `ssl` option names, as TRUST's `tls_opts` uses them. |
| `tls_verify` | `verify_peer` | **none: required** when `transport` is `tls`; refused when it is `tcp` | A closed set of one value today, written out so that the file says how peers are verified and so that another mode (pins, section 7 Q3) is a visible change. `verify_peer`: both sides present a certificate; each is verified against `cacertfile` (chain, depth at most 4, validity dates); a peer with no certificate is refused. A **dialing** node also checks the server certificate against the host part of the peer's node name (`stock@localhost` is checked against `localhost`), as a stock Erlang client does (fact 7), and sends that name as SNI. A **listening** node does not check a name in the client certificate (fact 9): the distribution handshake then names the node, which must be a manifest peer (D16), and the cookie digest must match. |

Cross-field rules added: `transport tls` needs `auth cookie` (`auth none` is the loopback test wire of M3 and stock nodes
never use it; the combination is refused rather than tested); `tls_opts` and `tls_verify` without `transport tls` are
refused. Unchanged: `cookie_file`, `listen_address`, `listen_port`, `epmd`, `epmd_port`, `net_ticktime_s`,
`open_timeout_ms`, `peers`, `frame_size_max`, the `redial` options. `open_timeout_ms` now also bounds the TLS handshake.

The fixed TLS profile (not configurable; ruled 2026-11-18, section 7 Q1, Q2 and Q4):

- TLS 1.3 only. A stock OTP 28 node must therefore write `{versions, ['tlsv1.3']}` in both halves of its
  `ssl_dist_optfile` (fact 3: its default is TLS 1.2 only).
- Key exchange: `X25519MLKEM768` preferred, classical `X25519` accepted. Two BEES nodes negotiate the hybrid; a stock OTP
  28 node negotiates X25519 (fact 5). The audit line of every link names the group that was negotiated.
- Suites `TLS_AES_256_GCM_SHA384` or `TLS_CHACHA20_POLY1305_SHA256`.
- Signatures (certificates and handshake): Ed25519, ECDSA P-256 with SHA-256, and **RSA with RSA-PSS**
  (`rsa_pss_rsae_sha256/384/512` for an ordinary RSA key, `rsa_pss_pss_*` for an RSA-PSS key), RSA keys of **at least 2048
  bits** (OpenSSL security level 2, set explicitly for this profile). PKCS#1 v1.5 handshake signatures are not offered or
  accepted (TLS 1.3 forbids them in the handshake anyway). The RSA acceptance is in ONE named place of the engine,
  `BEES_TLS_BEAM_RSA_SIGALGS` in `native/tls/silica_bees_tls.c`, used by profile 16 only: TRUST (profile 0) and TEMPUS (profile
  1) still refuse RSA and still require the hybrid group.
- No ALPN (fact 6), no session tickets, resumption, 0-RTT, renegotiation or compression.

How the values reach the node: as today, the generator compiles them in (`tools/bees_conf.py` reads `bees.config` at build
time, `tools/bees_config_beam.py` writes `beam_conf`); the engine is given the three absolute paths, each ended by a NUL
byte, and opens the files itself at the first handshake (a file that cannot be loaded then is the audit line
`tls_identity_error` and no link). No C code reads configuration.

The boot lines of a TLS node (the summary's `transport=tls tls_verify=verify_peer` and a banner that says what the link is):

```
[bees] BEAM mode: Erlang cookie authentication inside TLS 1.3 (transport tls, verify_peer against cacertfile, 127.0.0.1); key exchange X25519MLKEM768 or classical X25519; certificates Ed25519, ECDSA P-256 or RSA (PSS, 2048 bits or more); a downgrade from TRUST
```

## 4. TLS or plaintext, per listener and per dialed peer

- **One decision per node.** A node has one listener (N2b) and it is a TLS listener exactly when `transport` is `tls`; every
  dialed peer is dialed with TLS exactly then. This is what `-proto_dist inet_tls` is for a stock node. Mixed nodes are
  section 7 Q5.
- **A plaintext peer on a TLS listener** (a stock `inet_tcp` node, a `{transport, tcp}` BEES node, or anything else): its
  first bytes are not a TLS record, the engine fails the handshake, the link audits
  `tls_handshake_failed ... as server`, the carrier is closed (the engine's alert is sent first), and no distribution byte
  is read or written. Nothing is started for the peer (no proxies, no slot claim).
- **A TLS peer on a plaintext listener:** the ClientHello's first two bytes (`16 03`) read as a 2-byte handshake length
  of 5635, above the handshake cap, so `conn` audits a bad frame length and closes, as for any garbage (existing N2 rule;
  unchanged). The dialing TLS node sees the carrier close during its handshake and audits
  `closed_by_peer stage tls_handshake, as client`.
- **A BEES plaintext dialer on a TLS listener** receives the alert bytes or the close, reads them as a bad frame length,
  and closes (existing rule).
- A dialing node with `redial true` retries a refused TLS link exactly like any lost link (N2c), each attempt an audit line.

## 5. Bounds and failures

| Event | What happens |
| --- | --- |
| The TLS handshake does not finish within `open_timeout_ms` (a silent peer, a stalled one) | audit `timeout stage tls_handshake`, carrier closed, `(:link_down, fault)` to the connection actor |
| The peer's certificate does not verify (another CA, expired, not yet valid, a dialed server whose name does not match) | audit `tls_verify_failed`, an alert to the peer, link down |
| The peer presents no certificate | audit `tls_verify_failed` (no certificate), link down |
| Version, group, suite or signature outside the profile; a plaintext peer | audit `tls_handshake_failed`, link down |
| This node's certificate, key or CA file cannot be loaded | audit `tls_identity_error`, link down, no byte sent |
| OpenSSL older than 4.1.0 at run time | audit `tls_engine_refused`, link down |
| The server refuses this node's certificate after the handshake (TLS 1.3, fact 10) or any later fatal alert or bad record | audit `tls_alert_or_record_error`, link down |
| The peer closes with close_notify | `(:link_down, closed)`, as a carrier's close |
| Ciphertext fed to the engine at once | at most 64 MiB (the engine's existing cap); plaintext is delivered at most one TLS record (16384 bytes) per carrier credit, so the frame cap `frame_size_max` and the handshake cap apply to plaintext exactly as before |
| Memory per connection | one OpenSSL connection object and two memory buffers, freed by the writer when the carrier has gone; the link and writer hold no heap value in their state (SD-35) |
| Wrong cookie over TLS | unchanged N2 behaviour, after the TLS handshake: `challenge reply refused (bad cookie)` or the stock node's refusal |

A refusal never reaches the distribution layer as data: the connection actor sees `(:link_down, _)` only, and the audit line
that explains it comes first (written by the connection actor, because an FFI worker may not print, E2103).

## 6. What is built (see the status section for results)

- Engine: profile 16 in `native/tls/silica_bees_tls.c` (additive; profiles 0 and 1 and every signature unchanged).
- `src/inter_nodal/dangerous_beam_tls.silica`: `btls` (link), `btlsw` (writer), `btlsl` (listener).
- `src/inter_nodal/dangerous_beam_net.silica`: the 4-byte handshake framing when `beam_conf@tls()`, and the audit message
  of the TLS link.
- `src/shim/beam_tls_edge.part` and `beam_tls_none.part`, chosen by `tools/bees_edge_gen.py`; `beam_node_edge.part` calls
  them where it makes a link carrier or opens the listener.
- `tools/bees_conf.py` (the beam section: `tls_opts`, `tls_verify`, the rules of section 3), `tools/bees_config_beam.py`
  (`tls`, the specs, the banner and summary), `tools/bees_beam_tls_certs.py` (test certificates from fixed seeds).
- Trials `trials/n2t_pair` (BEES to BEES) and `trials/n2t_live` (stock `erl -proto_dist inet_tls`).
- 2026-11-19, the fuzzer's findings F1-1 and F1-2 (spikes/F1-fuzzer.md), in `dangerous_beam_net.silica`: (F1-1) an EPMD lookup
  that ends without "found" (not registered, an answer EPMD does not give, a close before the answer, an EPMD that accepts and
  stays silent or sends part of an answer) fails the link: the lookup actor `epm` sends the link's connection actor
  `(:link_down, fault)`, as a refused dial does, and ends the never-opened link carrier (`remove_actor` for a `(:tcp)` carrier; a
  `:close` before `:open` for the BEAM TLS link, which then removes its own carrier: `btls`, the `abandon` step); the teardown
  then tells the redial actor and, with redial on, the next attempt (a new lookup) follows the back-off. A lookup is now bounded
  by `open_timeout_ms` from the moment its EPMD carrier is up (audit `epmd: no answer within open_timeout_ms`), and an answer that
  arrives in pieces is read to its end (code 1 no longer counts the exchange as over). (F1-2) the connection actor never casts
  `:close` to its carrier: it asks its writer `tx` (kind 8, close only), so the close reaches the carrier after every write the
  connection actor queued before it, and once `tx` has sent `:close` (kind 6 or 8) it casts nothing more to the carrier.

## 7. Questions for the owner, and the rulings

**RULED 2026-11-18 (owner, relayed by the coordinator): the recommendations are accepted.** Q1 (a), Q2 (a), Q3 (a), Q5 (a),
Q6 (a) now with (b) recorded as a later option, Q7 (a), Q9 (a), Q10 deferred with the Mbed TLS engine: each **RULED
2026-11-18 (owner): recommendation accepted**, decided, no longer provisional. **Q8: (b), `transport` has NO default**; a
`beam` section must say `tcp` or `tls` (this changes D25; every existing trial's bees.config already states its transport,
so none changed). **Q4: (b) is built**, on the coordinator's reading that interoperating with standard BEAM nodes is a stated
purpose of BEAM mode; **RULED (b) by the owner, confirmed 2026-11-19**: RSA certificates are accepted in the BEAM profile (the
engine's profile 16; the coordinator's "profile 2" is this profile, numbered 16 because TEMPUS's self-test uses 2 as the
profile that does not exist) with RSA-PSS signatures only, keys of at least 2048 bits, behind the one macro
`BEES_TLS_BEAM_RSA_SIGALGS`. Summary of the rulings as recorded on 2026-11-19: Q1 TLS 1.3 only; Q2 hybrid preferred, classical
X25519 accepted from any verified peer; Q3 `verify_peer` against a CA only; Q4 RSA (RSA-PSS, 2048 bits minimum, the macro);
Q5 one transport per node; Q6 as stock; Q7 the host name check always on; Q8 `transport` has no default; Q9 no revocation;
Q10 the boards deferred. Every one is **RULED**; none is provisional. The table is kept as it was asked.

| # | Question | Options | Recommendation |
| --- | --- | --- | --- |
| Q1 | **TLS 1.2.** Stock OTP 28 distribution speaks TLS 1.2 only unless its optfile says `{versions, ['tlsv1.3']}` (fact 3). | (a) TLS 1.3 only: the stock side must set the option (built). (b) Also accept TLS 1.2 with ECDHE and AEAD suites only, behind an explicit option (for example `{tls_versions, ['tlsv1.3', 'tlsv1.2']}`, no default change). (c) Accept 1.2 always. | **(a)**. One line in the stock node's optfile is a small price, TLS 1.3 is what OTP supports on every release BEES targets, and 1.2 would add renegotiation and suite questions to the profile. Take (b) only if a cluster that cannot change its optfile turns up. |
| Q2 | **Classical key exchange.** Stock OTP 28 has no X25519MLKEM768 (fact 5), so interoperation needs classical X25519. | (a) Hybrid preferred, X25519 accepted from any verified peer (built). (b) X25519 only for peers marked in the file (as D44 does for TRUST), hybrid for the rest. (c) Hybrid only: no stock interoperation until OTP ships the group. | **(a)** for BEAM mode: the mode is already the stated downgrade to BEAM-equivalent security, the cookie handshake inside is MD5, and a per-peer list would have to name every stock node. Revisit when OTP's `ssl` offers the hybrid; then (b) becomes cheap. |
| Q3 | **Pins as in TRUST (D43).** Should BEAM-mode TLS also accept trust by the SHA-512 pin of the peer certificate instead of a CA? | (a) `verify_peer` with a CA only (built). (b) add `tls_verify` value `pins` with a pins file. | **(a)** now: a CA is what Erlang clusters use and what a stock node can check; pins on one side only would not help a stock peer. `tls_verify` is a closed set so that (b) can be added without changing a file that says `verify_peer`. |
| Q4 | **RSA certificates.** Many Erlang clusters use RSA certificates; the provisional profile refuses them (Ed25519 and ECDSA P-256 only, as TRUST). | (a) refuse. (b) add `rsa_pss_rsae_sha256/384/512` (and RSA-PSS certificate signatures), minimum 2048 bits. | **(b) if interoperation with existing clusters matters**, since their certificates are rarely re-issued for one new node; (a) otherwise. This is the question most likely to block a real deployment. |
| Q5 | **Mixed transports on one node** (some peers TLS, some plaintext; or two listeners). | (a) one transport per node (built). (b) a per-peer `{transport, tcp or tls}` and a second listener. | **(a)**: it is what a stock node does, and a mixed node needs two listeners and two EPMD names to be coherent. |
| Q6 | **Binding the certificate to the node name on the listening side.** A stock server accepts any certificate its CA signed and lets the cookie decide (fact 9); `inet_tls_dist:verify_client` is the optional stricter check. | (a) as stock by default (built). (b) require the client certificate's SAN to hold the host part of the node name it then claims in the handshake. | **(a)** now, **(b)** as a later option: it needs the certificate's names handed up from the engine and a rule for nodes behind address translation. |
| Q7 | **The dialer's host name check** cannot be turned off (Erlang allows `{server_name_indication, disable}` and a custom check). | (a) always on (built). (b) an option to turn it off. | **(a)**. |
| Q8 | **The default of `transport`** stays `tls` (D25). A `beam` section that names no transport now needs `tls_opts` and `tls_verify`, where until today it was told to write `{transport, tcp}`. | (a) keep D25. (b) no default: the file must say `tcp` or `tls`. | **(b)** fits the ruling of 2026-11-17 on `redial` ("it has to be explicitly stated"). **Ruled (b) and built.** |
| Q9 | **Certificate revocation** (CRL, OCSP) is not checked; Erlang's `crl_check` is off by default too. | (a) none (built). (b) a CRL file option. | **(a)** for now. |
| Q10 | **The boards.** Mbed TLS (D40) has no profile 16 yet; a BEAM-mode TLS node on a board is not built. | build it with the Mbed TLS engine when that engine exists | defer with the Mbed TLS engine. |

## 8. Corrections needed in other documents (listed, not made, except bees-config-file.md 5.2)

Made (the coordinator allowed section 5.2 only, because `tools/test_bees_conf.py` compares that table with the reader's):
`bees-config-file.md` 5.2: the `transport` row (no default) and the new rows `tls_opts` and `tls_verify`.

Still to make:

- `bees-config-file.md`: rule 7 (required values: `beam.transport`, and `tls_opts` and `tls_verify` with `transport tls`); rule 8
  (files: the beam certificate, key and CA; the key file's mode); rule 9 ("`transport tls` before the TLS engine exists" is no
  longer "not built yet"; add: `auth none` with `transport tls` is refused); the 5.2 introduction ("the cookie and EPMD parts are
  built" gains "and TLS, N2T"); the worked example of section 6 (`{transport, tcp}, %% tls does not exist yet`, about line 320);
  section 11's list of options a boot-time reader could read (`beam.transport` is there; add the two TLS options).
- `contract/wire-v1.md`: line 13 (the 2026-11-06 amendment: add that BEAM mode has an `inet_tls_dist`-compatible TLS transport,
  N2T, and that inside TLS the handshake messages have a 4-byte length); line 489 (the Security row: "may later use the
  `inet_tls_dist`-compatible TLS profile (D25)" becomes built, with the profile of this note); line 559 ("No authentication, no
  encryption ... a TLS engine is not chosen" is stale twice over: the cookie digest is built, N2, and TLS is built for both
  modes); a new short section for the TLS transport of BEAM mode (versions, groups, signatures, no ALPN, SNI and the name check,
  the 4-byte handshake framing, EPMD plaintext).
- `development-plan/inter-nodal-modes.md` 4.5: the option table's default of `transport` (none), `auth` unchanged; the profile
  paragraph ("TLS 1.3, X25519, ECDSA or RSA certificates") becomes this note's profile (hybrid preferred, X25519 accepted;
  Ed25519, ECDSA P-256, RSA-PSS from 2048 bits; no ALPN; TLS 1.3 only, so a stock node needs `{versions, ['tlsv1.3']}`); 4.2 L1
  ("both transports, `tcp` and `tls`": built); the line-41 comparison table is still right.
- `development-plan/mvp.md`: a row **N2T** in the next-stage table after N2b (design, what was built, the trials, what stock
  Erlang needs); the status line of section 5's heading; the "Not in this stage" row "EPMD discovery, and interoperating with
  stock Erlang nodes" may mention TLS interop.
- `development-plan/roadmap.md`: a milestone row N2T; **D25 amended** (TLS distribution is built; `transport` has no default,
  ruled 2026-11-18); a new decision for the BEAM TLS profile (the rulings Q1 to Q10 of section 7: TLS 1.3 only; hybrid preferred
  and classical X25519 from any verified peer; `verify_peer` with a CA only; RSA-PSS from 2048 bits accepted in BEAM mode only;
  one transport per node; no client-name binding yet; no revocation; boards deferred); D40's text may say the engine now has
  three profiles; the S12 line (line 433) "the same interface must also offer the BEAM-mode compatibility profile, checked
  against stock `inet_tls_dist`" is done on hosted platforms.
- `contract/what-is-required-to-use.md`: the engine requirement (OpenSSL at least 4.1.0) now also applies to a BEAM-mode node
  with `{transport, tls}` (the page speaks of TRUST only); a plaintext BEAM node still needs no TLS library; a short paragraph
  on what the stock Erlang side needs (`-proto_dist inet_tls`, an `ssl_dist_optfile` with `{versions, ['tlsv1.3']}`,
  `verify_peer`, `fail_if_no_peer_cert`, a certificate whose subjectAltName holds the host part of its node name).
- `contract/so-you-want-to-write-a-compiler.md`: a node program for a TLS BEAM node passes `--use dangerous_beam_tls` to
  `tools/bees_edge_gen.py` and links `libsilica_bees_tls.a` and OpenSSL; nothing else changes for a compiler.
- `documents/` (no bold there): there is no BEAM-mode page yet (`semp.md`, `tempus.md`, `trust.md`); if one is written it should
  carry the options of section 3 and the stock-side settings. `documents/trust.md` needs no change.
- `README.md`: the BEAM-mode paragraph (if it says plaintext only) and the list of what is built: BEAM-mode links can run inside
  TLS and interoperate with `erl -proto_dist inet_tls`.
- `tools/README.md`: the new tools `bees_beam_tls_certs.py`, `bees_beam_tls_probes.py`, `bees_beam_tls_live.py`,
  `bees_beam_tls_rsa_keys.py`, and the trials `n2t_pair`, `n2t_live`.
- `development-plan/silica-defects.md`: nothing new (no Silica defect was met in N2T).

## 9. Status (2026-11-18, updated 2026-11-19)

Built and run on macOS (Apple Silicon), compiler silica-999909, OpenSSL 4.1.0, stock OTP 28 (ssl 11.2).

- **Engine** (`native/tls/silica_bees_tls.c`, additive): profile 16, `bees_tls_set_args(role, 16)`: no ALPN; a cacertfile is
  required; groups `X25519MLKEM768:X25519`; signatures Ed25519, ECDSA P-256 and the RSA-PSS list `BEES_TLS_BEAM_RSA_SIGALGS`;
  security level 2; an optional fifth spec field, the name a client checks the server certificate against and sends as SNI.
  Profiles 0 and 1 take the paths they took before; `make -C native tls-selftest` prints the same lines before and after.
- **Silica**: `src/inter_nodal/dangerous_beam_tls.silica` (new: `btls`, `btlsw`, `btlsl`); `dangerous_beam_net.silica` (the
  4-byte handshake framing under `beam_conf@tls()`, on both the send side, `hsf`, and the assembler; the audit message kind 12);
  `src/shim/beam_tls_edge.part`, `beam_tls_none.part` and two calls in `beam_node_edge.part`.
- **Tools**: `bees_conf.py` (`transport` required; `tls_opts`, `tls_verify`; the rules of section 3), `bees_config_beam.py`
  (`tls`, `tls_server_spec`, `tls_client_spec_of`, banner and summary), `bees_edge_gen.py` (pastes one of the two parts),
  `bees_beam_tls_certs.py` with `bees_beam_tls_rsa_keys.py`, `bees_beam_tls_probes.py`, `bees_beam_tls_live.py`; unit tests
  `tools/test_bees_beam_tls.py`.
- **Trials**: `trials/n2t_pair` (22 outputs: three nodes on one TLS listener, redial inside TLS, an RSA peer, six refusals
  between BEES nodes, eleven `openssl s_client` probes) and `trials/n2t_live` (22 outputs: eleven scenarios against stock
  `erl -proto_dist inet_tls`, both directions, Ed25519 and RSA certificates, the refusals, and since 2026-11-19
  `bees_redials_epmd`, F1-1's deterministic case: node `r` (redial on, 6 s) starts before the stock node, its EPMD lookup fails,
  the link fails like a refused dial, and its next attempt finds the stock node and links inside TLS; the driver states that the
  stock node registered before that attempt). 2026-11-19: on a loaded machine (load average 20 to 50) `n2t_pair`'s staggers
  were too short for a freshly built hub to listen (the edge saw a refused connect) and for h1 to end before h2 bound the same
  port; the pair stagger is now 3 s and the redial trio's 4 s (no golden changed).
- **F1-1 and F1-2 (2026-11-19)**: F1-1 reproduced first (`bees_fuzz.py replay --seed 7 --surface beam_dial --case 39`: after
  `epmd: the peer is not registered` nothing more), then fixed (section 6); after the fix that replay and the other
  `epmd/*` kinds (one byte, half a port, silent, accepted and held with no answer: cases 324, 84, 193, 267) are `ok`, and 400
  `beam_dial` cases of seed 7 give 0 findings (6 `no_redial` before the timeout was added, 29 in the F1 note's run). Shown
  deterministically by `n2t_live`'s `bees_redials_epmd` (inside TLS); the plaintext path by the replays. F1-2: not
  reproduced (0 of 300 on `--repeat 300`, as before; 0 findings in 400 `beam_accept` cases); the window the finding describes
  (the connection actor's own `:close` overtaking a reply queued at `tx`) is closed by design (`tx` kind 8). The residual
  SD-43 window (a carrier that ends by itself because the peer closed, while a write is queued at `tx`) remains Silica's.
  Nothing new for silica-defects.md. The fuzzer's EXPECTED lists need no change.
- **Not built**: TLS 1.2; a per-peer transport; client-certificate name binding (Q6 b); revocation; the boards (Mbed TLS);
  Linux goldens (the trials need recording on the Linux machine); a C self-test of profile 16 inside
  `native/tls/selftest` (its output is a golden of `trials/n4_trust_tls`, so nothing was added there: the Silica trials and the
  `s_client` probes cover the profile instead).
- **Observed and worth knowing**: certificates signed with PKCS#1 v1.5 by an RSA authority (the commonest kind in existing
  clusters) were not tried; only RSA keys under an Ed25519 authority and under an RSA-PSS-signing authority were. OpenSSL
  checks a chain's signature algorithms against the configured list only in its strict modes, so such a chain is expected to
  verify, but that is not shown by a trial.

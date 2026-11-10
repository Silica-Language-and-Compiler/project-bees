# The BEES distribution profile: Erlang distribution (handshake version 6) with typed ETF payloads, version 1

**Status: written 2026-11-06 (milestone M5) from the code and tests of milestones M1b to M4. It replaces the first
version of this file (the tag-free typed frame of milestone M1), which no code produces any more.** The file keeps its
name so that links to it stay valid. It describes what the reference implementation **does**, not what was planned.

**What this is.** BEES nodes talk to each other with the wire of the Erlang distribution protocol, latest handshake
version (6), and carry typed messages as the External Term Format (ETF). It is a **profile**: a strict subset of what
OTP 28 speaks, with a few places where BEES deliberately differs (section 9). It is complete enough to write a second
implementation of a BEES node from it. It does **not** make a BEES node interoperable with a stock Erlang node: the
handshake has no cookie digest, so a stock node cannot connect (section 9).

**Amended 2026-11-06 (roadmap D36 to D38; a plan, nothing here is built).** (1) **BEAM mode** (this profile) will add Erlang's cookie authentication in milestone N2, so a stock node can connect; the text below describes the MVP as built, without it. (2) **TRUST is a separate protocol, not layered around this one**: its wire is SEMP's (a 4-byte length and one ETF map per frame, mutual TLS 1.3, ALPN `trust/1`) and it cannot talk to a regular BEAM node; where this file says "security is TRUST's" it means TRUST's own transport is a different implementation, not a wrapper for this stream. (3) The language's `encode`/`decode((:etf), ...)`, `wireframe` and hosted `(:tcp)` carrier exist on `silica-999935`; this profile's bytes are unchanged, but the code that produces them (`bees_wire`, BEES's carrier, the receive stub) is to be replaced by the language's (N0.0, N1). (4) Conversion between typed values and these bytes is to be done in the `sequence` of a `sequence ... produces pure` block, in a connection's separate send and receive actors (mvp.md 3.3 and 4).

**Not in the MVP, and said again where it matters:** no authentication, no encryption (security is TRUST's, which is
not built), no reconnect, one live link per node, no atom cache, no distribution header, no control message except
`REG_SEND`. The receive step in BEES's code is a stub, so the language gives no taint guarantee about received bytes (section 10); the language's own `decode` exists on 999935 and the port is N0.0.

Companion documents: [development-plan/mvp.md](../development-plan/mvp.md) (the plan and the milestones),
[development-plan/spikes/M1b-etf-codec.md](../development-plan/spikes/M1b-etf-codec.md) (the codec),
[M2](../development-plan/spikes/M2-carrier-transport.md), [M3](../development-plan/spikes/M3-distribution.md) and
[M4](../development-plan/spikes/M4-demo.md) (the carrier, the layer and the demo),
[development-plan/silica-transport-alignment.md](../development-plan/silica-transport-alignment.md) (what Silica is
designing and how BEES's interim relates to it), [so-you-want-to-write-a-compiler.md](so-you-want-to-write-a-compiler.md)
(what a compiler author gets from the node layer, section B1a).

## 0. How to read the evidence labels

Every layout or rule below carries one label, so that you can tell what was checked and what was only read or argued.

| Label | Meaning |
| --- | --- |
| **[oracle]** | Byte-compared with OTP 28 (`erl`, erts-15.0, kernel-10.0 on the development machine). By `tools/etf_cases.py check` (232 typed vectors against a live `erl`) or by a test in `tools/test_bees_dist.py` that asks a live `erl`. |
| **[test]** | Checked by a test or a trial that does not ask `erl`: a Python test in `tools/`, or a two-process or in-memory Silica trial whose recorded output (a `.scout` golden under `trials/`) is committed. |
| **[code]** | Read from the code (file named) and not exercised by a test. This is a statement about what the code does, which a second reading can get wrong. |
| **[argued]** | A consequence of a rule or of OTP's documented behaviour that nothing here ran. |

The Python tests were **re-run on 2026-11-06 while writing this file**: `python3 tools/test_bees_dist.py` (17 tests, ok),
`python3 tools/test_bees_wire_gen.py` (18 tests, ok), `python3 tools/etf_cases.py check` ("232 typed vectors match the
installed erl"). The Silica trials (`make -C trials integrate`: 106 passed at the end of M4) were **not** re-run for this
document, because no code changed; the `.scout` goldens it cites are the committed ones. Section 11 lists what was
never tested.

Words in capitals (MUST, MUST NOT) are requirements on an implementation that wants to talk to the reference
implementation. All multi-byte integers are big-endian.

## 1. The life of a connection

1. Two nodes each hold a **peer table** fixed at build time (D16): the node names they may talk to. A node's one link is
   its first `peer` line: `dial` connects to that peer, `listen` binds a port and accepts one connection, which must name
   a node of the table. The carrier is a reliable ordered byte stream (TCP on `127.0.0.1` in the reference
   implementation; the host must be `127.0.0.1`, the build refuses another).
2. The **handshake** (section 3) runs with 2-byte length framing: the dialer sends `N`, the listener answers `s` (`ok`)
   and `N`. The link is up on the listener as soon as it has sent its `N`, and on the dialer as soon as it has accepted
   that `N`. There is **no further handshake message**.
3. After it, the link carries 4-byte-length frames (section 4): **net ticks** (zero length) and **data frames**, each one
   control message `REG_SEND` followed by one typed payload (section 5).
4. A violation of the framing closes the link. A bad content of an intact frame drops that frame and keeps the link
   (section 8). A lost link ends the proxies and is not redialled.

## 2. Notation

`u8`, `u16`, `u32`, `u64` are unsigned big-endian integers of 1, 2, 4, 8 bytes. `"x"` is the ASCII bytes of x. A frame
of the 2-byte framing is `u16 length, body`; of the 4-byte framing `u32 length, body`; `length` counts the body only.

## 3. The handshake (version 6, without the digest)

### 3.1 Framing and sizes

Handshake messages use **2-byte length framing** [code: `bees_dist.silica`, `dangerous_bees_net.silica`]. The length of a
received handshake message MUST be 1 to 512; anything else is a framing violation and closes the link (`bad_len` in
`dangerous_bees_net.silica`; the trial `before_handshake` shows a zero length closing the link, section 8). A handshake message is
at most 270 bytes in practice (a node name is 1 to 255 bytes).

### 3.2 The three messages

| Step | Sender | Body | Length of body |
| --- | --- | --- | --- |
| 1 | dialer | `"N"`, flags `u64`, creation `u32`, name length `u16`, name | 15 + n |
| 2 | listener | `"sok"` (the status message `s`, text `ok`) | 3 |
| 3 | listener | `"N"`, flags `u64`, challenge `u32`, creation `u32`, name length `u16`, name | 19 + n |

`n` is the node name's byte count, 1 to 255. The name is ASCII (bytes 0 to 127; a byte above 127 is refused as a bad name
message) and is, on the sender's side, the manifest's `node` line (letters, digits, `_ . @ -`).

- **Step 1 and step 3 layouts equal the messages `dist_util` writes in OTP 28** (`<<$N, Flags:64, Creation:32, NameLen:16>>`
  and `<<$N, Flags:64, Challenge:32, Creation:32, NameLen:16>>` with `{packet, 2}` framing): **[oracle]**
  `tools/test_bees_dist.py` `test_n_messages_as_dist_util_writes_them` lays the two messages out in a live `erl` and
  compares them with the bytes the Silica trial `m3_dist_frames` printed (`trials/m3_dist_frames/main.scout`), and
  `test_n_init` / `test_n_acc` / `test_s_ok` compare the same bytes with an independent Python writer (**[test]**).
- **Flags**: the sender writes the constant `0x4_0307_0F94` (section 3.3) in both `N` messages. A receiver MUST check that
  its peer's flags **contain every bit** of that constant; extra bits are ignored (nothing optional is used) [code:
  `bees_dist@flags_ok`]. A missing bit closes the link (a bad name message, reason `bad_tag`).
- **Creation**: any `u32`. BEES writes the manifest's `creation` line (default 1; the build refuses values at or above
  2^32). A received creation is **not interpreted or checked** [code]. In OTP the creation comes from EPMD and tells
  incarnations of a node apart; here nothing does (section 9).
- **Challenge** (step 3): BEES writes **zero** and ignores the received value [code]. The field exists only so that the
  message keeps OTP's shape.
- **Status** (step 2): the dialer MUST receive exactly the three bytes `s o k`; anything else closes the link ("status is
  not ok") [code]. The listener never sends another status (a refusal is a silent close, section 8).
- **Worked bytes** (both from the trial `m3_dist_frames`, node `b@127.0.0.1` dialing node `a@127.0.0.1`, creation 1 and 7;
  **[oracle]** and **[test]** as above):

```
step 1  001a 4e 0000000403070f94 00000001 000b 62403132372e302e302e31
step 2  0003 736f6b
step 3  001e 4e 0000000403070f94 00000000 00000007 000b 61403132372e302e302e31
        len  N  flags            challenge creation namelen name
```

### 3.3 The distribution flags

The constant is **`0x4_0307_0F94`** (`0x0000000403070F94`). It is exactly the union of OTP 28's
`MANDATORY_DFLAGS_25` and `MANDATORY_DFLAGS_26` as defined in kernel's `dist.hrl` (**[oracle]** `tools/test_bees_dist.py`
`test_mandatory_set_is_the_union_in_dist_hrl`, which reads `dist.hrl` from the installed OTP and computes the union).
`ERL_DIST_VER_LOW` and `ERL_DIST_VER_HIGH` are both 6 in that file, so version 6 is the only version a current OTP speaks
(read from `dist.hrl`; the test checks the flag union, not the version numbers).

| Flag (OTP name) | Value | OTP meaning (the protocol's documentation; the values and names are read from `dist.hrl`, the meanings are not tested) | BEES |
| --- | --- | --- | --- |
| `DFLAG_EXTENDED_REFERENCES` | `0x4` | the node understands references with more than one id word | set; references are not carried (refused `:unsupported`) |
| `DFLAG_FUN_TAGS` | `0x10` | the node understands the old fun encoding | set; funs are not carried (refused) |
| `DFLAG_NEW_FUN_TAGS` | `0x80` | the node understands `NEW_FUN_EXT` | set; funs are not carried (refused) |
| `DFLAG_EXTENDED_PIDS_PORTS` | `0x100` | pids and ports may have large ids | set; the pid in `REG_SEND` is a `NEW_PID_EXT` |
| `DFLAG_EXPORT_PTR_TAG` | `0x200` | the node understands `EXPORT_EXT` | set; exports are not carried (refused) |
| `DFLAG_BIT_BINARIES` | `0x400` | the node understands `BIT_BINARY_EXT` | set; bit binaries are not carried (refused `:unsupported`) |
| `DFLAG_NEW_FLOATS` | `0x800` | floats are written as `NEW_FLOAT_EXT` (8-byte IEEE) | set and used |
| `DFLAG_UTF8_ATOMS` | `0x1_0000` | atoms may be `ATOM_UTF8_EXT` and `SMALL_ATOM_UTF8_EXT` | set and used (BEES writes `SMALL_ATOM_UTF8_EXT`) |
| `DFLAG_MAP_TAG` | `0x2_0000` | the node understands `MAP_EXT` | set and used (records) |
| `DFLAG_BIG_CREATION` | `0x4_0000` | creations are 32 bits wide | set and used (the creation in `NEW_PID_EXT` and in the `N` messages) |
| `DFLAG_HANDSHAKE_23` | `0x100_0000` | the OTP 23 handshake: the dialer sends `N` first, 32-bit creation | set and used |
| `DFLAG_UNLINK_ID` | `0x200_0000` | the OTP 26 link protocol (`UNLINK_ID` and its acknowledgement) | set; no link control message is sent or accepted |
| `DFLAG_V4_NC` | `0x4_0000_0000` | version 4 node containers: pids, ports and references with 32-bit id and serial | set and used (`NEW_PID_EXT` has a 4-byte id and a 4-byte serial) |

**BEES sets the flags OTP makes mandatory so that its bytes are OTP's; it does not implement everything a flag claims.**
Where the table says "refused", the matching term is refused by the codec (section 5), not decoded. BEES does **not** set:
`DFLAG_MANDATORY_25_DIGEST` (`0x400_0000`, OTP's shorthand for the OTP 25 set; **open**, mvp.md section 9, point 1),
`DFLAG_DIST_HDR_ATOM_CACHE` (`0x2000`), `DFLAG_FRAGMENTS` (`0x80_0000`), `DFLAG_PUBLISHED`, `DFLAG_ATOM_CACHE`,
`DFLAG_SEND_SENDER`, `DFLAG_SPAWN`, `DFLAG_ALIAS`, `DFLAG_NAME_ME` or any other optional flag.

### 3.4 Sequence and checks

Dialer (`dangerous_bees_net.silica`, `hs_*`, and `bees_dist.silica`) [code, exercised end to end by the trial `handshake_cast`]:

1. Connect (retry until `open_ms`). Send step 1.
2. Read a 2-byte length (1 to 512), then the body. It MUST be `s o k`.
3. Read a 2-byte length, then the body. It MUST be a step 3 message: `N` (else `bad_tag`), flags containing the constant
   (else `bad_tag`), name length at least 1 and the body exactly `19 + n` bytes (else `truncated`), a valid ASCII name
   (else `unsupported` or `bad_utf8`). The name MUST be the node this link was built to dial (the first `peer` line);
   another name closes the link ("not the node dialed").
4. The link is up. Nothing is sent to acknowledge.

Listener:

1. Bind, accept one connection (within `open_ms`).
2. Read a 2-byte length (1 to 512), then the body. It MUST be a step 1 message with the same checks (body exactly
   `15 + n` bytes). The name MUST be in the peer table; an unlisted name closes the link ("unlisted node").
3. Send step 2, then step 3, and the link is up.

A violation at any point is audited, the link is closed, and no further handshake byte is sent. **Handshake tested:**
`trials/m3_dist` scenario `handshake_cast` (both nodes print `handshake complete with <peer>`, the cast arrives), `unlisted`
(`x@127.0.0.1` is not in a's table: `unlisted node, link closed`, nothing delivered), `before_handshake` (section 8)
**[test]**. The step 3 name check on the dialer ("not the node dialed"), a wrong flag set, a status other than `ok` and a
bad name message have **no trial**: they are **[code]**.

## 4. After the handshake

### 4.1 Framing

Every frame is `u32 length, body`. A length of **0 is a net tick** (section 4.2). A body length of 1 to **4096** is a data
frame; any other length (above 4096) closes the link ("bad frame length, link closed"). The reference implementation
reads the length, then exactly that many body bytes [code: `dangerous_bees_net.silica`, `bad_len`, `rx_len`]. The hostile-frame
scenario `hostile_close` of `trials/m4_demo` sends a length prefix of 65,536 and shows the audit line `bad frame length,
link closed too_large 5` (the language's `wireframe` names the reason; before the port it was `length 65536`) and both sides
seeing the link go down **[test]**.

**What BEES sends.** A data frame of at most 4096 bytes **including its 4-byte prefix** (so a body of at most 4092 bytes),
and a payload (the ETF term after the control message) of at most 4000 bytes [code: `bees_dist@reg_send_frame`]. **What
BEES accepts:** a body of up to 4096 bytes **[code]**; a body of exactly 4096 bytes was not tested at the frame level
(the codec's 4096-byte limit on the payload term was: section 5.2).

### 4.2 Net ticks

- **A tick is the frame `00 00 00 00`** (a 4-byte zero length, no body) [code: `dangerous_bees_net@write_tick`]. OTP's tick is a
  zero-length packet in the same framing [argued].
- **Each side ticks when it has been idle.** The writer arms a timer of `tick_ms` when the link comes up; each time it
  fires, the writer sends a tick **if it has written no frame during that interval**, then re-arms [code: `dangerous_bees_net@tx`,
  `sent`]. `tick_ms` 0 sends no ticks (a test setting). Default `tick_ms` 15,000 ms (the build accepts 0 to 60,000).
- **A received tick is counted and is not answered.** The connection keeps a count and prints `net ticks seen (1 yes, 0
  no)` when the link goes down [code]. **Not echoed:** an echo of every tick would ping-pong for ever (M3 spike, section
  7). This corrects the first plan, which said a tick was "answered in kind".
- **A silent peer is lost.** Every read of the next part of the stream waits at most `io_ms` (default 60,000 ms; the build
  accepts 1 to 60,000) for bytes; if none arrive in that time the carrier ends the link with reason `timeout`, the peer
  is treated as lost and its proxies end [code: `native/src/silica_bees_tcp.c`, `bees_tcp_read_part`, "waiting at most
  `timeout_ms` for each chunk"]. Any received byte (a tick, part of a frame) counts as life.
- **Tested:** `ticks_alive` (both nodes idle 4.5 s with `io_ms` 1.5 s and `tick_ms` 0.5 s: the link stays up and a cast sent
  afterwards arrives) and `ticks_absent` (a peer that sends no ticks: node a prints `link down, proxies ended; reason
  timeout` and `proxy ended (killed)` after 1.5 s) **[test]** (`trials/m3_dist/ticks_alive.*.scout`,
  `ticks_absent.*.scout`). The **count** of received ticks being non-zero is in the code but **not in any golden** (the
  output after the marker of `ticks_alive` is dropped by the harness). OTP's own detection (a sampling of the received
  byte count each quarter of `net_ticktime`) is **not reproduced**; the defaults are OTP's values (60 s and a tick each
  15 s) and the rule is a read timeout [argued about OTP].

### 4.3 The data frame

```
u32 length
u8  112                                   pass-through (OTP's message type byte for a message without a distribution header)
ETF control message                       131 104 4 | 97 6 | pid | 119 0 | atom name        (REG_SEND, section 4.4)
ETF payload                               131 ...  one typed term (section 5), ending at the last byte of the frame
```

There is **no distribution header** (flag `0x2000` is not set) and no atom cache, so every term in the frame is a whole
ETF term with its own `131` version byte [code; the layout of the whole frame equals `term_to_binary({6, Pid, '',
counter})` after a `112` **[oracle]**, section 4.4]. A frame whose first body byte is not 112 is dropped (`bad_tag`, or
`unsupported` for a byte that equals one of BEES's unsupported tag numbers) [code].

### 4.4 The one control message: REG_SEND

`REG_SEND` is OTP's control message `{6, FromPid, Unused, ToName}`: send to the process registered under `ToName` on the
receiving node. It is the **only** control message BEES sends or accepts.

```
offset  bytes                       meaning
0       131                         ETF version byte
1       104 4                       SMALL_TUPLE_EXT, arity 4
3       97 6                        SMALL_INTEGER_EXT 6: the operation REG_SEND
5       88                          NEW_PID_EXT: FromPid
6       119 n  node-name            the node of the sender, SMALL_ATOM_UTF8_EXT (n bytes, ASCII)
6+2+n   u32 id                      the sending proxy's number: its index among the manifest's `remote` lines (0 first)
        u32 serial                  0
        u32 creation                the sender's creation (the manifest's `creation`, default 1)
        119 0                       the empty atom '' (OTP's unused "cookie" slot)
        119 m  name                 ToName: SMALL_ATOM_UTF8_EXT (m bytes, ASCII): the registered name
```

**Worked frame** (`trials/m3_dist_frames`, `{6, Pid, '', counter}` with `Pid` = id 3, serial 0, creation 1 of node
`b@127.0.0.1`, and the payload `#{op => inc, n => 5}`):

```
0000003f                                   length 63
70                                         112
83 68 04 61 06                             131, {…4 elements}, 6
58 77 0b 62403132372e302e302e31            NEW_PID_EXT, node b@127.0.0.1
   00000003 00000000 00000001              id 3, serial 0, creation 1
77 00                                      ''
77 07 636f756e746572                       counter
83 74 00000002                             131, map of 2 pairs
   77 01 6e   61 05                        n => 5          (keys in name order: n before op)
   77 02 6f70 77 03 696e63                 op => inc
```

This whole frame, the NEW_PID_EXT and the payload equal what OTP 28 writes: **[oracle]** `test_reg_send_against_erl`
builds `Pid = binary_to_term(<<131,88,119,11,"b@127.0.0.1",3:32,0:32,1:32>>)` (and checks `term_to_binary(Pid)` gives the
same bytes back), then `term_to_binary({6, Pid, '', counter})` and `term_to_binary(#{op => inc, n => 5},
[deterministic])`, builds `<<112, Ctl/binary, Pay/binary>>` and compares it with what the Silica trial printed.
`test_reg_send_structure` checks the offsets above on the recorded bytes **[test]**.

**The receiver is stricter than OTP.** It requires, in this order, the bytes `112`, `131`, `104 4`, `97 6` and `88`
exactly [code: `bees_dist@reg_send_target`]; the node atom in any of the four atom encodings (tags 119, 118, 115, 100);
12 bytes for id, serial and creation (**not interpreted**: only their presence is checked); then `119 0` exactly; then
the target name in any of the four atom encodings; then the payload, which MUST start before the end of the frame. An
operation other than 6 (LINK, SEND, EXIT, UNLINK, and every other control message), a `PID_EXT` (tag 103) instead of a
`NEW_PID_EXT`, a tuple of another arity or another encoding of the integer or the empty atom is **dropped** (reason
`bad_tag`, or `unsupported` for byte values that coincide with an unsupported tag number: an artefact of one helper) and
audited; the link stays up. **Tested on a live link:** the pid from another node and a target name nobody holds
(`hostile` #4 and #5, section 8); a name that is held but not served is checked in memory by `m3_dist_frames`. The drop
of the other control messages, of tag-103 pids and of a wrong arity is **[code]** only.

**Receive checks, in order** [code: `dangerous_bees_net@frame_done` and the functions it calls; each refusal that has a trial is
marked]:

1. The control message parses as above (else `bad_tag`/`truncated`/`unsupported`, or `bad_utf8` and `unsupported` for the
   name text).
2. The pid's **node name equals the connected peer's name** (else `:foreign_actor`, code 15). **[test]** `hostile` #4 of
   `trials/m4_demo` (`frame dropped foreign_actor 15`) and `test_bees_dist.py` `Parsed` ("reg_send from another node, code
   15").
3. The target name is an **atom the program holds** (else `:unknown_atom`, code 10; **[test]** `hostile` #5).
4. The target name is a **local name** (a `local` manifest line); otherwise the frame is dropped with the audit line
   "frame dropped, not a name this node serves" **[test]** (`reg_send local_index of counter (a remote name) -1` in
   `m3_dist_frames`).
5. The payload is **validated against that name's declared type** before anything is decoded or allocated for it
   (section 5.5). A refusal is audited as `payload refused <reason>` and the frame is dropped. **[test]** `hostile` #1 to #3.
6. A deliverer (a short-lived actor) decodes the payload and `cast_registered`s the value to the local name.

**The sender** (the generated proxy for a `remote` name): encodes the payload with the codec of section 5, builds the frame
above with `FromPid` id = the proxy's index, and gives it to the one writer, which writes it only while the link is up. A
frame whose encoding fails, or whose payload exceeds 4000 bytes, is **dropped silently** by the proxy (no audit entry)
[code: `bees_dist_gen.py`, `proxy_<name>`: the cast to the writer is made only when the frame length is positive], and a
frame submitted before the link is up is dropped (no queue) [code: `dangerous_bees_net@is_write`].

## 5. The payload: ETF, a subset, typed by the target name

The type of a payload is **fixed by the registered name** it is sent to: the manifest ties each `remote` and `local` name to
a Silica type. There is no tag on the wire that names the type, and no schema digest; a mismatch shows up as a refused
payload (the manifest of the first codec had kind ids and a digest; they are gone).

### 5.1 The manifest lines of a node

(Format in `tools/bees_dist_gen.py` and `tools/bees_wire_gen.py`; tested by `tools/test_bees_dist.py` `Manifest` and
`tools/test_bees_wire_gen.py` **[test]**.)

```
node     <name>                                this node's name (ASCII letters, digits, _ . @ -; at most 255 bytes)
creation <n>                                   optional, 0 .. 2^32-1, default 1
timing   <open_ms> <io_ms> <tick_ms>           optional, defaults 10000 60000 15000 (1..60000 each; tick_ms may be 0)
peer     <name> <host> <port> <listen|dial>    host 127.0.0.1 only; the first peer line is this node's one link
remote   <name> @ <peer> cast <type>           a registered name on that peer: a proxy actor is registered here under it
local    <name> cast <type>                    a registered name here that a peer may send to: a deliverer delivers to it
```

At most 16 `remote` and 16 `local` names; a name cannot be both, or declared twice; a `remote` names a listed peer; a
`peer` is not this node; `<name>` is `[a-z][a-z0-9_]*`. The names of all messages are added to the program's atom table.

### 5.2 Frame and limits

A payload is **one ETF term, starting with the version byte 131 and ending at the last byte of the frame**: a first byte
other than 131 is `:bad_version`, bytes after the term are `:trailing_bytes`, an empty frame is `:truncated`. These checks
and every limit below are enforced **before anything is allocated for what they guard**, and a refusal costs no more memory
than accepting a full frame **[test]** (`m1_wire_reject`, `m1_wire_memory`: 200,000 hostile and valid frames, 1.9 MB peak
resident set, recorded in M1b; not re-run for this file).

| Limit | Value | Reason on breach | Evidence |
| --- | --- | --- | --- |
| payload frame, version byte included | **4096** bytes (4097 refused, 4096 accepted) | `:too_large` | [test] `m1_wire_reject` |
| nesting depth | **16** levels (the 17th is refused) | `:too_deep` | [test] `m1_wire_reject` (16 ok, 17 refused, encode and a hand-built frame) |
| elements of a list | **256** (257 refused) | `:too_long` | [test] `m1_wire_reject` |
| elements of a STRING_EXT | 256 | `:too_long` | [test] `m1_wire_reject`, vector in `etf_cases.py` |
| arity of a tuple (the large tuple form) | at most 256 when a record field's value is skipped; otherwise the declared arity (a mismatch is refused) | `:too_long`, `:missing_field`, `:unknown_field` | [code] `bees_wire@skip_big_tuple` |
| string (BINARY_EXT) | **1024** bytes (1025 refused) | `:too_long` | [test] `m1_wire_reject` |
| atom spelling | **255** bytes (256 refused) | `:too_long` | [test] `m1_wire_reject` |
| a count larger than the bytes left | refused before any element is built | `:truncated` (the count in a list or string) or the limit's reason when it is over the limit | [test] `m1_wire_reject` (count 4294967295 and count 200 with 3 elements) |

**These limits are below BEAM's, and that is a known gap to close in milestone N1.** User ruling 2026-11-06 (R1): "The frame and
argument caps are to be the same as BEAM." The caps, which `bees.config` will carry, default to and are bounded by what the
BEAM/Erlang distribution allows, established against the installed `erl` (full table with how each figure was verified, and the
caveat about its version, in [bees-config-file.md](../development-plan/bees-config-file.md) section 5.4):

| | BEAM | BEES today |
| --- | --- | --- |
| frame (4-byte packet length; fragments and the distribution header are not offered) | up to 4294967295 bytes (the width of the prefix: argued, not checked) | **4096** |
| atom | 255 characters (checked by running) | 255 bytes, ASCII only |
| tuple arity | 16777215 (checked by running) | skipped tuples at most 256 |
| list, map | no fixed limit below memory (10 million elements and 1 million keys checked by running) | **256** elements; no free-form maps |
| binary | 1 GiB checked by running; up to the packet by the 32-bit length (argued) | **1024** bytes |
| nesting depth | none below memory (5 million levels checked by running) | **16** |
| big integer | 4,194,239 bits in the installed build (checked by running) | 64 bits |

The 4096-byte frame, depth 16, 256 elements and 1024-byte binaries are **current implementation limits of the typed codec and the
memory model, not design limits**; N1 lifts them toward BEAM's (the limits become arguments of the language's `decode` and
`wireframe@unframe`, and a refusal is still made before anything is allocated). Until then a configured value above what is built
is a boot error ("not built yet"), never clamped. The limits above this paragraph stay true of the code as built.

**Depth** counts tuples, maps, lists and STRING_EXT as one level each; a scalar does not; the outermost composite is level 1
(M1b, decision 1). A message type that nests deeper than 16 can never be decoded; the generator warns.

### 5.3 The mapping, per Silica type

The encoder writes exactly what `term_to_binary/1` of OTP 26 and later writes (minor version 1; `[deterministic]` for maps).
The decoder accepts every valid encoding of the same value that is listed in the right-hand column and **no other**. All
rows: **[oracle]** `tools/etf_cases.py check` (232 typed vectors from a live `erl`, matched today; each encodes to the same
bytes as `term_to_binary` and round-trips, each alternative decodes to the canonical value, each hostile frame is refused
with the expected reason; the vectors were played through Silica in the `m1_wire_types*` trials and their goldens are
compared byte for byte with the vectors by `tools/test_bees_wire_gen.py`).

| Silica type | Written as | Read (every other tag is refused) |
| --- | --- | --- |
| `int8`..`int64`, `uint8`..`uint64` | the smallest of `SMALL_INTEGER_EXT` (97, 0..255), `INTEGER_EXT` (98, 32-bit signed), `SMALL_BIG_EXT` (110, at most 8 digit bytes, fewest digits) | 97, 98 and 110 with **at most 8 digit bytes**; any valid encoding of a value in the declared range (a `SMALL_BIG_EXT` for 5 is accepted); a value outside the width is `:out_of_range`; a 9th digit byte is `:out_of_range`; a sign byte above 1 is `:bad_tag`; a `uint64` above the `int64` range is carried as a small big |
| `char` | as an integer, 0 to 127 | the same, range-checked (`:out_of_range` above 127), and an element of a STRING_EXT |
| `float64` | `NEW_FLOAT_EXT` (70) | 70 only; the old text float (99, written by `minor_version` 0) is `:unsupported`; infinity and NaN are `:out_of_range`; `-0.0` and subnormals round-trip |
| `float32` | `NEW_FLOAT_EXT` of the same value as a `float64` (exact widening) | 70; a `float64` that a `float32` cannot hold exactly is `:out_of_range` |
| `boolean` | the atoms `true`, `false` as `SMALL_ATOM_UTF8_EXT` | any of the four atom tags; another atom is `:bad_variant`; an integer is `:bad_tag` |
| `atom` | `SMALL_ATOM_UTF8_EXT` (119) | 119, 118, 115, 100; the spelling MUST be **an atom the program holds** (else `:unknown_atom`); an empty spelling is `:unknown_atom` |
| `string` | `BINARY_EXT` (109), at most 1024 bytes | 109 only (a list is `:bad_tag`) |
| tuple | `SMALL_TUPLE_EXT` (104); `LARGE_TUPLE_EXT` (105) above 255 | both; fewer components than declared is `:missing_field`, more is `:unknown_field` |
| record | `MAP_EXT` (116) with atom keys **in name order** (bytewise order of the field names) | keys **in any order**; a repeated key is `:duplicate_field`, an unknown key `:unknown_field`, a missing one `:missing_field`; a key that is not an atom is `:bad_tag`. Key spellings are compared with the field names as text; a key need not be a held atom |
| `List[T]` | `LIST_EXT` (108), the elements, `NIL_EXT` (106); the empty list is `NIL_EXT`; a list whose elements are all 0..255 (integers or chars) is `STRING_EXT` (107) | all three; an improper tail is `:bad_tag`; a STRING_EXT is read for any integer or char element type |

**Text rule (ASCII).** Strings, atom spellings and chars are ASCII, **0 to 127, control characters and NUL included**.
Valid UTF-8 beyond ASCII is `:unsupported`; bytes that are not UTF-8 are `:bad_utf8`; a Latin-1 atom tag with a byte above 127
is `:unsupported`. The reason is Silica's, which has no conversion from bytes to text beyond a table of literals.

**Atoms only if the program holds them.** An atom is never created from a received spelling (D16): the spelling is looked up
in the program's atom table (`bees_atoms`, generated from the manifests, including every message name) and refused when absent.

**Records.** erl's default `term_to_binary` writes the keys of a small map in atom-table order, which no other
implementation can reproduce, so the oracle uses `[deterministic]` (keys in term order, atoms by name); BEES writes name
order to match. A record of more than 32 fields is written in name order and read in any order, but erl uses hash order
above 32 keys and **no vector covers it** (**[argued]** for that case).

**Not carried** (a type that uses one is a build error, or a received tag of that kind is refused `:unsupported`):
tagged tuples (atom literal types), `unit`, `float16`, actor and supervisor references, regions, references, `buf`,
function types, sum types, `Map`, `Set` and other standard data structures, text beyond ASCII, integers beyond 64 bits,
pids, references, ports and funs as typed values, compressed terms (tag 80), atom-cache references (82), bit binaries
(77), `LARGE_BIG_EXT` (111), maps as terms of any shape. **Any-type terms are not BEES's job** (ruled 2026-11-05): a
compiler for a dynamic language handles them. **Silica's own transport design will replace the typed part of this
section** (D35): when `encode`/`decode((:etf), ...)` is in the compiler, the generated codec goes and the bytes stay.

### 5.4 Order of checks within a payload

Frame (131, then the term); then the term field by field in order, the first refusal wins; entering a composite at level 17
is `:too_deep`; bytes left over after the term are `:trailing_bytes`. Records: one pass finds where each value starts
(a skipper that enforces the limits), then each field is decoded in declared order.

### 5.5 Dispatch

The target name selects the type (`bees_wire_msgs@index_of`, then `validate_named`; the unit is generated). A name that is
no message is `:unknown_atom`. The receive path validates the whole payload (`validate_named`) **before** the deliverer
decodes it **[test]** (`m3_dist_frames`: `payload validates 0`, `payload decoded n 5`, `payload decoded op inc`).

## 6. The rejection reasons (the language's atoms)

BEES uses exactly Silica's sixteen rejection atoms (`src/inter_nodal/bees_wire.atoms`, codes 1 to 16 in this order). These
are what a payload or a control message is refused with and what an audit line prints.

| Code | Atom | Produced when |
| --- | --- | --- |
| 1 | `:bad_version` | the first byte of a payload is not 131 |
| 2 | `:truncated` | a read past the end, a count larger than the bytes left, a handshake message of the wrong length |
| 3 | `:trailing_bytes` | bytes after the term |
| 4 | `:bad_tag` | a tag the type does not take; an improper list tail; a sign byte above 1; an unexpected byte in the control message; a handshake message that is not `N` or whose flags miss a mandatory bit |
| 5 | `:too_large` | a frame over 4096 bytes held, a write past the buffer |
| 6 | `:too_deep` | the 17th level |
| 7 | `:too_long` | a list or tuple over 256, a binary over 1024, an atom over 255 bytes |
| 8 | `:out_of_range` | an integer outside the declared width, a 9-digit big, infinity, NaN, a `float64` a `float32` cannot hold |
| 9 | `:bad_utf8` | text bytes that are not UTF-8 |
| 10 | `:unknown_atom` | an atom the program does not hold (including the empty atom); a target name that is no message |
| 11 | `:bad_variant` | a `boolean` that is another atom |
| 12 | `:missing_field` | a record key or a tuple component missing |
| 13 | `:duplicate_field` | a record key twice |
| 14 | `:unknown_field` | a record key that is no field; a tuple with too many components |
| 15 | `:foreign_actor` | a `REG_SEND` pid whose node is not the connected peer (first produced by M3; the codec itself never produces it) |
| 16 | `:unsupported` | a tag of the format BEES does not implement; valid UTF-8 beyond ASCII; the old float text |

`:unsupported` versus `:bad_tag`: a tag of the format that BEES does not implement is `:unsupported`; any other tag the reader
did not expect is `:bad_tag` (M1b, decision 3). **[test]** each reason has a vector or a trial case in `etf_cases.py` or
`m1_wire_reject` except `:foreign_actor` (the hostile-frame scenario of `m4_demo`, and `m3_dist_frames`).

## 7. What BEES refuses before the codec runs

| Check | Rule | Evidence |
| --- | --- | --- |
| Frame length | handshake 1 to 512; frame 0 (a tick) or 1 to 4096 | [test] `before_handshake`, `hostile_close`; the 512 and 4096 bounds themselves are [code] |
| Mandatory flags | the peer's flags contain every bit of `0x4_0307_0F94` | [code] (the constant is [oracle]) |
| Node name | the handshake name is in the peer table (listener) or is the dialed node (dialer) | [test] `unlisted`; the dialer's check is [code] |
| Sender of a frame | the `REG_SEND` pid's node is the connected peer | [test] `hostile` #4 |
| Target | an atom the program holds, and a name this node serves | [test] `hostile` #5, `m3_dist_frames` |
| Payload | validated against the name's type | [test] `hostile` #1 to #3 |

## 8. Connection rules

All rows are `trials/m3_dist` or `trials/m4_demo` scenarios (**[test]**: two separate operating-system processes, listener
started first, each program's output compared with its committed golden) unless marked [code].

| Rule | What happens | Evidence |
| --- | --- | --- |
| **One live link per node** | the first `peer` line is the link; a `listen` node accepts one connection and closes its listening endpoint; there is no second link | [code] (`bees_dist_gen.py`, `link_*`; the carrier holds one peer per listener) **Code ported 2026-11-09, built and run 2026-11-10 on silica-999926 (see [silica-transport-alignment.md](silica-transport-alignment.md) and the 2026-11-09 and 2026-11-10 sections of [silica-defects.md](silica-defects.md)):** with the language's listener (transport design 6.2, 2026-11-09) the listening carrier keeps listening; `dangerous_bees_net` adopts the first accepted connection and leaves later ones unopened. |
| **No reconnect** | a lost link ends every proxy (`kill_abnormal`, reason `(:explicit, :killed)`) and the node does not redial; a sender that casts to the ended proxy fails with `(:explicit, :actor_not_found)` (Silica's own rule for a dead actor) | [test] `m4_demo` `kill` (node a SIGKILLed: b prints `link down, proxies ended; reason closed`, `proxy ended (killed)`, `ticker failed: actor_not_found`) |
| **Unlisted node closed** | a listener whose peer's `N` names a node not in its table audits `unlisted node, link closed`, closes, sends nothing | [test] `unlisted` (a: `unlisted node, link closed x@127.0.0.1 -1`, `frames dropped - 1`) |
| **Frame before handshake dropped** | a first length of 0 or above 512 in the handshake framing: `frame before handshake dropped, link closed` | [test] `before_handshake` (a raw peer whose first bytes are a data frame: audit line with `length 0`, link closed, nothing delivered) |
| **A framing violation closes the link** | a bad length, a bad handshake message, an unlisted name, a status that is not `ok`, a frame that does not fit the buffer | [test] as above and `hostile_close`; the others [code] |
| **A bad content of an intact frame drops it** | a pid from another node, an unknown or unserved target, a refused payload, any control message but `REG_SEND`: the frame is dropped, counted and audited, and the link stays up | [test] `hostile` (five cases, then a good request answered); other control messages [code] |
| **Silence toward the peer** | a refusal sends nothing back (no `s not_allowed`, no error frame): a close right after a write races the writer | [code] (M3 decision 4) |
| **Peer-table check** | on the listener the name of the dialing node; on the dialer the name of the answering node; and on every frame the pid's node | as above |
| **Pid from another node refused** | `:foreign_actor`, frame dropped, link kept | [test] `hostile` #4 |
| **Ticks** | section 4.2 | [test] `ticks_alive`, `ticks_absent` |

Audit lines are the program's own observability (`bees_ingress@audit`: `[bees audit] <kind> <who> <n>` on standard output)
and are not part of the wire; they never contain payload content.

## 9. Differences from OTP

OTP 28 (kernel-10.0) is the reference. "Stock" means an unmodified Erlang node.

| Area | OTP | BEES | Evidence |
| --- | --- | --- | --- |
| **Authentication** | cookie: the acceptor sends a challenge, the dialer answers with an MD5 digest over the cookie and the challenge and sends its own challenge (`r`), the acceptor answers with a digest (`a`) | **none**: no digest, no cookie, no `r`, no `a`. The challenge field of step 3 is sent as 0 and ignored. **A stock node cannot connect to a BEES node and the reverse**, because it expects those steps. **Planned (D36, N2): BEAM mode adds exactly these steps** (MD5 and a random challenge through the native edge) | [code]; stock interop **not attempted** (M3 spike: a fake EPMD attempt did not get a connection out of `erl -name`, not pursued) |
| **Security** | the cookie only; TLS is a separate distribution transport | **none yet.** Planned: BEAM mode gets Erlang's cookie (N2), and may later use the `inet_tls_dist`-compatible TLS profile (D25). **TRUST** (mutual TLS 1.3, ALPN `trust/1`, certificate fingerprints) is a **separate protocol, not a layer around this stream** (D36) and is not built either. **The MVP link has no authentication and no encryption**; every node prints a test-only banner at start. `127.0.0.1` only | [test] the banner is in every golden |
| **EPMD** | name resolution and the listening port come from EPMD | none: host and port are in the manifest | [code] |
| **Handshake variants** | several (`n`, `N`, the older versions) | version 6 `N` only | [code] |
| **Status messages** | `ok`, `ok_simultaneous`, `nok`, `not_allowed`, `alive`, `named` | only `ok`; a refusal is a silent close | [code] |
| **Simultaneous connect** | resolved by comparing names | not possible: one node dials, the other listens, one link | [code] |
| **Creation** | assigned by EPMD, distinguishes incarnations | a manifest constant, written and never checked | [code] |
| **Flags** | negotiated: the intersection is used | a constant, and the peer's flags MUST contain it; **BEES sets flags whose features it does not implement** (funs, references, bit binaries, exports) and refuses those terms | [oracle] value; [code] behaviour |
| **Atom cache, distribution header, fragments** | optional features, used by default (header and cache) | none: flags `0x2000` and `0x80_0000` are not set, every term is a whole ETF term with its own `131`, messages are `112` + control + payload | [code] |
| **Control messages** | about twenty (`LINK`, `SEND`, `EXIT`, `UNLINK`, `NODE_LINK`, `REG_SEND`, `GROUP_LEADER`, `EXIT2`, `SEND_TT`, `PAYLOAD_EXIT`, `SPAWN_REQUEST`, `ALIAS_SEND`, ...) | **`REG_SEND` only.** Any other operation is dropped and audited | [code]; the drop of other operations is not tested |
| **The control message's encoding** | accepts the encodings its own encoder can produce | exactly `131 104 4 97 6 88 ... 119 0 ...` (section 4.4), with the node and target atom in any of the four atom tags | [code] |
| **The pid in `REG_SEND`** | a real process identifier | **a proxy's index** (id), serial 0, the sender's creation; **the receiver checks only the node** and ignores id, serial and creation. It is not an actor identity | [code] (M3 decision 5) |
| **Addressing** | pids, registered names, aliases | **registered names only** | [code] |
| **Ticks** | each side sends a tick when idle; liveness by sampling the received byte count each quarter of `net_ticktime` (60 s) | each side sends a tick when idle (`tick_ms`, 15 s); liveness by a read timeout (`io_ms`, 60 s); a received tick is counted and not echoed | [test] section 4.2; the OTP column is [argued] |
| **Frame size** | no small limit (the `{packet, 4}` length: up to 4294967295 bytes) | **4096 bytes per frame**, payload term at most 4096 (4000 sent): **below BEAM's, a known gap closed in N1** (section 5.2) | [test] payload; frame [code] |
| **Term shapes** | any term | **the ETF subset of section 5, typed by the target name**: no pids, references, ports, funs, bit binaries, big integers beyond 64 bits, compressed terms, or any-type terms | [oracle] and [test] |
| **Text** | UTF-8 and Latin-1 | **ASCII 0..127 only** | [test] |
| **Atoms** | created on receipt | **only atoms the program holds** (D16) | [test] |
| **Integers** | arbitrary size | up to 64 bits (8 digit bytes) | [oracle] |
| **Floats** | `NEW_FLOAT_EXT` | the same; infinity and NaN refused | [oracle] |
| **Map key order on write** | atom-table order by default | **name order** (equal to erl's `[deterministic]`); any order accepted on read | [oracle] |
| **Links, monitors, remote spawn, `net_kernel`, `nodedown`** | yes | none (D20, D28); a lost node is seen as the proxy ending | [code] |
| **Receive step** | the emulator's decoder | **the language's `decode((:etf), frame, { limits })`** since the port (built and run 2026-11-10 on silica-999926; the M3 to M5 code had a stub, `bees_ingress@recreate`, which copied the parts and did not clear taint). The checker raises nothing on carrier bytes, but the FFI result handler is not yet checked (SD-25), so the taint guarantee is the language's to complete (section 10) | [test] **Code ported 2026-11-09, built and run 2026-11-10 on silica-999926 (see [silica-transport-alignment.md](silica-transport-alignment.md) and the 2026-11-09 and 2026-11-10 sections of [silica-defects.md](silica-defects.md)):** ported: the stub is deleted; the deliverer decodes with the language's `decode((:etf), frame, { limits })` inside `produces pure` and the connection actor validates with the same call first (section 10). |

## 10. The receive step and what this profile does not guarantee

Bytes returned by a foreign call are tainted in Silica. BEES's M3 to M5 code was built on `silica-999936`, whose compiler had no
`decode`, `encode` or `recreate` (all E2007 "unknown function", **[test]** `trials/m3_decode_probe` as it was then), so BEES's
receive step is one function, `bees_ingress@recreate`, a **stub** that copies a frame's parts into a buffer. It works
only because the handler that receives a foreign-function result is not checked (SD-25). **A compiler that checks
handlers will reject this code, and the language gives no taint guarantee about received bytes.** What the layer does
guarantee, in the sense of "malformed or hostile bytes cannot fault or exhaust the receiver", is BEES's own validation:
the length is bounded before any byte is stored, every read is bounds-checked and rejects instead of faulting, the
control message and target are checked, and the payload is validated against the declared type before anything is
decoded. That is **[test]** for the crafted classes in `m1_wire_reject`, `m1_wire_memory` and the six frames of the
`m4_demo` hostile scenarios, and **not** a fuzzing result.

**Update 2026-11-06 (silica-999935; read-only checks, not BEES trials).** The language now has `encode((:etf), value) -> string` and
`decode((:etf), frame) -> (:ok, T) | (:rejected, atom)`, which replace `recreate` (SD-32 resolved), with `wireframe` for the 4-byte
framing and a hosted `(:tcp)` carrier. **The required design (user ruling): the decode, and the encode, each happen in the
`sequence` of a `sequence ... produces pure ... end` block, in the connection's receive actor and send actor, so no tainted value
crosses an actor boundary or a cast.** The language's `transport_beam_demo` does this; a BEES probe confirms encode-then-decode round-trips
inside such a sequence (first byte 131). **Unproven:** that `decode` applied to bytes that came from a carrier passes the taint checker
end to end in BEES's own receive-actor shape; milestone N0.1 tests it and N0.0 ports the code. When that is done the stub is gone,
the limits become the arguments of `decode` and `wireframe@unframe`, and the bytes of this profile do not change.

**Update 2026-11-10: the port below is built and run on silica-999926** (`m2_carrier_tcp`, `m3_dist`, `m3_dist_frames`, `m4_demo`
pass; the checker raises no taint diagnostic on `decode` of carrier bytes, with SD-25's caveat). Changes from the text below: the
carrier is granted one receive credit at a time, when the per-frame assembler asks for more bytes; a listening node's link is
started by a listen actor on the accepted connection; the audit line of a frame received before the handshake now reads
`bad_tag 4` (the 2-byte length read from a 4-byte frame is 0). Details in the 2026-11-10 section of
`development-plan/silica-defects.md`.

**Update 2026-11-09 (the port, by reading only; built and run 2026-11-10, see the update above).** The stub is gone from the code. The receive path is now:
the language's `(:tcp)` carrier delivers string segments as `(:rx, segment)` to the connection actor (`dangerous_bees_net@conn`), which hands
each to a short-lived per-frame assembler; the assembler reassembles with `wireframe@unframe` (4-byte framing, `max_frame` 4096) or,
during the handshake, with BEES's own 2-byte `bees_dist@unframe2` (`max_frame` 512), and returns the frame body; the connection
actor parses the control message with `bees_dist@reg_send_target` (bounds-checked reads over the string), validates the payload
against the target name's declared type with the language's `decode` (generated `bees_msgs@validate_named`, limits
`{ max_bytes: 4096, max_depth: 16, max_length: 1024 }` for variable-sized types), and a short-lived deliverer decodes it again in the
`sequence` of its `produces pure` block and `cast_registered`s the value. The sending path is `encode((:etf), value)` in the proxy,
`bees_dist@reg_send_body`, `bees_dist@frame4` (`wireframe@frame`) and one `(:tx, segment, self())` from the writer. The bytes of this
profile are unchanged. Two things this profile described that changed with the carrier: a bad frame length is now reported by the
language's `wireframe` as the atom `too_large` (the audit line no longer carries the length), and a silent peer is detected by
`dangerous_bees_net`'s own idle timer (the language's carrier has no read timeout), still with reason `timeout`.

## 11. Not covered, and not tested

- **A stock Erlang node was never connected** to a BEES node, in either direction. The byte layouts equal OTP's
  (section 3.2, 4.4, 5.3) but the **behaviour** against an OTP peer is untested, and by design it cannot complete the
  handshake (no digest).
- **No authentication, no encryption.** The cookie digest (BEAM mode, N2) is not built, and TRUST (a separate implementation) and its TLS are not built; a TLS engine is not chosen (it needs the user's explicit approval, D38).
- **One live link per node, one peer per listener, no reconnect, no backoff, no flow control**, one frame in flight per
  direction, `127.0.0.1` only, macOS arm64 only (Apple Silicon), fixed ports.
- **Records over 32 fields**, tagged tuples, `unit`, `float16`, text beyond ASCII, big integers, maps and sets as message
  types: not carried.
- **Compile cost limits a message type** to a few fields per record (a flat record of 22 fields did not compile in 300 s:
  SD-36); a real message type should be grouped into records of two to four fields. **Since the port, four is a hard limit:**
  the language's derived decoder cannot decode a record of five or more fields on Apple Silicon (SD-37, 2026-11-10).
- **Hostile input** is five crafted content classes and one framing class in the live link (`m4_demo`), the M1 rejection
  cases and 232 vectors; **no fuzzing**, no slow-sender test (a peer that claims a 4096-byte frame and sends it slowly
  holds the link until `io_ms`), no frame of exactly 4096 bytes at the link level.
- **Rate and memory** are measured once per version (`m4_demo` `measure`, 8 in flight): before the port 19.1 round trips per
  second with a 547-byte payload and about 90 MiB peak per node (the part-at-a-time carrier, SD-35); **after the port
  (2026-11-10, silica-999926) 311.0 round trips per second and 6.3 MiB peak per node**. Not a benchmark.
- **The OTP columns of section 9** that are marked [argued] describe OTP from its documentation and source layout; nothing
  here ran them.

## 12. Reference implementation

| Piece | Where |
| --- | --- |
| Handshake and `REG_SEND` byte layouts (pure functions over strings), the 2-byte handshake framing (`unframe2`), the 4-byte framing through the language's `wireframe` (`frame4`) | `src/inter_nodal/bees_dist.silica` |
| The node: the receive actor `conn` (the carrier's owner: handshake and data phases, the idle timer), the per-frame assembler `asm` (`wireframe@unframe`), the send actor `tx` (ticks) | `src/inter_nodal/dangerous_bees_net.silica` |
| The audit trail and the numbering of the language's rejection atoms | `src/inter_nodal/bees_ingress.silica`, `bees_wire.atoms` |
| The message codecs over the language's `encode`/`decode` (generated per manifest: `enc_<name>`, `dec_<name>`, `validate_named`) | generated `bees_msgs` (`tools/bees_dist_gen.py`) |
| The typed ETF codec core of M1b (the `m1_wire_*` trials and the oracle only; not on the node path) | `src/inter_nodal/bees_wire.silica`, `tools/bees_wire_gen.py` |
| Generators: peer table, proxies and deliverers, message codecs | `tools/bees_dist_gen.py` (via `tools/bees_config.py generate`) |
| The carrier: the language's `(:tcp)` carrier (Silica stdlib `dangerous_tcp_carrier` over `dangerous_sockets`), spawned by the root unit's edge | `src/shim/bees_tcp_edge.part` (`carrier_new`), `tools/bees_edge_gen.py`; the socket wrappers' archive and sidecar: `native/Makefile`, `native/dangerous_exposure_source/sockets` |
| Oracle, vectors and trial generator | `tools/etf_cases.py`, `tools/etf_oracle/typed.vectors` |
| Tests | `tools/test_bees_dist.py` (17), `tools/test_bees_wire_gen.py` (18); trials `m1_wire_*`, `m2_carrier_tcp`, `m3_dist`, `m3_dist_frames`, `m3_decode_probe`, `m4_demo` (goldens of the last four to be re-recorded after the 2026-11-09 port) |

The first version of this document (a tag-free typed frame with kind ids, a schema digest and a hello frame, FNV-1a
over a canonical schema text, and a packing into 8-byte words) is in git history before this rewrite. Nothing in it is
produced by any code now; its limits (frame 4096, depth 16, list 256, atom 255, string 1024) carried over, and its
ASCII-only text rule widened from a printable set to 0 to 127.

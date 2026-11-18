# X1: Mac and Linux interchange (BEES on one machine talking to BEES, or to a stock erl, on the other)

Status 2026-11-18: built and run. Until today every trial ran all its nodes on one machine. X1 puts one node on the Mac and
the other on the Linux box and records that as two repeatable trials, `trials/x1_interchange_beam` (BEAM mode) and
`trials/x2_interchange_trust` (TRUST over mutual TLS 1.3), run by one command from the Mac. 12 scenarios, 24 goldens, all passing.
No change to `src/` was needed and no Silica defect was found.

## The two machines

| | "here" (the machine the driver runs on) | "there" (the remote machine of `.bees_build_hosts`) |
|---|---|---|
| machine | Mac, Apple Silicon, macOS 26.7.2 | `aalang.org` (`aalang-web`), Ubuntu 25.10, x86_64, 2 cores, 3.9 GB |
| platform id | `macos_applesilicon` | `linux_x86_64` |
| compiler | `silica-999909-macos-applesilicon` (the pin) | `silica-999944-linux-x86_64` |
| OpenSSL | 4.1.0 (Homebrew) | 4.1.0 (`/opt/openssl`) |
| erl | OTP 28 (`/usr/local/erlang/bin/erl`) | OTP 27 (`/usr/bin/erl`) |
| MD5 for the cookie digest | CommonCrypto | OpenSSL EVP |
| random | `CCRandomGenerateBytes` | `getrandom(2)` |
| tree | the checkout | `~/bees-interchange`, synced by the driver (beside `~/silica`, which is only read) |

## Reachability (measured 2026-11-18)

- **Mac to Linux: direct.** The Mac resolves `aalang.org` (138.197.209.113) and reaches it on the trial ports: a throwaway listener
  on the remote on 22800 and on 22900 (every IPv4 interface) accepted a connection from the Mac, which the remote saw as coming
  from 157.201.64.9 (the Mac's address after translation; its own address is a private 10.x one). No firewall blocks 22800 to
  22999 there. Round trip about 45 ms. The driver repeats this probe at the start of every run and prints the result.
- **Linux to Mac: not possible directly.** From the remote, the Mac's translated address answers `No route to host` and its
  private addresses time out. The Mac's own application firewall is off; the translation is what stops it. This direction runs
  through an **ssh -R forward** carried by the driver's own ssh session.
- Seen in passing, not used and not changed: the Linux box's system EPMD (port 4369, every interface) is reachable from the
  Mac over the internet. The trials use a private EPMD on 127.0.0.1 and never touch it.
- No firewall, router or system setting was changed on either machine.

## Network paths used

One ssh master session (`ssh -M`, key-based, batch mode) is opened per run; every remote command, the rsync and every forward
travel in it (`ssh -O forward`, cancelled after each scenario). Three paths:

| path | who dials what | what each node believed |
|---|---|---|
| **direct** | a node here dials the remote's public address; the listener there binds every IPv4 interface (`0.0.0.0`) for the seconds the scenario runs, because the carrier binds 127.0.0.1 or every interface and nothing between (SR-1) | the dialer: the remote's name or address; the listener: a connection from 157.201.64.9 |
| **-R** | a node there dials `127.0.0.1:PORT` on its own machine; sshd carries it to `127.0.0.1:PORT` here, where the listener binds 127.0.0.1 only | both nodes: 127.0.0.1 |
| **-L** | a node here dials `127.0.0.1:PORT`; ssh carries it to `127.0.0.1:PORT` there | both nodes: 127.0.0.1 |

A forward carries the TCP byte stream unchanged, so the BEES protocol bytes (the distribution handshake and frames, or the TLS
records) are the ones the two programs wrote; what a forward does NOT show is a route, a translation or a firewall between the
two machines. So: **"Mac dials Linux" is proven over the real network; "Linux dials Mac" is proven for the protocol and the two
platforms' code, over a forward.**

## What was run

`tools/bees_interchange.py` (driver) and `tools/bees_interchange_node.py` (runs one program under the driver's control on either
machine; when its control channel ends it kills what it started). Per scenario the two outputs are normalised (runtime addresses,
the runtime's root-actor line, the remote machine's name and address replaced by `THERE_HOST` and `THERE_IPV4`) and compared with
`NAME.here.macos_applesilicon.scout` and `NAME.there.linux_x86_64.scout`.

### `trials/x1_interchange_beam` (ports 22800..22899)

Cookie: 32 random hex digits per run, written mode 600 on both machines, removed afterwards; the stock erl gets it through
`-args_file` (not on its command line, where other users of the machine could read it).

| scenario | path | what happens | result |
|---|---|---|---|
| `here_dials` | direct, port 22800 | node `hd` (Mac) dials node `tl` (Linux) **by name**: BEES's resolver answers the address, cookie handshake both ways, `hd` sends `req 21`, `tl` answers `ans 42` and sends its own `req 34`, `hd` answers `ans 68`, all over the one link | pass |
| `there_dials` | -R 22801 | node `td` (Linux) dials node `hl` (Mac); the same exchange with the roles on the other machines | pass |
| `erl_there_dials` | -L 22890 (EPMD), -R 22810 | `n2_live`'s `stock_dials` with the **stock erl on Linux** and BEES (`el`) on the Mac: BEES registers with the stock node's EPMD, `net_adm:ping` pong, `{inbox, BEES} ! Term`, a BEES pid handed out and used, link, unlink, monitor, a link to a pid BEES does not have (noproc), 26 s idle on ticks, BEES killed: nodedown, noconnection | pass |
| `erl_there_listens` | -L 22890, -L 22811 | `n2_live`'s `bees_dials`, stock erl on Linux, BEES (`ed`) on the Mac: BEES asks EPMD, dials, casts to the stock node's registered process, the stock node answers over the same link | pass |
| `erl_here_dials` | -R 22890, -L 22810 | `stock_dials` with the **stock erl on the Mac** and BEES on Linux | pass |
| `erl_here_listens` | -R 22890, -R 22811 | `bees_dials` with the stock erl on the Mac and BEES on Linux | pass |

The four erl scenarios use forwards only, by choice: a stock node is a remote shell for whoever passes the cookie handshake, so
erl and its private EPMD stay on 127.0.0.1 of their machine (`inet_dist_use_interface {127,0,0,1}`, distribution port fixed at
22811, `-start_epmd false`). The BEES side's outputs are byte for byte `n2_live`'s goldens with this trial's two port numbers,
and each scenario's output is the same whichever machine runs which side.

### `trials/x2_interchange_trust` (ports 22900..22999)

Two nodes, each a server (a whitelist holding the other's certificate) and a client (a pin of the other's address to its
certificate), no CA configured (D43). Certificates: `certs/`, TEST ONLY, made once with `tools/bees_test_certs.sh` (the tooling
of `trials/n4_trust_tls`): `a.pem` is node `there`, `b.pem` is node `here`, `u.pem` is in no whitelist. The test keys travel to the
remote with the tree, as `n4_trust_tls`'s already do; no other key was copied.

| scenario | path | what happens | result |
|---|---|---|---|
| `here_calls` | direct, port 22900 | node `here` (Mac) calls node `there` (Linux): four requests, one TLS 1.3 connection each (hello and token issue, token fast path, a cast, a binary argument and result); both sides log `TLSv1.3 X25519MLKEM768 TLS_AES_256_GCM_SHA384 alpn trust/1, mutual`; Linux admits the Mac by the SHA-512 of `b.pem` | pass |
| `there_calls` | -R 22901 | node `there` (Linux) calls node `here` (Mac); the Mac admits Linux by the SHA-512 of `a.pem` | pass |
| `here_wrong_pin` | direct | node `p` (Mac) pins the server's address to another certificate: `{error, server_not_pinned}`; the Linux server logs `closed_by_peer ... stage tls_handshake` and admits nothing | pass |
| `there_wrong_pin` | -R 22901 | the same from Linux against the Mac's server | pass |
| `here_unlisted` | direct | node `u` (Mac) presents `u.pem`: the handshake completes, the Linux server logs `whitelist_reject fp=86b29b... fingerprint not in the whitelist, connection closed`; the call answers `{error, closed}` | pass |
| `there_unlisted` | -R 22901 | the same from Linux against the Mac's server | pass |

In the `there_*` scenarios TLS is end to end between the two BEES nodes; ssh only carries the ciphertext.

## Differences between the platforms

None in behaviour. Specifically looked at:

- **Byte order and word size:** both machines are little-endian with 64-bit words (arm64 and x86_64), so the trials do not put a
  big-endian or 32-bit machine against a 64-bit one; within that, every frame written on one was read on the other (the
  distribution handshake's big-endian fields, the ETF integers 21 to 68, an ETF binary, TRUST's 4-byte frame lengths).
- **MD5 and random:** the cookie digest computed with CommonCrypto on the Mac is accepted by the one computed with OpenSSL EVP on
  Linux, and the reverse, and each by a stock erl of the other machine (OTP 27 and OTP 28).
- **OpenSSL:** 4.1.0 on both; the same group (X25519MLKEM768) and suite on both sides; the SHA-512 certificate fingerprints
  computed on one machine match the pins and whitelist entries compiled on the other.
- **Compiler generations:** the Mac nodes are built by 999909 and the Linux nodes by 999944; the encode/decode they derive
  interoperate.
- **Timing:** a node build takes about 14 s on the Mac and 36 to 67 s on the Linux box. Nothing in the outputs depends on the 45 ms round trip: the dialing role waits 3 s before its first request (1.5 s in the
  one-machine trials), TRUST's timeouts in these nodes are 3 to 5 s, and the link-down audit lines whose place depends on which
  program is stopped first are dropped (as `n2_multilink` does).

## Defects and fixes

- **BEES tooling, fixed:** `tools/run_all_trials.py`'s sync list did not exclude `unreadable_whitelist.config`, which
  `trials/n3_trust` writes mode 000 on each machine; rsync cannot open it and ends with status 23, so a remote sync from a tree
  where `n3_trust` has run failed. The name is now in `SYNC_EXCLUDES` (the interchange driver uses the same list).
- **Silica:** none found; no entry was added to `silica-defects.md`.
- **BEES `src/`:** unchanged.

## Limits

- **Owner statement, 2026-11-18:** "This network limits access to the mac. Linux to mac will be tested on a different network."
  The ssh -R forward is accepted for now as the protocol proof of that direction. **Open item: Linux dials Mac over a real
  route: to be run on a network that allows inbound connections to the Mac.** The driver runs it without a code change:

  ```
  make interchange SILICA_COMPILER=... BEES_INTERCHANGE_HERE_ADDRESS=<the Mac's IPv4 address as the Linux box can dial it>
  # or: tools/bees_interchange.py --here-address <IPv4>
  ```

  With the address given, only the four BEES-with-BEES scenarios of that direction run, directly and with no forward, under
  their own names: `there_dials_direct` (BEAM), `there_calls_direct`, `there_wrong_pin_direct`, `there_unlisted_direct` (TRUST).
  The Mac's listeners then bind every IPv4 interface (`0.0.0.0:22801`, `0.0.0.0:22901`: those two ports must be open to the
  Linux box), the Linux nodes dial the given address (written into their `bees.config` and pin files by the node Makefiles, so
  the nodes are rebuilt), and the driver first probes both ports from the remote and prints the result; a blocked port fails
  those scenarios with that reason. They have no goldens yet: the listen address is part of a node's output, so the first run
  shows MISSING; read `NAME_direct.here.sout` and `NAME_direct.there.sout` (the Mac's address is written `HERE_IPV4`), then
  record with `--record`. Without the option everything runs as described above, the forward being the default. Not exercised
  in this mode: the code path of the option itself (the probe from the remote, the `0.0.0.0` listeners on the Mac) has only its
  unit test and `--list`; the node templates with the default values produce the nodes that pass today.
- The direct path is proven in one direction only (Mac dials Linux); on this network Linux cannot reach the Mac, so that direction
  and all four erl scenarios ran through ssh forwards and say nothing about routes or firewalls. The erl scenarios stay on
  forwards in either mode.
- A direct listener binds every IPv4 interface of the remote (no narrower choice in the carrier, SR-1). In BEAM mode that is a
  cookie-authenticated, unencrypted listener on a public address for a few seconds per run; in TRUST mode a mutual-TLS one. The
  TRUST client entry of a node that has a whitelist also starts that node's listener (`trust_start`), so node `there` listens on
  `0.0.0.0:22900` during `there_calls` too, although nothing dials it then.
- TRUST dials IPv4 literals only (a name answers `dns_error`: by design, DNS is not built for TRUST); the driver resolves the
  remote's name and the node Makefiles write the address into the pin file and the client role. BEAM mode dials the name.
- The goldens are for the Mac as "here" and Linux as "there". Driving from the Linux box with the Mac as the remote would need the
  Mac to be reachable by ssh and its own goldens.
- Both platforms are 64-bit little-endian; a board (ESP32-S3, NUCLEO) is the first place where word size differs.
- Not covered across machines: redial after a lost link, more than two nodes, EPMD on the peer host reached over the network
  (it is forwarded), `n2_live`'s wrong-cookie and unlisted-node refusals (BEAM-mode refusals are covered on one machine by
  `n2_live` and `n2_auth`), TRUST's token expiry, quarantine and the hostile-peer suite (`n4_trust_tls`).

## How to run

```
cp .bees_build_hosts.example .bees_build_hosts      # then set the remote path, compiler, SILICA_ROOT (tools/README.md)
make interchange SILICA_COMPILER=/path/to/silica-999909-macos-applesilicon
```

Without `.bees_build_hosts` it prints `interchange: skipped: no remote (...)` and succeeds. The interchange trials are not
leaves (their directories hold `interchange.mk`, not `Makefile`), so `make integrate` and `tools/run_all_trials.sh` never run them.
The line used for this work:

```
linux_x86_64 manager@aalang.org ~/bees-interchange /opt/openssl 2 SILICA_COMPILER=/home/manager/silica/binaries/silica-compiler-linux_x86_64 SILICA_ROOT=/home/manager/silica
```

A full run with everything built takes about two minutes (half of it the two 26 s tick waits of the erl scenarios); the
first run builds 7 nodes here and 7 there (about 2 and 5 minutes, at the same time), 6.5 minutes in all. A node is rebuilt only when its inputs
changed (`.interchange_stamp`; `--rebuild` forces it).

## Left on the remote machine

`~/bees-interchange` (about 80 MB: the synced tree and the Linux builds of the interchange nodes and of `native/`). No process, no
listener, no cookie file: the driver removes the cookie, cancels the forwards, closes the session and checks with `pgrep` that
nothing of the trials is running. `~/silica` and `~/bees-linux` were not written to.

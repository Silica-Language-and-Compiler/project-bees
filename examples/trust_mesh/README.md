# trust_mesh: five TRUST nodes that all call each other

This example runs five BEES nodes in TRUST mode on one machine. Every node is a TRUST server and also a TRUST client of
the other four. That is a complete mesh: 5 nodes, 20 directed pairs (n1 calls n2 is one pair, n2 calls n1 is another).
All traffic is inside mutual TLS 1.3. Nothing here uses `plaintext_test_only`.

The certificates and keys in `certs/` are TEST ONLY. They belong to nobody. Never use them for a real node.

## What you need

- The Silica compiler that BEES is pinned to (`tools/silica.generation`).
- OpenSSL 4.1.0 or later, installed by you (`contract/what-is-required-to-use.md`). BEES ships no TLS library.
- python3, make and clang.

## How to run it

From this directory:

```
make start SILICA_COMPILER=/path/to/silica-compiler
```

This builds the TLS engine and the five programs (about three minutes), runs the mesh once (about ten seconds), and
prints the check and the output of node 1. If you leave `SILICA_COMPILER` out, the compiler of `tools/silica.mk` is used.
Write it on the make command line; a value in the environment is not read.

As a trial, from the top of the tree:

```
SILICA_COMPILER=/path/to/silica-compiler tools/run_all_trials.sh --local-only --only n5_trust_mesh
```

The trial is `trials/n5_trust_mesh`. It builds and runs this example and compares six outputs with the recorded ones.

## What is in here

| Path | What it is |
| --- | --- |
| `nodes/n1` to `nodes/n5` | One directory per node: `bees.config`, `trust_whitelist.config`, `trust_servers.config`. |
| `nodes/node.mk` | How a node is built. The same for all five. |
| `roles/mesh.role` | The program of a node. The same for all five. |
| `roles/mesh_demo.silica` | The function a node offers to its peers, `mesh:relay/2`. |
| `roles/mesh.trust` | The list of functions a peer may name. One line. |
| `roles/mesh.atoms` | The atoms the program adds to BEES's own. |
| `certs/` | Five self-signed test certificates and keys. `make_certs.sh` made them once. |
| `mesh_run.py` | Starts the five programs, stops them, and writes the check. |
| `mesh.*.scout` | The recorded outputs (one set per platform). |

The five programs are built from the same sources. Only the configuration differs.

## The configuration of a node

Look at `nodes/n3`. Three files make node 3 a member of the mesh.

`bees.config` says the mode is `trust`, the node listens on `127.0.0.1:24403`, and its certificate is `n3.pem`. It has
no `beam` section, because a node is BEAM or TRUST and never both. It has no `cacertfile`, so no certificate chain is
checked. A peer is trusted only by the SHA-512 of its certificate.

`trust_whitelist.config` lists who may call node 3: the certificates of n1, n2, n4 and n5. Each may call `mesh:relay/2`
and nothing else. This file is what makes node 3 a server.

`trust_servers.config` lists whom node 3 may call: the addresses of the other four nodes, each pinned to that node's
certificate. This file is what makes node 3 a client. If a server shows another certificate, the call fails.

The configuration is read when the program is built, as in the TRUST trials (`tools/bees_config_trust.py`). Change a
file, then build again. The ports are the block of `n5_trust_mesh` in `tools/trial_ports.py`: port 24401 is node 1, and
so on to 24405.

`bees.config` also writes `session`. With it, one TLS connection to a peer carries every call to that peer. `idle_ms` is
30 seconds, longer than the run, so no connection closes while the example runs.

## What the nodes do

A baton goes round the mesh. The node that holds it calls `mesh:relay([Hop, Caller])` on one other node. The node that
answers now holds the baton and makes the next call. Node 1 starts.

A node calls its four servers in the order of its pin file: the next node, then the node two on, three on, four on. With
that order the baton uses each of the 20 directed pairs once and comes back to node 1. That is one lap. The example
runs two laps:

- Lap 1 (hops 1 to 20) opens the 20 TLS connections, one for each directed pair.
- Lap 2 (hops 21 to 40) makes 20 more calls over the connections that are already open. No new connection is made.

At the end every node holds eight open TLS connections: four it opened and four it accepted.

The answer to a call is `Hop * 100 + Caller * 10 + the number of the node that answered`. So the line

```
hop 9: n2 called 127.0.0.1:24404 mesh:relay([9, 2]): {ok, int 924}
```

says that node 2 called the address of node 4 at hop 9, and that node 4 answered (the last digit).

## The check

`mesh.check` is written from the output of all five nodes. A call is counted only when its answer is `{ok, int N}` and
N names the node at the address that was called.

```
calls answered by the right node, caller in rows, server in columns (2 laps, so 2 for every pair):
     n1  n2  n3  n4  n5
n1    -   2   2   2   2
n2    2   -   2   2   2
n3    2   2   -   2   2
n4    2   2   2   -   2
n5    2   2   2   2   -
directed pairs with every call answered: 20 of 20
calls answered: 40 of 40
hops in order, none twice, none missing: yes
calls with another outcome: 0
TLS connections opened as a client, n1 to n5: 4 4 4 4 4
TLS connections accepted as a server, n1 to n5: 4 4 4 4 4
sessions ended before a node's done line: 0
failure lines before a node's done line: 0
nodes that printed their done line: 5 of 5
nodes that ended with exit=0: 5 of 5
```

The other five recorded outputs, `mesh.n1` to `mesh.n5`, are what each node printed up to its `done` line: the boot
lines, one line for each call it made, and the audit lines of each connection it accepted.

## What this example does not show

- The calls are made one at a time, with a wait of 200 ms before each. The nodes never call at the same moment. The
  reason is a Silica defect (SD-49 in `development-plan/silica-defects.md`): two actors of one program that print at the
  same moment can mix their lines, and then the output cannot be compared with a recorded one. So this example shows
  that every pair works and that all 20 connections stay open together. It does not show load.
- All five nodes run on one machine, on 127.0.0.1. Two machines are the business of `trials/x2_interchange_trust`.
- No node is stopped and started again, and no call is refused. The refusals (a wrong pin, a certificate that is in no
  whitelist) are in `trials/n4_trust_tls`.
- What a node prints after its `done` line is not compared. When the nodes are told to exit, the order in which their
  connections end is not fixed. That part of the output is kept in `mesh.nK.raw`.
- The baton's route comes from the order of the pin files. If you change that order, the baton may stop before it has
  used every pair, and the check will say so.

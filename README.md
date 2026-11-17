# Project BEES

**BEAM Elastic Execution Surface**

This file records the **intended scope** of Project BEES.

Project BEES is the **shim that lets BEAM languages** (Erlang, Elixir, Gleam, LFE) **be compiled to Silica and its constructs**. It is not a reproduction of the BEAM's code API for Silica programmers. Each BEAM language is compiled to Silica by its own language-to-Silica compiler. Those compilers are separate projects, and all of them target the BEES target contract. BEAM processes become plain Silica actors, BEAM atoms are Silica atoms held in Silica's atom table, and OTP's supervisors, gen_servers, and state machines become Silica's own constructs. BEES supplies the rest of what compiled BEAM code needs and Silica lacks: the term model, BIFs, ETS, ports, and distribution (timers are Silica's own). BEES does not duplicate every BEAM type or behaviour: its aim is to make compiling a BEAM language to Silica **possible, not easy**. It is built **in Silica** and is meant to **sit where a conventional BEAM would**, while adding **first-class support for running and balancing work across many cores** and **across a network**—so placement, migration, and integration with I/O and clustering are not afterthoughts.

The name nods to **Bogdan and Björn’s Erlang Abstract Machine (BEAM)**. BEES is not a reimplementation of OTP in full, many parts of which exist in native Silica including actors and supervisors; it is a **focused execution surface** and **shim** that carries that lineage forward in a new substrate.

## Scope (in)

- **Target contract** — the language-neutral specification that language-to-Silica compilers target. For each BEAM construct it says which Silica construct or BEES component it becomes. It comes with a conformance kit that compilers can check themselves against.
- **Execution surface** — the boundary at which “BEAM-like” code meets the host: schedulers, actor lifecycle hooks, links, and networking-aware execution (as the project defines them over time).
- **Multi-core** — **balancing and affinitizing actors** to cores, and policies for fairness, yielding, and locality, appropriate to a Silica-backed runtime. Silica schedules each core; BEES balances and places across cores through Silica's `migrate_actor()`. On OS-hosted apps it balances BEAM-style between the Silica runtime's carrier threads, and exclusive placement is never guaranteed, because the OS owns the cores. Running raw on a chip, it balances BEAM-style-ish directly onto the cores, and a pin is exclusive.
- **Networking** — **distribution-oriented paths**: naming or addressing actors across nodes, and protocols or adapters for sending messages and coordinating placement. There are two modes: **SEMP/TRUST**, secure by default, of which BEES is the first implementation, and **standard BEAM distribution**, an explicit downgrade for interoperating with Erlang/OTP clusters. They are two separate implementations, chosen in the BEES configuration file `bees.config` (a design, not built yet).
- **Clear dependency on Silica** — BEES is expected to use Silica for compilation and any runtime pieces that are already in Silica; **its repository** is meant to track the **orchestration layer, APIs, and integration** that are specific to a BEAM-style surface rather than the whole compiler.
- **Documentation of intent** — what is guaranteed, what is compatible with Erlang/OTP concepts, and what is **Silica-specific** behavior.

## Scope (out) — for now

- Claiming **bug-for-bug, wire-format, or full OTP compatibility** with any particular Erlang/BEAM release without explicit, tested guarantees.
- Loading or interpreting `.beam` bytecode at run time. BEAM-language code is compiled ahead of time.
- Duplicating every BEAM type and behaviour. Where Silica differs (for example, supervisor-only exit trapping, or Silica-shaped failure messages), the language compiler adapts.
- The language-to-Silica compilers themselves. Each one is its own project.
- Holding or depending on OTP source code. Each compiler converts the OTP behaviours and libraries its language uses. Where BEES itself needs such a facility (`gen_tcp`, `file`, `erpc`, `global`, and so on), it implements it in Silica.
- Replacing the **entire** Silica project; BEES is a **sibling** product and repository whose role is the **actor execution and distribution** story on top of Silica.
- **Vendor-specific** deployment recipes unless they are clearly optional and documented as such.

(Adjust this section as the project ships concrete milestones.)

## Relationship to Silica

Silica provides the **language and toolchain** including actors and supervisors; Project BEES defines the **runtime-facing contract** and **infrastructure** for a BEAM-execution surface: scheduling, distribution hooks, and the glue between generated code and the machine. **Versioning** between Silica and BEES; The are no common version numbers between Silica and BEES. Each has its own release schedule.

## What you need to install

BEES ships no TLS library; see [contract/what-is-required-to-use.md](contract/what-is-required-to-use.md).

## BEES is an implementation of SEMP

SEMP is a secure communication overlay for distributed systems. It has two parts: TRUST, for nodes that stay up, and TEMPUS, for nodes that come and go. BEES is an implementation of SEMP, and its default mode, the mode a program gets unless it asks for something else, is SEMP's. The documents directory explains each part in plain words: [documents/semp.md](documents/semp.md), [documents/trust.md](documents/trust.md) and [documents/tempus.md](documents/tempus.md).

Being an implementation of SEMP has consequences for anyone who builds on BEES:

- Every node has a certificate. Nodes are identified by the SHA-512 fingerprint of their certificate, and every connection is TLS 1.3 with certificates on both sides. A node you have not listed is closed on without an answer.
- Nothing is allowed unless it has been granted. Each peer in the whitelist may run nothing, anything, or a stated list of modules and functions. Some functions are never allowed to any peer.
- Each remote call is one request on its own connection. There is no fully connected mesh and no long-lived channel between nodes in this mode.
- There is no EPMD and no shared cookie. A caller connects to an explicit host and port.
- A refused peer is told nothing. Failures are written to the receiving node's own log, and a peer that keeps failing is quarantined until an operator resets it.
- The settings live in a configuration file, bees.config, and the certificates, whitelist and pins are files you provide. BEES does not ship a TLS library: see [contract/what-is-required-to-use.md](contract/what-is-required-to-use.md).

Status: TRUST is built in BEES. TEMPUS is planned for after the first release and is not built yet.

## Status

Currently BEES is in its inception phase.

## License

Project BEES is licensed under the **Apache License, Version 2.0**.

## Contributing & heritage

When describing BEES publicly, it helps to **credit the BEAM and its origins** in one line, for example: *inspired by Bogdan and Björn’s Erlang Abstract Machine and the Erlang/OTP community.*

## BEES and standard BEAM nodes

BEES can also be used to connect to standard BEAM nodes, but no single node can be both a BEAM node and a SEMP node. A node runs in one mode or the other. To make one node do both would leave the entire network of nodes open to the same security weaknesses as pure BEAM node networks, because a network of nodes is only as secure as its least secure node. A node that speaks both would be a way into the SEMP network for anything that can reach it as a BEAM node. Forking BEES to add such a bridge is highly discouraged for security reasons.

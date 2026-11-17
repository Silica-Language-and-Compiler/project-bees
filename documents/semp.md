# SEMP

SEMP is a secure communication network overlay for large distributed systems. It keeps the Erlang way of calling functions on other nodes, and replaces how nodes find each other, prove who they are, and decide what they may do. It has two parts, TRUST and TEMPUS, and it uses each for the kind of node it suits.

## The problem it solves

In standard Erlang distribution every node connects to every other node, finds them through a directory called EPMD, and trusts anyone who knows a shared cookie. Connected nodes can run nearly anything on each other. This is convenient, and it assumes everyone on the network is trustworthy. A distributed system on a real network, with real attackers and with nodes that come and go, cannot assume that.

SEMP is built for that world. Its rules are the same for every node:

- Every connection is TLS 1.3 with certificates on both sides.
- Nothing is allowed unless it was granted, and the grant is per peer and per function.
- Each call is its own short connection, so there is no fully connected mesh to attack or to slow down.
- A refused peer learns nothing. Errors go to the local log, never back over the wire.
- Nodes that misbehave are scored and, if needed, quarantined.
- There is no EPMD, and a caller connects to an explicit host and port found through DNS.

## How SEMP uses TRUST

TRUST is SEMP's layer for nodes that stay up. Servers and services whose certificates are known ahead of time are listed in each other's whitelists. They call each other with single requests, with tokens making repeated calls quick. This is where the actual remote function calls happen, and it is where the whitelist, permissions and suspicion rules are enforced.

## How SEMP uses TEMPUS

TEMPUS is SEMP's layer for nodes that come and go. Such nodes cannot be listed ahead of time, so TEMPUS admits them by a short-lived token signed by the producer plus proof of the node's own key, and lets them find each other by gossip sampling. Three groups are kept apart: edge peers (the transient nodes), bridge peers (stable nodes that connect to TRUST networks) and sentinel peers (the ones that guard admission).

## How the two fit together

A transient node joins through TEMPUS: it is admitted by a sentinel, it finds other transient nodes by sampling, and when it needs a stable service it goes through a bridge peer. The bridge peer is part of a TRUST network, and from that point TRUST's rules apply: certificate identity, whitelist, permissions and suspicion. Neither layer weakens the other. TEMPUS decides who may be a member. TRUST decides what a member may do.

## Status in BEES

BEES is an implementation of SEMP. TRUST is built in BEES and TEMPUS is planned for after the first release. The README says what that means for programs written for BEES.

See also: trust.md and tempus.md.

# TRUST

TRUST stands for Trusted, Rapid, Unmodifiable, Secure Topology. It is the part of SEMP that connects nodes which stay up for a long time: servers, services and other stable members of a distributed system.

## What it is

TRUST lets one node call a function on another node, and nothing more. Each call is one request on its own connection. The caller connects, asks for one function to be run (a call, which waits for the answer, or a cast, which does not), and the connection closes. There is no long-lived channel between nodes, no automatic connection of every node to every other node, and no shared secret that every node holds.

Every connection is protected by TLS 1.3 with certificates on both sides. A node is identified by its certificate, and the identity is the SHA-512 fingerprint of that certificate. Before anything runs, the receiving node checks that fingerprint against its own whitelist.

## How it works, in short

1. The caller looks up the host name and connects to an explicit host and port. There is no discovery service.
2. Both sides present certificates. A node that has no certificate, or whose certificate is not on the whitelist, is closed on without an answer.
3. The receiving node may give the caller a short-lived token. On the next connection the caller presents the token and skips part of the start-up work, which makes repeated calls faster. A token is never kept across a restart.
4. The caller sends the request: a module, a function and its arguments.
5. The receiving node checks that the function is allowed for this caller, runs it, and sends back the result for a call.
6. The connection closes.

## What controls what a caller may do

Each whitelist entry says what that peer may run: nothing, anything, or a list of modules and functions. Some functions can never be run by a peer, whatever the whitelist says, such as those that load code, control the operating system, open sockets, create atoms or change how processes are traced. Functions in BEES's own internal modules are also off limits.

A node that misbehaves is noticed. Each peer has a suspicion count that rises with protocol violations, refused requests, errors and timeouts, and falls when permitted requests succeed. A peer that goes over the limit is quarantined: its token is withdrawn and its requests are refused until it has recovered. An operator can reset a peer by hand.

A node never tells a refused peer why it was refused. Errors are written to the receiving node's own log and are never sent over the connection, so an attacker learns nothing from a failure.

## Why it exists

Standard Erlang distribution was built for machines on a trusted network. Once a node has joined, it can run almost anything on any other node it can reach, the one shared cookie is all that stands between an outsider and the whole system, and every node ends up connected to every other. That works inside a locked room. It does not work between machines on networks you do not control.

TRUST replaces that with a strict model:

- Identity is a certificate, not a shared secret.
- Authority is granted per peer, per function, and defaults to nothing.
- One request per connection keeps the number of connections small and stops one bad connection from reaching far.
- Silent refusal and local logging give an attacker no feedback.
- Suspicion and quarantine contain a node that has been compromised or has gone wrong, without taking the whole system down.

## What TRUST does not do

TRUST does not use EPMD or the standard Erlang start-up handshake. It does not keep a connection open for streaming. It does not send error details back to the caller. Nodes that need those things belong in a different arrangement, and a node that is part of a SEMP network does not use them.

See also: semp.md (how SEMP uses TRUST and TEMPUS together) and tempus.md (the part for nodes that come and go).

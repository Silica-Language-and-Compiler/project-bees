# TEMPUS

TEMPUS stands for Transient Entities Managed by a Peer-overlay for Unified Security. It is the part of SEMP for nodes that come and go: phones, laptops, browsers and other short-lived members of a system. In BEES, most of TEMPUS is built: networked nodes, the TLS link, a bridge node, start-up checks, gossip discovery and admission. Example clients exist in Python, Kotlin, Swift and Silica, for illustration only. What is left is listed in development-plan/tempus-progress.md.

## What it is

TEMPUS is a membership layer. It keeps every node supplied with a fresh, unbiased sample of the other nodes it can reach, even though nodes are joining and leaving all the time. It uses a gossip protocol called Cyclon for this. Each node holds a small view of its peers, and the views are shuffled between neighbours on a timer, with the oldest entries dropped first.

TEMPUS keeps three groups of peers apart, and the groups never mix:

- Edge peers are the short-lived, high-churn nodes. They make up most of the network.
- Bridge peers are longer-lived nodes that connect the TEMPUS network to TRUST networks. They are how short-lived nodes reach stable ones.
- Sentinel peers are longer-lived nodes that guard admission. They are where a new node proves that it belongs.

## How a node is admitted

Joining and sampling are separate. Sampling only ever sees nodes that have already been admitted. To be admitted a node needs all of the following:

1. Its own key pair, made when it first runs. Its identity is derived from the public key. No secret is shared between peers.
2. A token from the producer, the service that owns the product. The token is short-lived, normally a few minutes, and it names the node's public key and its kind of peer. The producer signs it.
3. Proof that the node holds the matching private key. A verifier sends a fresh challenge and the node signs it, so a copied token is useless to anyone who lacks the key.
4. A current signing key on the token. When the producer rotates its key, tokens made with the old key are refused and honest nodes simply fetch a new token.
5. For apps on phones, an attestation from the platform, so the producer only signs tokens for genuine, unmodified builds on real devices.

A node without a valid, current token and the matching proof is not admitted and never appears in anyone's view.

## Why it exists

TRUST works by listing the nodes it trusts in advance. That is the right design for servers, but it cannot work for nodes that appear without warning, change address, and number in the thousands. They cannot be on a list written beforehand.

TEMPUS answers a different question: how does a node that nobody listed prove that it is a genuine member, without any shared secret that could leak? The answer is a short-lived token from the producer plus proof of the node's own key, and the answer to how nodes find each other without a central directory is gossip sampling over only the admitted nodes.

## How it relates to TRUST

TEMPUS is built on top of TRUST. It reuses TRUST's transport, framing, encoding and request handling, and adds membership and admission for peers that come and go. Where an ephemeral node reaches a stable service, it does so through a bridge peer into a TRUST network, and TRUST's own rules apply there.

See also: trust.md (the part for stable nodes) and semp.md (how both fit together).

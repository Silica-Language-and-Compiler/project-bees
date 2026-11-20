#!/bin/bash
# TEST ONLY. Makes the five certificates and keys of examples/trust_mesh (certs/n1.pem ... n5.pem, each with its key) with the
# OpenSSL the programmer installed (OPENSSL, default the first openssl on PATH; nothing is downloaded). Each certificate is
# SELF-SIGNED (Ed25519, no CA): a node trusts a peer by the SHA-512 of the peer's certificate alone, as a pin (the peer as a
# server) and as a whitelist entry (the peer as a client), D43. Run by hand, once; the example uses the files it leaves, so the
# fingerprints in the goldens stay fixed. It refuses to replace an existing directory: every golden that prints a
# fingerprint would change. The keys are fixtures, mode 600, and belong to nobody; never use them for a real node.
#
#   examples/trust_mesh/make_certs.sh DIR
set -eu
DIR=${1:?usage: make_certs.sh DIR}
OPENSSL=${OPENSSL:-openssl}
[ -e "$DIR" ] && { echo "make_certs: $DIR exists; remove it first (every golden that prints a fingerprint changes)"; exit 1; }
mkdir -p "$DIR"
cd "$DIR"
for n in n1 n2 n3 n4 n5; do
    "$OPENSSL" genpkey -algorithm ed25519 -out "$n-key.pem"
    "$OPENSSL" req -x509 -new -key "$n-key.pem" -subj "/CN=bees-mesh-example-$n (self-signed, TEST ONLY)" \
        -not_before 20260101000000Z -not_after 20360101000000Z \
        -addext basicConstraints=critical,CA:FALSE -addext keyUsage=critical,digitalSignature -out "$n.pem"
done
chmod 600 ./*-key.pem
for n in n1 n2 n3 n4 n5; do
    printf '%-3s sha512 %s\n' "$n" "$("$OPENSSL" x509 -in "$n.pem" -noout -fingerprint -sha512 | sed 's/^.*=//; s/://g' | tr A-F a-f)"
done | tee fingerprints.txt

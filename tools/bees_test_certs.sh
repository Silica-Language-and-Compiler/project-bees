#!/bin/bash
# TEST ONLY. Makes the certificates and keys of the N4.1 TRUST-over-TLS trials (trials/n4_trust_tls/certs) with the
# programmer-installed OpenSSL's command-line tool (OPENSSL, default the first openssl on PATH; nothing is downloaded).
# Run by hand, once; the trials use the files it leaves, so the fingerprints in the goldens stay fixed. It refuses to
# replace an existing directory (rm -rf it first): every golden that prints a fingerprint would change.
#
#   tools/bees_test_certs.sh DIR
#
#   ca          the test CA (Ed25519, self-signed, CA:TRUE): the cacertfile of every node
#   a           node a's certificate (Ed25519, signed by ca): the server
#   b           node b's certificate (Ed25519, signed by ca): the client; whitelisted on a
#   n           a client whitelisted with the spec none (Ed25519, signed by ca)
#   u           a client signed by ca but in no whitelist (unlisted)
#   p           a client with an ECDSA P-256 key (signed by ca), whitelisted: the profile's second certificate kind
#   rogue_ca    another CA; r is signed by it (a certificate from the wrong CA)
#   x           signed by ca but expired (2020 to 2021)
#   z           signed by ca, RSA 2048: a signature kind the profile refuses
#   w           SELF-SIGNED (Ed25519, no CA): a node with no cacertfile, trusted by its pin and the whitelist alone (D43)
# The keys are test fixtures, mode 600, and belong to nobody; they are never a node's real identity.
set -eu
DIR=${1:?usage: bees_test_certs.sh DIR}
OPENSSL=${OPENSSL:-openssl}
[ -e "$DIR" ] && { echo "bees_test_certs: $DIR exists; remove it first (every golden that prints a fingerprint changes)"; exit 1; }
mkdir -p "$DIR"
cd "$DIR"
NB=20260101000000Z NA=20360101000000Z
ca() {   # NAME CN
    "$OPENSSL" genpkey -algorithm ed25519 -out "$1-key.pem"
    "$OPENSSL" req -x509 -new -key "$1-key.pem" -subj "/CN=$2" -not_before $NB -not_after $NA \
        -addext basicConstraints=critical,CA:TRUE -addext keyUsage=critical,keyCertSign,cRLSign -out "$1.pem"
}
leaf() {  # NAME CA KEYALG NOT_BEFORE NOT_AFTER SERIAL
    case "$3" in
        ed25519) "$OPENSSL" genpkey -algorithm ed25519 -out "$1-key.pem" ;;
        p256) "$OPENSSL" genpkey -algorithm EC -pkeyopt ec_paramgen_curve:P-256 -out "$1-key.pem" ;;
        rsa) "$OPENSSL" genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out "$1-key.pem" ;;
    esac
    "$OPENSSL" req -new -key "$1-key.pem" -subj "/CN=bees-test-$1" -out "$1.csr"
    printf 'basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature\n' > "$1.ext"
    "$OPENSSL" x509 -req -in "$1.csr" -CA "$2.pem" -CAkey "$2-key.pem" -set_serial "$6" -not_before "$4" -not_after "$5" \
        -extfile "$1.ext" -out "$1.pem"
    rm -f "$1.csr" "$1.ext"
}
ca ca "BEES TRUST test CA (TEST ONLY)"
ca rogue_ca "a CA nobody configured (TEST ONLY)"
leaf a ca ed25519 $NB $NA 101
leaf b ca ed25519 $NB $NA 102
leaf n ca ed25519 $NB $NA 103
leaf u ca ed25519 $NB $NA 104
leaf p ca p256 $NB $NA 105
leaf r rogue_ca ed25519 $NB $NA 106
leaf x ca ed25519 20200101000000Z 20210101000000Z 107
leaf z ca rsa $NB $NA 108
"$OPENSSL" genpkey -algorithm ed25519 -out w-key.pem
"$OPENSSL" req -x509 -new -key w-key.pem -subj "/CN=bees-test-w (self-signed)" -not_before $NB -not_after $NA \
    -addext basicConstraints=critical,CA:FALSE -addext keyUsage=critical,digitalSignature -out w.pem
chmod 600 ./*-key.pem
for f in a b n u p r x z w ca rogue_ca; do
    printf '%-9s sha512 %s\n' "$f" "$("$OPENSSL" x509 -in "$f.pem" -noout -fingerprint -sha512 | sed 's/^.*=//; s/://g' | tr A-F a-f)"
done | tee fingerprints.txt

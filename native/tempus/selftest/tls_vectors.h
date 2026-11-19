/* TEST ONLY: the public keys of the TEMPUS test identities (tools/bees_tempus_certs.py, fixed seeds), as the
 * `cryptography` package derives them: what bees_tls_peer_key must return for each certificate. */
static const uint8_t bridge_pub[32] = {79,208,153,204,212,125,120,147,223,233,236,36,65,78,203,13,155,84,32,35,42,173,48,217,28,70,91,227,60,190,101,196};
static const uint8_t node_pub[32] = {41,172,186,225,65,188,202,240,178,46,26,148,211,77,11,199,54,30,82,109,11,254,18,200,151,148,188,147,34,150,109,215};
static const uint8_t other_pub[32] = {37,67,185,47,241,9,85,17,71,106,220,131,105,219,109,220,147,54,101,161,25,120,221,161,64,78,225,6,108,169,85,157};
static const uint8_t sentinel_pub[32] = {205,20,179,127,149,110,149,49,148,255,127,183,59,61,129,220,197,97,214,26,117,56,9,75,124,62,26,100,62,229,243,170};

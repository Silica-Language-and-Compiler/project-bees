/* BEES native edge, BEAM mode (milestone N2): Erlang's cookie authentication needs an MD5 digest and a random 32-bit
 * challenge. Both come from the system's own CommonCrypto (part of libSystem on macOS: CC_MD5, CCRandomGenerateBytes);
 * nothing is downloaded or bundled. macOS on Apple Silicon only.
 *
 * Results follow the tagged-result convention of the language's socket wrappers: { tag, value, error_code }, tag 0 ok.
 * The cookie is read from its file by the edge and never leaves it: Silica code sees only challenges (numbers it sends on
 * the wire anyway) and digests (which it sends or compares). */
#include <stdint.h>

typedef struct bees_beam_tagged {
    int64_t tag;
    int64_t value;
    int64_t error_code;
} bees_beam_tagged;

/* Read the cookie file at path (path_ptr, path_len: the compiler's string form; the pair is the whole parameter list,
 * SD-30) and keep its content for bees_beam_digest. tag 0: ok, value = cookie length; 1: open or read failed (errno in
 * error_code); 2: the file is readable or writable by group or others (OTP refuses a loose .erlang.cookie the same way);
 * 3: the content is empty, longer than 255 bytes, or holds a byte outside ASCII 32..126 (one trailing LF or CRLF is
 * dropped); 4: not a regular file. A failed load forgets any cookie loaded before. */
bees_beam_tagged bees_beam_load_cookie(const uint8_t *path_ptr, uint64_t path_len);

/* A random challenge, 0 .. 2^32-1, from CCRandomGenerateBytes. tag 0 ok; 1 the generator failed (status in error_code). */
bees_beam_tagged bees_beam_challenge(int64_t unused);

/* MD5(cookie ++ decimal(challenge)) (dist_util:gen_digest/2), kept per thread for bees_beam_digest_word. tag 0 ok; 5 no
 * cookie is loaded; 6 the challenge is outside 0 .. 2^32-1. */
bees_beam_tagged bees_beam_digest(int64_t challenge);

/* Word i (0..3) of the last digest computed on this thread, as an unsigned big-endian 32-bit number (bytes 4i .. 4i+3).
 * tag 0 ok; 6 i out of range. */
bees_beam_tagged bees_beam_digest_word(int64_t i);

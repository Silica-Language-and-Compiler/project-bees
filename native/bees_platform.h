/* The BEES native edge's platform interface (internal; not a Silica wrapper header).
 *
 * Everything in native/src, native/tls and native/trust is common code: it is written against C11 and POSIX only and
 * reaches the platform's own facilities ONLY through the functions declared here. Each platform directory beside this
 * file (native/macos, native/linux, native/esp32s3, native/nucleo) implements them, one function per file, with
 * its own platform.mk naming the compiler flags that platform needs. native/Makefile compiles the directory named by
 * BEES_PLATFORM (see native/README.md). A platform that cannot honour a contract below does not build.
 */
#ifndef BEES_PLATFORM_H
#define BEES_PLATFORM_H

#include <stddef.h>
#include <stdint.h>

/* bees_platform_random: fill out[0..n) with bytes from the platform's cryptographically secure source (macOS: the
 * system CSPRNG; Linux: the kernel's; ESP32-S3 and NUCLEO-L476RG: the hardware RNG, with its physical entropy source
 * on). Returns 0 on success and a non-zero platform error code otherwise; on failure the buffer content is unspecified.
 * It never blocks for longer than the platform's seeding and it never returns predictable bytes. */
int bees_platform_random(uint8_t *out, size_t n);

/* bees_platform_md5: the 16-byte MD5 digest of data[0..n). MD5 is not a secure hash; it is here only because Erlang's
 * cookie handshake (BEAM mode) is defined with it. Thread-safe; never fails. */
void bees_platform_md5(const void *data, size_t n, uint8_t out[16]);

#endif

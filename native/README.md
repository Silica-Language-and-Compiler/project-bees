# native/

The BEES native edge: the C that sits behind the `dangerous_exposure_source` wrappers (gap ledger section 4).

```
native/
  bees_platform.h                 the internal platform interface: bees_platform_random, bees_platform_md5
  Makefile                        builds the archives into dangerous_exposure_source/lib/ for BEES_PLATFORM
  src/                            COMMON: clock and poll (silica_bees_native.c), DNS, resolver, BEAM-mode cookie edge (silica_bees_beam.c)
  tls/                            COMMON: the TLS engine over OpenSSL (silica_bees_tls.c), selftest/
  trust/                          COMMON: TRUST-mode random ETF and constant-time compare (silica_bees_trust.c)
  dangerous_exposure_source/      the wrapper headers and .meta files Silica reads (bees/ beam/ trust/ tls/ resolve/), lib/ (built
                                  archives, ignored by git) and the sockets link into the Silica tree
  macos/                          platform: Apple Silicon (built and tested)
  linux/                          platform: Linux x86_64 (placeholder, README only)
  esp32s3/                        platform: ESP32-S3 (placeholder, README only)
  nucleo/                         platform: NUCLEO-L476RG (placeholder, README only)
```

## Rule

Common code (`src/`, `tls/`, `trust/`) is C11 and POSIX only. It reaches anything that differs between platforms only through
`bees_platform.h`:

| function | contract | macOS | Linux (later) | ESP32-S3 / NUCLEO (later) |
|---|---|---|---|---|
| `bees_platform_random(out, n)` | secure random bytes, 0 or an error code | `CCRandomGenerateBytes` | `getrandom(2)` | hardware RNG with its physical entropy source |
| `bees_platform_md5(data, n, out)` | 16-byte MD5 (Erlang cookie scheme) | CommonCrypto `CC_MD5` | OpenSSL EVP | Mbed TLS |

Every Apple-specific header, symbol and flag lives under `native/macos/`: `CommonCrypto/*`, `CCRandomGenerateBytes`, `CC_MD5`,
`-arch`, `-mmacosx-version-min`, the linker's `-macos_version_min`, Homebrew's OpenSSL and LLVM locations, BSD `sed -i ''`. A grep for
those outside `native/macos/` (and `tools/*.mk` text that only names the variables) finds nothing. The socket wrappers are
Silica's own (`compiler/stdlib/net/silica_sockets.c`, built here as `libsilica_sockets.a`); their platform flags (`SO_NOSIGPIPE` on
macOS) are Silica's concern.

A platform directory holds `platform.mk` (variables `PLATFORM_CFLAGS`, `PLATFORM_ASFLAGS`, `PLATFORM_LDFLAGS`, `PLATFORM_NATIVE_SRCS`,
`PLATFORM_TRUST_SRCS`, `PLATFORM_OPENSSL_DIRS`, `PLATFORM_CLANG`, `PLATFORM_SED_INPLACE`) and one C file per interface function.
`PLATFORM_NATIVE_SRCS` are compiled into `libsilica_bees_native.a` (BEAM mode needs random and MD5), `PLATFORM_TRUST_SRCS` into
`libsilica_bees_trust.a` (TRUST needs random). The wrapper headers, `.meta` files and the `dangerous_exposure_source` links of the
trial leaves stay where they were: Silica reads them from there and they are platform-free.

## Selecting a platform

`BEES_PLATFORM` (the directory) and `BEES_PLATFORM_ID` (the identifier in golden names, `macos_applesilicon`, `linux_x86_64`) default
from `uname -s`/`uname -m` (`tools/platform.mk`, `tools/platform_id.py`): `make -C native BEES_PLATFORM=macos`. A platform whose
`platform.mk` is missing stops the build with a message naming the directory.

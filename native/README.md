# native/

The BEES native edge: the C that sits behind the `dangerous_exposure_source` wrappers (gap ledger section 4).

```
native/
  bees_platform.h                 the internal platform interface: bees_platform_random, bees_platform_md5
  Makefile                        builds the archives into dangerous_exposure_source/lib/ for BEES_PLATFORM
  src/                            COMMON: clock and poll (silica_bees_native.c), the ONE resolver (silica_bees_resolve.c, with its test stub), BEAM-mode cookie edge (silica_bees_beam.c)
  tls/                            COMMON: the TLS engine over OpenSSL (silica_bees_tls.c), selftest/
  trust/                          COMMON: TRUST-mode random ETF and constant-time compare (silica_bees_trust.c)
  dangerous_exposure_source/      the wrapper headers and .meta files Silica reads (bees/ beam/ trust/ tls/ resolve/), lib/ (built
                                  archives, ignored by git) and the sockets link into the Silica tree
  macos/                          platform: Apple Silicon (built and tested)
  linux/                          platform: Linux x86_64 and aarch64, one directory (built and tested)
  esp32s3/                        platform: ESP32-S3 (placeholder, README only)
  nucleo/                         platform: NUCLEO-L476RG (placeholder, README only)
```

## Rule

Common code (`src/`, `tls/`, `trust/`) is C11 and POSIX only. It reaches anything that differs between platforms only through
`bees_platform.h`:

| function | contract | macOS | Linux | ESP32-S3 / NUCLEO (later) |
|---|---|---|---|---|
| `bees_platform_random(out, n)` | secure random bytes, 0 or an error code | `CCRandomGenerateBytes` | `getrandom(2)`, repeated on `EINTR` | hardware RNG with its physical entropy source |
| `bees_platform_md5(data, n, out)` | 16-byte MD5 (Erlang cookie scheme) | CommonCrypto `CC_MD5` | OpenSSL EVP (`EVP_Digest`, `EVP_md5()`) | Mbed TLS |

Every Apple-specific header, symbol and flag lives under `native/macos/`: `CommonCrypto/*`, `CCRandomGenerateBytes`, `CC_MD5`,
`-arch`, `-mmacosx-version-min`, the linker's `-macos_version_min`, Homebrew's OpenSSL and LLVM locations, BSD `sed -i ''`,
`ipconfig getifaddr`. A grep for those outside `native/macos/` (and `tools/*.mk` text that only names the variables) finds nothing
(`tools/test_platform_and_ports.py` checks the common C and `native/linux/`). What only Linux needs lives under `native/linux/` the
same way: `-D_GNU_SOURCE`, `-no-pie -rdynamic -lpthread`, the rpath to the programmer's OpenSSL, GNU `sed -i`, `ip route`. The socket wrappers are
Silica's own (`compiler/stdlib/net/silica_sockets.c`, built here as `libsilica_sockets.a`); their platform flags (`SO_NOSIGPIPE` on
macOS) are Silica's concern.

A platform directory holds `platform.mk` (variables `PLATFORM_CFLAGS`, `PLATFORM_SRC_CFLAGS`, `PLATFORM_ASFLAGS`, `PLATFORM_LDFLAGS`,
`PLATFORM_NATIVE_SRCS`, `PLATFORM_TRUST_SRCS`, `PLATFORM_NATIVE_NEEDS_CRYPTO`, `PLATFORM_RPATH_FLAG`, `PLATFORM_OPENSSL_DIRS`,
`PLATFORM_CLANG`, `PLATFORM_SED_INPLACE`, `PLATFORM_LOCAL_IPV4`; every platform.mk sets every one, empty where it has nothing to
say) and one C file per interface function. `PLATFORM_SRC_CFLAGS` is for the platform's own C files only (Linux: the OpenSSL
headers for MD5). `PLATFORM_NATIVE_NEEDS_CRYPTO` says that `libsilica_bees_native.a` calls OpenSSL on this platform, so a program
that names the archive is linked with `-lcrypto` (Linux; on macOS MD5 is in libSystem). `PLATFORM_RPATH_FLAG` is the linker's
rpath option where a shared OpenSSL outside the system directories needs one (Linux). `PLATFORM_LOCAL_IPV4` is the command that
prints this machine's non-loopback IPv4 address (`trials/n1_addr`).
`PLATFORM_NATIVE_SRCS` are compiled into `libsilica_bees_native.a` (BEAM mode needs random and MD5), `PLATFORM_TRUST_SRCS` into
`libsilica_bees_trust.a` (TRUST needs random). The wrapper headers, `.meta` files and the `dangerous_exposure_source` links of the
trial leaves stay where they were: Silica reads them from there and they are platform-free.

## Selecting a platform

`BEES_PLATFORM` (the directory) and `BEES_PLATFORM_ID` (the identifier in golden names, `macos_applesilicon`, `linux_x86_64`, `linux_aarch64`) default
from `uname -s`/`uname -m` (`tools/platform.mk`, `tools/platform_id.py`): Darwin/arm64 gives `macos`, Linux/x86_64 and Linux/aarch64 give `linux`
(`make -C native BEES_PLATFORM=macos` says it by hand). A platform whose `platform.mk` is missing (`esp32s3`, `nucleo`) stops the
build with a message naming the directory. On Linux `OPENSSL_PREFIX` matters to every archive that holds MD5, not only to the TLS
engine: see `native/linux/README.md`.

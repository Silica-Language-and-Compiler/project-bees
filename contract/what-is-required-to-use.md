# What is required to use BEES

**Status: written 2026-11-10 (roadmap D40, the TLS engine decision).** BEES does **not** ship any TLS library. Anyone building a program with BEES installs the engine for their platform themselves. This page says which, which versions, and why.

## 1. TLS engine and random source, by platform

| Platform | TLS engine | Random source | Minimum version |
|---|---|---|---|
| macOS and other Apple platforms | OpenSSL (you install it; macOS's bundled TLS library is not OpenSSL) | The platform's system CSPRNG | **OpenSSL 4.1.0** |
| Linux | OpenSSL | The Linux kernel CSPRNG | **OpenSSL 4.1.0** |
| NUCLEO-L476RG, bare metal | Mbed TLS | The STM32L476RG hardware RNG | **Mbed TLS 4.2.0** (the latest release). **X25519MLKEM768 is not supported; the requirement is relaxed here (classical X25519 is used).** |
| ESP32-S3, bare metal | Mbed TLS | The hardware RNG with its physical entropy source enabled | **Mbed TLS 4.2.0** (the latest release). **X25519MLKEM768 is not supported; the requirement is relaxed here (classical X25519 is used).** |

The programmer obtains and installs these. BEES neither downloads, vendors nor builds them.

**Enforced, with no exception (user ruling 2026-11-12):** on hosted platforms an OpenSSL older than 4.1.0 is refused three ways.
`native/tls/silica_bees_tls.c` stops at compile time (`OPENSSL_VERSION_NUMBER < 0x40100000L`); `native/Makefile` refuses to build
the TLS engine and says which OpenSSL it found (`OPENSSL_PREFIX`, default Homebrew's `/opt/homebrew/opt/openssl`, then
`openssl@4`) and that 4.1.0 is the minimum; and a TRUST node's TLS link refuses at run time when the OpenSSL library it loaded is
older (the engine reports `OpenSSL_version_num()`, the link decides). The trials that need TLS fail with the Makefile's message;
they do not skip. BEAM-mode and plaintext (`plaintext_test_only`) TRUST programs do not use the engine. Verified on macOS (Apple
Silicon) with OpenSSL 4.1.0 (23 Oct 2026, Homebrew).

### Linux: getting OpenSSL 4.1.0 (usage note, 2026-11-17)

Distribution packages lag. **Until `apt` (or the package tool your distribution uses) offers OpenSSL 4.1.0 or later, you must build
and install OpenSSL yourself, following OpenSSL's own instructions** (<https://github.com/openssl/openssl/blob/master/INSTALL.md>:
download the 4.1.0 or later release, `./Configure --prefix=/opt/openssl --libdir=lib`, `make`, `make install`). BEES does not do
this for you (it ships and builds no TLS library). Then tell BEES where it is with `OPENSSL_PREFIX` (for example
`make -C native OPENSSL_PREFIX=/opt/openssl`); BEES refuses an OpenSSL older than 4.1.0 at compile time, at build time and at run
time, so a distribution's older package is never used by accident. The runtime also has to find the library: install it where the
loader looks, or set `LD_LIBRARY_PATH=/opt/openssl/lib` (or link statically; `libssl.a` is built too). Check the version with
`/opt/openssl/bin/openssl version`. As of 2026-11-17 Ubuntu 25.10's package is OpenSSL 3.5.3, which is below the minimum.
Verified install on the Linux test machine: OpenSSL 4.1.0 at `/opt/openssl`.

## 2. How the minimum is chosen

- **Hosted platforms (Apple, Linux):** the minimum is **the latest release that supports X25519MLKEM768**, the hybrid post-quantum key exchange that TRUST's TLS profile requires (spike S12, requirement R3). It is not the oldest release that supports it. When a newer release that supports it ships, this page is updated to that release.
- **Boards (NUCLEO-L476RG, ESP32-S3):** the minimum is **the latest Mbed TLS release**, whether or not it supports X25519MLKEM768 (none does yet, see section 3). When a newer Mbed TLS ships, this page is updated to it.

## 3. X25519MLKEM768 support, checked 2026-11-10

Method: read-only web checks of the projects' own release pages and change logs. Parts of some long pages were truncated in the reading tool, so treat a "not found" as "not found in what was read", and re-check before relying on it.

**OpenSSL**
- First release with it: **3.5.0** (8 Apr 2025). Its news lists "Support for PQC algorithms (ML-KEM, ML-DSA and SLH-DSA)" and says "The default TLS keyshares have been changed to offer X25519MLKEM768 and X25519."
- The 4.0 change log carries it forward (default group list still led by X25519MLKEM768 and X25519; further hybrid groups appended).
- **Latest stable release seen: OpenSSL 4.1.0 (23 Oct 2026), so that is the stated minimum.** Releases seen on the 3.x line since 3.5: 3.6.5 and 3.5.9 (security patches, 29 Sep 2026). A 3.5 or 3.6 build supports the group, but is below the stated minimum.
- To confirm on an installed build: `openssl list -kem-algorithms`, and a TLS 1.3 handshake that negotiates X25519MLKEM768.

**Mbed TLS (NUCLEO-L476RG and ESP32-S3)**
- **No Mbed TLS release was found that supports X25519MLKEM768, ML-KEM, or any post-quantum or hybrid key exchange.** Releases read: 4.2.0 (7 Jul 2026), 4.1.1, 4.1.0 (31 Mar 2026), 4.0.0 and the 3.6 line (3.6.7 latest); the TF-PSA-Crypto releases 1.0.0 to 1.2.0 mention none either (1.1.0 adds SHAKE only).
- A question on the Mbed TLS mailing list, "Do we have support for x25519mlkem768 in Mbed TLS?", showed no reply in the archive.
- The latest Mbed TLS release is **4.2.0** (7 Jul 2026), so that is the stated board minimum, but TRUST's X25519MLKEM768 requirement cannot be met on the boards today.

**For now the engine for both boards stays Mbed TLS (user decision 2026-11-10).** wolfSSL was looked at as a library that does support X25519MLKEM768 and was not adopted; its memory fit on the boards is unmeasured.

## 4. Relaxation on the boards (roadmap D41)

**Decided 2026-11-10 (user):** the X25519MLKEM768 requirement is relaxed for the NUCLEO-L476RG and ESP32-S3. They use classical X25519 key exchange in TLS 1.3; every other profile rule is unchanged. Hosted platforms keep X25519MLKEM768.

Open consequences:
1. A hosted node's TRUST profile refuses classical-only peers, so a board cannot connect to a hosted node unless the hosted side accepts X25519 for configured board peers. **Decided 2026-11-16 (D44): per-peer opt-in** (a whitelist entry marked classical-allowed, `classical_allowed_certs` in `bees.config`); built 2026-11-16. Peer trust is by pin and whitelist, and `cacertfile` is optional (D43, built).
2. Revisit the relaxation when Mbed TLS adds the group.
3. Each board's own SDK may pin its own Mbed TLS version (the ESP-IDF on the ESP32-S3 in particular); check the version a programmer actually gets.

## 5. Other requirements

- The Silica compiler generation BEES is verified against is pinned in `tools/silica.generation`.
- BEES builds on macOS and Apple Silicon first; Linux follows Silica's phase 3.

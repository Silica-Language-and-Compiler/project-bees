# native/linux (Linux x86_64 and aarch64, built and tested)

Platform ids `linux_x86_64` and `linux_aarch64` (Raspberry Pi 5; added 2026-11-21), both `BEES_PLATFORM=linux`: the C and `platform.mk` have no
architecture-dependent part (`getrandom(2)`, OpenSSL EVP, GNU sed, `ip route`), so one directory serves both and only the golden names differ.
The text below describes the x86-64 box of 2026-11-18. Built and run on Ubuntu 25.10 (kernel 6.17, glibc, GNU make 4.4.1, cc = gcc
for the C, clang 20.1.8 for the assembly and the link, OpenSSL 4.1.0 at `/opt/openssl`) on 2026-11-18. The goldens
`NAME.linux_x86_64.scout` sit beside the Mac ones.

One file per function of `../bees_platform.h`, plus `platform.mk`:

- `bees_platform_md5.c`: MD5 from OpenSSL's EVP interface (`EVP_Digest` with `EVP_md5()`; the programmer's OpenSSL 4.1.0 or later,
  `OPENSSL_PREFIX`, the same installation the TLS engine uses). Erlang's cookie scheme needs it. An OpenSSL with no MD5 at all
  (a FIPS-only provider set) stops the program with a message: BEAM mode cannot run there.
- `bees_platform_random.c`: the kernel's random source (`getrandom(2)` with flags 0: blocking until the pool is seeded, never
  after; no `/dev/urandom` fallback that could return before seeding; a call interrupted by a signal, `EINTR`, is repeated; a short
  count continues).
- `platform.mk`:

| variable | value | why |
|---|---|---|
| `PLATFORM_CFLAGS` | `-D_GNU_SOURCE` | under `-std=c11` glibc hides POSIX (`getaddrinfo`, `clock_gettime`, `poll`) and `cfmakeraw` (Silica's transport wrappers) |
| `PLATFORM_SRC_CFLAGS` | `-I$(OPENSSL_PREFIX)/include` | the platform sources only (`bees_platform_md5.c`) |
| `PLATFORM_ASFLAGS` | empty | |
| `PLATFORM_LDFLAGS` | `-no-pie -rdynamic -lpthread` | crt1.o calls `main` (no entry flag); the emitted tables hold absolute addresses; the failure report finds a behavior's name with `dladdr` (`.dynsym`) |
| `PLATFORM_NATIVE_SRCS`, `PLATFORM_TRUST_SRCS` | random and MD5; random | as on macOS |
| `PLATFORM_NATIVE_NEEDS_CRYPTO` | `1` | a program that names `libsilica_bees_native.a` is linked with `-lcrypto` (`tools/trial.mk`); the linker keeps it only when the program uses the cookie digest |
| `PLATFORM_RPATH_FLAG` | `-Wl,-rpath,` | `/opt/openssl/lib` is not a system library directory: the programs find `libssl.so.4` and `libcrypto.so.4` through an rpath |
| `PLATFORM_OPENSSL_DIRS` | `/opt/openssl /usr/local/openssl /usr/local` | looked at when `OPENSSL_PREFIX` is not set |
| `PLATFORM_CLANG` | empty (plain `clang`), `cc` when there is no clang | assembler and link driver |
| `PLATFORM_SED_INPLACE` | `sed -i` | GNU sed |
| `PLATFORM_LOCAL_IPV4` | `ip -4 route get 192.0.2.1 ...` | this machine's non-loopback IPv4 address (`trials/n1_addr`); no packet is sent |

There is no linker flag for the main thread's stack on Linux (macOS: `-stack_size`); the kernel takes it from the process limit
(`ulimit -s`, 8 MiB by default), which is enough for every trial but one. `trials/c1_codec_term` builds terms of 60,000 tokens
on the main thread and needs more: its Makefile sets `NEEDS_MAIN_STACK := 1`, and the runner then starts its entry under
`ulimit -s 262144` (`PLATFORM_MAIN_STACK_KB` in `platform.mk`), the 256 MiB the macOS link gives every program. A Linux
application with the same need must be started under a raised limit too.

The Linux flags Silica's own transport wrappers need (`compiler/stdlib/net`) are Silica's concern.

## Building and running

```
make -C native SILICA_ROOT=~/silica OPENSSL_PREFIX=/opt/openssl
SILICA_ROOT=~/silica OPENSSL_PREFIX=/opt/openssl SILICA_COMPILER=~/silica/binaries/silica-compiler-linux_x86_64 \
    tools/run_all_trials.sh --local-only -j 2
```

`SILICA_COMPILER` must name a Linux compiler: the default, `$(SILICA_ROOT)/binaries/silica-compiler`, is the macOS one in a
checkout copied from a Mac. A leaf run by hand takes it on the make command line (`make -C trials/LEAF integrate
SILICA_COMPILER=...`); the runner hands its environment's value on that way. From the Mac, a line in `.bees_build_hosts` does all
of it (`tools/README.md`).

## Setting up a Linux machine without root (2026-11-21)

Done on the Ubuntu 24.04 box (x86-64) and the Raspberry Pi 5 (Debian 13), everything under the home directory, no system package touched:

- **OpenSSL 4.1.0** (`openssl-4.1.0.tar.gz`, SHA-256 `50c17baf54cb008f6ce42d50deb4b28050a1aad711636cabd4b241c7e90cc2fd`, checked against openssl.org and the GitHub release):
  `./Configure --prefix=$HOME/opt/openssl --libdir=lib no-docs "-Wl,-rpath,\$(LIBRPATH)"`, `make`, `make install_sw`. The rpath matters: the trials run
  `$OPENSSL_PREFIX/bin/openssl s_client`, which without it cannot find `libssl.so.4` (the probes then fail quietly). It offers X25519MLKEM768 and Ed25519.
- **Erlang/OTP 29.1.2** (`otp_src_29.1.2.tar.gz`, SHA-256 `c79966661e35fe4aff8ec003db63682e3b33b10b672220d51bf93c0a9244b049`, equal to the GitHub digest) into
  `~/opt/erlang` (`./configure --prefix=$HOME/opt/erlang --without-javac --without-wx --without-odbc`); the box's own OTP 25 is too old for the `n2*` trials.
- **A Python whose `ssl` is built on OpenSSL 4.1.0 or 3.5 or later**, with `cryptography`: the TEMPUS example clients (`c2`, `c3`, `t3`, `t6`) offer
  X25519MLKEM768 through Python's own `ssl`, which the Ubuntu 24.04 system Python (OpenSSL 3.0.13) cannot. On that box Python 3.15.2 was built
  (`--with-openssl=$HOME/opt/openssl --with-openssl-rpath=auto`; 3.13.9 does not compile against OpenSSL 4: `_ssl.c` uses the ASN.1 structures that 4.0 made
  opaque) with zlib 1.3.1 in `~/opt/zlib` (the box has no zlib headers), then `python3 -m pip install cryptography`. The Pi's Debian Python 3.13 sits on OpenSSL 3.5.7 and needs nothing.
- `.bees_build_hosts`: `OPENSSL_PREFIX` is the 4th field; the notes carry `SILICA_COMPILER`, `SILICA_ROOT`, `BEES_COMPILE_JOBS` and
  `BEES_PATH_PREFIX=/home/u/opt/python/bin:/home/u/opt/erlang/bin` (directories put before the remote's `PATH`).

## Goldens

208 goldens were recorded on the Linux box on 2026-11-18 with `silica-999944-linux-x86_64` (the box's
`binaries/silica-compiler-linux_x86_64`; the Mac pin is `silica-999909-macos-applesilicon`), each after its run output was
compared with the Mac golden. 203 are the same as the Mac golden byte for byte, the three-node meshes, the Erlang interchange
(`n2_live`, against the box's own `erl`), TRUST and TRUST over TLS among them. The others differ in these ways only:

| difference | where | why |
|---|---|---|
| `#1  actor_thread_main` for `#1  _actor_thread_main` | every failure report with a call stack (`a02_spawn_supervisor`, `s01_trait_mapping`, `s10_failure_paths`) | Mach-O symbol names carry a leading underscore, ELF's do not |
| `supervisor_acb:  (nil)` for `0x0` | `s10_failure_paths` | glibc prints a null pointer (`%p`) as `(nil)` (`src/shim/bees_reporter.silica` notes it) |
| `agent_type_atom: 27` for `29` | `s01_trait_mapping` (two entries) | the atom's index in the compiler's table; the Linux compiler numbers it differently (the Mac build of the same generation number prints 29) |
| `8000`, `exit=0` for `stack reservation failed`, `exit=71` | `s03_actor_ceiling/ceiling_default_reservation` | the default stack reservation is the machine's memory plus swap of address space per actor: about 3.9 GB on this box, so 8,000 actors fit in the address space; on the Mac the address space ends near 4,000. This golden follows the machine's memory, not only the platform |
| `actor_not_found`, `exit=1` for a second report, `0`, `0`, `exit=0` | `s01_trait_mapping/sd23_cast_from_region_state_child_second_dispatch` | the compiler generation: the Linux compiler shows the behaviour of the Mac pin 999909 (a cast to an ended actor ends the caller); the Mac golden was re-recorded on 2026-11-18 with the newer `silica-999906-macos-applesilicon`, where that cast returns false |

One ordering race showed on the two-core box and is settled by post-processing (`TRUST_LATE_RESULT_LAST`, `tools/silica.mk`; the
goldens of both platforms are unchanged by it): `negative.a` of `n3_trust` and `n4_trust_tls`, see the comment there and the
2026-11-18 section of `development-plan/silica-defects.md`.

## Goldens of the third platform, `linux_aarch64` (2026-11-21)

`NAME.linux_aarch64.scout` goldens exist beside the x86-64 ones, recorded from a run on a Raspberry Pi 5 (Debian 13, kernel 6.18, 4 cores,
about 4 GB, OpenSSL 4.1.0 built into the home directory, compiler `silica-999926-linux-aarch64`). Each was compared first with the
Linux x86-64 golden (after the corrections below) and with the output of the x86-64 run (compiler `silica-999934-linux-x86_64`, Ubuntu 24.04):
every one but `s03_actor_ceiling/ceiling_default_reservation` is the same as its x86-64 twin (the comparison ignores white space and blank
lines, as `make integrate` does), so the two Linux platforms print the same call stacks, atom indexes and fault lines. The rule of
`tools/test_platform_and_ports.py` is: every Mac golden has a golden for each of `linux_x86_64` and `linux_aarch64`, except a trial
declared for other platforms (`trials/LEAF/platforms`, `tools/README.md`) and the entries of `GOLDEN_EXCEPTIONS` there, each with its reason (none since the changes described below).

x86-64 goldens recorded or re-recorded on 2026-11-21 (compiler 999934), each equal to the Mac golden except for the differences of the
table above:

| golden | reason |
|---|---|
| `c3_tempus_bridge/b1`, `b2` | recorded before the Mac's re-recording of 1e9d7f6: the line `clock: the system clock is read` and the order of the first two lines |
| `c4_tempus_boot/dangerous_any` | the message text was `control_test_only on a listen address...` (the option was removed in 1e9d7f6); the Mac text is now printed |
| `c4_tempus_boot/dangerous_clockback` | no golden had been recorded (the Mac's is the same) |
| `s01_trait_mapping/sd23_cast_from_region_state_child_second_dispatch` | the compiler generation: 999934 now behaves like the Mac's 999899 (the cast returns, the failure report with `agent_type_atom: 27` and `actor_thread_main`) where 999944's golden said `actor_not_found` |
| `n5_trust_mux`: `cancel.a`, `interleave.b`, `protocol.a`, `protocol.b`, `shutdown.a`; `n5_trust_mux_tls`: `cancel.a`, `interleave.b`, `protocol.a`, `protocol.b` | recorded for the first time. `protocol.*` equal the Mac's. The others differ from the Mac's in what SD-47 predicts: a request that keeps its worker busy stops the server's connection actor, so a client close during the call is seen after the worker has ended (`session.end reason=client_close` for `client_cancel`, no `pause` line, a slow answer ahead of the quick ones). Identical in every run on x86-64 (4 runs) and on AArch64 |

Recorded later the same day, after three changes to the trials (each output then equal to the Mac golden on both Linux platforms):
`c1_codec_term/main` (the entry is run under `ulimit -s 262144`, see "main thread's stack" above; before, it faulted at "6 large terms and
limits"); every output of `n5_trust_mux` and `n5_trust_mux_tls`, among them `pause.a` and the two `interleave.a` that varied from run to
run and the five that had been recorded with the differences SD-47 predicted (the demo's `slow` now waits by calling a helper actor, so a
request in work no longer stops the server's other actors; `pause` keeps its first pause under the 1000 ms a write of Silica's TCP carrier
waits: N5-multiplexing.md, Q15). `GOLDEN_EXCEPTIONS` is empty.
The three goldens edited by hand on 2026-11-20 and never run (`n3_trust` and `n4_trust_tls` `negative.b`, `n5_trust_mux` `compat_negative.b`) were run on both platforms and match, once the runtime's `link_lost` report of a refused connection's carrier is left out of the output (`STRIP_CARRIER_LINK_LOST`, `tools/silica.mk`).

`s03_actor_ceiling/ceiling_default_reservation` asked for 8,000 actors, and whether that many fit followed the machine's memory and
swap (they fit on the Mac with no swap in use and on a 3.9 GB box, and did not on the Pi 5 or the 14 GB box). It asks for 100,000 since
2026-11-21, which no machine with more than about 1.3 GB of memory and swap can reserve, so the three platforms print the same abort (the
Linux line has no function name after the address).

## Not ported

The `measure` targets (`trials/m4_demo`, `n1_frames`, `n3_trust`, `n4_trust_tls`, `n2_soak`; none is part of `make integrate`) run
programs under BSD `/usr/bin/time -l` and read its report (`tools/run_demo.py`, `run_trust_pair.py`, `soak.py`, `m4_measure.py`).
GNU time takes `-v` and prints kilobytes in another layout; those tools still say `-l`.

# native/linux (Linux x86_64, built and tested)

Platform id `linux_x86_64`, `BEES_PLATFORM=linux`. Built and run on Ubuntu 25.10 (kernel 6.17, glibc, GNU make 4.4.1, cc = gcc
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
(`ulimit -s`, 8 MiB by default), which is enough for every trial.

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

## Not ported

The `measure` targets (`trials/m4_demo`, `n1_frames`, `n3_trust`, `n4_trust_tls`, `n2_soak`; none is part of `make integrate`) run
programs under BSD `/usr/bin/time -l` and read its report (`tools/run_demo.py`, `run_trust_pair.py`, `soak.py`, `m4_measure.py`).
GNU time takes `-v` and prints kilobytes in another layout; those tools still say `-l`.

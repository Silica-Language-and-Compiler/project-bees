# native/linux (placeholder: the Linux x86_64 counterparts, not written yet)

Platform id `linux_x86_64`, `BEES_PLATFORM=linux`. Nothing here builds yet: `native/linux/platform.mk` does not exist, so
`make` on Linux stops with "platform 'linux' has no build yet" (tools/platform.mk). The Linux port is a later task.

What belongs here, one file per function of `../bees_platform.h`, plus `platform.mk`:

- `bees_platform_md5.c`: MD5 from OpenSSL's EVP interface (`EVP_Digest` with `EVP_md5()`, a legacy digest; the programmer's
  OpenSSL 4.1.0 or later at `/opt/openssl` on aalang.org, the same installation the TLS engine uses). Erlang's cookie scheme needs it.
- `bees_platform_random.c`: the kernel's random source (`getrandom(2)`, blocking until the pool is seeded, no `/dev/urandom` fallback
  that could return before seeding; retry on `EINTR`).
- `platform.mk`: `PLATFORM_CFLAGS` (no `-arch`, no `-mmacosx-version-min`), `PLATFORM_ASFLAGS`, `PLATFORM_LDFLAGS` (GNU ld
  flags for entry `main` and the stack size), `PLATFORM_NATIVE_SRCS`, `PLATFORM_TRUST_SRCS`, `PLATFORM_OPENSSL_DIRS`
  (`/opt/openssl`), `PLATFORM_CLANG`, and `PLATFORM_SED_INPLACE := sed -i` (GNU sed; the trial Makefiles still say BSD `sed -i ''`).
- Anything else Linux needs and macOS does not (`-pthread`, `-lrt`), and the Linux socket flags Silica's own wrappers need are
  Silica's concern (compiler/stdlib/net).

Also on the list for that port: the trial Makefiles' `sed -i ''` (BSD), `perl`/`pty` use in `tools/run_trial.py`, the `ipconfig getifaddr`
in `trials/n1_addr`, and the goldens `NAME.linux_x86_64.scout` recorded beside the Mac ones.

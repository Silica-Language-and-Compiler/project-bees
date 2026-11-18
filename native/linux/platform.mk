# Linux on x86_64 (platform id linux_x86_64): the toolchain settings and the facilities native/ and tools/ use that differ
# from the other platforms. Included by native/Makefile and tools/silica.mk when BEES_PLATFORM is linux (tools/platform.mk).
# The values follow Silica's own trials/platform/linux_x86_64.mk.
#
# C compiler flags for every native object (also the TLS self-test). -D_GNU_SOURCE: under -std=c11 glibc hides POSIX
# (getaddrinfo, clock_gettime, poll, strdup) and cfmakeraw, which Silica's transport wrappers call, unless a feature macro asks.
PLATFORM_CFLAGS := -D_GNU_SOURCE
# What the platform's own sources (bees_platform_md5.c) need on top: the headers of the programmer's OpenSSL. Recursive on
# purpose: OPENSSL_PREFIX is settled after this file is read (native/Makefile).
PLATFORM_SRC_CFLAGS = $(if $(OPENSSL_PREFIX),-I$(OPENSSL_PREFIX)/include)
# Assembler and linker flags for the trial programs (Silica's .sams output). crt1.o calls main, so no entry flag. -no-pie:
# the emitted data tables hold absolute addresses and the distribution's compilers default to PIE. -rdynamic: the actor
# failure report names the running behavior with dladdr, which on glibc sees only .dynsym. GNU ld has no flag that sizes the
# main thread's stack (the kernel takes it from the process limit, `ulimit -s`); none of the trials needs more than the default.
PLATFORM_ASFLAGS :=
PLATFORM_LDFLAGS := -no-pie -rdynamic -lpthread
# the platform's sources, compiled into the archives (bees_platform.h): random into both the BEAM-mode and TRUST archives
PLATFORM_NATIVE_SRCS := bees_platform_random.c bees_platform_md5.c
PLATFORM_TRUST_SRCS := bees_platform_random.c
# bees_platform_md5.c calls OpenSSL: a program linked with libsilica_bees_native.a is linked with libcrypto too (tools/trial.mk)
PLATFORM_NATIVE_NEEDS_CRYPTO := 1
# an OpenSSL outside the system's library directories is found at run time through an rpath to its lib directory
PLATFORM_RPATH_FLAG := -Wl,-rpath,
# where a programmer's OpenSSL is looked for when OPENSSL_PREFIX is not set
PLATFORM_OPENSSL_DIRS := /opt/openssl /usr/local/openssl /usr/local
# the system's clang (cc when there is none: GNU as accepts the emitted text too)
PLATFORM_CLANG := $(shell command -v clang >/dev/null 2>&1 || echo cc)
# GNU sed: -i takes no separate argument
PLATFORM_SED_INPLACE := sed -i
# this machine's non-loopback IPv4 address (trials/n1_addr): the source address of the default route; no packet is sent
PLATFORM_LOCAL_IPV4 := ip -4 route get 192.0.2.1 2>/dev/null | sed -n 's/.* src \([0-9.]*\).*/\1/p' | head -n 1

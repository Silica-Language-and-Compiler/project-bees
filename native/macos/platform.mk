# macOS on Apple Silicon (platform id macos_applesilicon): the toolchain settings and the facilities native/ and tools/ use
# that exist only here. Included by native/Makefile and tools/silica.mk when BEES_PLATFORM is macos (tools/platform.mk).
ARCH ?= arm64
MACOS_MIN_VERSION ?= 26.0
# C compiler flags for every native object (also the TLS self-test)
PLATFORM_CFLAGS := -arch $(ARCH) -mmacosx-version-min=$(MACOS_MIN_VERSION)
# assembler and linker flags for the trial programs (Silica's .sams output, entry symbol main, no C runtime)
PLATFORM_ASFLAGS := -mmacosx-version-min=$(MACOS_MIN_VERSION)
PLATFORM_LDFLAGS := -Wl,-e,main -Wl,-macos_version_min,$(MACOS_MIN_VERSION) -Wl,-stack_size,0x10000000
# the platform's sources, compiled into the archives (bees_platform.h): random into both the BEAM-mode and TRUST archives
PLATFORM_NATIVE_SRCS := bees_platform_random.c bees_platform_md5.c
PLATFORM_TRUST_SRCS := bees_platform_random.c
# where a programmer's OpenSSL is looked for when OPENSSL_PREFIX is not set (Homebrew)
PLATFORM_OPENSSL_DIRS := /opt/homebrew/opt/openssl /opt/homebrew/opt/openssl@4
# Homebrew's LLVM clang is preferred when present, as in Silica's own project Makefiles
PLATFORM_CLANG := $(shell test -x /opt/homebrew/opt/llvm/bin/clang && echo /opt/homebrew/opt/llvm/bin/clang)
# BSD sed: -i takes a (here empty) backup suffix
PLATFORM_SED_INPLACE := sed -i ''

# Which platform this build is for. Included by native/Makefile and tools/silica.mk.
#
#   BEES_PLATFORM     the directory under native/ with the platform's C and platform.mk: macos | linux | esp32s3 | nucleo
#   BEES_PLATFORM_ID  the identifier put in every golden's file name before its extension
#                     (NAME.macos_applesilicon.scout); the same spelling Silica uses (test.macos_applesilicon.sout)
#
# Default from uname: Darwin/arm64 -> macos, macos_applesilicon; Linux/x86_64 -> linux, linux_x86_64. Override on the
# command line or in the environment. tools/platform_id.py is the same table for Python.
_BEES_UNAME_S := $(shell uname -s)
_BEES_UNAME_M := $(shell uname -m)
ifeq ($(_BEES_UNAME_S)/$(_BEES_UNAME_M),Darwin/arm64)
BEES_PLATFORM ?= macos
BEES_PLATFORM_ID ?= macos_applesilicon
else ifeq ($(_BEES_UNAME_S)/$(_BEES_UNAME_M),Linux/x86_64)
BEES_PLATFORM ?= linux
BEES_PLATFORM_ID ?= linux_x86_64
endif
ifeq ($(BEES_PLATFORM)$(BEES_PLATFORM_ID),)
$(error no BEES platform for $(_BEES_UNAME_S)/$(_BEES_UNAME_M): set BEES_PLATFORM (macos|linux|esp32s3|nucleo) and BEES_PLATFORM_ID)
endif
BEES_PLATFORM_ID ?= $(error BEES_PLATFORM is $(BEES_PLATFORM) but BEES_PLATFORM_ID is not set (macos_applesilicon, linux_x86_64, ...))
BEES_PLATFORM ?= $(error BEES_PLATFORM_ID is $(BEES_PLATFORM_ID) but BEES_PLATFORM is not set (macos, linux, ...))
export BEES_PLATFORM BEES_PLATFORM_ID

_BEES_PLATFORM_MK := $(BEES_ROOT)/native/$(BEES_PLATFORM)/platform.mk
ifeq ($(wildcard $(_BEES_PLATFORM_MK)),)
$(error platform '$(BEES_PLATFORM)' has no build yet: $(_BEES_PLATFORM_MK) does not exist (see native/$(BEES_PLATFORM)/README.md))
endif
include $(_BEES_PLATFORM_MK)

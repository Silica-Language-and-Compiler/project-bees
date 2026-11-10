# The BEES native edge: one C archive, libsilica_bees_native.a (gap ledger §4), built from src/ into
# dangerous_exposure_source/lib/ where Silica's sidecar link_library expects it; and the language's socket wrappers
# (Silica's compiler/stdlib/net/silica_sockets.c, the Fifi library of the hosted (:tcp) carrier, transport design 6.3),
# built here into the same lib/ as libsilica_sockets.a, the way Silica's own trials build it as a fixture. The wrappers'
# sidecar is reached through the link dangerous_exposure_source/sockets -> the Silica tree's compiler/stdlib/net.
# macOS on Apple Silicon only.
THIS_DIR := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
SILICA_ROOT ?= $(abspath $(THIS_DIR)../../silica)
CC ?= clang
ARCH ?= arm64
MACOS_MIN_VERSION ?= 26.0
CFLAGS := -std=c11 -Wall -Wextra -O2 -arch $(ARCH) -mmacosx-version-min=$(MACOS_MIN_VERSION) \
	-I$(THIS_DIR)dangerous_exposure_source/bees
BUILD := $(THIS_DIR)build
LIB := $(THIS_DIR)dangerous_exposure_source/lib
SRCS := $(wildcard $(THIS_DIR)src/*.c)
OBJS := $(patsubst $(THIS_DIR)src/%.c,$(BUILD)/%.o,$(SRCS))
ARCHIVE := $(LIB)/libsilica_bees_native.a
SOCKETS_SRC := $(SILICA_ROOT)/compiler/stdlib/net/silica_sockets.c
SOCKETS_OBJ := $(BUILD)/silica_sockets.o
SOCKETS_ARCHIVE := $(LIB)/libsilica_sockets.a
SOCKETS_LINK := $(THIS_DIR)dangerous_exposure_source/sockets

.PHONY: all clean
all: $(ARCHIVE) $(SOCKETS_ARCHIVE) $(SOCKETS_LINK)

$(BUILD)/%.o: $(THIS_DIR)src/%.c $(wildcard $(THIS_DIR)dangerous_exposure_source/bees/*.h)
	@mkdir -p $(BUILD)
	$(CC) $(CFLAGS) -c $< -o $@

$(ARCHIVE): $(OBJS)
	@mkdir -p $(LIB)
	ar rcs $@ $^
	@echo "[native] $(ARCHIVE)"

$(SOCKETS_OBJ): $(SOCKETS_SRC)
	@mkdir -p $(BUILD)
	$(CC) $(CFLAGS) -c $< -o $@

$(SOCKETS_ARCHIVE): $(SOCKETS_OBJ)
	@mkdir -p $(LIB)
	ar rcs $@ $^
	@echo "[native] $(SOCKETS_ARCHIVE) (the language's socket wrappers, from $(SOCKETS_SRC))"

$(SOCKETS_LINK):
	ln -sfn "$(SILICA_ROOT)/compiler/stdlib/net" "$@"

clean:
	rm -rf $(BUILD) $(ARCHIVE) $(SOCKETS_ARCHIVE)

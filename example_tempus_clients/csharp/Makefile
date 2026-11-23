# The C# extension for TEMPUS: a client and a node. EXAMPLE ONLY, not for production: see README.md.
#
#   make build   checks the layering (test/layering_check.py: the library and the driver depend on no test code and on
#                no package), then compiles into build/bin/:
#                  BeesTempus/BeesTempus.dll            the extension alone (lib/): what an application references.
#                                                       No Main, no test code
#                  BeesTempusDriver/bees-tempus.dll     the driver (driver/): the command line of the client half and
#                                                       an example application that is a node; `dotnet` runs it
#   make test    compiles the test support (testing/) and the tests (test/) as well, and runs the tests of the client
#                half and of the node half (the second reads the cases that test/model_cases.py writes from the two
#                Python models). make test-build compiles and runs nothing
#   make clean   removes build/
#
# Needs the .NET SDK 11 (dotnet) and OpenSSL 4.1.0 or later (libssl and libcrypto, found at run time: see README.md).
# The node tests also need python3. DOTNET may be given on the command line.
#
# Nothing is fetched. No project references a package; nuget.config beside this file removes every package source, so a
# restore has nowhere to send a request; the variables below turn off the SDK's telemetry and its checks for updates,
# and keep what the SDK writes for itself (its first-run files, its empty package folder) under build/ and out of the
# home directory.
HERE := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
BEES_ROOT := $(abspath $(HERE)/../..)
DOTNET ?= dotnet
export DOTNET_CLI_TELEMETRY_OPTOUT := 1
export DOTNET_NOLOGO := 1
export DOTNET_SKIP_FIRST_TIME_EXPERIENCE := 1
export DOTNET_GENERATE_ASPNET_CERTIFICATE := false
export DOTNET_CLI_WORKLOAD_UPDATE_NOTIFY_DISABLE := 1
export DOTNET_CLI_HOME := $(HERE)/build/home
export NUGET_PACKAGES := $(HERE)/build/home/packages
export NUGET_HTTP_CACHE_PATH := $(HERE)/build/home/http-cache
BIN := $(HERE)/build/bin
LIB_DLL := $(BIN)/BeesTempus/BeesTempus.dll
DRIVER_DLL := $(BIN)/BeesTempusDriver/bees-tempus.dll
TEST_DLL := $(BIN)/BeesTempusTests/bees-tempus-tests.dll
CASES := $(HERE)/build/model_cases.txt
COMMON := $(HERE)/Directory.Build.props $(HERE)/nuget.config
LIB_SRC := $(wildcard $(HERE)/lib/*.cs) $(HERE)/lib/BeesTempus.csproj $(COMMON)
DRIVER_SRC := $(wildcard $(HERE)/driver/*.cs) $(HERE)/driver/BeesTempusDriver.csproj
TEST_SRC := $(wildcard $(HERE)/test/*.cs $(HERE)/testing/*.cs) $(HERE)/test/BeesTempusTests.csproj $(HERE)/testing/BeesTempusTesting.csproj
# one build of the extension at a time on this machine (build_lock.py says why)
BUILD = python3 "$(HERE)/build_lock.py" "$(HERE)/build/.build.lock" "$(DOTNET)" build --nologo -v quiet '-clp:ErrorsOnly;NoSummary' --configfile "$(HERE)/nuget.config"

.PHONY: build test-build test clean tools layering
build: layering $(DRIVER_DLL)
test-build: layering $(TEST_DLL)
tools:
	@command -v "$(DOTNET)" > /dev/null && "$(DOTNET)" --version > /dev/null 2>&1 || { echo "FAIL: the .NET SDK (dotnet) is not installed or not on PATH; see example_tempus_clients/csharp/README.md"; exit 1; }
	@v=$$("$(DOTNET)" --version 2> /dev/null | sed 's/\..*//'); case "$$v" in ''|*[!0-9]*) v=0;; esac; \
	[ "$$v" -ge 11 ] || { echo "FAIL: the .NET SDK ($(DOTNET)) is release $$v; release 11 is what this extension was built with; see example_tempus_clients/csharp/README.md"; exit 1; }
layering:
	@python3 "$(HERE)/test/layering_check.py" "$(HERE)" > /dev/null || { python3 "$(HERE)/test/layering_check.py" "$(HERE)"; exit 1; }
$(DRIVER_DLL): $(LIB_SRC) $(DRIVER_SRC) | tools
	@$(BUILD) "$(HERE)/driver/BeesTempusDriver.csproj" && touch "$@"
$(LIB_DLL): $(DRIVER_DLL)
$(TEST_DLL): $(LIB_SRC) $(TEST_SRC) | tools
	@$(BUILD) "$(HERE)/test/BeesTempusTests.csproj" && touch "$@"
$(CASES): $(HERE)/test/model_cases.py $(wildcard $(BEES_ROOT)/tools/bees_tempus_*model.py $(BEES_ROOT)/tools/test_bees_tempus_view.py $(BEES_ROOT)/tools/test_bees_tempus_store.py)
	@mkdir -p "$(HERE)/build"
	@python3 "$(HERE)/test/model_cases.py" "$@"
test: layering $(TEST_DLL) $(CASES)
	@python3 "$(HERE)/test/layering_check.py" "$(HERE)"
	@cd "$(BEES_ROOT)" && "$(DOTNET)" "$(TEST_DLL)" client "$(BEES_ROOT)"
	@cd "$(BEES_ROOT)" && "$(DOTNET)" "$(TEST_DLL)" node "$(BEES_ROOT)" "$(CASES)"
clean:
	@rm -rf "$(HERE)/build"

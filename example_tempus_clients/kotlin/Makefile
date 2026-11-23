# The Kotlin extension for TEMPUS: a client and a node. EXAMPLE ONLY, not for production: see README.md.
#
#   make build   compiles two files into build/:
#                  bees-tempus.jar         the extension alone (lib/*.kt): what an application puts on its class path,
#                                          beside the Kotlin standard library. No main function, no test code
#                  bees-tempus-client.jar  the extension, the driver application (driver/Main.kt) and the Kotlin
#                                          runtime: java -jar runs it
#   make gossip  build, then four instances of the driver as one TEMPUS network on this machine
#                (../gossip/gossip_run.py run kotlin)
#   make test    compiles the extension, the driver and test/*.kt into build/bees-tempus-client-test.jar and runs the
#                tests of the client (test/TestMain.kt), of the gossip of lib/Gossip.kt (test/GossipTest.kt) and of the
#                node (test/NodeTestMain.kt, which reads the cases that test/model_cases.py writes from the two Python
#                models). make test-build compiles and runs nothing
#   make clean   removes build/
#
# Needs kotlinc and a JDK of release 27 or later: its TLS can offer the key exchange group X25519MLKEM768 (OpenJDK 25
# cannot). The node tests also need python3. KOTLINC and JAVA may be given on the command line.
HERE := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
BEES_ROOT := $(abspath $(HERE)/../..)
KOTLINC ?= kotlinc
JAVA ?= java
LIB_JAR := $(HERE)/build/bees-tempus.jar
JAR := $(HERE)/build/bees-tempus-client.jar
TEST_JAR := $(HERE)/build/bees-tempus-client-test.jar
CASES := $(HERE)/build/model_cases.txt
LIB_SRC := $(wildcard $(HERE)/lib/*.kt)
SRC := $(LIB_SRC) $(wildcard $(HERE)/driver/*.kt)
TEST_SRC := $(wildcard $(HERE)/test/*.kt)
# kotlinc prints warnings about the JDK's own restricted methods on a new JDK; they are not about this code
KFLAGS := -nowarn

.PHONY: build test-build test clean tools gossip
build: $(LIB_JAR) $(JAR)
test-build: $(TEST_JAR)
tools:
	@command -v "$(KOTLINC)" > /dev/null || { echo "FAIL: the Kotlin compiler (kotlinc) is not installed or not on PATH; see example_tempus_clients/kotlin/README.md"; exit 1; }
	@command -v "$(JAVA)" > /dev/null && "$(JAVA)" -version > /dev/null 2>&1 || { echo "FAIL: no Java runtime (java) is installed or on PATH; see example_tempus_clients/kotlin/README.md"; exit 1; }
	@v=$$("$(JAVA)" -XshowSettings:properties -version 2>&1 | sed -n 's/^ *java.specification.version = //p'); case "$$v" in ''|*[!0-9]*) v=0;; esac; \
	[ "$$v" -ge 27 ] || { echo "FAIL: the Java runtime ($(JAVA)) is release $$v; release 27 or later is needed (its TLS offers X25519MLKEM768); see example_tempus_clients/kotlin/README.md"; exit 1; }
$(LIB_JAR): $(LIB_SRC) | tools
	@mkdir -p "$(HERE)/build"
	"$(KOTLINC)" $(KFLAGS) -d "$@" $(LIB_SRC)
$(JAR): $(SRC) | tools
	@mkdir -p "$(HERE)/build"
	"$(KOTLINC)" $(KFLAGS) -include-runtime -d "$@" $(SRC)
$(TEST_JAR): $(SRC) $(TEST_SRC) | tools
	@mkdir -p "$(HERE)/build"
	"$(KOTLINC)" $(KFLAGS) -include-runtime -d "$@" $(SRC) $(TEST_SRC)
$(CASES): $(HERE)/test/model_cases.py $(wildcard $(BEES_ROOT)/tools/bees_tempus_*model.py $(BEES_ROOT)/tools/test_bees_tempus_view.py $(BEES_ROOT)/tools/test_bees_tempus_store.py)
	@mkdir -p "$(HERE)/build"
	@python3 "$(HERE)/test/model_cases.py" "$@"
test: $(TEST_JAR) $(CASES)
	@cd "$(BEES_ROOT)" && "$(JAVA)" -cp "$(TEST_JAR)" bees.tempus.test.TestMainKt "$(BEES_ROOT)"
	@cd "$(BEES_ROOT)" && "$(JAVA)" -cp "$(TEST_JAR)" bees.tempus.test.GossipTestKt "$(BEES_ROOT)"
	@cd "$(BEES_ROOT)" && "$(JAVA)" -cp "$(TEST_JAR)" bees.tempus.test.NodeTestMainKt "$(BEES_ROOT)" "$(CASES)"
gossip: build
	@JAVA="$(JAVA)" python3 "$(HERE)/../gossip/gossip_run.py" run kotlin
clean:
	@rm -rf "$(HERE)/build"

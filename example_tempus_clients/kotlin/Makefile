# The Kotlin example TEMPUS client. EXAMPLE ONLY, not for production: see README.md.
#
#   make build   compiles src/*.kt into build/bees-tempus-client.jar (the client and the Kotlin runtime it needs)
#   make test    compiles the client and test/*.kt into build/bees-tempus-client-test.jar and runs the tests
#                (make test-build compiles that file and runs nothing)
#   make clean   removes build/
#
# Needs kotlinc and a JDK whose TLS can offer the key exchange group X25519MLKEM768 (OpenJDK 27 can; OpenJDK 25
# cannot). KOTLINC and JAVA may be given on the command line.
HERE := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
BEES_ROOT := $(abspath $(HERE)/../..)
KOTLINC ?= kotlinc
JAVA ?= java
JAR := $(HERE)/build/bees-tempus-client.jar
TEST_JAR := $(HERE)/build/bees-tempus-client-test.jar
SRC := $(wildcard $(HERE)/src/*.kt)
TEST_SRC := $(wildcard $(HERE)/test/*.kt)
# kotlinc prints warnings about the JDK's own restricted methods on a new JDK; they are not about this code
KFLAGS := -nowarn -include-runtime

.PHONY: build test-build test clean tools
build: $(JAR)
test-build: $(TEST_JAR)
tools:
	@command -v "$(KOTLINC)" > /dev/null || { echo "FAIL: the Kotlin compiler (kotlinc) is not installed or not on PATH; see example_tempus_clients/kotlin/README.md"; exit 1; }
	@command -v "$(JAVA)" > /dev/null && "$(JAVA)" -version > /dev/null 2>&1 || { echo "FAIL: no Java runtime (java) is installed or on PATH; see example_tempus_clients/kotlin/README.md"; exit 1; }
$(JAR): $(SRC) | tools
	@mkdir -p "$(HERE)/build"
	"$(KOTLINC)" $(KFLAGS) -d "$@" $(SRC)
$(TEST_JAR): $(SRC) $(TEST_SRC) | tools
	@mkdir -p "$(HERE)/build"
	"$(KOTLINC)" $(KFLAGS) -d "$@" $(SRC) $(TEST_SRC)
test: $(TEST_JAR)
	@cd "$(BEES_ROOT)" && "$(JAVA)" -cp "$(TEST_JAR)" bees.tempus.test.TestMainKt "$(BEES_ROOT)"
clean:
	@rm -rf "$(HERE)/build"

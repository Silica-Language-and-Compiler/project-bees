# The C# extension for TEMPUS

The C# extension lets a program written in C#, or in another language of .NET, take part in a TEMPUS network. TEMPUS
is the gossip membership mode of BEES: nodes find each other by exchanging signed records over mutually authenticated
TLS 1.3 connections. An extension is code in a language other than Silica that lets an application in that language
take part. The extension has two halves. The client half connects to a node as an ordinary peer and makes one request,
or listens and answers one. The node half makes the application a member of the network: a node, with stores of its
own, that joins, shuffles, answers and admits as the Silica node of `src/tempus` does.

It is a usable example, to be used carefully, as the directory's [README](../README.md) says of every extension. The
section "What stands between this and production use" below says what has and what has not been done, and so what
care means here. Everything it was checked with uses keys, certificates and tokens made from fixed seeds that are written in
this repository. The documents [What do I need to do to write a TEMPUS client?](../writing-a-tempus-client.md) and
[What do I need to do to write a TEMPUS node?](../writing-a-tempus-node.md) say what a client and a node have to do,
in a form that does not depend on any one language.

There is one gossip implementation here: the node half, with the client half beneath it, as in every extension of
this directory. The lighter peer is the driver's `gossip` command (the section "The driver's `gossip` command" below):
a thin command over that same node, not a second implementation.

## What it is

It uses the .NET base library and one library that is not part of .NET: OpenSSL, version 4.1.0 or later, which it
calls for TLS, for Ed25519 signatures, for SHA-512 and for reading certificates. It calls OpenSSL as a C library
through P/Invoke, which is the foreign function interface of .NET. The extension contains no C code and references no
NuGet package. The section "Why not SslStream" says why .NET's own TLS could not be used.

The layout is the one every extension in this directory has:

- `lib/` is the extension: one class library project, `BeesTempus.csproj`, with no `Main` and no test code.
  - `Etf.cs` writes and reads the part of the Erlang external term format that the frames use.
  - `Frames.cs` holds the messages, with every bound on their fields, and the structure of a token.
  - `OpenSsl.cs` declares the OpenSSL functions that are called, and finds the two libraries.
  - `Crypto.cs` holds Ed25519, SHA-512, random bytes and certificates.
  - `Admission.cs` holds the identity (key, certificate, token, listen address) and the client half's verifier.
  - `Tls.cs` holds the TLS settings and one TLS connection with one deadline.
  - `Client.cs` holds `Client.Dial`, `Listener`, and `Outcome`, the plain value that says what happened on a
    connection.
  - `View.cs` holds the view of one store and the steps of one store, as pure functions and one small class.
  - `Clock.cs` holds what one reading of the clock does to a node, as a pure function, and the machine's clock.
  - `Config.cs` holds a node's configuration and its refusals.
  - `Node.cs` and `NodeConn.cs` hold the node and one connection of a node.
- `driver/` is a program over the library: the command line of the client half, the `gossip` command that runs a
  node for the gossip example in `../gossip`, and an example application that is a node. It references the library
  and nothing else.
- `testing/` is test support, in a project of its own, `BeesTempusTesting.csproj`: keys from fixed seeds, a function
  that makes tokens, and a clock, timers and draws that a test sets by hand. The library and the driver do not
  reference it, and an application must not.
- `test/` holds the tests, a plain console program with no test framework, the tool `model_cases.py` that writes the
  cases the store tests read, and `layering_check.py`.

`build_lock.py`, beside this file, lets one build of the extension run at a time on a machine. Several trials build
the extension into the same `build/` directory, and `dotnet build` does not expect a second build of the same project
at the same moment.

`test/layering_check.py` is run by every build. It fails the build when the library or the driver references the
test support project or any package, when a source file under `lib/` or `driver/` names the test support's namespace,
or when one holds code that only a test has a use for (a token maker, or the test-only frames `tick` and `clock` as
kinds to send or to serve). The extension does not contain the two test-only frames or their answer, `done`. To the
client half they are frames of no kind, and a node refuses them as it refuses any frame that is not a request.

## What an application depends on

An application references one project, `lib/BeesTempus.csproj`, or the file that project builds,
`build/bin/BeesTempus/BeesTempus.dll`. It needs .NET 11 and OpenSSL 4.1.0 or later on the machine it runs on. It
needs nothing else. Everything is in the namespace `Bees.Tempus`. What an application uses of it: `Identity`,
`SigningKey`, `Certificate`, `TempusConfig` with `StoreConfig` and `SentinelAddress`, `TempusNode`, `NodeEvent`,
`NodeEnvironment`, `ConfigRefused`, and for the client half `Client.Dial`, `Listener`, `Verifier`, `Settings`,
`Request` and `Outcome`. The declarations marked `internal` are not for an application.

## What must be installed

Two things, and nothing else. No package is downloaded.

1. The .NET SDK, release 11. Version 11.0.100 was used, installed with Homebrew: `brew install dotnet`. It supplies
   the compiler, the build tool (`dotnet build`) and the runtime (`dotnet NAME.dll`).
2. OpenSSL 4.1.0 or later. Version 4.1.0 was used, installed with Homebrew: `brew install openssl@4`. The extension
   refuses an older one when it first makes a TLS context, and says which version it found.

The extension looks for `libssl` and `libcrypto` in this order: the directory an application wrote into
`OpenSsl.LibraryDirectory` before its first use of the extension; the directory in the environment variable
`BEES_OPENSSL_LIB`; `/opt/homebrew/opt/openssl@4/lib` and `/usr/local/opt/openssl@4/lib`, which are where Homebrew
puts it on a Mac; and then the system's own search for `libssl.4.dylib` and `libcrypto.4.dylib`, or `libssl.so.4` and
`libcrypto.so.4`. When neither is found it says which paths it tried.

The tests and the trials also read files of this repository (the recorded output of other trials, and the TEST ONLY
certificates in `trials/t5_tempus_tls/certs`), and the trials need what every TEMPUS trial needs: the Silica compiler,
OpenSSL for the Silica nodes, and Python 3 with the `cryptography` package for the Python test support.

## Building with no network

No project here references a package, so a build needs nothing from the network. Four things make sure that no
request is made, and the Makefile sets all of them:

- `nuget.config` beside this file removes every package source and every fallback folder, and the build is given it
  with `--configfile`. A restore then has no address to send a request to.
- `Directory.Build.props` sets `NuGetAudit` to false, because the audit asks a package source for its data, and
  `UseAppHost` to false, so that a program is run as `dotnet NAME.dll` and no host executable has to be found.
- The environment variables `DOTNET_CLI_TELEMETRY_OPTOUT=1` and `DOTNET_CLI_WORKLOAD_UPDATE_NOTIFY_DISABLE=1` turn
  off the SDK's telemetry and its check for workload updates. `DOTNET_NOLOGO=1`, `DOTNET_SKIP_FIRST_TIME_EXPERIENCE=1`
  and `DOTNET_GENERATE_ASPNET_CERTIFICATE=false` turn off what the SDK does the first time it is run.
- `DOTNET_CLI_HOME`, `NUGET_PACKAGES` and `NUGET_HTTP_CACHE_PATH` point under `build/`, so that what the SDK writes
  for itself stays in this directory and out of the home directory.

`dotnet build` and the restore inside it were run in this way on a machine that had no NuGet folder at all, and they
succeeded. What was not done: the network was not watched while they ran. That no request is made rests on there
being no package source and on the settings above.

## How to build and run

From this directory:

```
make build     # checks the layering, then builds the library and the driver into build/bin/
make test      # builds the test support and the tests as well, and runs them
make clean
```

`make build` runs `dotnet build driver/BeesTempusDriver.csproj`, which builds the library first. The driver is
`build/bin/BeesTempusDriver/bees-tempus.dll`. It prints its usage when it is run with no arguments. Every option is
required unless the usage says it is optional, because none of the values has a default: the time bound of a
connection, the clock difference allowed and the shuffle length belong to the network the client joins.

```
dotnet build/bin/BeesTempusDriver/bees-tempus.dll dial 127.0.0.1:25401 \
    --cert CERT.pem --key KEY.pem --token TOKEN.hex --addr 127.0.0.1:25403 \
    --producer-pub HEX --kid k1 --skew 10 --timeout-ms 5000 --shuffle-length 3 \
    sample tempus_edge 3
```

- `--cert` and `--key` are the client's certificate, self-signed over its Ed25519 key, and that key as an unencrypted
  PKCS#8 PEM file.
- `--token` is a file that holds the token from the producer as hex digits.
- `--whitelist-cert FILE` may be given any number of times. Each names the certificate of a bridge or a sentinel the
  client accepts. With none, the client accepts no bridge and no sentinel.
- `--now SECONDS` replaces the system clock for the token checks. It exists for the trials, whose tokens are valid at
  fixed times. Without it the client reads the system clock.
- The requests are `sample STORE N`, `shuffle STORE` (which offers the client's own entry at age 0), and
  `call REQ_ID MODULE FUNCTION [INT]...` and `cast REQ_ID MODULE FUNCTION [INT]...` to a bridge.
- `listen HOST:PORT ... --count N` accepts N connections and answers a sample or a shuffle with the client's own
  entry, or with no entries when the store is of another type than the client's token.
- `read-hex HEX SHUFFLE_LENGTH` reads one frame body and says what it is.
- `node KEY=VALUE ...` is the example application that is a node. The usage lists its keys, which are those of the
  configuration below. It prints the node's lines and what the application is told, and ends when its standard input
  says `exit` or ends.
- `gossip OPTIONS` is the command the gossip example runs. The next section describes it.

The outcome of a connection is printed as one line, for example
`reply sample_reply entries=[0:1fae2ad7f75a0ded] store=tempus_edge peer=b19edad2958934e1 typ=tempus_edge`. The first
word is one of `reply`, `served`, `key_rotated`, `refused` (this client refused the peer; the reason follows),
`closed` (the connection closed with no reply, which is all that a refusal by the peer ever shows, and is also the
ordinary end of a `cast`), `timeout`, `tls_failed` and `unreachable`.

## The driver's `gossip` command

`dotnet build/bin/BeesTempusDriver/bees-tempus.dll gossip OPTIONS` makes the program a member of a TEMPUS network.
It is what the gossip example in `../gossip` runs for its `csharp`, `mixed` and `trio` networks, with the options and
the output that the Python, Kotlin, Swift and Rust drivers' `gossip` commands have. It is a thin command over the
library's node (`TempusNode`): it builds a `TempusConfig` and an `Identity` from its options, starts the node, and
prints. There is no second gossip implementation behind it.

- The options are those of `dial` without `--shuffle-length`, and `--store-edge`, `--store-bridge` and
  `--store-sentinel` (each `CAPACITY:SHUFFLE_LENGTH:TICK_MS`), `--join-retry-ms FIRST:MAX`, `--sentinel HOST:PORT`
  (any number; none for a first sentinel) and, optionally, `--run-ms MS`. `--addr` is also where the node listens.
- The role is the type the token carries. The skew is `--skew` times 1000 milliseconds.
- The `--whitelist-cert` files become the whitelist, named `cert1`, `cert2` and so on in their order, and every
  `--sentinel` names the first of them. The command line does not say which certificate is which sentinel's, and the
  node does not need it: it requires that a sentinel's name is an entry of the whitelist, and admits a sentinel whose
  certificate is any entry. With a `--sentinel` and no `--whitelist-cert` the node refuses to start.
- `--now SECONDS` gives the node one fixed reading as its clock, through a `NodeEnvironment` with the machine's timers
  and random source. The library takes such an environment on any address; the command takes `--now` on a loopback
  `--addr` only, which is the rule the Silica node keeps for a clock its caller supplies. Without `--now` the node
  reads the machine's clock (`NodeEnvironment.System`).
- It prints the node's own lines and its audit lines as the node writes them, `learned STORE ID16 HOST:PORT` the first
  time a peer appears in a view the node reports, and a line `told: ...` for what the application is told. It runs
  until SIGINT or SIGTERM, or for `--run-ms`, and then prints `known STORE: ID16 ...` for each store, every peer it ever
  learned of, sorted.

A node requires values the command line does not carry. The command states them itself, as the constants `Gossip*` in
`driver/Program.cs`: at most 16 accepted connections at once (`inflightMax`), a clock that goes back is followed
(`clockBack` follow, so no `clockBackLimitS`), a reading that fails after a good one leaves the node going on with its
last reading (`clockFail` continue), and the clock is read every 1000 ms (`clockReadMs`). These are the driver's
choices for the gossip example, the same as the other drivers make. They are not defaults of the library, which has
none, and they are not recommendations: an application decides each of them for its own network.

The key is read by the library as it is for `dial` (`Identity.Load`, an unencrypted PKCS#8 PEM file); no OpenSSL
function was added for this command.

## Why not SslStream

`SslStream` is the TLS of .NET. On macOS it is Apple's TLS, and the cryptography of .NET is Apple's as well. Each of
the following was tried on 2026-11-23 with .NET 11.0.100 on macOS 26 against a running Silica TEMPUS node, and none
of it can be used.

- The identity cannot be loaded. `X509Certificate2.CreateFromPemFile` with a certificate and a key that are Ed25519
  throws `CryptographicException: '1.3.101.112' is not a known key algorithm.` (1.3.101.112 is the object identifier
  of Ed25519.) The same call succeeds for a P-256 key. The certificate alone, without its key, loads. So a client
  cannot present its certificate, which a TEMPUS node requires.
- With its default engine, `SslStream` cannot be asked for TLS 1.3 alone: `AuthenticateAsClient` throws
  `AuthenticationException` whose inner exception is `PlatformNotSupportedException: The requested security protocol
  is not supported.` The node sees the connection close during the handshake.
- With Apple's Network framework as the engine, which is chosen by setting the environment variable
  `DOTNET_SYSTEM_NET_SECURITY_USENETWORKFRAMEWORK` to 1, the handshake is attempted and fails with
  `NetworkFrameworkException: Network Framework error -9824 in domain TLS`. The node writes `tls_handshake_failed`.
  This agrees with what the Swift extension found: the Network framework does not offer Ed25519 as a signature
  algorithm in its handshake.
- .NET 11 has no Ed25519 type in its base library, so tokens and proofs could not be signed or verified with it, and
  `MLKem.IsSupported` is false on this machine. `SHA512` works, and the tests check that it agrees with OpenSSL's.

So the extension calls OpenSSL for all of it. The Ed25519 signatures OpenSSL makes are the same bytes on every call
for the same key and message, so the tokens and proofs made in the tests can be compared byte for byte with those of
the other extensions.

How OpenSSL is called. `lib/OpenSsl.cs` declares each function with `DllImport` and resolves the two library names
itself (`NativeLibrary.SetDllImportResolver`). Several OpenSSL settings are C macros and not functions; the file calls
what they expand to, `SSL_CTX_ctrl` with the macro's number: 123 and 124 for the lowest and highest TLS version, 92
for the list of key exchange groups, 98 and 102 for the lists of signature algorithms. OpenSSL calls back into the
extension in two places, the choice of the application protocol and the acceptance of the peer's certificate chain;
both are static methods marked `UnmanagedCallersOnly`. OpenSSL never touches the TCP connection. The connection is a
`System.Net.Sockets.Socket`; the TLS engine reads and writes two buffers in memory, and `lib/Tls.cs` moves bytes
between them and the `Socket`. That keeps every wait under the one deadline of the connection.

## A node

A node of the extension is an edge or a sentinel. An edge is an ordinary member. A sentinel is a member that others
join through; its certificate is listed in the other nodes' tempus whitelist. The third type, the bridge, is not
provided: a bridge is also a member of a TRUST network, and the extension has no TRUST side. A configuration whose
role is `bridge` is refused. The section "What a node does not cover" says what a bridge would need.

### How an application starts a node

The application supplies three things: its identity, its configuration, and a function that is told what happens.

.NET cannot make or load an Ed25519 key on macOS, so the extension offers both. `SigningKey.FromSeed(bytes)` makes
the key of a 32-byte seed and `SigningKey.FromPem(text)` reads an unencrypted PKCS#8 PEM text.
`Certificate.SelfSign(key, commonName, serial, notBefore, notAfter)` makes the certificate that is self-signed over a
key, and `Certificate.FromPem(text)` reads one. `Identity.Load(certificateFile, keyFile, token, address)` reads both
from files. `token` is the bytes the producer gave the application. `address` is the text `host:port` that other
nodes dial; it is what the node advertises. The private key stays inside the `SigningKey` object, which hands it to
OpenSSL only. The extension never writes it to a line or a frame, and has no call that returns its bytes.

```csharp
using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using System.Threading;
using Bees.Tempus;

static class Example
{
    static void Main()
    {
        byte[] token = File.ReadAllBytes("token.bin");               // from the producer; the application fetched it
        var me = Identity.Load("node.pem", "node-key.pem", token, "192.0.2.10:7000");
        var sentinel = Certificate.FromPem(File.ReadAllText("sentinel.pem"));
        var config = new TempusConfig(
            role: "edge", listenAddress: "0.0.0.0", port: 7000,
            sentinels: new[] { new SentinelAddress("192.0.2.1", 7000, "s1") },
            edge: new StoreConfig(20, 5, 10000), bridge: new StoreConfig(8, 3, 30000), sentinel: new StoreConfig(8, 3, 30000),
            producerKid: Encoding.UTF8.GetBytes("k1"), producerKey: File.ReadAllBytes("producer.pub"),
            whitelist: new[] { new KeyValuePair<string, Certificate>("s1", sentinel) },
            shuffleTimeoutMs: 5000, inflightMax: 16, clockSkewMs: 30000,
            clockBack: "follow", clockBackLimitS: null, clockFail: "pause", clockReadMs: 1000,
            joinRetryInitialMs: 1000, joinRetryMaxMs: 60000);
        var node = TempusNode.Start(config, me, (n, e) =>
        {
            switch (e)
            {
                case NodeEvent.OwnTokenInvalid x: /* fetch a new token, then n.SetToken(bytes) */ break;
                case NodeEvent.KeyRotated x: /* the producer has a new key: fetch a token under it, then n.SetToken(bytes) */ break;
                case NodeEvent.ClockUnreadable x: Console.Error.WriteLine(x.What); break;
                case NodeEvent.Stopped x: Console.Error.WriteLine(x.Why); break;       // only a new node ends this
                case NodeEvent.ListenFailed x: Console.Error.WriteLine(x.Why); break;
                case NodeEvent.ViewChanged x: break;
            }
        });
        Thread.Sleep(Timeout.Infinite);                              // the node runs on its own threads
    }
}
```

The numbers in the example are an example's; none of them is a default. The constructor of `TempusConfig` has no
optional parameter, so the compiler refuses a call that leaves one out. `TempusNode.Start` throws `ConfigRefused` and
writes the line `tempus: boot refused: WHY` when a value is outside its bounds or the identity does not fit; nothing
is started then. The node reads the machine's clock itself: no call passes it the time of day.

A running node takes these calls from its application. `SetToken(bytes)` passes a new token; the application
refreshes its token at half the token's lifetime. `SetProducerKey(kid, key)` passes a new producer key.
`Sample(store, n)` gives up to `n` entries of one of the node's stores, drawn at random, which is how an application
finds a bridge to call. `ViewOf(store)` gives the whole view of one store. `Dispose()` stops the node.

### The configuration

The parameters of `TempusConfig` are the keys of the `tempus` section of `bees.config` (design section 11) in the
casing of C#, with the same meanings and the same bounds. A value outside its bounds is refused with the text
`tools/bees_tempus_conf.py` uses, without the file's name and line, which a value does not have.

| Parameter | Bounds | Meaning |
| --- | --- | --- |
| `role` | `edge`, `sentinel` (`bridge` is refused) | the node's own type, and the type its token must carry |
| `listenAddress`, `port` | an IPv4 literal or a host name; 1 to 65535 | where the node listens |
| `sentinels` | 1 to 16; empty only for a sentinel that is the first | each a host, a port, and the name of its certificate in `whitelist` |
| `edge`, `bridge`, `sentinel` | capacity 1 to 256; shuffle length 1 to 64 and at most the capacity; tick 100 to 3600000 ms | the three stores |
| `producerKid`, `producerKey` | 1 to 64 bytes; 32 bytes | the one current producer key |
| `whitelist` | | by name, the certificate of each bridge and sentinel the node accepts, in the order the audit lines count entries in |
| `shuffleTimeoutMs` | 100 to 60000 | one bound for a whole connection, from the dial or the accept to the close |
| `inflightMax` | 1 to 64 | accepted connections at once |
| `clockSkewMs` | 0 to 300000 | the clock difference allowed when a token's time is judged |
| `clockBack` | `follow`, `hold`, `stop` | what a reading of the clock earlier than the node's time does |
| `clockBackLimitS` | 0 to 86400 under `stop`; `null` under the other two, where a number is refused | the greatest step back that `stop` still follows |
| `clockFail` | `continue`, `pause` | what a reading that fails after a good one does |
| `clockReadMs` | 100 to 60000 | how often the clock is read |
| `joinRetryInitialMs`, `joinRetryMaxMs` | 100 to 3600000, the second not below the first | the delays between attempts to join |

Four things differ from the section, and each is a choice the project owner has not ruled on. The Kotlin extension
made the same four.

- The keys `edge_spec`, `bridge_spec` and `sentinel_spec` are absent. They say what an admitted peer may call, and
  only a bridge serves calls.
- `identity_keyfile`, `identity_certfile`, `whitelist_file` and `whitelist_cert_dir` are not parameters: the
  application passes an `Identity` and the certificates themselves. The address the node advertises is the
  `Identity`'s, which the section does not name.
- A sentinel whose certificate name is not in `whitelist` is refused. The Silica tools do not check this.
- `clockSkewMs` is turned into the whole seconds the node compares tokens with by dividing by 1000 and dropping the
  rest. How the Silica side converts it is not built yet.

The Silica tool refuses a listen address other than `127.0.0.1`, `localhost` and `0.0.0.0` as not built yet. That is
a limit of the Silica carrier, not a rule, and the extension listens on any IPv4 address or host name that .NET
binds. The Silica node refuses an externally driven node on an address that is not loopback; the extension has no
such node, so it has no such refusal.

### What the application is told

The function is called on the node's own thread, in order, and must return soon. It may call the node's methods.

| Event | When | The Silica node's message |
| --- | --- | --- |
| `OwnTokenInvalid` with `Why` | a tick found the node's own token not valid any more; ticking has stopped until `SetToken` | 80 |
| `KeyRotated` with `Kid` and `Dialed` | a peer answered the node's advert with `key_rotated` and named its current kid | 81, when the node had dialed |
| `ClockUnreadable` with `What` | the clock could not be read; told once for each failure, not once for each reading | 86 |
| `Stopped` with `Why` | the clock went back by more than `clockBackLimitS` under `stop`: the node admits nobody and does not tick, for good | 87 |
| `ListenFailed` with `Why` | the node could not listen on its address | none: the Silica node writes a line |
| `ViewChanged` with `Store` and `Entries` | after each step that may have changed a store: a join's answer, a tick, an answered shuffle, an insert | none: a Silica test node writes a line |

One difference is deliberate and not ruled. The Silica node tells its application of `key_rotated` only when the node
itself dialed; when the peer dialed, it writes the audit line and tells nobody. The extension tells its application
in both cases, because the design says that the node reports `key_rotated` to its application, and the event's
`Dialed` says which case it is. The Python, Swift and Kotlin extensions also tell the application in both cases.

The node writes the Silica node's lines, word for word: the boot lines, the `join:`, `tick` and `clock:` lines, and
one `[tempus audit]` line for each admission, refusal and close. They go to the standard output, or to the function
given to `NodeEnvironment.System(log)`. No line holds a private key, a token or a time of day.

### How it is built inside

All of the node's state has one owner: one thread, the node thread. The state is the three stores, the clock state,
the node's token and producer key, the counts of connections, and the join. The node thread takes one action after
another from a queue that only it reads. Everything else puts an action on that queue: the timers, the acceptor, each
connection and the application's calls. Each connection runs on a thread of its own with a copy of the values it
needs (the node's identity and token, the kid, the producer key, the node's time, the skew, the whitelist, the entry
bound and the deadline), taken on the node thread when the connection begins. It does the TLS handshake and the
admission, hands an admitted peer's request to the node thread and waits for the answer. No store is ever touched by
two threads, and there is no lock around one.

A connection is counted at the TCP accept, on the node thread, and the choice to close it for the clock's state or
for the inflight limit is made there. Its TLS handshake is completed all the same, and the audit line is written
after it. The count falls when the connection has ended, before the close that waits for the peer to read.

The clock, the timers, the draws and the nonces come from a `NodeEnvironment`. `NodeEnvironment.System()` is the
machine's clock, real timers and the system's secure random source (seven bytes for each draw), and it is what an
application gets when it passes nothing. A test passes its own clock, timers and draws through the same parameter.
That is the only way a test drives a node. No frame a peer can send sets the clock or causes a tick.

## What a node does, against the design

- The stores (design section 3): capacity, ages to 65535, the oldest entry as partner with a draw to settle a tie,
  the buffer with the node's own entry only in the store of its own type (OQ-5), the merge that prefers the younger
  entry also against an entry just sent (NQ-16), the partner put back at age 0 in a store of another type (NQ-15),
  sent entries put back after a failed shuffle and into what room a merge leaves (OQ-12).
- Joining (section 6): one `sample` for each store to a configured sentinel, the next sentinel when one does not
  answer, retries with a delay that doubles from `joinRetryInitialMs` to `joinRetryMaxMs`, the sentinel kept in the
  node's sentinel store (NQ-12), the request that waits while the clock is paused (ruling 1.d), and a sentinel asked
  again when a tick finds a view empty. A sentinel inserts every peer that samples it, after the sample (NQ-13).
- Shuffles: each store on its own timer, entries whose token has expired dropped before each tick, one connection
  with one deadline (NQ-14), a tick during a shuffle in flight only ages, a failed partner dropped. A gossiped
  address is dialed only when it is an IPv4 literal and a port, as the Silica node does.
- Admission (section 4): the channel binding, the token's structure, kid, time with the skew, `sub`, the tempus
  whitelist rule in both directions (NQ-4), the id hash, the producer's signature, the proof of possession in both
  directions, `key_rotated` with the wait that keeps the frame from a reset, and every entry of a received frame
  verified without contact. The events and the reasons are the Silica node's.
- Limits (section 8): the frame ceiling judged from the length alone, an accepted shuffle bounded by the greatest of
  the three shuffle lengths at the connection and by the store's own at the store, `inflightMax` with the connection
  beyond it closed after its handshake (`inflight_refused`), one bound for a connection, and the closes
  `clock_refused` and `clock_stopped`.
- TLS as the Silica node has it: a handshake that ends with a fatal alert when the dialer does not offer `tempus/1`
  (`alpn_mismatch`), no certificate as a failed handshake (`tls_verify_failed`), and a certificate with a P-256 key
  let through the handshake and refused after it (`tempus_cert_key`). The node reads the key exchange group the
  handshake chose and refuses any other than X25519MLKEM768 (`tls_group_refused`).
- The clock (sections 4 and 10): seconds since 1970 UTC from the machine's clock, read at start and every
  `clockReadMs`; no listening before the first reading; `follow`, `hold`, `stop` with its limit; `continue`, `pause`.
- A node whose own token has expired stops ticking, tells its application and goes on answering (NQ-17).

Not done, because only a bridge does it: the score of a peer (NQ-19, NQ-23). The Silica connection actor tells its
node of each refusal of an accepted peer, and every node that is not a bridge drops that message. The extension
sends no such message.

## What a node does not cover

- The bridge role. A bridge needs a TRUST implementation in C#: mutual TLS 1.3 with pinned certificates and the
  TRUST whitelist with its permission specs, the reconnect token, TRUST's suspicion and quarantine rules, its frames
  and its client. It needs a second identity with its own key, the table of exported functions with the forbidden
  guard and the permission spec for each peer type, the table of scores for each peer with its bounds from the
  application, the call timeout, and the hand-over of each admitted call to the application (design section 17). None
  of it exists here. What does exist and a bridge could use: the TLS layer over OpenSSL, which would need a second
  profile with the ALPN name `trust/1` and pinned certificates, the codec, which would need the terms TRUST's values
  use beyond integers, atoms, binaries, lists and maps, and the node, whose `call` and `cast` branch is the one
  place that refuses today.
- The text of a refusal of a malformed frame is the Silica node's for every case the trials show. For other
  malformed frames the verdict is the same and the words may differ, because the Silica reader's words come from the
  Silica language's own decoder.
- A node dials a gossiped address only when it is an IPv4 literal and a port. Sentinels may be named by host name,
  which .NET resolves; the Silica node dials sentinels by IPv4 literal only.
- A node does not check that a peer's certificate is self-signed, because the Silica node's TLS engine does not: it
  accepts any issuer and judges the peer by the certificate's key and fingerprint. The design says a TEMPUS
  certificate is self-signed. The client half of the extension does check it, as the other client halves do.
- A node says `not a request: unknown_atom` of a frame that names an atom outside `src/tempus/bees_tempus.atoms`
  and `src/trust/bees_trust.atoms`, as a Silica program built without the test unit does. A Silica program that
  holds more atoms says `unknown kind` of some of those frames.
- A new token passed with `SetToken` is not judged when it is passed, as in the Silica node; one that is not valid
  shows at the next tick. Only its length is checked at once.

## What the client half checks

On the TLS connection, for both directions: TLS 1.3 only; the group X25519MLKEM768 only, read back from the
connection after the handshake; the cipher suites TLS_AES_256_GCM_SHA384 and TLS_CHACHA20_POLY1305_SHA256 only; the
signature algorithm ed25519 only; the application protocol `tempus/1`; a certificate from the peer, whose key is
Ed25519 and which is signed by its own key with issuer equal to subject. No certificate authority is consulted and
the certificate's dates are not checked, as the design rules.

On the peer's advert, in the node's order: the bounds of every field; the binding (the advert's `pub` is the key of
the certificate the peer presented); the token's `kid` (a token under another `kid` is answered with the one
`key_rotated` frame); the time; `sub`; the whitelist rule in both directions; the identifier as the SHA-512 of the
key; the producer's signature over the token's payload bytes as they were received. Then the proof of possession.

On a reply: it is the reply the request calls for; it names the store of the request; a sample's reply holds no more
entries than were asked for; every entry verifies for that store. One entry that does not verify refuses the whole
reply. A `result` must carry the `req_id` of the call. A call or a cast is sent only to a peer admitted with a bridge
token.

As a listener: the same admission, then one request. A `shuffle` is given to the application's handler only when its
every entry verifies. A `sample` and a `shuffle` are answered for the same store. Anything else is closed with no
reply.

One time bound covers a whole connection. A frame above 131072 bytes is refused from its length alone. When the
extension closes a connection it first ends its own sending, then reads until the peer has closed or half a second
has passed, so that a frame it has just sent (a `key_rotated`, a reply) is not lost.

## What it was checked against

Everything below was run on one machine: macOS on Apple Silicon, with the versions named above. Nothing was run on
Linux: the .NET SDK is not installed on the project's Linux machines, the three trials are declared for the Mac
only in their `platforms` files, and on a machine without `dotnet` each of them fails and says so.

`make test` runs the layering check and two test programs.

The client tests, 44 of them:

- The frames golden of `trials/t2_tempus_frames`. That trial prints every frame and token the Silica frame unit
  writes or deliberately breaks, as hex, with what the Silica reader made of each. The extension builds the 27 frames
  and tokens that concern a client from the same inputs and gets the same bytes, and it reads every recorded frame
  and gives the same verdict. The test frames `tick` and `clock` and their answer `done` are checked to be refused.
- The codec by itself: round trips, the order of map keys, the integer forms, the reader's refusals.
- The TEST ONLY identities of `tools/bees_tempus_ids.py`: the public key, identifier and certificate fingerprint of
  the eight test certificates; the eight certificates made again from their seeds, byte for byte; and the 112 test
  tokens, signed here from the same seeds and compared byte for byte.
- The 20 admission cases of `trials/t4_tempus_admission`, with the verdict and the reason the Silica node gave for
  each.
- The channel binding and the whitelist rule.
- The client half against itself over real mutual TLS 1.3 on 127.0.0.1: admission both ways, each request, each
  cause of refusal, `key_rotated` in both directions, replies that must be refused, a peer nobody listens for and a
  peer that never answers.

The node tests, 25 of them:

- the view and the store: 20623 calls of view functions and 6006 store steps, which are the calls the two
  independent Python models (`tools/bees_tempus_view_model.py`, `tools/bees_tempus_store_model.py`) make to compute
  every line of the goldens of `trials/t0_tempus_view` and `trials/t1_tempus_store`, and 9508 more on generated
  views and stores; each is made again in C# and must give the model's answer;
- the clock: every line of the goldens of `trials/t0_tempus_clock` computed again;
- the configuration: the refusals of `tools/test_bees_tempus_conf.py` that a value can show, with their words, and
  five start refusals of `trials/c4_tempus_boot` with the Silica node's line (the sixth, an externally driven node
  on an address that is not loopback, has no counterpart);
- the node's judgement of an entry on the cases of `trials/t4_tempus_admission`, verdict and reason, and that a
  frame of the test unit names an atom a production node does not hold.

Three trials run the extension with real Silica programs. Each is run from the BEES root directory with
`tools/run_all_trials.sh --local-only --only NAME`.

- `trials/c12_tempus_csharp` runs the client tests and then walks the client half against real BEES TEMPUS nodes. A
  test node joins through the client, which listens as a sentinel. The client samples and shuffles as a sentinel and
  as an edge, is dialed by the node for a shuffle, and sees what it answered in the node's stores. The node refuses
  the client for each reason a token can be wrong, and for requests that break a bound. The client refuses the node
  when the client's clock says the node's token has expired or is not valid yet, when the client holds another
  producer key as current, and when the whitelist rule is broken. The client meets a peer that misbehaves on
  purpose, in both positions; that peer is the Python test support. Then a node that is not a test node and reads the
  machine's clock, met by the client reading the machine's clock too, and the command line, dialing and listening.
- `trials/c13_tempus_node_csharp` runs the node tests and then nodes of the extension and Silica nodes in one
  network. It shows a C# edge joining through a Silica sentinel and a Silica edge joining through a C# sentinel;
  shuffles started by each side and answered by the other, in the store of the node's own type and in stores of
  another type, with each side's entries in the other's store; a partner that is not there; a good peer and 42
  kinds of bad peer sent to a Silica node and to a C# node, with the audit lines required to be the same; the
  inflight limit and four refusals of the TLS handshake in the same way; the clock's choices on C# nodes whose clock
  the trial sets; the node's own token expiring and being replaced; `key_rotated` told to the application in both
  directions; and a C# node that is not a test node, on the machine's clock and its own timers, through which a
  Silica node that is not a test node joins, both refusing the `tick` and `clock` frames.
- `trials/c16_tempus_bridge_csharp` walks the client half against two real bridges and the TRUST node behind them:
  a call answered with its result, a cast delivered, each refusal a client can provoke, the bridge's bounds, the
  whitelist rule for a bridge's certificate in both directions, a bridge found in a store and called, and what the
  client sees when the TRUST node refuses the bridge or is not there.

`trials/c16_tempus_bridge_csharp/COVERAGE.md` goes through the behaviour list of the design's section 16.2 row by
row for the client half.

Not shown by any test or trial: a clock that cannot be read at start; an entry whose token has expired leaving a
view of a node of the extension before a tick; the retry delay of a join doubling over real time; a tick that finds
a view empty and asks a sentinel again by a join request; a listen address that cannot be bound; a sentinel named by
host name; many connections at once beyond the inflight test; `tls_group_refused`, because every peer the trials have
offers one group only; and a node that runs for longer than a trial. The driver's `gossip` command is run by the
gossip example (`trials/c7_tempus_gossip`), whose check shows C# nodes joining through a C# sentinel, a Swift sentinel
and a Silica sentinel, learning of every edge and merging shuffles, for a few seconds on one machine; it drives no
refusal. The driver's `node` command, the example
application, is in no trial: it was run by hand once on 2026-11-23, as a sentinel on the machine's clock that the
driver's `dial` command sampled twice, and with a configuration that is refused.

## What stands between this and production use

- No review as production code, by anyone.
- No test under load, no long run, no measurement of memory or of threads, and no test on Linux, on Windows or on
  another .NET than 11.0.100 or another OpenSSL than 4.1.0.
- Every key, certificate and token it was run with is a test fixture.
- Each connection has a thread of its own. A connection whose peer never closes holds its thread until the
  connection's bound; a node that is disposed leaves connections in hand to end by that bound.
- The OpenSSL objects are freed by finalizers and by the close of a connection. Nothing was measured to show that
  none is leaked.
- The private key is read from an unencrypted file or a seed and held in memory by OpenSSL. Nothing is done to
  protect it beyond never giving it out.
- The four choices listed under "The configuration", what the application is told of `key_rotated`, and where the
  OpenSSL libraries are looked for are not ruled.
- The bridge role is absent.

## What the client half does not cover

- The arguments of a call on the command line are integers only. In code they may be any term of the codec's
  subset.
- The value of a `result` is read only when it is made of integers, atoms, binaries, lists and maps with atom keys. A
  value that holds a tuple, a float or anything else is refused; the outcome still carries the reply's bytes.
- It does not fetch or refresh a token, and by itself it keeps no store of entries. Joining a network, keeping the
  three stores and shuffling on a timer are the node half's.
- The client trial does not drive the node behaviours that only test frames or timing can reach on a Silica node
  (the connection limit, the node's clock moving, a node's token being replaced). The node trial shows those on nodes
  of the extension.

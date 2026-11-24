// swift-tools-version:6.0
// The Swift TEMPUS extension: the wire and client code (TempusClient), the node
// (TempusNode), and what only tests and trials use (TempusClientTesting and the test programs). README.md says what an
// application depends on.
// No remote dependency: the system's Foundation, and the OpenSSL already installed on the machine through the module
// map of lib/COpenSSL. The Makefile beside this file passes the place of OpenSSL's headers and libraries.
//   lib/TempusClient              the client library: the wire, admission, dial and a listener
//   lib/TempusNode                the node library: an application that is a TEMPUS node depends on it
//   lib/COpenSSL                  the module map for the installed OpenSSL
//   driver/tempus-client          the driver application: a command line over the two libraries (`gossip` runs a node)
//   driver/tempus-node-example    an application that is a node: it links TempusNode and nothing of the tests
//   testing/TempusClientTesting   TEST ONLY: tokens and identities from fixed seeds, and a clock, timers and draws set
//                                 by hand, for the tests and the trials. No library target depends on it
//   testing/tempus-node-trial     TEST ONLY: the node program of trials/c8_tempus_node_swift
//   test/tempus-client-tests      the unit tests of the client library, as a plain program
//   test/tempus-node-tests        the unit tests of the node library, as a plain program (test/model_check.py drives
//                                 its `model` mode)
// Language modes: TempusClient and the programs over it alone are written for Swift 5 mode; TempusNode and everything
// that depends on it for Swift 6 mode (strict concurrency).
import PackageDescription

let v5: [SwiftSetting] = [.swiftLanguageMode(.v5)]
let v6: [SwiftSetting] = [.swiftLanguageMode(.v6)]

let package = Package(
    name: "TempusClient",
    platforms: [.macOS("26.0")],
    products: [
        // what an application depends on: TempusNode to be a node, TempusClient alone to be a client
        .library(name: "TempusClient", targets: ["TempusClient"]),
        .library(name: "TempusNode", targets: ["TempusNode"]),
        .executable(name: "tempus-node-example", targets: ["tempus-node-example"]),
        // the driver, the tests and the trial program: they link TempusClientTesting, which holds TEST ONLY material
        .executable(name: "tempus-client", targets: ["tempus-client"]),
        .executable(name: "tempus-client-tests", targets: ["tempus-client-tests"]),
        .executable(name: "tempus-node-tests", targets: ["tempus-node-tests"]),
        .executable(name: "tempus-node-trial", targets: ["tempus-node-trial"]),
    ],
    targets: [
        .systemLibrary(name: "COpenSSL", path: "lib/COpenSSL"),
        .target(name: "TempusClient", dependencies: ["COpenSSL"], path: "lib/TempusClient", swiftSettings: v5),
        .target(name: "TempusNode", dependencies: ["TempusClient", "COpenSSL"], path: "lib/TempusNode", swiftSettings: v6),
        .executableTarget(name: "tempus-node-example", dependencies: ["TempusNode"], path: "driver/tempus-node-example",
                          swiftSettings: v6),
        .target(name: "TempusClientTesting", dependencies: ["TempusClient", "TempusNode"],
                path: "testing/TempusClientTesting", swiftSettings: v6),
        .executableTarget(name: "tempus-client", dependencies: ["TempusClient", "TempusNode", "TempusClientTesting"],
                          path: "driver/tempus-client", swiftSettings: v5),
        .executableTarget(name: "tempus-client-tests", dependencies: ["TempusClient", "TempusClientTesting"],
                          path: "test/tempus-client-tests", swiftSettings: v5),
        .executableTarget(name: "tempus-node-tests", dependencies: ["TempusNode", "TempusClientTesting"],
                          path: "test/tempus-node-tests", swiftSettings: v6),
        .executableTarget(name: "tempus-node-trial", dependencies: ["TempusNode", "TempusClientTesting"],
                          path: "testing/tempus-node-trial", swiftSettings: v6),
    ]
)

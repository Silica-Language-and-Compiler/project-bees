// swift-tools-version:6.0
// The Swift TEMPUS extension: the wire and client code (TempusClient), the node (TempusNode), and what only tests and
// trials use (TempusTestSupport and the executables). README.md says what an application depends on.
// No remote dependency: the system's Foundation, and the OpenSSL already installed on the machine through the module
// map of Sources/COpenSSL. The Makefile beside this file passes the place of OpenSSL's headers and libraries.
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
        // tests and trial programs: they link TempusTestSupport, which holds TEST ONLY material
        .executable(name: "tempus-client", targets: ["tempus-client"]),
        .executable(name: "tempus-client-tests", targets: ["tempus-client-tests"]),
        .executable(name: "tempus-node-tests", targets: ["tempus-node-tests"]),
        .executable(name: "tempus-node-trial", targets: ["tempus-node-trial"]),
    ],
    targets: [
        .systemLibrary(name: "COpenSSL"),
        .target(name: "TempusClient", dependencies: ["COpenSSL"], swiftSettings: v5),
        .target(name: "TempusNode", dependencies: ["TempusClient", "COpenSSL"], swiftSettings: v6),
        .executableTarget(name: "tempus-node-example", dependencies: ["TempusNode"], swiftSettings: v6),
        .target(name: "TempusTestSupport", dependencies: ["TempusClient", "TempusNode"], swiftSettings: v6),
        .executableTarget(name: "tempus-client", dependencies: ["TempusClient", "TempusTestSupport"], swiftSettings: v5),
        .executableTarget(name: "tempus-client-tests", dependencies: ["TempusClient", "TempusTestSupport"], swiftSettings: v5),
        .executableTarget(name: "tempus-node-tests", dependencies: ["TempusNode", "TempusTestSupport"], swiftSettings: v6),
        .executableTarget(name: "tempus-node-trial", dependencies: ["TempusNode", "TempusTestSupport"], swiftSettings: v6),
    ]
)

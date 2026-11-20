// swift-tools-version:5.9
// The Swift example TEMPUS client. An example only: not for production (see README.md).
// No remote dependency: the system's Foundation, and the OpenSSL already installed on the machine through the module
// map of Sources/COpenSSL. The Makefile beside this file passes the place of OpenSSL's headers and libraries.
import PackageDescription

let package = Package(
    name: "TempusClient",
    platforms: [.macOS("26.0")],
    products: [
        .library(name: "TempusClient", targets: ["TempusClient"]),
        .executable(name: "tempus-client", targets: ["tempus-client"]),
        .executable(name: "tempus-client-tests", targets: ["tempus-client-tests"]),
    ],
    targets: [
        .systemLibrary(name: "COpenSSL"),
        .target(name: "TempusClient", dependencies: ["COpenSSL"]),
        .executableTarget(name: "tempus-client", dependencies: ["TempusClient"]),
        .executableTarget(name: "tempus-client-tests", dependencies: ["TempusClient"]),
    ]
)

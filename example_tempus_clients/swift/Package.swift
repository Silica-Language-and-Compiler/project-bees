// swift-tools-version:5.9
// The Swift example TEMPUS client. An example only: not for production (see README.md).
// No remote dependency: the system's Foundation, and the OpenSSL already installed on the machine through the module
// map of lib/COpenSSL. The Makefile beside this file passes the place of OpenSSL's headers and libraries.
//   lib/TempusClient              the client library: what an application would take as its starting point
//   lib/COpenSSL                  the module map for the installed OpenSSL
//   driver/tempus-client          the driver application: a command line over the library
//   testing/TempusClientTesting   TEST ONLY: tokens and identities from fixed seeds, for the tests and the trial
//   test/tempus-client-tests      the unit tests, as a plain program
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
        .systemLibrary(name: "COpenSSL", path: "lib/COpenSSL"),
        .target(name: "TempusClient", dependencies: ["COpenSSL"], path: "lib/TempusClient"),
        .target(name: "TempusClientTesting", dependencies: ["TempusClient"], path: "testing/TempusClientTesting"),
        .executableTarget(name: "tempus-client", dependencies: ["TempusClient", "TempusClientTesting"], path: "driver/tempus-client"),
        .executableTarget(name: "tempus-client-tests", dependencies: ["TempusClient", "TempusClientTesting"],
                          path: "test/tempus-client-tests"),
    ]
)

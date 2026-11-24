// Finds the installed OpenSSL (libssl and libcrypto) and tells the linker where it is. Nothing is compiled here and
// nothing is fetched. The directory is OPENSSL_PREFIX when that is set (the Makefile beside the workspace sets it the
// way the BEES Makefiles do, from native/<platform>/platform.mk, PLATFORM_OPENSSL_DIRS); otherwise the same Homebrew
// places are tried. With none found the system's own library path is used, and the link step says what is missing.
use std::env;
use std::path::Path;

fn main() {
    println!("cargo:rerun-if-env-changed=OPENSSL_PREFIX");
    let mut places: Vec<String> = Vec::new();
    if let Ok(p) = env::var("OPENSSL_PREFIX") {
        if !p.is_empty() {
            places.push(p);
        }
    }
    places.push("/opt/homebrew/opt/openssl".to_string());
    places.push("/opt/homebrew/opt/openssl@4".to_string());
    for p in places {
        if Path::new(&p).join("include/openssl/ssl.h").exists() {
            println!("cargo:rustc-link-search=native={}/lib", p);
            return;
        }
    }
    println!("cargo:warning=no OpenSSL was found under OPENSSL_PREFIX or Homebrew; the linker will look in its own places");
}

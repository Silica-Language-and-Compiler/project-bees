//! What the tests share: where the BEES tree is, and how a recorded output of a trial is read.
use std::path::PathBuf;

/// The root of the BEES tree: BEES_ROOT when set (the Makefile sets it), else four directories above this crate.
pub fn bees_root() -> PathBuf {
    match std::env::var("BEES_ROOT") {
        Ok(p) if !p.is_empty() => PathBuf::from(p),
        _ => PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../.."),
    }
}

pub fn read(path: &str) -> String {
    let p = bees_root().join(path);
    std::fs::read_to_string(&p).unwrap_or_else(|e| panic!("cannot read {}: {}", p.display(), e))
}

/// The recorded outputs NAME.PLATFORM.scout of one trial leaf: (file name, text).
pub fn goldens(leaf: &str, name: &str) -> Vec<(String, String)> {
    let dir = bees_root().join("trials").join(leaf);
    let mut out = Vec::new();
    for e in std::fs::read_dir(&dir).unwrap_or_else(|e| panic!("cannot list {}: {}", dir.display(), e)).flatten() {
        let f = e.file_name().to_string_lossy().into_owned();
        if f.starts_with(&format!("{}.", name)) && f.ends_with(".scout") {
            out.push((f.clone(), std::fs::read_to_string(e.path()).expect("a golden is text")));
        }
    }
    out.sort();
    assert!(!out.is_empty(), "no golden {}.*.scout in trials/{}", name, leaf);
    out
}

//! The engine's state file, written and read the same way by both hosts.
//!
//! Two rules:
//!
//! * **A save replaces the file in one step.** The JSON goes to a temporary
//!   file next to it, is flushed to disk, and only then renamed over the old
//!   one. A crash in the middle leaves the previous save intact instead of a
//!   truncated file.
//! * **A file that cannot be read is moved aside, never overwritten.** The host
//!   then starts fresh, and its first save would otherwise replace the only copy
//!   of the positions and the forward-test record with an empty book. The
//!   unreadable file keeps its content under a new name for a person to look at.

use std::io::Write;
use std::path::{Path, PathBuf};

use crate::engine::Persisted;

/// What [`load`] found.
#[derive(Debug)]
pub enum Loaded {
    Restored(Box<Persisted>),
    /// No state file yet: a first start.
    Missing,
    /// The file exists but does not parse. `moved_to` is where it went, or
    /// `None` when even the rename failed (the host should then not save over it).
    Unreadable { error: String, moved_to: Option<PathBuf> },
}

/// Write `state` to `path` atomically (temporary file, fsync, rename).
pub fn save(path: &Path, state: &Persisted) -> std::io::Result<()> {
    let json = serde_json::to_vec(state).map_err(std::io::Error::other)?;
    if let Some(dir) = path.parent().filter(|d| !d.as_os_str().is_empty()) {
        std::fs::create_dir_all(dir)?;
    }
    let tmp = path.with_extension("json.tmp");
    {
        let mut f = std::fs::File::create(&tmp)?;
        f.write_all(&json)?;
        f.sync_all()?;
    }
    std::fs::rename(&tmp, path)
}

/// Read the state file. An unreadable one is renamed to
/// `<name>.unreadable-<UTC time>` so the next save cannot destroy it.
pub fn load(path: &Path) -> Loaded {
    let text = match std::fs::read_to_string(path) {
        Ok(t) => t,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Loaded::Missing,
        Err(e) => return Loaded::Unreadable { error: e.to_string(), moved_to: None },
    };
    match serde_json::from_str::<Persisted>(&text) {
        Ok(p) => Loaded::Restored(Box::new(p)),
        Err(e) => {
            let stamp = chrono::Utc::now().format("%Y%m%dT%H%M%SZ");
            let name = path.file_name().map(|n| n.to_string_lossy().to_string()).unwrap_or_else(|| "state.json".into());
            let aside = path.with_file_name(format!("{name}.unreadable-{stamp}"));
            let moved_to = std::fs::rename(path, &aside).ok().map(|_| aside);
            Loaded::Unreadable { error: e.to_string(), moved_to }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::engine::Engine;

    fn dir(tag: &str) -> PathBuf {
        let d = std::env::temp_dir().join(format!("pythia-persist-{tag}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&d);
        std::fs::create_dir_all(&d).unwrap();
        d
    }

    #[test]
    fn a_save_round_trips_and_leaves_no_temporary_file() {
        let d = dir("roundtrip");
        let path = d.join("state.json");
        let mut e = Engine::new();
        e.manual_order("crypto:BTC/USD", crate::connectors::Side::Buy, 500.0);
        save(&path, &e.to_persisted()).unwrap();
        assert!(!d.join("state.json.tmp").exists());
        match load(&path) {
            Loaded::Restored(p) => assert_eq!(p.positions.len(), 1),
            other => panic!("expected a restore, got {other:?}"),
        }
        let _ = std::fs::remove_dir_all(&d);
    }

    #[test]
    fn a_missing_file_is_a_first_start() {
        let d = dir("missing");
        assert!(matches!(load(&d.join("state.json")), Loaded::Missing));
        let _ = std::fs::remove_dir_all(&d);
    }

    #[test]
    fn an_unreadable_file_is_moved_aside_so_the_next_save_cannot_destroy_it() {
        let d = dir("unreadable");
        let path = d.join("state.json");
        std::fs::write(&path, b"{\"cash\": 12, truncated").unwrap();
        let moved = match load(&path) {
            Loaded::Unreadable { moved_to: Some(m), .. } => m,
            other => panic!("expected the file to be moved aside, got {other:?}"),
        };
        assert!(!path.exists());
        assert_eq!(std::fs::read(&moved).unwrap(), b"{\"cash\": 12, truncated");
        // The fresh engine's first save goes to the normal name, the old content survives.
        save(&path, &Engine::new().to_persisted()).unwrap();
        assert!(moved.exists() && path.exists());
        let _ = std::fs::remove_dir_all(&d);
    }
}

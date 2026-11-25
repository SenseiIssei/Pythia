//! A crash leaves a trace. The release build aborts on a panic and the Windows
//! app has no console, so without this the window is simply gone. The report
//! stays on this machine; nothing is sent anywhere.

use std::io::Write;
use std::path::{Path, PathBuf};

/// Above this size the log starts over, so a crash loop cannot fill the disk.
const MAX_BYTES: u64 = 256 * 1024;

/// Append one report to `path`.
pub fn record(path: &Path, report: &str) -> std::io::Result<()> {
    if let Some(dir) = path.parent().filter(|d| !d.as_os_str().is_empty()) {
        std::fs::create_dir_all(dir)?;
    }
    let full = std::fs::metadata(path).is_ok_and(|m| m.len() > MAX_BYTES);
    let mut f = std::fs::OpenOptions::new().create(true).write(true).append(!full).truncate(full).open(path)?;
    f.write_all(report.as_bytes())?;
    f.sync_all()
}

/// Write every panic to `path` before the process goes down, on top of what
/// the panic hook does already (the message on stderr).
pub fn install(path: PathBuf, version: &'static str) {
    let before = std::panic::take_hook();
    std::panic::set_hook(Box::new(move |info| {
        let thread = std::thread::current();
        let report = format!(
            "{} pythia {version} {} {} thread {}: {info}\n",
            chrono::Utc::now().format("%Y-%m-%dT%H:%M:%SZ"),
            std::env::consts::OS,
            std::env::consts::ARCH,
            thread.name().unwrap_or("?"),
        );
        let _ = record(&path, &report);
        before(info);
    }));
}

#[cfg(test)]
mod tests {
    use super::*;

    fn file(tag: &str) -> PathBuf {
        let d = std::env::temp_dir().join(format!("pythia-crash-{tag}-{}", uuid::Uuid::new_v4()));
        d.join("crash.log")
    }

    #[test]
    fn reports_are_appended_and_a_full_log_starts_over() {
        let p = file("append");
        record(&p, "one\n").unwrap();
        record(&p, "two\n").unwrap();
        assert_eq!(std::fs::read_to_string(&p).unwrap(), "one\ntwo\n");
        std::fs::write(&p, vec![b'x'; MAX_BYTES as usize + 1]).unwrap();
        record(&p, "three\n").unwrap();
        assert_eq!(std::fs::read_to_string(&p).unwrap(), "three\n");
        std::fs::remove_dir_all(p.parent().unwrap()).ok();
    }

    #[test]
    fn a_panic_lands_in_the_file() {
        let p = file("panic");
        install(p.clone(), "9.9.9");
        let _ = std::thread::Builder::new().name("crash-test".into()).spawn(|| panic!("the test panic")).unwrap().join();
        let text = std::fs::read_to_string(&p).unwrap();
        let line = text.lines().find(|l| l.contains("thread crash-test")).expect("the report");
        assert!(line.contains("pythia 9.9.9"), "{line}");
        assert!(text.contains("the test panic"), "{text}");
        assert!(text.contains("crash.rs"), "the place is named: {text}");
        std::fs::remove_dir_all(p.parent().unwrap()).ok();
    }
}

//! Read Cursor agent transcripts into the per-project database.

use crate::error::{Result, TangError};
use crate::index_store::{file_updated_at, finish_session, write_sessions, SessionDraft};
use crate::project::ProjectIdentity;
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::collections::HashSet;
use std::fs;
use std::path::{Path, PathBuf};

pub struct CursorIndexResult {
    pub indexed: i64,
    pub deleted: i64,
    pub skipped: i64,
    pub warnings: Vec<String>,
}

pub fn index_cursor(
    cursor_home: &Path,
    project: &ProjectIdentity,
    database_path: &Path,
) -> Result<CursorIndexResult> {
    let home = cursor_home.canonicalize().map_err(|_| {
        TangError::new(
            "missing-store",
            "The configured Cursor home is unavailable.",
        )
    })?;
    let slug = project_slug(project);
    let root = home.join("projects").join(slug).join("agent-transcripts");
    if !root.is_dir() {
        return Err(TangError::new(
            "missing-store",
            "No Cursor agent transcripts were found for this project.",
        ));
    }
    let namespace = format!(
        "store-{:x}",
        Sha256::digest(home.to_string_lossy().as_bytes())
    );
    let root_path = project_root(project);
    let hint = root_path.to_string_lossy().to_string();
    let mut logs = Vec::new();
    collect_transcripts(&root, &mut logs)?;
    logs.sort();
    let mut saved = Vec::new();
    let mut warnings = Vec::new();
    let mut protected = HashSet::new();
    let mut skipped = 0;
    for log in logs {
        if is_symlink(&log) {
            if let Some(source_id) = source_id_for_transcript(&log, &namespace) {
                protected.insert(source_id);
            }
            warnings.push(format!(
                "skipped symlinked Cursor transcript {}",
                log.display()
            ));
            continue;
        }
        match read_transcript(&log, &namespace, &hint, &home, &root_path, &mut warnings) {
            Ok(record) => saved.push(record),
            Err(message) => {
                if let Some(source_id) = source_id_for_transcript(&log, &namespace) {
                    protected.insert(source_id);
                }
                skipped += 1;
                warnings.push(message);
            }
        }
    }
    let wrote = write_sessions(
        database_path,
        &project.key,
        "cursor",
        &namespace,
        "R",
        &saved,
        &protected,
    )?;
    Ok(CursorIndexResult {
        indexed: wrote.indexed,
        deleted: wrote.deleted,
        skipped,
        warnings,
    })
}

fn read_transcript(
    path: &Path,
    namespace: &str,
    hint: &str,
    cursor_home: &Path,
    project_root: &Path,
    warnings: &mut Vec<String>,
) -> std::result::Result<crate::index_store::SavedSession, String> {
    let native_id = path
        .file_stem()
        .and_then(|name| name.to_str())
        .unwrap_or("")
        .to_string();
    if native_id.is_empty() {
        return Err(format!(
            "Cursor transcript has no session name: {}",
            path.display()
        ));
    }
    let bytes = fs::read(path).map_err(|_| format!("cannot read {}", path.display()))?;
    let mut turns = Vec::new();
    let mut started: Option<String> = None;
    let mut updated: Option<String> = None;
    for (number, line) in String::from_utf8_lossy(&bytes).lines().enumerate() {
        if line.trim().is_empty() {
            continue;
        }
        let row: Value = match serde_json::from_str(line) {
            Ok(value) => value,
            Err(_) => {
                warnings.push(format!(
                    "skipped malformed Cursor transcript {}:{}",
                    path.display(),
                    number + 1
                ));
                continue;
            }
        };
        if let Some(timestamp) = row_timestamp(&row) {
            if started
                .as_deref()
                .is_none_or(|current| timestamp.as_str() < current)
            {
                started = Some(timestamp.clone());
            }
            if updated
                .as_deref()
                .is_none_or(|current| timestamp.as_str() > current)
            {
                updated = Some(timestamp);
            }
        }
        let role = match row.get("role").and_then(Value::as_str) {
            Some("user") => "user",
            Some("assistant") => "agent",
            _ => continue,
        };
        let Some(blocks) = row
            .get("message")
            .and_then(|message| message.get("content"))
            .and_then(Value::as_array)
        else {
            continue;
        };
        let text = blocks
            .iter()
            .filter(|block| block.get("type").and_then(Value::as_str) == Some("text"))
            .filter_map(|block| block.get("text").and_then(Value::as_str))
            .collect::<Vec<_>>()
            .join("\n");
        if !text.trim().is_empty() {
            turns.push((role.to_string(), text));
        }
    }
    let mut fingerprint = Sha256::new();
    fingerprint.update(&bytes);
    if let Some(sidecar) = sidecar_times(cursor_home, project_root, &native_id, warnings) {
        fingerprint.update(&sidecar.bytes);
        if let Some(created) = sidecar.started {
            started = Some(created);
        }
        if let Some(revised) = sidecar.updated {
            updated = Some(revised);
        }
    }
    let fallback = file_updated_at(path);
    let started = started.unwrap_or_else(|| fallback.clone());
    let updated = updated.unwrap_or(fallback);
    let digest = format!("{:x}", fingerprint.finalize());
    let locator = path.to_string_lossy();
    finish_session(SessionDraft {
        adapter: "cursor",
        namespace,
        native_id: &native_id,
        locator: locator.as_ref(),
        fingerprint: &digest,
        project_hint: hint,
        started_at: &started,
        updated_at: &updated,
        health: "unknown",
        title: None,
        turns,
    })
}

struct SidecarTimes {
    started: Option<String>,
    updated: Option<String>,
    bytes: Vec<u8>,
}

fn sidecar_times(
    cursor_home: &Path,
    project_root: &Path,
    native_id: &str,
    warnings: &mut Vec<String>,
) -> Option<SidecarTimes> {
    let meta = cursor_home
        .join("chats")
        .join(workspace_chat_hash(&project_root.to_string_lossy()))
        .join(native_id)
        .join("meta.json");
    if is_symlink(&meta) || !meta.is_file() {
        return None;
    }
    let bytes = match fs::read(&meta) {
        Ok(bytes) => bytes,
        Err(_) => {
            warnings.push(format!("cannot read Cursor sidecar {}", meta.display()));
            return None;
        }
    };
    let value: Value = match serde_json::from_slice(&bytes) {
        Ok(value) => value,
        Err(_) => {
            warnings.push(format!(
                "Cursor meta.json had an unsupported shape: {}",
                meta.display()
            ));
            return None;
        }
    };
    Some(SidecarTimes {
        started: epoch_millis(value.get("createdAtMs")),
        updated: epoch_millis(value.get("updatedAtMs")),
        bytes,
    })
}

pub fn workspace_chat_hash(project_dir: &str) -> String {
    hex(&md5(project_dir.as_bytes()))
}

fn hex(bytes: &[u8]) -> String {
    const DIGITS: &[u8; 16] = b"0123456789abcdef";
    let mut out = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        out.push(DIGITS[(byte >> 4) as usize] as char);
        out.push(DIGITS[(byte & 0x0f) as usize] as char);
    }
    out
}

fn epoch_millis(value: Option<&Value>) -> Option<String> {
    let millis = value?.as_i64()?;
    if millis < 0 {
        return None;
    }
    Some(crate::timeutil::rfc3339_secs((millis / 1000) as u64))
}

fn md5(message: &[u8]) -> [u8; 16] {
    fn f(x: u32, y: u32, z: u32) -> u32 {
        (x & y) | (!x & z)
    }
    fn g(x: u32, y: u32, z: u32) -> u32 {
        (x & z) | (y & !z)
    }
    fn h(x: u32, y: u32, z: u32) -> u32 {
        x ^ y ^ z
    }
    fn i(x: u32, y: u32, z: u32) -> u32 {
        y ^ (x | !z)
    }
    const SHIFTS: [u32; 64] = [
        7, 12, 17, 22, 7, 12, 17, 22, 7, 12, 17, 22, 7, 12, 17, 22, 5, 9, 14, 20, 5, 9, 14, 20, 5,
        9, 14, 20, 5, 9, 14, 20, 4, 11, 16, 23, 4, 11, 16, 23, 4, 11, 16, 23, 4, 11, 16, 23, 6, 10,
        15, 21, 6, 10, 15, 21, 6, 10, 15, 21, 6, 10, 15, 21,
    ];
    const CONSTANTS: [u32; 64] = [
        0xd76aa478, 0xe8c7b756, 0x242070db, 0xc1bdceee, 0xf57c0faf, 0x4787c62a, 0xa8304613,
        0xfd469501, 0x698098d8, 0x8b44f7af, 0xffff5bb1, 0x895cd7be, 0x6b901122, 0xfd987193,
        0xa679438e, 0x49b40821, 0xf61e2562, 0xc040b340, 0x265e5a51, 0xe9b6c7aa, 0xd62f105d,
        0x02441453, 0xd8a1e681, 0xe7d3fbc8, 0x21e1cde6, 0xc33707d6, 0xf4d50d87, 0x455a14ed,
        0xa9e3e905, 0xfcefa3f8, 0x676f02d9, 0x8d2a4c8a, 0xfffa3942, 0x8771f681, 0x6d9d6122,
        0xfde5380c, 0xa4beea44, 0x4bdecfa9, 0xf6bb4b60, 0xbebfbc70, 0x289b7ec6, 0xeaa127fa,
        0xd4ef3085, 0x04881d05, 0xd9d4d039, 0xe6db99e5, 0x1fa27cf8, 0xc4ac5665, 0xf4292244,
        0x432aff97, 0xab9423a7, 0xfc93a039, 0x655b59c3, 0x8f0ccc92, 0xffeff47d, 0x85845dd1,
        0x6fa87e4f, 0xfe2ce6e0, 0xa3014314, 0x4e0811a1, 0xf7537e82, 0xbd3af235, 0x2ad7d2bb,
        0xeb86d391,
    ];
    let bit_len = (message.len() as u64).wrapping_mul(8);
    let mut data = message.to_vec();
    data.push(0x80);
    while data.len() % 64 != 56 {
        data.push(0);
    }
    data.extend_from_slice(&bit_len.to_le_bytes());
    let mut a0 = 0x6745_2301_u32;
    let mut b0 = 0xefcd_ab89_u32;
    let mut c0 = 0x98ba_dcfe_u32;
    let mut d0 = 0x1032_5476_u32;
    for chunk in data.chunks(64) {
        let mut words = [0_u32; 16];
        for (index, word) in words.iter_mut().enumerate() {
            *word = u32::from_le_bytes(chunk[index * 4..index * 4 + 4].try_into().unwrap());
        }
        let (mut a, mut b, mut c, mut d) = (a0, b0, c0, d0);
        for index in 0..64 {
            let (mixed, source) = match index {
                0..=15 => (f(b, c, d), index),
                16..=31 => (g(b, c, d), (5 * index + 1) % 16),
                32..=47 => (h(b, c, d), (3 * index + 5) % 16),
                _ => (i(b, c, d), (7 * index) % 16),
            };
            let mixed = mixed
                .wrapping_add(a)
                .wrapping_add(CONSTANTS[index])
                .wrapping_add(words[source]);
            a = d;
            d = c;
            c = b;
            b = b.wrapping_add(mixed.rotate_left(SHIFTS[index]));
        }
        a0 = a0.wrapping_add(a);
        b0 = b0.wrapping_add(b);
        c0 = c0.wrapping_add(c);
        d0 = d0.wrapping_add(d);
    }
    let mut out = [0_u8; 16];
    out[0..4].copy_from_slice(&a0.to_le_bytes());
    out[4..8].copy_from_slice(&b0.to_le_bytes());
    out[8..12].copy_from_slice(&c0.to_le_bytes());
    out[12..16].copy_from_slice(&d0.to_le_bytes());
    out
}

fn row_timestamp(row: &Value) -> Option<String> {
    if let Some(text) = row.get("timestamp").and_then(Value::as_str) {
        return Some(text.to_string());
    }
    let millis = row
        .get("timestamp")
        .and_then(Value::as_i64)
        .or_else(|| row.get("createdAt").and_then(Value::as_i64))?;
    Some(crate::timeutil::rfc3339_secs((millis / 1000).max(0) as u64))
}

fn source_id_for_transcript(path: &Path, namespace: &str) -> Option<String> {
    let native_id = path.file_stem()?.to_str()?;
    Some(format!("cursor:{namespace}:{native_id}"))
}

fn project_root(project: &ProjectIdentity) -> PathBuf {
    project
        .database_path
        .parent()
        .and_then(Path::parent)
        .map(Path::to_path_buf)
        .unwrap_or_else(|| project.database_path.clone())
}

fn project_slug(project: &ProjectIdentity) -> String {
    let root = project_root(project);
    let text = root.to_string_lossy();
    let trimmed = text.trim_matches('/');
    if trimmed.is_empty() {
        "root".to_string()
    } else {
        trimmed.replace('/', "-")
    }
}

fn collect_transcripts(dir: &Path, found: &mut Vec<PathBuf>) -> Result<()> {
    let entries = fs::read_dir(dir).map_err(|_| {
        TangError::new(
            "missing-store",
            "The Cursor agent-transcripts directory could not be listed.",
        )
    })?;
    for entry in entries {
        let path = entry
            .map_err(|_| {
                TangError::new(
                    "missing-store",
                    "The Cursor agent-transcripts directory could not be listed.",
                )
            })?
            .path();
        if is_symlink(&path) {
            continue;
        }
        if path.is_dir() {
            collect_transcripts(&path, found)?;
        } else if path.extension().and_then(|ext| ext.to_str()) == Some("jsonl") {
            found.push(path);
        }
    }
    Ok(())
}

fn is_symlink(path: &Path) -> bool {
    path.symlink_metadata()
        .map(|meta| meta.file_type().is_symlink())
        .unwrap_or(true)
}

#[cfg(test)]
mod tests {
    use super::{hex, md5};

    #[test]
    fn md5_matches_the_empty_and_abc_vectors() {
        assert_eq!(hex(&md5(b"")), "d41d8cd98f00b204e9800998ecf8427e");
        assert_eq!(hex(&md5(b"abc")), "900150983cd24fb0d6963f7d28e17f72");
    }
}

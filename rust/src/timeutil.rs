//! RFC 3339 UTC formatting without an extra time crate.

pub fn rfc3339_now() -> String {
    let seconds = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|duration| duration.as_secs())
        .unwrap_or(0);
    rfc3339_secs(seconds)
}

pub fn rfc3339_secs(seconds: u64) -> String {
    let (year, month, day) = civil_from_days((seconds / 86_400) as i64);
    let clock = seconds % 86_400;
    let hour = clock / 3600;
    let minute = (clock % 3600) / 60;
    let second = clock % 60;
    format!("{year:04}-{month:02}-{day:02}T{hour:02}:{minute:02}:{second:02}Z")
}

fn civil_from_days(days: i64) -> (i64, u32, u32) {
    let z = days + 719_468;
    let era = if z >= 0 { z } else { z - 146_096 } / 146_097;
    let doe = (z - era * 146_097) as u64;
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146_096) / 365;
    let y = yoe as i64 + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let day = (doy - (153 * mp + 2) / 5 + 1) as u32;
    let month = (if mp < 10 { mp + 3 } else { mp - 9 }) as u32;
    let year = if month <= 2 { y + 1 } else { y };
    (year, month, day)
}

#[cfg(test)]
mod tests {
    use super::rfc3339_secs;

    #[test]
    fn unix_epoch_and_the_next_day() {
        assert_eq!(rfc3339_secs(0), "1970-01-01T00:00:00Z");
        assert_eq!(rfc3339_secs(86_400), "1970-01-02T00:00:00Z");
    }
}

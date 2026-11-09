use std::fmt;

#[derive(Debug)]
pub struct TangError {
    pub code: &'static str,
    pub message: String,
}

impl TangError {
    pub fn new(code: &'static str, message: impl Into<String>) -> Self {
        Self {
            code,
            message: message.into(),
        }
    }
}

impl fmt::Display for TangError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(&self.message)
    }
}

impl std::error::Error for TangError {}

pub type Result<T> = std::result::Result<T, TangError>;

pub fn storage(error: rusqlite::Error) -> TangError {
    TangError::new("storage-unavailable", error.to_string())
}

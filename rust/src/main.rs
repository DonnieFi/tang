#![forbid(unsafe_code)]

use std::io::{self, Write};
use std::process::ExitCode;

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let stdout = io::stdout();
    let mut stdout = stdout.lock();
    match tang::run_with(&args, &mut stdout) {
        Ok(()) => ExitCode::SUCCESS,
        Err(error) => {
            let _ = writeln!(io::stderr(), "error[{}]: {error}", error.code);
            let _ = stdout.flush();
            ExitCode::from(2)
        }
    }
}

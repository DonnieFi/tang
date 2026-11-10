# Doctor

`tang doctor` checks that SQLite can open the project database and that FTS5 works in memory. It does not scan harness homes, hash native logs, or start another process. A missing database is reported unavailable and is not created.

There is no `--quick` mode and no per-harness doctor status. The command exits with the `doctor` error when a check is not ready.

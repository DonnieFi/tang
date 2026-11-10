# Index cost

`tang index` reads the native sources named by its home flags. `adapter_checkpoints` stores a schema-4 fingerprint for each source. An unchanged, previously valid source is not parsed again. A changed source is rewritten. A missing source is deleted, or tombstoned when a continuation edge still points at it.

The authoritative database stays `PROJECT/.tang/tang.db`. Tang does not add a daemon, a background scanner, or a second database for search. `tang search` and `tang recall` read derived databases and do not open native logs.

The July 2026 timings came from the removed Python indexer. They are not measurements of this Rust CLI, and the benchmark script is gone. Time the Rust command only against a temporary project created for that run. Do not point `tang index` at a real harness home to collect a benchmark.

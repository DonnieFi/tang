# Index cost

`tang index` reads the native sources named by its home flags and rewrites derived rows for the current project. It does not create `adapter_checkpoints`, so an unchanged session is parsed again on the next index. There is no incremental skip.

The authoritative database stays `PROJECT/.tang/tang.db`. Tang does not add a daemon, a background scanner, or a second database for search. `tang search` and `tang recall` read derived databases and do not open native logs.

The July 2026 timings came from the removed Python indexer. They are not measurements of this Rust CLI, and the benchmark script is gone. Time the Rust command only against a temporary project created for that run. Do not point `tang index` at a real harness home to collect a benchmark.

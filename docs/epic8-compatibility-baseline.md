# Epic 8 compatibility baseline

Frozen public contracts before internal hardening (`tang-2mr`). Branch:
`epic/10-beta-release` (includes beta parity work); re-verify on
`epic/08-architecture-hardening` before promotion.

| Seam | Guard tests |
| --- | --- |
| CLI subcommands | `tests/test_release_cli.py` |
| Link destinations | `tests/test_continuation.py`, `tests/test_harness_capabilities.py` |
| Target resolution | `tests/test_target_resolution.py` (if present), link/graph CLI tests |
| Context pack JSON | `tests/test_context_service.py`, skill workflow |
| Index partial/complete | `tests/test_indexing.py` |
| Graph map | `tests/test_graph.py`, `tests/test_graph_cli.py` |
| Adapter read-only | `tests/test_codex_adapter.py`, `test_grok_adapter.py`, `test_opencode_adapter.py` |
| Privacy/redaction | `tests/test_redaction.py`, capsule tests |

Internal modules targeted by Epic 8 children: `target.py`, `continuation.py`,
`indexing.py`, `repository.py`, `adapters/{codex,grok,opencode,cursor}.py`.

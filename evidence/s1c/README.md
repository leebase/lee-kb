# S1C owner-acceptance evidence

`S1C-lee-kb.json` is the content-free owner-acceptance artifact required by the
frozen LeeOS S1C plan (Deliver 7). It is generated, never hand-edited:

```
python3 tools/produce_s1c_owner_evidence.py --output evidence/s1c/S1C-lee-kb.json
```

The generator exits `0` when `status` is `accepted` and `1` when it is `failed`,
so it doubles as a check. Omit `--output` to print the artifact to stdout.

Regenerating runs, for real: `pytest tests/test_owner.py`,
`pytest tests/test_mcp.py`, `compileall src/lee_kb/owner.py`, a live
`lee_kb.mcp` stdio handshake against a temporary corpus it builds itself, the
per-case focused tests behind the permission matrices, mutation probes on a
private copy of `src/lee_kb`, and the no-write cycle. It takes about 25 seconds,
writes nothing outside `--output` (plus the usual `__pycache__`/`.pytest_cache`),
and never touches `~/.config/lee-kb` or any sibling repository.

`stable_body_sha256` is reproducible on the same toolchain; `generated_at`,
`artifact_sha256` and the `owner_repository` commit/dirty fields are expected to
differ between runs. To confirm reproducibility:

```
python3 tools/produce_s1c_owner_evidence.py --output /tmp/s1c-check.json
python3 -c "import json;a=json.load(open('evidence/s1c/S1C-lee-kb.json'));b=json.load(open('/tmp/s1c-check.json'));print(a['status']==b['status'] and a['stable_body_sha256']==b['stable_body_sha256'])"
```

The schema, the contract mapping, and every unsatisfied row are documented in
`docs/s1c-owner-contract.md`. Current status is `failed`; read
`failure_reasons` for the exact reasons.

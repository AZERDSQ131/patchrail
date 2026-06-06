# Agent Control Plane Demo

This example is a checked-in, no-install transcript for PatchRail's local Agent
Control Plane demo. It starts from the bundled CI fixture, creates a local SQLite
queue, records approval and rejection gates, exports reviewer handoff artifacts,
and reports the safety boundary.

The versioned transcript is real CLI output:

- [demo-output.md](demo-output.md)

Regenerate it from a source checkout with a stable output directory name:

```bash
uv run --extra dev patchrail evidence control-plane-demo \
  --out-dir patchrail-control-plane-demo \
  --force \
  --format markdown
```

The command is local-only. It does not use network access, GitHub write
permission, external models, billing, public comments, pull requests, or
funding claims.

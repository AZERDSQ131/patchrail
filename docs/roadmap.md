# Roadmap

## v0.1

- Local CI failure classifier.
- Markdown, JSON, and text reports.
- Local redaction helper for shared logs.
- Fixture-backed tests.
- Local fixture benchmark command.
- Initial 40-fixture CI failure zoo.
- Safety, ethics, and security documentation.
- Release-prep evidence checklist for tests, lint, benchmark, doctor, package
  artifacts, safety review, and manual publish gates.

## v0.2

- Larger CI failure fixture set toward 40+ cases.
- Expanded Node and TypeScript drift fixtures toward 28 total benchmark cases.
- Expanded Python dependency-resolution fixtures to reach 40 total benchmark cases.
- GitHub Actions report artifact example.
- Reproducible `patchrail-ci-triage` artifact example with Markdown, JSON,
  benchmark and doctor outputs.
- Classifier fixture contribution flow.

## v0.3

- Experimental local SQLite queue for maintainer work items.
- Human approval states for local decisions.
- Exportable audit log.
- CI report to queue-item demo.
- Direct `ci-result.json` import into pending local queue items.
- Local audit event export for add, approve, reject, and handoff decisions.
- Local proposal records for reviewable patch plans linked to queue items.
- Proposal approval/rejection audit events without granting write permission.

## v0.4

- Experimental `patchrail funded-issues list/explain` over local JSON metadata.
- Safe-only filtering by default, with `--include-risky` limited to local output visibility.
- Contribution etiquette and anti-abuse guardrails.
- Risk explanations for ambiguous scope, spam-attractive work, and missing contribution guidelines.
- No automatic claims, comments, pull requests, maintainer contact, external API fetch, or model call.

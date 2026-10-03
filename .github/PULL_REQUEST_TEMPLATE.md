## What

<!-- One or two sentences: what does this change do? -->

## Why

<!-- Link the issue, or explain the motivation. -->

## Checklist

- [ ] `pytest`, `ruff check src tests scripts`, and `mypy src` pass locally
- [ ] New behavior has tests (adapters: sanitized fixture + test file)
- [ ] Any fixture data is fully sanitized (no real paths, code, or personal data)
- [ ] Signal, statistics or factor changes are reflected in `docs/methodology.md`
- [ ] If `contextrot share` output changed: `docs/sharing.md` updated, and `SCHEMA` bumped if a field changed meaning or was removed
- [ ] If output changed visibly: showcase media regenerated (`scripts/capture_showcase.py`)

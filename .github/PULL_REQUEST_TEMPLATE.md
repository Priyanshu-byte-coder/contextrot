## What

<!-- One or two sentences: what does this change do? -->

## Why

<!-- Link the issue, or explain the motivation. -->

## Checklist

- [ ] `pytest`, `ruff check src tests`, and `mypy src` pass locally
- [ ] New behavior has tests (adapters: sanitized fixture + test file)
- [ ] Any fixture data is fully sanitized (no real paths, code, or personal data)
- [ ] Signal/statistics changes are reflected in `docs/methodology.md`

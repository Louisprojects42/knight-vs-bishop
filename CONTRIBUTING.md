# Contributing

Use Python 3.12+ and install `python -m pip install -e ".[dev]"` in a virtual
environment. Run these checks before submitting a pull request:

```bash
python -m unittest discover -s tests -v
ruff check src tests
kb-study render
node scripts/check_report.js
python -m build
```

Keep downloads and reduced databases in ignored `work/` or `data/` directories.
Tests and ordinary CI must not fetch chess archives. Use synthetic positions to
test piece identity, ratings, adjacent evaluations, normalization and model
behavior. Preserve an actual before/after example when fixing a scientific bug.

Explain any change to sampling, exclusions, rating ownership, piece tracking,
winning-chance transforms, checkpoint selection, model controls or uncertainty
in the methods documentation. Do not silently replace the published research
run with a different cohort. A new run should have its own manifests, result
directory, dependency record and validation results.

Empty cells stay missing. Distinguish unique games from player-games and move
opportunities. Keep raw event counts beside rates. Label observational results
and sparse groups, and avoid treating engine move execution as complete causal
credit for a piece.

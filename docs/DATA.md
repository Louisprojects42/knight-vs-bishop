# Data and reproducibility

## Included in Git

`results/` contains the published summary JSON and CSVs, model coefficients and
calibration, normalized clock numerator/denominator table, sampling manifests,
validation records, PNG/SVG figures, Markdown results and offline HTML.
These are enough for `kb-study summary` and `kb-study render` without network
access. No player-level database is required for those commands.

The published manifests retain source URLs, offsets, checksums and counts.
Worker database paths have been made relative for publication; the source-range
checksums are unchanged. `analysis_run_provenance.json` records the original
research environment and script hashes. `repository_provenance.json` records
the packaged source separately. Repository refactoring does not change the
published statistical estimates.

## Optional reduced-data release asset

The existing `knight_bishop_reduced_data.zip` is approximately 390 MB. It is kept
outside Git, and can be attached to a GitHub release when publishing. There is
no published download URL until the repository and release are created.
`data_assets.json` records the archive and member sizes and SHA-256 hashes.

Once you have that archive, from the repository root:

```bash
python scripts/import_reduced_data.py /path/to/knight_bishop_reduced_data.zip --results results
kb-study validate
kb-study analyze
kb-study render
```

The importer verifies the archive checksum and each expected member before
installing it. An existing identical file is retained; an existing different
file is refused. It extracts only the six named reduced-data files, translates
the old `expanded/` prefix to the requested result directory, and does not use
unrestricted ZIP extraction.

| File | Contents |
|---|---|
| `study.sqlite` | Selected game/player JSON and immediately evaluated original minor-piece moves |
| `outcomes.sqlite` | One qualifying checkpoint and recorded outcome per game |
| `player_games.csv` | General sample, one record per player-game |
| `evaluated_player_games.csv` | Player-games meeting adjacent-evaluation coverage criteria |
| `matched_positions.csv` | FENs, ratings, checkpoint, pawn/king covariates and outcomes |
| `clock_normalization.csv` | Event counts, eligible move counts and normalized rates in clock buckets |

Git ignores the large files even after local import. The clock table is small
enough to publish and is already committed for figure reproduction. Raw game
downloads are not included in the release asset.

## Database schema

`study.sqlite` has `games(id, month, window_id, general_sample, has_eval, players,
outcome)` and `moves(game_id, ply, window_id, piece, color, rating_band,
time_control, speed, game_length, clock_seconds, cp_before, cp_after, win_before,
win_after, delta_pp, loss_pp, blunder_200cp, blunder_20pp)`. The game/move primary
keys prevent duplicate observations. `players` is a JSON list of two records.
Game `outcome` contains only the earlier capture-sample checkpoint search;
**use `outcomes.sqlite` for the full actual-outcome cohort**.

`outcomes.sqlite` has `outcomes(game_id, window_id, month, data)`, with JSON `data`
holding the recorded FEN, material, bishop owner, ratings, pawn/king features,
result, date, time control and eventual completed length.

CP values and winning chances in move records are in the mover's perspective.
`delta_pp = win_after - win_before`; `loss_pp = max(0, -delta_pp)`. Clocks record
the mover's remaining time after the move. Material capture values are gross
captured points, not net material profit. See [METHODS.md](METHODS.md) for precise
denominators and eligibility rules.

## Reproduce without the optional asset

Use the full sampling pipeline in [README.md](../README.md). It reads HTTP byte
ranges from monthly source archives in RAM, then persists reduced records.
Changing seed, window size, strata or months requires a new checkpoint work
directory. Resume settings are checked before using a saved plan. The result
will depend on the unchanged source archive bytes; retained checksums audit
the two passes.

Lichess exports are [CC0](https://database.lichess.org/). Anonymous player hashes
are pseudonymous identifiers, not a guarantee of anonymity: game IDs remain
publicly linkable. The repository publishes aggregates and excludes the
player-level records from normal Git history.

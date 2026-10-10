# Knight vs bishop: expanded empirical study

This is the expanded principal analysis. See [the report](../results/report.html)
and [results.json](../results/results.json) for actual sample sizes and results. `sampling_manifest.json`
records every source URL, byte range, frame size, checksum, seed, filter count and
processing duration. `outcome_sampling_manifest.json` audits the second pass.

## Design and cohorts

The source frame is the six Lichess standard archives for April–September 2026.
Each compressed archive is divided into eight equal byte strata. Seed 20261009
chooses one random 16 MiB range wholly inside each stratum, for 48 distributed
windows. Recover complete independent Zstandard frames within the ranges;
discard partial frame edges and incomplete PGN records. Validate server HTTP 206
and Content-Range responses. No archive payload is written to disk.

This is a **distributed archive-window sample**, not an exhaustive six-month
census or an exact uniform sample of games. Compressed density and the complete-
frame requirement affect game inclusion. Bytes near stratum edges can have
different inclusion chances. Results describe the sampled windows; clustering
does not correct this selection bias. Sampling across six months and throughout
each archive fixes the original pilot's narrow chronological coverage without
pretending to scan every game in the source archives.

There are three explicitly separated cohorts:

1. **Capture/spatial cohort:** select 6% of eligible games using a stable seeded
   BLAKE2 hash of game ID. Average captures and geometric metrics over these
   player-games. Do not mix the deliberately oversampled evaluated games into
   these estimates. This cohort measures captures, attacks and legal mobility.
2. **Evaluated-move cohort:** process every eligible game in the windows with
   `%eval` annotations. Save knight/bishop moves only when both the immediate
   pre-move and post-move positions have evaluations. Do not carry an old eval
   across a missing annotation or invent an opening eval of zero. Clock analyses
   additionally require the mover's `%clk`. This selected engine-annotated cohort
   may differ from ordinary Lichess games.
3. **Actual-outcome cohort:** in a second pass, search **every eligible game in
   those same windows** for balanced bishop-vs-knight positions, rather than
   limiting this rarer cohort to the 6% capture sample. The payload hashes must
   agree across passes before analysis. This provides real wins/draws/losses and
   an adjusted observational winning comparison.

## Filters and bins

Exclude an entire game when either rating is below 500, non-numeric or missing;
exactly 500 is retained. Exclude BOT-tagged players, self-play, non-rated events,
variants, custom starting positions, unfinished results, inconsistent result tags,
invalid PGNs, illegal/null moves and games shorter than two half-moves. Selected
game IDs are unique in SQLite. Provisional rating uncertainty and historical
cheating status cannot be inferred reliably from these headers.

The user's `750-100` is interpreted as `750-1000`. Display labels retain the
requested style, but the bands are precisely:

| Label | Inclusion rule |
|---|---|
| 500–750 | 500 <= rating < 750 |
| 750–1000 | 750 <= rating < 1000 |
| 1000–1500 | 1000 <= rating < 1500 |
| 1500–2000 | 1500 <= rating < 2000 |
| 2000–2500 | 2000 <= rating < 2500 |
| 2500+ | rating >= 2500 |

Attribute a piece's data to its owner, not just White's rating. These are Lichess
Glicko-2 ratings, despite the PGN tag name `Elo`.
The capture/evaluation rating rows count a game when at least one relevant owner
belongs to that band. A game with owners in different bands can therefore appear
in two band game counts; those counts must not be added to estimate unique games.

Keep both forms of game length:

- **Time-control pool:** ultrabullet (<30s), bullet (<180s), blitz (<480s), rapid
  (<1500s), classical (>=1500s), using base + 40*increment estimated seconds.
  Unknown/correspondence stays separate. Store the exact base+increment tag too.
- **Actual move count:** 1–20, 21–40, 41–60, 61+ full moves, using ceil(plies/2).
  For example 41 half-moves falls in 21–40, not 1–20. Actual length is a property
  of the completed game, not a pre-game condition; outcome results split by
  eventual length are descriptive and can be affected by selection/collider bias.

## Material captured and original-piece identities

Track all eight starting minor pieces through moves and captures. A promoted
knight or bishop does not become an original piece. Original pieces receive
credit for captures even when immediately recaptured. Captured promoted pieces
retain their ordinary type value.

Pawn=1, knight=bishop=3, rook=5, queen=9. Report the combined material captured
by a player's two original knights or two original bishops per player-game.
The reduced player records store per-original-piece values, so the report
multiplies by two. This is gross capture value, not net material profit.

Spatial metrics remain as secondary diagnostics: mean attacked squares per
original piece over post-move positions, and mean legal moves per original
piece on that owner's turns. Original pieces contribute zero after capture;
undeveloped pieces stay in the denominator. Spatial control is no longer used
as the principal measure of winning contribution.

## Winning contribution: engine assessment

Use the public [Lichess winning-chance mapping](https://lichess.org/page/accuracy):

`W(cp) = 100 / (1 + exp(-0.00368208 * cp))`.

Convert the pre/post White-point-of-view evaluations to the mover's perspective.
For a move made by an original knight or bishop, store:

- `delta_pp = W_after - W_before`: signed percentage-point change;
- `loss_pp = max(0, -delta_pp)`: winning chance lost; **lower is better**;
- the exact before/after centipawn values, clock, ply, game ID, owner rating band,
  exact time control, speed, eventual game length and two event flags.

Main per-move statistics use **the number of eligible moves** as denominator,
not just blunders, captures or games. This is the normalization idea used by
the [reference chess-blunders study](https://github.com/Antiochian/chess-blunders/blob/main/README.md).
Five-second clock buckets retain numerator counts and opportunity counts;
graphs divide the former by the latter. `%clk` is the mover's remaining time
after the move, not inferred thinking time. Increment and possible berserk
games require care. Exact 180+0, 300+0 and 600+0 comparisons are supplied.

The 200cp event flag uses loss >=200cp, except when both pre/post mover
evaluations remain >=+300cp. This explicit practical-winning cutoff is our
analysis choice; it is not a claim to reproduce every detail of that historical
script or today's Lichess classification. The second flag is a loss of at least
20 winning-chance percentage points, another explicitly defined analysis
threshold. Mates are encoded as +/-100000 cp, mapping to essentially 0/100.

Also report signed cumulative change per original piece/game for player-games
with >=80% pre/post evaluation coverage over original minor-piece moves and
at least one evaluated move from both types. Missing evaluations are never
imputed as zero. Retain coverage and eligible counts so this calculation can be
audited or rerun at a stricter cutoff.

**Interpretation:** evaluation loss measures how safely players execute moves
with a piece, not the full value of owning it. A good move can merely maintain
an advantage already present; engine noise can create positive swings. Passive
support and threats that induce an opponent's error are not causally attributed
to the supporting piece. Lichess's fixed mapping is not individually calibrated
to each rating tier; conclusions at beginner ratings therefore need the actual-
outcome cross-check. No Stockfish depth or engine-version field is guaranteed
for these annotations.

## Winning contribution: actual outcomes

At predeclared checkpoints after 20, 30, 40, 50, 60, 80 or 100 full moves,
take the **first** qualifying position in each game, with at least four later
half-moves. Both players must be in the same requested rating band and their
rating difference <=100. Each has exactly one original minor piece remaining:
one bishop versus one knight. Pawn, rook and queen counts must be equal for
the two sides. Promotions cannot supply the comparison pieces.

This is an equal-material natural comparison; games can include equal rooks or
queens as well as pure minor-piece endgames. It does not treat different pawn
locations or king activity as equal simply because material counts match.
Save the qualifying FEN, checkpoint, pawn/king features and eventual outcome.
Both players' actual win rates and the shared draw rate are reported. The
shortest move-count bin has no such outcome positions by design; engine move
statistics still cover those short games.

Fit ridge-regularized logistic regression to the actual binary win indicator
(win=1, draw/loss=0), using mirrored White/Black rows and these predictors:

- owning a bishop rather than a knight, with rating-band interactions;
- rating gap, colour, side to move, equal pawn/rook/queen counts, checkpoint ply;
- differences in passed pawns, blocked pawns, central pawns, pawn islands and
  king distance to the central four squares;
- rating band, time-control pool and month.

Do not include eventual game length or any post-checkpoint play in predictors.
For each subgroup, standardize the fitted model over that subgroup's observed
covariates, changing the piece-type indicator and its rating interactions.
Report the adjusted bishop-minus-knight win-probability difference in percentage
points, with window-clustered sandwich confidence intervals. This is a model
contrast between the two piece types, not an intervention performed on a board.
Only piece-by-rating interactions are fitted. Adjusted speed/length cells average
that pooled model's contrast within each subgroup; they are not separate fitted
piece-by-speed or piece-by-length effects. Raw rates and their bootstrap intervals
provide the direct descriptive comparisons within those cells.

Hold out approximately 20% of complete archive windows for validation: both
colors and all positions from those windows stay together. Record Brier score,
log loss, baseline scores, calibration counts and convergence. Fit the final
descriptive model to all matches afterwards. Ridge penalty=0.5; Newton steps
use backtracking and analytic gradients/Hessians. The algorithm and coefficients
are saved so adjustments can be reviewed.

**Interpretation:** an adjusted association with real wins in the defined
matched-position population. It cannot prove a causal effect of swapping pieces.
Earlier trades, pawn structure, piece-square placement and player decisions
create selection effects; some remain unmeasured. General winning contribution
of all original pieces throughout all games is not identifiable from this design.

## Confidence intervals and reporting

Use 1,000 bootstrap replicates of the 48 sampled archive windows for capture and
move-rate ratios, preserving all games/moves within a window. The outcome model
uses a sandwich covariance clustered by the same windows, with a finite-cluster
correction and approximate normal intervals. These are pointwise exploratory
95% intervals. They do not correct sampling density, engine-annotation selection,
repeated players across windows or the many subgroup comparisons.

Flag a capture or actual-outcome cell as too small when it has <200 games or
<6 contributing windows. Move-rate comparisons additionally require >=200
distinct eligible games from each type; always inspect game counts and opportunity counts.
Empty cells remain missing, not zero. Sparse classical/high-rating cells can
remain inconclusive despite the broad source coverage.

## Reduced data retained, downloads removed

- `study.sqlite`: game/player records and eligible knight/bishop move records.
- `outcomes.sqlite`: one recorded FEN and actual outcome per qualifying game.
- `player_games.csv`, `evaluated_player_games.csv`: general and qualified
  evaluated cohorts, with IDs and denominators.
- `clock_normalization.csv`: numerator/denominator data for clock plots.
- `matched_positions.csv`: matched-position dataset and outcome covariates.
- Three rating/speed/length summary CSVs, `outcome_model.json`,
  `model_calibration.csv`, `results.json`, manifests, methods and plots.

SQLite allows querying the reduced data without rescanning PGNs. No serialized
Python `eval()` is used. Archive windows are in memory only and are released
after preprocessing; intermediate reduced SQLite shards are deleted after
successful merge. The first pilot's downloaded prefix and diagnostic range
files are also deleted after the expanded run. Useful result tables are retained.

## Reproduce

Install the repository with Python 3.12+ and `python -m pip install -e .`.
Run `kb-study render` from the repository root to regenerate the report and all
seven figures from the committed summaries without network access.

For a fresh source run, follow the sampling, outcome, analysis, validation and
render commands in [README.md](../README.md). Use a new ignored `work/` directory
for each sampling configuration. For the published reduced-data archive, use
the verified importer described in [DATA.md](DATA.md).

The CLI accepts `--out` for preprocessing and `--results` for analysis/rendering.
Both default to `results/` relative to the working directory. Monthly source
archives are not downloaded in full. Increasing strata or changing months can
extend coverage; the model derives month controls from the supplied cohort.

The reference study inspired reduced preprocessing, separate numerator and
normalizer recording, and rating/time-control plots. This implementation uses
proper board replay, owning-player ratings and adjacent annotations to avoid
parity errors from dropped move comments.

Sources: [Lichess database](https://database.lichess.org/),
[Lichess winning-chance mapping](https://lichess.org/page/accuracy),
[reference study](https://github.com/Antiochian/chess-blunders/blob/main/README.md),
[python-chess](https://python-chess.readthedocs.io/en/latest/).

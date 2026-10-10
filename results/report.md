# Knight vs bishop: six-month results

Source coverage: April–September 2026, 48 random distributed windows, 48 observed dates.
Scanned 1,769,562 records; general capture cohort 104,417 games; evaluated cohort 181,031 games / 3,980,877 eligible minor-piece moves; actual-outcome cohort 55,663 balanced games.

**Main finding:** Actual outcomes do not establish an overall winner. The capture, influence and engine metrics describe different aspects of contribution.

| Metric | Knights | Bishops |
|---|---:|---:|
| Captured points / player-game (both original pieces) | 3.546 | 4.105 |
| Attacked squares / original piece / position | 3.526 | 3.723 |
| Legal destinations / original piece / owner turn | 2.442 | 2.493 |
| Engine winning chance LOST / evaluated move (pp; lower better) | 4.020 | 4.137 |
| Signed winning-chance change / evaluated move (pp) | -3.895 | -4.014 |
| Cumulative signed change / original piece / qualified player-game (pp) | -11.448 | -10.383 |
| Actual win rate in balanced B-v-N positions (%) | 46.20 | 45.73 |
| Adjusted actual win probability (%) | 45.92 | 46.00 |

Adjusted bishop-minus-knight difference: **+0.08 percentage points**, 95% interval [-0.75, +0.90]. Shared observed draw rate: 8.07%.

| Rating band | General games | Captures N / B | Engine loss N / B (pp/move) | Matched outcome games | Adjusted B−N win probability (pp), 95% interval |
|---|---:|---:|---:|---:|---:|
| 500-750 | 1,224 | 3.28 / 3.41 | 6.27 / 6.41 | 37 | 8.31 [-9.61, 26.22] |
| 750-1000 | 6,255 | 3.46 / 3.78 | 5.46 / 5.47 | 607 | -2.49 [-9.95, 4.97] |
| 1000-1500 | 34,232 | 3.51 / 4.02 | 4.52 / 4.66 | 12,451 | 2.14 [0.30, 3.99] |
| 1500-2000 | 52,522 | 3.54 / 4.12 | 3.83 / 3.96 | 29,722 | 0.04 [-1.04, 1.13] |
| 2000-2500 | 21,169 | 3.64 / 4.29 | 3.20 / 3.28 | 11,974 | -1.48 [-2.97, 0.01] |
| 2500+ | 1,865 | 3.77 / 4.56 | 2.73 / 2.82 | 872 | -5.28 [-10.79, 0.22] |

The HTML table also separates time controls and completed move counts. All rating bands are lower-inclusive and upper-exclusive.

**Interpretation:** the actual-outcome comparison is an adjusted observational association in a defined equal-material bishop-versus-knight population. It does not identify causal credit for every original piece throughout the game. Engine losses measure execution on evaluated moves; they do not include all passive threats or opponent-induced errors.

Validation: held-out window Brier score 0.2457, baseline 0.2483; log loss 0.6844, baseline 0.6897.

Downloaded 1.61 GB in two RAM-only passes over 175.7 GB of source archives. These are sampled windows, not a full-archive census. Raw archive windows are not retained. Reduced data, manifests, model, numerator/normalizer tables and methods are saved.

Methods: [METHODS.md](../docs/METHODS.md). Sources: [Lichess database](https://database.lichess.org/), [winning-chance formula](https://lichess.org/page/accuracy), [reference study](https://github.com/Antiochian/chess-blunders/blob/main/README.md).

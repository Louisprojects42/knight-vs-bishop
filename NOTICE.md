# Sources and licenses

Project code is licensed under **GPL-3.0-or-later**, with the full license in
`LICENSE`. The project depends on [python-chess](https://python-chess.readthedocs.io/en/latest/),
which documents its license as GPL 3 or later. Dependencies are installed by the
package manager; their source and binaries are not vendored in this repository.

The [Lichess database](https://database.lichess.org/) publishes its exports under
CC0. Source URLs, byte ranges, frame metadata and payload checksums are recorded in
the two published sampling manifests. The source games and engine annotations
come from those exports; this project does not run a new Stockfish analysis.

[Antiochian/chess-blunders](https://github.com/Antiochian/chess-blunders/blob/main/README.md)
inspired the preprocessing, numerator/denominator recording and rating/clock
plots. The project uses its own implementation rather than distributing that
study's source code. The winning-chance transform comes from the
[Lichess accuracy documentation](https://lichess.org/page/accuracy).

The GNU GPL license text is reproduced verbatim from the python-chess upstream
license file. This project is not affiliated with any of the above projects.

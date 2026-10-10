"""Stream Lichess PGNs and compare original knights and bishops.

Requires: chess==1.11.2, zstandard==0.25.0, numpy>=2.0.
See README.md for definitions, sampling, and interpretation.
"""
from __future__ import annotations

import argparse
import contextlib
import csv
import hashlib
import io
import json
import logging
from pathlib import Path
import re
import sys
import time
import urllib.request
from collections import Counter, defaultdict

import chess
import chess.pgn
import numpy as np
import zstandard

TYPES = (chess.KNIGHT, chess.BISHOP)
VALUES = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3,
          chess.ROOK: 5, chess.QUEEN: 9}
HEADER = re.compile(r'^\[(\w+) "(.*)"\]$', re.M)
RESULT = re.compile(r'(1-0|0-1|1/2-1/2|\*)\s*$')
METRICS = ('capture', 'influence', 'mobility')


@contextlib.contextmanager
def open_text(source):
    """Stream local PGN/zstd files or a full remote zstd archive."""
    with contextlib.ExitStack() as stack:
        if source.startswith(('https://', 'http://')):
            binary = stack.enter_context(urllib.request.urlopen(source, timeout=60))
        else:
            binary = stack.enter_context(open(source, 'rb'))
        if source.endswith('.zst'):
            binary = stack.enter_context(zstandard.ZstdDecompressor().stream_reader(binary))
        yield stack.enter_context(io.TextIOWrapper(binary, encoding='utf-8-sig'))


def records(stream):
    """Yield records and flag any incomplete tail of a partial download."""
    lines = []
    for line in stream:
        if line.startswith('[Event ') and lines:
            text = ''.join(lines)
            yield text, bool(RESULT.search(text))
            lines = []
        lines.append(line)
    if lines and ''.join(lines).strip():
        text = ''.join(lines)
        yield text, bool(RESULT.search(text))


def exclusion(headers, min_rating=500):
    if not headers.get('Event', '').startswith('Rated '):
        return 'not_rated'
    if headers.get('Variant', 'Standard') != 'Standard':
        return 'variant'
    if headers.get('SetUp') == '1' or 'FEN' in headers:
        return 'nonstandard_start'
    if any(headers.get(k) == 'BOT' for k in ('WhiteTitle', 'BlackTitle')):
        return 'bot'
    if headers.get('Result') not in ('1-0', '0-1', '1/2-1/2'):
        return 'unfinished'
    ratings = [headers.get(k, '') for k in ('WhiteElo', 'BlackElo')]
    if not all(x.isdigit() for x in ratings):
        return 'missing_rating'
    if min(map(int, ratings)) < min_rating:
        return 'below_rating_floor'
    if headers.get('White') == headers.get('Black'):
        return 'self_play'
    if not headers.get('Site', '').startswith('https://lichess.org/'):
        return 'missing_game_id'
    return None


def speed(time_control):
    """Estimated duration = base + 40*increment; keep rating pools separate."""
    try:
        base, increment = map(int, time_control.split('+'))
    except (ValueError, AttributeError):
        return 'unknown_or_correspondence'
    seconds = base + 40 * increment
    for threshold, name in ((29, 'ultrabullet'), (179, 'bullet'),
                            (479, 'blitz'), (1499, 'rapid')):
        if seconds <= threshold:
            return name
    return 'classical'


def rating_bin(rating, width=250):
    lower = 500 + ((rating - 500) // width) * width
    return f'{lower}-{lower + width - 1}'


class Tracker:
    """Identity tracking prevents promotions from changing the denominator."""
    def __init__(self, board):
        self.origins = {
            square: (color, piece_type)
            for color in (chess.WHITE, chess.BLACK) for piece_type in TYPES
            for square in board.pieces(piece_type, color)
        }
        self.captures = Counter()
        self.victims = Counter()
        self.attacks = Counter()
        self.exposure = Counter()
        self.legal = Counter()
        self.turns = Counter()
        self.snapshots = 0

    def before_move(self, board, move):
        # Only generate legal moves for original minor pieces on their own turn.
        color = board.turn
        self.turns[color] += 1
        mask = sum(chess.BB_SQUARES[sq] for sq, key in self.origins.items()
                   if key[0] == color)
        for candidate in board.generate_legal_moves(from_mask=mask):
            self.legal[self.origins[candidate.from_square]] += 1
        identity = self.origins.get(move.from_square)
        if identity and board.is_capture(move):
            victim_type = (chess.PAWN if board.is_en_passant(move)
                           else board.piece_type_at(move.to_square))
            self.captures[identity] += VALUES[victim_type]
            self.victims[(*identity, victim_type)] += 1
        self.origins.pop(move.to_square, None)
        if identity:
            del self.origins[move.from_square]
            self.origins[move.to_square] = identity

    def after_move(self, board):
        self.snapshots += 1
        for square, identity in self.origins.items():
            self.attacks[identity] += board.attacks_mask(square).bit_count()
            self.exposure[identity] += 1


def analyze_game(game, bin_width=250):
    if game.errors:
        raise ValueError('PGN parse error')
    board = game.board()
    if board.fen() != chess.STARTING_FEN:
        raise ValueError('Unexpected initial board')
    tracker = Tracker(board)
    for move in game.mainline_moves():
        if not move or not board.is_legal(move):
            raise ValueError('Illegal or null move')
        tracker.before_move(board, move)
        board.push(move)
        tracker.after_move(board)
    if tracker.snapshots < 2:
        raise ValueError('Fewer than two plies')
    rows = []
    h = game.headers
    for color, name, opponent in ((chess.WHITE, 'White', 'Black'),
                                   (chess.BLACK, 'Black', 'White')):
        rating = int(h[name + 'Elo'])
        row = dict(game_id=h['Site'].rsplit('/', 1)[-1],
                   utc_date=h.get('UTCDate', h.get('Date', '')),
                   utc_time=h.get('UTCTime', ''),
                   color=name.lower(), rating=rating,
                   opponent_rating=int(h[opponent + 'Elo']),
                   rating_bin=rating_bin(rating, bin_width),
                   speed=speed(h.get('TimeControl', '')),
                   time_control=h.get('TimeControl', ''),
                   opening=h.get('ECO', '?'), result=h['Result'],
                   termination=h.get('Termination', ''), plies=tracker.snapshots)
        for piece_type, label in ((chess.KNIGHT, 'knight'), (chess.BISHOP, 'bishop')):
            key = color, piece_type
            exposure = tracker.exposure[key]
            # All original pieces, including undeveloped ones, stay in denominators.
            row[label + '_capture'] = tracker.captures[key] / 2
            row[label + '_influence'] = tracker.attacks[key] / (2 * tracker.snapshots)
            row[label + '_mobility'] = tracker.legal[key] / (2 * tracker.turns[color])
            row[label + '_alive_influence'] = tracker.attacks[key] / exposure if exposure else 0
            row[label + '_survival_fraction'] = exposure / (2 * tracker.snapshots)
            for victim_type in VALUES:
                row[label + '_captured_' + chess.piece_name(victim_type)] = tracker.victims[(*key, victim_type)]
        rows.append(row)
    return rows


def clustered_summary(rows, repetitions=500, seed=20261009, minimum_games=200):
    """Paired B-N comparison; resample whole games, preserving both colors.

    Group numerator/denominator pairs by game. Resampling games rather than
    pieces or plies avoids treating observations within a game as independent.
    Repeated players across games remain a limitation (see README).
    """
    groups = defaultdict(dict)
    for row in rows:
        keys = [('all', 'all'), ('all', row['rating_bin']),
                (row['speed'], 'all'), (row['speed'], row['rating_bin'])]
        values = [1.] + [row[piece + '_' + metric] for metric in METRICS
                         for piece in ('knight', 'bishop')]
        for key in keys:
            existing = groups[key].setdefault(row['game_id'], np.zeros(7))
            existing += values
    rng = np.random.default_rng(seed)
    output = []
    for (pool, band), games in sorted(groups.items()):
        array = np.array(list(games.values()))
        total = array.sum(axis=0)
        means = total[1:] / total[0]
        bootstrap = np.empty((repetitions, 3))
        for start in range(0, repetitions, 16):
            count = min(16, repetitions - start)
            indices = rng.integers(0, len(array), size=(count, len(array)))
            sampled = array[indices].sum(axis=1)
            rates = sampled[:, 1:] / sampled[:, :1]
            bootstrap[start:start+count] = rates[:, 1::2] - rates[:, ::2]
        item = dict(speed=pool, rating_bin=band, games=len(games), player_games=int(total[0]))
        for i, metric in enumerate(METRICS):
            knight, bishop = means[2*i:2*i+2]
            lower, upper = np.quantile(bootstrap[:, i], [0.025, 0.975])
            verdict = ('too_few_games' if len(games) < minimum_games else
                       'bishop' if lower > 0 else 'knight' if upper < 0 else 'inconclusive')
            item.update({metric + '_knight': float(knight), metric + '_bishop': float(bishop),
                         metric + '_bishop_minus_knight': float(bishop - knight),
                         metric + '_ci_low': float(lower), metric + '_ci_high': float(upper),
                         metric + '_leader': verdict})
        output.append(item)
    return output


def write_csv(path, rows):
    if not rows:
        return
    with path.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input', action='append', required=True, help='Local .pgn/.pgn.zst or archive URL; repeat for months')
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--sample-rate', type=float, default=1., help='Stable hash sampling fraction; scan entire archive for an unbiased month sample')
    p.add_argument('--seed', type=int, default=20261009)
    p.add_argument('--bin-width', type=int, default=250)
    p.add_argument('--bootstrap', type=int, default=500)
    p.add_argument('--minimum-games', type=int, default=200)
    p.add_argument('--max-games', type=int, help='Pilot only: stop early; this is NOT a random month sample')
    p.add_argument('--prefix', action='store_true', help='Declare that inputs are bounded chronological prefixes')
    args = p.parse_args()
    if not 0 < args.sample_rate <= 1 or args.bin_width <= 0 or args.bootstrap < 100:
        p.error('Require sample rate in (0,1], positive bin width, and at least 100 bootstrap replicates')
    if args.max_games is not None and args.max_games < 1:
        p.error('--max-games must be positive')
    args.out.mkdir(parents=True, exist_ok=True)
    logging.getLogger('chess.pgn').setLevel(logging.CRITICAL)
    rows, seen, counts = [], set(), Counter()
    started = time.monotonic()
    sources = []
    stop = False
    for source in args.input:
        info = {'input': source}
        if not source.startswith(('http://', 'https://')):
            path = Path(source)
            digest = hashlib.sha256()
            with path.open('rb') as raw:
                for chunk in iter(lambda: raw.read(1024*1024), b''):
                    digest.update(chunk)
            info.update(bytes=path.stat().st_size, sha256=digest.hexdigest())
        sources.append(info)
        with open_text(source) as stream:
            for raw, complete in records(stream):
                counts['records_seen'] += 1
                if not complete:
                    counts['incomplete_record'] += 1
                    continue
                headers = dict(HEADER.findall(raw))
                reason = exclusion(headers)
                if reason:
                    counts[reason] += 1
                    continue
                counts['header_eligible'] += 1
                game_id = headers['Site'].rsplit('/', 1)[-1]
                value = int.from_bytes(hashlib.blake2b(f'{args.seed}:{game_id}'.encode(), digest_size=8).digest(), 'big') / 2**64
                if value >= args.sample_rate:
                    counts['hash_not_selected'] += 1
                    continue
                if game_id in seen:
                    counts['duplicate_selected_game'] += 1
                    continue
                try:
                    game = chess.pgn.read_game(io.StringIO(raw))
                    if game is None:
                        raise ValueError('Empty record')
                    pair = analyze_game(game, args.bin_width)
                except (ValueError, KeyError, TypeError, AssertionError):
                    counts['invalid_or_too_short'] += 1
                    continue
                seen.add(game_id)
                rows.extend(pair)
                counts['analyzed_games'] += 1
                if counts['analyzed_games'] % 1000 == 0:
                    print(f"Analyzed {counts['analyzed_games']:,} games in {time.monotonic()-started:.0f}s", flush=True)
                if args.max_games and counts['analyzed_games'] >= args.max_games:
                    stop = True
                    break
        if stop:
            break
    if not rows:
        raise SystemExit('No eligible, valid games found')
    print('Computing paired game-cluster bootstrap intervals...', flush=True)
    summary = clustered_summary(rows, args.bootstrap, args.seed, args.minimum_games)
    write_csv(args.out / 'per_game.csv', rows)
    write_csv(args.out / 'summary.csv', summary)
    metadata = dict(sources=sources, counts=dict(counts), sample_rate=args.sample_rate,
                    seed=args.seed, bin_width=args.bin_width, bootstrap_repetitions=args.bootstrap,
                    minimum_games_for_leader=args.minimum_games, rating_floor=500,
                    material_values={chess.piece_name(k): v for k, v in VALUES.items()},
                    pilot=bool(args.prefix or args.max_games),
                    selection='chronological prefix / early stop' if args.prefix or args.max_games else 'stable hash sample of supplied sources',
                    first_observed=min(r['utc_date']+' '+r['utc_time'] for r in rows),
                    last_observed=max(r['utc_date']+' '+r['utc_time'] for r in rows),
                    versions=dict(python=sys.version.split()[0], chess=chess.__version__,
                                  zstandard=zstandard.__version__, numpy=np.__version__),
                    elapsed_seconds=round(time.monotonic()-started, 2))
    (args.out / 'results.json').write_text(json.dumps(dict(metadata=metadata, summary=summary), indent=2), encoding='utf-8')
    print(json.dumps(dict(metadata=metadata, overall=next(r for r in summary if r['speed']=='all' and r['rating_bin']=='all')), indent=2))


if __name__ == '__main__':
    main()

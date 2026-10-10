"""Wide-window Lichess study with reduced move records and actual outcomes.

See docs/METHODS.md. Downloaded archive windows live only in RAM.
"""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import io
import json
import logging
import math
from pathlib import Path
import random
import re
import sqlite3
import subprocess
import sys
import time
import urllib.request
import requests

import chess
import chess.pgn
import zstandard
from . import core as kb

BANDS = ['500-750','750-1000','1000-1500','1500-2000','2000-2500','2500+']
LENGTHS = ['1-20 moves','21-40 moves','41-60 moves','61+ moves']
MAGIC = bytes.fromhex('28b52ffd')
CHECKPOINTS = {40,60,80,100,120,160,200}
SCHEMA = '''
CREATE TABLE IF NOT EXISTS games(
 id TEXT PRIMARY KEY, month TEXT, window_id TEXT, general_sample INTEGER,
 has_eval INTEGER, players TEXT, outcome TEXT);
CREATE TABLE IF NOT EXISTS moves(
 game_id TEXT, ply INTEGER, window_id TEXT, piece TEXT, color TEXT,
 rating_band TEXT, time_control TEXT, speed TEXT, game_length TEXT,
 clock_seconds REAL, cp_before REAL, cp_after REAL,
 win_before REAL, win_after REAL, delta_pp REAL, loss_pp REAL,
 blunder_200cp INTEGER, blunder_20pp INTEGER,
 PRIMARY KEY(game_id,ply));
'''


def band(rating):
    for upper,label in zip((750,1000,1500,2000,2500,math.inf),BANDS):
        if rating < upper:
            return label
    raise ValueError(rating)


def game_length(plies):
    return LENGTHS[0] if plies<=40 else LENGTHS[1] if plies<=80 else LENGTHS[2] if plies<=120 else LENGTHS[3]


def stable_fraction(value, seed=20261009):
    return int.from_bytes(hashlib.blake2b(f'{seed}:{value}'.encode(),digest_size=8).digest(),'big') / 2**64


def win_percent(cp):
    # Lichess public mapping, source: lichess.org/page/accuracy.
    return 100/(1+math.exp(-.00368208*max(-10000,min(10000,cp))))


def node_cp(node):
    evaluation = node.eval()
    return None if evaluation is None else evaluation.white().score(mate_score=100000)


def pawn_features(board,color):
    pawns = list(board.pieces(chess.PAWN,color))
    opponents = list(board.pieces(chess.PAWN,not color))
    files = sorted({chess.square_file(s) for s in pawns})
    islands = sum(i==0 or f>files[i-1]+1 for i,f in enumerate(files))
    direction = 1 if color else -1
    passed = 0
    blocked = 0
    center = 0
    for sq in pawns:
        file,rank = chess.square_file(sq),chess.square_rank(sq)
        passed += not any(abs(chess.square_file(o)-file)<=1 and (chess.square_rank(o)-rank)*direction>0 for o in opponents)
        next_rank = rank+direction
        blocked += 0<=next_rank<8 and bool(board.piece_at(chess.square(file,next_rank)))
        center += file in (3,4)
    king = board.king(color)
    king_distance = min(chess.square_distance(king,c) for c in (chess.D4,chess.E4,chess.D5,chess.E5))
    return dict(passed=passed,islands=islands,blocked=blocked,central_pawns=center,king_center=king_distance)


def matched_position(board,tracker,headers,ply):
    """A balanced original-bishop vs original-knight natural comparison."""
    ratings = [int(headers[k]) for k in ('WhiteElo','BlackElo')]
    # Both owners in same user band and near-equal rating for raw outcome fairness.
    if band(ratings[0]) != band(ratings[1]) or abs(ratings[0]-ratings[1])>100:
        return None
    minors = {}
    for color in (chess.WHITE,chess.BLACK):
        n,b = list(board.pieces(chess.KNIGHT,color)),list(board.pieces(chess.BISHOP,color))
        if len(n)+len(b)!=1:
            return None
        sq = (n+b)[0]
        if sq not in tracker.origins or board.promoted & chess.BB_SQUARES[sq]:
            return None
        minors[color] = chess.KNIGHT if n else chess.BISHOP
    if minors[chess.WHITE] == minors[chess.BLACK]:
        return None
    counts = {}
    for piece_type in (chess.PAWN,chess.ROOK,chess.QUEEN):
        white,black = [len(board.pieces(piece_type,c)) for c in (chess.WHITE,chess.BLACK)]
        if white!=black:
            return None
        counts[chess.piece_name(piece_type)+'s'] = white
    return dict(fen=board.fen(),ply=ply,bishop_color='white' if minors[chess.WHITE]==chess.BISHOP else 'black',
                side_to_move='white' if board.turn else 'black',
                white_pawns=pawn_features(board,chess.WHITE),black_pawns=pawn_features(board,chess.BLACK),**counts)


def analyze(raw,month,window_id,general):
    game = chess.pgn.read_game(io.StringIO(raw))
    if game is None or game.errors:
        raise ValueError('PGN error')
    h = game.headers
    nodes = list(game.mainline())
    if len(nodes)<2 or game.board().fen()!=chess.STARTING_FEN:
        raise ValueError('short/nonstandard')
    board = game.board()
    tracker = kb.Tracker(board)
    identifier = h['Site'].rsplit('/',1)[-1]
    speed = kb.speed(h.get('TimeControl',''))
    length = game_length(len(nodes))
    has_eval = '[%eval' in raw
    previous = node_cp(game) if has_eval else None
    eval_moves,counts,matches = [],Counter(),None
    total_original = Counter()
    for ply,node in enumerate(nodes,1):
        move = node.move
        if not move or not board.is_legal(move):
            raise ValueError('illegal move')
        color = board.turn
        identity = tracker.origins.get(move.from_square)
        current = node_cp(node) if has_eval else None
        if identity:
            total_original[identity] += 1
        if identity and previous is not None and current is not None:
            before = win_percent(previous)
            after = win_percent(current)
            sign = 1 if color else -1
            if not color:
                before,after = 100-before,100-after
            delta = after-before
            cp_before,cp_after = sign*previous,sign*current
            # Study-style cp loss, explicit practical-winning cutoff at +300cp.
            cp_blunder = int(cp_before-cp_after>=200 and not(cp_before>=300 and cp_after>=300))
            clock = node.clock()
            color_name = 'white' if color else 'black'
            piece = chess.piece_name(identity[1])
            rating = int(h['WhiteElo' if color else 'BlackElo'])
            counts[identity,'evaluated'] += 1
            counts[identity,'delta'] += delta
            counts[identity,'loss'] += max(0,-delta)
            counts[identity,'positive'] += max(0,delta)
            counts[identity,'cp_blunder'] += cp_blunder
            counts[identity,'wp_blunder'] += delta<=-20
            eval_moves.append((identifier,ply,window_id,piece,color_name,band(rating),h.get('TimeControl',''),speed,length,
                               clock,cp_before,cp_after,before,after,delta,max(0,-delta),cp_blunder,int(delta<=-20)))
        tracker.before_move(board,move)
        board.push(move)
        tracker.after_move(board)
        if general and matches is None and ply in CHECKPOINTS and ply+4<=len(nodes):
            matches = matched_position(board,tracker,h,ply)
        previous = current
    players = []
    for color,name,opponent in ((chess.WHITE,'White','Black'),(chess.BLACK,'Black','White')):
        rating = int(h[name+'Elo'])
        row = dict(game_id=identifier,window_id=window_id,month=month,utc_date=h.get('UTCDate',h.get('Date','')),
                   utc_time=h.get('UTCTime',''),color=name.lower(),rating=rating,opponent_rating=int(h[opponent+'Elo']),
                   rating_band=band(rating),speed=speed,time_control=h.get('TimeControl',''),game_length=length,
                   plies=len(nodes),result=h['Result'],opening=h.get('ECO','?'),termination=h.get('Termination',''),
                   player_hash=hashlib.sha256(h[name].encode()).hexdigest()[:16],
                   actual_win=int(h['Result']==('1-0' if color else '0-1')),draw=int(h['Result']=='1/2-1/2'))
        for piece_type,label in ((chess.KNIGHT,'knight'),(chess.BISHOP,'bishop')):
            key = color,piece_type
            row[label+'_capture'] = tracker.captures[key]/2
            row[label+'_influence'] = tracker.attacks[key]/(2*len(nodes))
            row[label+'_mobility'] = tracker.legal[key]/(2*tracker.turns[color])
            row[label+'_moves'] = total_original[key]
            row[label+'_eval_moves'] = counts[key,'evaluated']
            row[label+'_delta_pp'] = counts[key,'delta']/2
            row[label+'_loss_pp'] = counts[key,'loss']/2
            row[label+'_positive_pp'] = counts[key,'positive']/2
            row[label+'_cp_blunders'] = counts[key,'cp_blunder']
            row[label+'_wp_blunders'] = counts[key,'wp_blunder']
        total = row['knight_moves']+row['bishop_moves']
        valid = row['knight_eval_moves']+row['bishop_eval_moves']
        row['eval_coverage'] = valid/total if total else None
        # Per-game attribution only where both original piece groups have coverage.
        row['eval_qualified'] = int(total>0 and valid/total>=.8 and row['knight_eval_moves']>0 and row['bishop_eval_moves']>0)
        players.append(row)
    if matches:
        matches.update(game_id=identifier,window_id=window_id,month=month,rating_band=players[0]['rating_band'],
                       speed=speed,time_control=h.get('TimeControl',''),game_length=length,
                       white_rating=int(h['WhiteElo']),black_rating=int(h['BlackElo']),
                       result=h['Result'],opening=h.get('ECO','?'),utc_date=players[0]['utc_date'])
    return identifier,int(has_eval),players,matches,eval_moves


def decode_complete_frames(payload,as_bytes=False):
    """Find independent zstd frames in a byte range; never use incomplete frames."""
    start = payload.find(MAGIC)
    blocks,frames = [],[]
    while start>=0 and start<len(payload):
        try:
            decoder = zstandard.ZstdDecompressor().decompressobj()
            uncompressed = decoder.decompress(payload[start:])
        except zstandard.ZstdError:
            start = payload.find(MAGIC,start+1)
            continue
        if not decoder.eof:
            break
        consumed = len(payload)-start-len(decoder.unused_data)
        frames.append(dict(start=start,compressed_bytes=consumed,uncompressed_bytes=len(uncompressed)))
        blocks.append(uncompressed)
        start = payload.find(MAGIC,start+consumed)
    if not blocks:
        raise ValueError('No complete independent zstd frames in window')
    joined=b''.join(blocks)
    return (joined if as_bytes else joined.decode('utf-8',errors='replace')),frames


def game_boundary_stream(stream):
    """Skip a partial leading game without decoding a whole window to Unicode."""
    for line in stream:
        if line.startswith('[Event '):
            yield line
            break
    yield from stream


def range_bytes(url,start,size):
    with requests.get(url,headers={'Range':f'bytes={start}-{start+size-1}'},stream=True,timeout=90) as response:
        content_range = response.headers.get('Content-Range','')
        if response.status_code!=206 or not content_range.startswith(f'bytes {start}-'):
            raise ValueError(f'Server did not honor range: {content_range}')
        payload = response.raw.read(size+1)
        if len(payload)!=size:
            raise ValueError(f'Incorrect byte count {len(payload)} vs {size}')
        return payload,content_range


def process_window(task):
    logging.getLogger('chess.pgn').setLevel(logging.CRITICAL)
    started = time.monotonic()
    db_path = Path(task['db_path'])
    info_path = db_path.with_suffix('.json')
    if db_path.exists() and info_path.exists():
        info = json.loads(info_path.read_text(encoding='utf-8'))
        info['resumed'] = True
        return info
    last_error = None
    for attempt in range(3):
        try:
            payload,content_range = range_bytes(task['url'],task['offset'],task['window_bytes'])
            break
        except Exception as exc:
            last_error = str(exc)
            if attempt==2:
                raise
            time.sleep(2*(attempt+1))
    decoded,frames = decode_complete_frames(payload,as_bytes=True)
    digest = hashlib.sha256(payload).hexdigest()
    del payload
    stream=io.TextIOWrapper(io.BytesIO(decoded),encoding='utf-8',errors='replace')
    del decoded
    counts = Counter()
    with sqlite3.connect(db_path) as connection:
        connection.executescript(SCHEMA)
        for raw,complete in kb.records(game_boundary_stream(stream)):
            counts['records_seen'] += 1
            if not complete:
                counts['incomplete_tail'] += 1
                continue
            headers = dict(kb.HEADER.findall(raw))
            reason = kb.exclusion(headers)
            if reason:
                counts[reason] += 1
                continue
            if kb.RESULT.search(raw).group(1)!=headers['Result']:
                counts['result_mismatch'] += 1
                continue
            counts['header_eligible'] += 1
            identifier = headers['Site'].rsplit('/',1)[-1]
            general = stable_fraction(identifier,task['seed'])<task['sample_rate']
            annotated = '[%eval' in raw
            if not general and not annotated:
                counts['not_selected'] += 1
                continue
            try:
                identifier,has_eval,players,outcome,moves = analyze(raw,task['month'],task['id'],general)
            except (ValueError,KeyError,TypeError,AssertionError):
                counts['invalid_or_too_short'] += 1
                continue
            cursor = connection.execute('INSERT OR IGNORE INTO games VALUES(?,?,?,?,?,?,?)',
                (identifier,task['month'],task['id'],int(general),has_eval,json.dumps(players,separators=(',',':')),
                 json.dumps(outcome,separators=(',',':')) if outcome else None))
            if cursor.rowcount==0:
                counts['duplicate'] += 1
                continue
            connection.executemany('INSERT INTO moves VALUES('+','.join('?' for _ in range(18))+')',moves)
            counts['processed_games'] += 1
            counts['general_sample_games'] += int(general)
            counts['annotated_games'] += has_eval
            counts['evaluated_minor_moves'] += len(moves)
            counts['matched_outcome_games'] += int(outcome is not None)
            counts['qualified_evaluation_player_games'] += sum(x['eval_qualified'] for x in players)
        connection.commit()
    stream.close()
    info = dict(task=task,counts=dict(counts),frames=frames,sha256=digest,content_range=content_range,
                elapsed_seconds=round(time.monotonic()-started,2),retry_error=last_error)
    info_path.write_text(json.dumps(info,indent=2),encoding='utf-8')
    return info


def prepare_tasks(months,strata,window_mib,sample_rate,seed,work):
    rng = random.Random(seed)
    tasks,archives = [],[]
    size = window_mib*1024*1024
    for month in months:
        url = f'https://database.lichess.org/standard/lichess_db_standard_rated_{month}.pgn.zst'
        with requests.get(url,headers={'Range':'bytes=0-0'},stream=True,timeout=60) as response:
            content_range = response.headers.get('Content-Range','')
            total = int(content_range.rsplit('/',1)[1])
            response.raw.read(1)
        archives.append(dict(month=month,url=url,compressed_bytes=total))
        for i in range(strata):
            low,high = total*i//strata,total*(i+1)//strata
            if high-low<=size:
                raise ValueError('Window larger than byte stratum')
            offset = rng.randint(low,high-size)
            identifier = f'{month}_s{i:02d}'
            tasks.append(dict(id=identifier,month=month,url=url,archive_bytes=total,stratum=i,
                              stratum_start=low,stratum_end=high,offset=offset,window_bytes=size,
                              sample_rate=sample_rate,seed=seed,db_path=str((work/(identifier+'.sqlite')).resolve())))
    return tasks,archives


def run(args):
    args.work.mkdir(parents=True,exist_ok=True)
    args.out.mkdir(parents=True,exist_ok=True)
    plan = args.work/'plan.json'
    if plan.exists():
        saved = json.loads(plan.read_text(encoding='utf-8'))
        if saved['months']!=args.months or saved['strata']!=args.strata or saved['sample_rate']!=args.sample_rate or saved['tasks'][0]['seed']!=args.seed or saved['tasks'][0]['window_bytes']!=args.window_mib*1024*1024:
            raise ValueError('Existing plan settings differ; use a new work directory')
        tasks,archives = saved['tasks'],saved['archives']
    else:
        tasks,archives = prepare_tasks(args.months,args.strata,args.window_mib,args.sample_rate,args.seed,args.work)
        plan.write_text(json.dumps(dict(months=args.months,strata=args.strata,sample_rate=args.sample_rate,
                                       tasks=tasks,archives=archives),indent=2),encoding='utf-8')
    started = time.monotonic()
    infos = []
    # File-based worker coordination also works on Windows environments where
    # multiprocessing named pipes are unavailable. Helpers have no visible window.
    pending = iter(tasks)
    running = []
    finished_dispatch = False
    while running or not finished_dispatch:
        while len(running)<args.workers and not finished_dispatch:
            try:
                task = next(pending)
            except StopIteration:
                finished_dispatch = True
                break
            task_file = args.work/(task['id']+'_task.json')
            task_file.write_text(json.dumps(task),encoding='utf-8')
            log_path = args.work/(task['id']+'.log')
            log = log_path.open('w',encoding='utf-8')
            process = subprocess.Popen([sys.executable,'-m','knight_bishop_study.sampling','--task-file',str(task_file.resolve())],
                                       stdout=log,stderr=subprocess.STDOUT,
                                       creationflags=subprocess.CREATE_NO_WINDOW if sys.platform=='win32' else 0)
            running.append((process,task,log,log_path))
        for item in list(running):
            process,task,log,log_path = item
            status = process.poll()
            if status is None:
                continue
            log.close()
            running.remove(item)
            if status:
                for other,_,handle,_ in running:
                    other.terminate()
                    other.wait()
                    handle.close()
                raise RuntimeError(f"Worker {task['id']} failed: {log_path.read_text(encoding='utf-8')[-6000:]}")
            info = json.loads(Path(task['db_path']).with_suffix('.json').read_text(encoding='utf-8'))
            infos.append(info)
            c = info['counts']
            print(f"{len(infos)}/{len(tasks)} windows · {task['id']} · {c.get('records_seen',0):,} scanned · {c.get('general_sample_games',0):,} general · {c.get('annotated_games',0):,} eval · {time.monotonic()-started:.0f}s",flush=True)
        if running:
            time.sleep(.5)
    database = args.out/'study.sqlite'
    with sqlite3.connect(database) as connection:
        connection.executescript('PRAGMA cache_size=-131072; PRAGMA temp_store=MEMORY; PRAGMA synchronous=OFF; PRAGMA journal_mode=MEMORY;')
        connection.executescript(SCHEMA)
        for i,info in enumerate(sorted(infos,key=lambda x:x['task']['id'])):
            alias = 'part'
            connection.execute(f'ATTACH DATABASE ? AS {alias}',(info['task']['db_path'],))
            connection.execute('INSERT OR IGNORE INTO games SELECT * FROM part.games')
            connection.execute('INSERT OR IGNORE INTO moves SELECT * FROM part.moves')
            connection.commit()
            connection.execute('DETACH DATABASE part')
        connection.executescript('CREATE INDEX IF NOT EXISTS moves_group ON moves(rating_band,speed,game_length,piece); CREATE INDEX IF NOT EXISTS games_window ON games(window_id);')
        final_counts = dict(processed_games=connection.execute('SELECT COUNT(*) FROM games').fetchone()[0],
                            general_sample_games=connection.execute('SELECT COUNT(*) FROM games WHERE general_sample=1').fetchone()[0],
                            annotated_games=connection.execute('SELECT COUNT(*) FROM games WHERE has_eval=1').fetchone()[0],
                            evaluated_minor_moves=connection.execute('SELECT COUNT(*) FROM moves').fetchone()[0],
                            matched_outcome_games=connection.execute('SELECT COUNT(*) FROM games WHERE outcome IS NOT NULL').fetchone()[0])
    total_counts = Counter()
    for info in infos:
        total_counts.update(info['counts'])
    manifest = dict(method='stratified random compressed-byte windows, independent complete zstd frames; stable hash general sample; all annotated games retained separately',
                    months=args.months,strata_per_month=args.strata,window_mib=args.window_mib,seed=args.seed,
                    sample_rate=args.sample_rate,archives=archives,windows=sorted(infos,key=lambda x:x['task']['id']),
                    raw_downloaded_bytes=sum(x['task']['window_bytes'] for x in infos),
                    source_archive_bytes=sum(x['compressed_bytes'] for x in archives),
                    scanned_counts=dict(total_counts),unique_counts=final_counts,
                    archive_storage='RAM only; no archive windows retained on disk',elapsed_seconds=round(time.monotonic()-started,2))
    (args.out/'sampling_manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    # Reduced database is retained as the deliverable. Intermediate reduced shards
    # can be removed safely after successful merge; deletion never targets folders.
    for info in infos:
        path = Path(info['task']['db_path']).resolve()
        if not path.is_relative_to(args.work.resolve()):
            raise ValueError('Shard outside intended work directory')
        path.unlink()
    print(json.dumps(final_counts),flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--months',nargs='+',default=[f'2026-{m:02d}' for m in range(4,10)])
    parser.add_argument('--strata',type=int,default=8)
    parser.add_argument('--window-mib',type=int,default=16)
    parser.add_argument('--sample-rate',type=float,default=.06)
    parser.add_argument('--seed',type=int,default=20261009)
    parser.add_argument('--workers',type=int,default=3)
    parser.add_argument('--work',type=Path,default=Path('work/wide_study'))
    parser.add_argument('--out',type=Path,default=Path('results'))
    parser.add_argument('--task-file',type=Path)
    arguments = parser.parse_args(argv)
    if not 0<arguments.sample_rate<=1 or arguments.strata<1 or arguments.window_mib<8 or arguments.workers<1:
        parser.error('Require sample-rate in (0,1], positive strata at least 8 MiB per window and positive workers')
    if arguments.task_file:
        process_window(json.loads(arguments.task_file.read_text(encoding='utf-8')))
    else:
        run(arguments)


if __name__ == '__main__':
    main()

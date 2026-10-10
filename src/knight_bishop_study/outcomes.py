"""Search all sampled-window games for balanced B-v-N outcome positions.

Reuses the random-byte sampling plan; raw range payloads are RAM-only.
"""
import argparse
from collections import Counter
import hashlib
import io
import json
import logging
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

import chess
import chess.pgn
from . import core as kb
from . import sampling as study

SCHEMA = 'CREATE TABLE IF NOT EXISTS outcomes(game_id TEXT PRIMARY KEY,window_id TEXT,month TEXT,data TEXT);'


def find_position_reference(raw,headers,task):
    game = chess.pgn.read_game(io.StringIO(raw))
    if game is None or game.errors:
        return None
    nodes = list(game.mainline())
    if len(nodes)<44:
        return None
    board = game.board()
    tracker = kb.Tracker(board)
    if board.fen()!=chess.STARTING_FEN:
        return None
    for ply,node in enumerate(nodes,1):
        move = node.move
        if not move:
            return None
        identity = tracker.origins.get(move.from_square)
        tracker.origins.pop(move.to_square,None)
        if identity:
            del tracker.origins[move.from_square]
            tracker.origins[move.to_square]=identity
        board.push(move)
        if ply in study.CHECKPOINTS and ply+4<=len(nodes):
            match = study.matched_position(board,tracker,headers,ply)
            if match:
                match.update(game_id=headers['Site'].rsplit('/',1)[-1],window_id=task['id'],month=task['month'],
                             rating_band=study.band(int(headers['WhiteElo'])),speed=kb.speed(headers.get('TimeControl','')),
                             time_control=headers.get('TimeControl',''),game_length=study.game_length(len(nodes)),
                             white_rating=int(headers['WhiteElo']),black_rating=int(headers['BlackElo']),
                             result=headers['Result'],opening=headers.get('ECO','?'),
                             white_player_hash=hashlib.sha256(headers['White'].encode()).hexdigest()[:16],
                             black_player_hash=hashlib.sha256(headers['Black'].encode()).hexdigest()[:16],
                             utc_date=headers.get('UTCDate',headers.get('Date','')),utc_time=headers.get('UTCTime',''))
                return match
    return None


class ImpossibleMatch(Exception):
    pass


class SnapshotVisitor(chess.pgn.BaseVisitor):
    """Replay once without constructing a game tree or replaying it again."""
    def __init__(self):
        self.headers={}
        self.tracker=None
        self.plies=0
        self.match=None
        self.remaining={chess.WHITE:4,chess.BLACK:4}
        self.minor_counts=Counter({(c,t):2 for c in (chess.WHITE,chess.BLACK) for t in kb.TYPES})

    def visit_header(self,name,value):
        self.headers[name]=value

    def begin_variation(self):
        return chess.pgn.SKIP

    def visit_move(self,board,move):
        if not move:
            raise ValueError('Null move')
        self.plies+=1
        identity=self.tracker.origins.get(move.from_square)
        captured=self.tracker.origins.pop(move.to_square,None)
        if captured:
            self.remaining[captured[0]]-=1
            self.minor_counts[captured]-=1
        if identity:
            del self.tracker.origins[move.from_square]
            self.tracker.origins[move.to_square]=identity
        if self.match is None:
            if min(self.remaining.values())==0:
                raise ImpossibleMatch()
            if all(n==1 for n in self.remaining.values()) and self.minor_counts[chess.WHITE,chess.KNIGHT]==self.minor_counts[chess.BLACK,chess.KNIGHT]:
                raise ImpossibleMatch()

    def visit_board(self,board):
        if self.tracker is None:
            if board.fen()!=chess.STARTING_FEN:
                raise ValueError('Nonstandard')
            self.tracker=kb.Tracker(board)
        elif self.match is None and self.plies in study.CHECKPOINTS:
            self.match=study.matched_position(board,self.tracker,self.headers,self.plies)

    def result(self):
        return self


def find_position(raw,headers,task):
    try:
        result=chess.pgn.read_game(io.StringIO(raw),Visitor=SnapshotVisitor)
    except ImpossibleMatch:
        return None
    if result is None or result.match is None or result.match['ply']+4>result.plies:
        return None
    match=result.match
    match.update(game_id=headers['Site'].rsplit('/',1)[-1],window_id=task['id'],month=task['month'],
                 rating_band=study.band(int(headers['WhiteElo'])),speed=kb.speed(headers.get('TimeControl','')),
                 time_control=headers.get('TimeControl',''),game_length=study.game_length(result.plies),
                 white_rating=int(headers['WhiteElo']),black_rating=int(headers['BlackElo']),
                 result=headers['Result'],opening=headers.get('ECO','?'),
                 white_player_hash=hashlib.sha256(headers['White'].encode()).hexdigest()[:16],
                 black_player_hash=hashlib.sha256(headers['Black'].encode()).hexdigest()[:16],
                 utc_date=headers.get('UTCDate',headers.get('Date','')),utc_time=headers.get('UTCTime',''))
    return match


def worker_impl(task):
    logging.getLogger('chess.pgn').setLevel(logging.CRITICAL)
    path = Path(task['outcome_db'])
    info_path = path.with_suffix('.json')
    if path.exists() and info_path.exists():
        return
    started = time.monotonic()
    for attempt in range(3):
        try:
            payload,content_range = study.range_bytes(task['url'],task['offset'],task['window_bytes'])
            break
        except Exception:
            if attempt==2:
                raise
            time.sleep(2*(attempt+1))
    digest = hashlib.sha256(payload).hexdigest()
    decoded,frames = study.decode_complete_frames(payload,as_bytes=True)
    del payload
    counts = Counter()
    stream=io.TextIOWrapper(io.BytesIO(decoded),encoding='utf-8',errors='replace')
    del decoded
    with sqlite3.connect(path) as db:
        db.executescript(SCHEMA)
        for raw,complete in kb.records(study.game_boundary_stream(stream)):
            counts['records_seen']+=1
            if not complete:
                counts['incomplete_tail']+=1
                continue
            headers=dict(kb.HEADER.findall(raw))
            reason=kb.exclusion(headers)
            if reason:
                counts[reason]+=1
                continue
            if kb.RESULT.search(raw).group(1)!=headers['Result']:
                counts['result_mismatch']+=1
                continue
            counts['header_eligible']+=1
            white,black=int(headers['WhiteElo']),int(headers['BlackElo'])
            if study.band(white)!=study.band(black) or abs(white-black)>100:
                counts['unmatched_rating']+=1
                continue
            # At least six captures are necessary to remove six starting minors.
            # Comments are stripped first so annotations cannot affect this screen.
            movetext=raw.split('\n\n',1)[-1]
            if __import__('re').sub(r'\{[^}]*\}','',movetext).count('x')<6:
                counts['too_few_captures']+=1
                continue
            counts['replayed_candidates']+=1
            try:
                match=find_position(raw,headers,task)
            except (ValueError,KeyError,TypeError,AssertionError):
                counts['invalid']+=1
                continue
            if match:
                cursor=db.execute('INSERT OR IGNORE INTO outcomes VALUES(?,?,?,?)',
                                  (match['game_id'],task['id'],task['month'],json.dumps(match,separators=(',',':'))))
                counts['matched_outcome_games']+=cursor.rowcount
        db.commit()
    stream.close()
    info_path.write_text(json.dumps(dict(task=task,sha256=digest,content_range=content_range,counts=dict(counts),
                                         elapsed_seconds=round(time.monotonic()-started,2)),indent=2),encoding='utf-8')


def worker(task):
    """Prevent duplicate writers when resuming or dispatching extra workers."""
    path=Path(task['outcome_db'])
    info=path.with_suffix('.json')
    lock=path.with_suffix('.lock')
    while True:
        if path.exists() and info.exists():
            return
        try:
            lock.mkdir()
            break
        except FileExistsError:
            time.sleep(.5)
    try:
        worker_impl(task)
    finally:
        lock.rmdir()


def run(args):
    args.work.mkdir(parents=True,exist_ok=True)
    plan=json.loads(args.plan.read_text(encoding='utf-8'))
    tasks=[]
    for task in plan['tasks']:
        task=dict(task,outcome_db=str((args.work/(task['id']+'.sqlite')).resolve()))
        tasks.append(task)
    pending=iter(tasks)
    running=[]
    done=[]
    exhausted=False
    started=time.monotonic()
    while running or not exhausted:
        while len(running)<args.workers and not exhausted:
            try:
                task=next(pending)
            except StopIteration:
                exhausted=True
                break
            task_file=args.work/(task['id']+'_task.json')
            task_file.write_text(json.dumps(task),encoding='utf-8')
            log_path=args.work/(task['id']+'.log')
            log=log_path.open('w',encoding='utf-8')
            process=subprocess.Popen([sys.executable,'-m','knight_bishop_study.outcomes','--task-file',str(task_file.resolve())],
                                     stdout=log,stderr=subprocess.STDOUT,
                                     creationflags=subprocess.CREATE_NO_WINDOW if sys.platform=='win32' else 0)
            running.append((process,task,log,log_path))
        for item in list(running):
            process,task,log,log_path=item
            status=process.poll()
            if status is None:
                continue
            log.close()
            running.remove(item)
            if status:
                for other,_,handle,_ in running:
                    other.terminate();other.wait();handle.close()
                raise RuntimeError(log_path.read_text(encoding='utf-8')[-6000:])
            info=json.loads(Path(task['outcome_db']).with_suffix('.json').read_text(encoding='utf-8'))
            done.append(info)
            c=info['counts']
            print(f"Outcomes {len(done)}/{len(tasks)} · {task['id']} · {c.get('matched_outcome_games',0):,} matches · {time.monotonic()-started:.0f}s",flush=True)
        if running:
            time.sleep(.5)
    args.out.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(args.out/'outcomes.sqlite') as db:
        db.executescript('PRAGMA cache_size=-131072; PRAGMA temp_store=MEMORY; PRAGMA synchronous=OFF; PRAGMA journal_mode=MEMORY;')
        db.executescript(SCHEMA)
        for info in done:
            db.execute('ATTACH DATABASE ? AS part',(info['task']['outcome_db'],))
            db.execute('INSERT OR IGNORE INTO outcomes SELECT * FROM part.outcomes')
            db.commit();db.execute('DETACH DATABASE part')
        matches=db.execute('SELECT COUNT(*) FROM outcomes').fetchone()[0]
    manifest=dict(windows=sorted(done,key=lambda x:x['task']['id']),unique_matched_games=matches,
                  raw_downloaded_bytes=sum(x['task']['window_bytes'] for x in done),
                  sampling='same windows as capture/eval scan, every eligible outcome candidate searched',
                  elapsed_seconds=round(time.monotonic()-started,2))
    (args.out/'outcome_sampling_manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    for info in done:
        shard=Path(info['task']['outcome_db']).resolve()
        if not shard.is_relative_to(args.work.resolve()):
            raise ValueError('Out-of-workspace shard')
        shard.unlink()
    print('Unique balanced outcome games:',matches,flush=True)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan',type=Path,default=Path('work/wide_study/plan.json'))
    parser.add_argument('--work',type=Path,default=Path('work/outcomes'))
    parser.add_argument('--out',type=Path,default=Path('results'))
    parser.add_argument('--workers',type=int,default=3)
    parser.add_argument('--task-file',type=Path)
    args=parser.parse_args(argv)
    if args.workers<1:
        parser.error('workers must be positive')
    if args.task_file:
        worker(json.loads(args.task_file.read_text(encoding='utf-8')))
    else:
        run(args)


if __name__ == '__main__':
    main()

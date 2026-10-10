"""Check the retained data against sampling manifests and metric definitions."""
import json
from pathlib import Path
import sqlite3

import chess
from . import sampling as study



def main(out=Path('results')):
    OUT=Path(out)
    source=json.loads((OUT/'sampling_manifest.json').read_text(encoding='utf-8'))
    outcome=json.loads((OUT/'outcome_sampling_manifest.json').read_text(encoding='utf-8'))
    hashes={r['task']['id']:r['sha256'] for r in source['windows']}
    assert len(hashes)>0 and len(hashes)==len(outcome['windows'])
    assert all(hashes[r['task']['id']]==r['sha256'] for r in outcome['windows'])
    db=sqlite3.connect(OUT/'study.sqlite')
    assert db.execute('PRAGMA quick_check').fetchone()[0]=='ok'
    counts=source['unique_counts']
    assert db.execute('SELECT COUNT(*) FROM games').fetchone()[0]==counts['processed_games']
    assert db.execute('SELECT COUNT(*) FROM moves').fetchone()[0]==counts['evaluated_minor_moves']
    invalid=db.execute('''SELECT COUNT(*) FROM moves WHERE
       win_before<0 OR win_before>100 OR win_after<0 OR win_after>100
       OR abs(delta_pp-(win_after-win_before))>1e-8
       OR abs(loss_pp-max(0,-delta_pp))>1e-8
       OR blunder_200cp!=(cp_before-cp_after>=200 AND NOT(cp_before>=300 AND cp_after>=300))
       OR blunder_20pp!=(loss_pp>=20)''').fetchone()[0]
    assert invalid==0
    rows=0
    for general,players in db.execute('SELECT general_sample,players FROM games'):
        pair=json.loads(players)
        assert len(pair)==2
        for player in pair:
            assert player['rating']>=500
            assert study.band(player['rating'])==player['rating_band']
            rows+=int(general)
    assert rows==2*counts['general_sample_games']
    db.close()
    db=sqlite3.connect(OUT/'outcomes.sqlite')
    assert db.execute('PRAGMA quick_check').fetchone()[0]=='ok'
    matches=0
    for text, in db.execute('SELECT data FROM outcomes'):
        row=json.loads(text)
        board=chess.Board(row['fen'])
        assert board.is_valid()
        assert min(row['white_rating'],row['black_rating'])>=500
        assert abs(row['white_rating']-row['black_rating'])<=100
        assert study.band(row['white_rating'])==study.band(row['black_rating'])==row['rating_band']
        assert row['ply'] in study.CHECKPOINTS
        assert row['result'] in ('1-0','0-1','1/2-1/2')
        for piece in (chess.PAWN,chess.ROOK,chess.QUEEN):
            assert len(board.pieces(piece,chess.WHITE))==len(board.pieces(piece,chess.BLACK))
        for color in (chess.WHITE,chess.BLACK):
            bishop=(row['bishop_color']=='white')==color
            assert len(board.pieces(chess.BISHOP,color))==int(bishop)
            assert len(board.pieces(chess.KNIGHT,color))==int(not bishop)
        matches+=1
    assert matches==outcome['unique_matched_games']
    db.close()
    result=dict(validated_games=counts['processed_games'],validated_evaluated_moves=counts['evaluated_minor_moves'],
                validated_matched_positions=matches,invalid_move_records=invalid,
                source_and_outcome_window_hashes_equal=True,sqlite_quick_checks='ok')
    (OUT/'data_validation.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    main()

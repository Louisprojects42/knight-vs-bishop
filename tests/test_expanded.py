import io
import unittest
import chess
import zstandard
from knight_bishop_study import sampling as study
from knight_bishop_study import core as kb
from knight_bishop_study import analysis
import numpy as np

class ExpandedTests(unittest.TestCase):
    def test_rating_boundaries(self):
        values = {500:'500-750',749:'500-750',750:'750-1000',999:'750-1000',1000:'1000-1500',
                  1499:'1000-1500',1500:'1500-2000',1999:'1500-2000',2000:'2000-2500',
                  2499:'2000-2500',2500:'2500+',3200:'2500+'}
        for rating,label in values.items():
            self.assertEqual(study.band(rating),label)

    def test_move_length_boundaries(self):
        self.assertEqual(study.game_length(40),'1-20 moves')
        self.assertEqual(study.game_length(41),'21-40 moves')
        self.assertEqual(study.game_length(80),'21-40 moves')
        self.assertEqual(study.game_length(81),'41-60 moves')
        self.assertEqual(study.game_length(121),'61+ moves')

    def test_winning_chance_mapping(self):
        self.assertEqual(study.win_percent(0),50)
        self.assertAlmostEqual(study.win_percent(100)+study.win_percent(-100),100)
        self.assertGreater(study.win_percent(200),study.win_percent(100))

    def test_range_frame_recovery_discards_incomplete_tail(self):
        compress = zstandard.ZstdCompressor()
        first = compress.compress(b'first')
        second = compress.compress(b'second')
        third = compress.compress(b'third')
        decoded,frames = study.decode_complete_frames(b'partial-start'+first+second+third[:5])
        self.assertEqual(decoded,'firstsecond')
        self.assertEqual(len(frames),2)

    def test_streamed_unicode_pgn_boundaries(self):
        payload='partial previous game\n[Event "Rated Blitz game"]\n[White "棋手"]\n\n1. e4 e5 1-0\n\n[Event "Next"]\n\n1. d4'
        compressed=zstandard.ZstdCompressor().compress(payload.encode('utf-8'))
        decoded,_=study.decode_complete_frames(compressed,as_bytes=True)
        stream=io.TextIOWrapper(io.BytesIO(decoded),encoding='utf-8')
        records=list(kb.records(study.game_boundary_stream(stream)))
        self.assertEqual(len(records),2)
        self.assertIn('棋手',records[0][0])
        self.assertEqual([r[1] for r in records],[True,False])

    def test_black_eval_sign_and_missing_adjacency(self):
        raw = '''[Event "Rated Blitz game"]
[Site "https://lichess.org/Test1234"]
[White "A"]
[Black "B"]
[WhiteElo "1000"]
[BlackElo "1050"]
[TimeControl "300+0"]
[Result "1-0"]

1. e4 { [%eval 0.2] [%clk 0:05:00] } e5 { [%eval 0.3] [%clk 0:05:00] }
2. Nf3 { [%eval 0.1] [%clk 0:04:58] } Nc6 { [%eval 0.5] [%clk 0:04:57] }
3. Bc4 { [%clk 0:04:54] } Nf6 { [%eval 0.9] [%clk 0:04:54] } 1-0
'''
        _,_,players,_,moves = study.analyze(raw,'2026-04','test',True)
        self.assertEqual(len(moves),2)
        self.assertEqual([m[1] for m in moves],[3,4])
        self.assertLess(moves[0][14],0)
        self.assertLess(moves[1][14],0)
        self.assertEqual(moves[1][10],-10)
        self.assertEqual(moves[1][11],-50)
        self.assertEqual(moves[1][4],'black')
        self.assertEqual(moves[1][9],297)

    def test_matched_position_requires_balanced_material(self):
        h={'WhiteElo':'1500','BlackElo':'1550'}
        board=chess.Board('4k3/5n2/4p3/8/8/3P4/2B5/4K3 w - - 0 21')
        tracker=kb.Tracker(board)
        match=study.matched_position(board,tracker,h,40)
        self.assertEqual(match['bishop_color'],'white')
        self.assertEqual(match['pawns'],1)
        board.remove_piece_at(chess.E6)
        self.assertIsNone(study.matched_position(board,tracker,h,40))

    def test_matched_position_rejects_large_rating_gap(self):
        board=chess.Board('4k3/5n2/4p3/8/8/3P4/2B5/4K3 w - - 0 21')
        self.assertIsNone(study.matched_position(board,kb.Tracker(board),{'WhiteElo':'1500','BlackElo':'1700'},40))

    def test_logistic_fit_recovers_a_known_win_association(self):
        rng=np.random.default_rng(42)
        x=np.column_stack([np.ones(10000),rng.integers(0,2,10000),rng.normal(size=10000)])
        truth=np.array([-.5,.6,.8])
        probability=1/(1+np.exp(-(x@truth)))
        target=rng.binomial(1,probability)
        beta,_,_,info=analysis.logistic_fit(x,target)
        self.assertTrue(info['converged'])
        np.testing.assert_allclose(beta,truth,atol=.1)

    def test_model_type_swap_updates_rating_interactions(self):
        x=np.zeros((2,34))
        x[:,0]=1
        x[0,14]=1
        x[1,18]=1
        x[:,19:24]=x[:,14:19]
        knight,bishop=analysis.bishop_versions(x)
        np.testing.assert_equal(knight[:,19:24],0)
        np.testing.assert_equal(knight[:,1],0)
        np.testing.assert_equal(bishop[:,1],1)
        np.testing.assert_equal(bishop[:,19:24],bishop[:,14:19])

    def test_cluster_ratio_uses_opportunities_not_cell_means(self):
        matrix=np.array([[1,1,3],[9,18,9]],float)
        weights=np.array([[1,1],[2,0],[0,2]],float)
        comparison=analysis.compare(matrix,weights,1,2,0)
        self.assertAlmostEqual(comparison['knight'],1.9)
        self.assertAlmostEqual(comparison['bishop'],1.2)
        self.assertAlmostEqual(comparison['difference'],-.7)

if __name__=='__main__':
    unittest.main()

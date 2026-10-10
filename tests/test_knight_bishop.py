"""Small behavioral tests for the analysis, using hand-checkable positions."""
import io
import unittest

import chess
import chess.pgn
from knight_bishop_study import core as kb


def advance(tracker, board, uci):
    move = chess.Move.from_uci(uci)
    assert board.is_legal(move), (board.fen(), uci)
    tracker.before_move(board, move)
    board.push(move)
    tracker.after_move(board)


class AnalysisTests(unittest.TestCase):
    def test_captured_piece_stops_contributing(self):
        board = chess.Board('4k3/8/8/3p4/8/2N5/8/4K3 w - - 0 1')
        tracker = kb.Tracker(board)
        advance(tracker, board, 'c3b5')
        before = tracker.attacks[chess.WHITE, chess.KNIGHT]
        advance(tracker, board, 'd5d4')
        advance(tracker, board, 'b5c3')
        advance(tracker, board, 'd4c3')
        at_capture = tracker.attacks[chess.WHITE, chess.KNIGHT]
        advance(tracker, board, 'e1f1')
        self.assertGreater(at_capture, before)
        self.assertEqual(tracker.attacks[chess.WHITE, chess.KNIGHT], at_capture)
        self.assertFalse(any(key[0] == chess.WHITE for key in tracker.origins.values()))

    def test_promotion_does_not_become_an_original_knight(self):
        board = chess.Board('4k3/P1r5/8/8/8/8/8/3K4 w - - 0 1')
        tracker = kb.Tracker(board)
        for uci in ('a7a8n', 'e8e7', 'a8c7'):
            advance(tracker, board, uci)
        self.assertEqual(sum(tracker.captures.values()), 0)
        self.assertEqual(sum(tracker.attacks.values()), 0)

    def test_capturing_promoted_minor_counts_three(self):
        board = chess.Board('4k3/8/8/8/4B3/8/1p6/4K3 b - - 0 1')
        tracker = kb.Tracker(board)
        advance(tracker, board, 'b2b1n')
        advance(tracker, board, 'e4b1')
        self.assertEqual(tracker.captures[chess.WHITE, chess.BISHOP], 3)

    def test_pinned_knight_has_attacks_but_no_legal_mobility(self):
        board = chess.Board('k3r3/8/8/8/8/8/4N3/4K3 w - - 0 1')
        tracker = kb.Tracker(board)
        advance(tracker, board, 'e1d1')
        self.assertEqual(tracker.legal[chess.WHITE, chess.KNIGHT], 0)
        self.assertGreater(tracker.attacks[chess.WHITE, chess.KNIGHT], 0)

    def test_known_capture_game_and_two_piece_denominator(self):
        game = chess.pgn.read_game(io.StringIO('''[Event "Rated Blitz game"]
[Site "https://lichess.org/Test1234"]
[White "A"]
[Black "B"]
[WhiteElo "1000"]
[BlackElo "1300"]
[TimeControl "300+0"]
[Result "1-0"]

1. e4 e5 2. Nf3 Nc6 3. Bc4 Nf6 4. Ng5 d5 5. exd5 Nxd5
6. Nxf7 Kxf7 7. Bxd5+ 1-0
'''))
        white, black = kb.analyze_game(game)
        self.assertEqual(white['knight_capture'], 1/2)
        self.assertEqual(white['bishop_capture'], 3/2)
        self.assertEqual(black['knight_capture'], 1/2)
        self.assertEqual(white['rating_bin'], '1000-1249')
        self.assertEqual(black['rating_bin'], '1250-1499')
        self.assertEqual(white['knight_captured_pawn'], 1)
        self.assertEqual(white['bishop_captured_knight'], 1)

    def test_rating_floor_either_player_and_exactly_500(self):
        h = dict(Event='Rated Blitz game', Site='https://lichess.org/Test1234',
                 White='A', Black='B', Result='1-0', WhiteElo='500', BlackElo='499')
        self.assertEqual(kb.exclusion(h), 'below_rating_floor')
        h['BlackElo'] = '500'
        self.assertIsNone(kb.exclusion(h))
        h['WhiteElo'] = '?'
        self.assertEqual(kb.exclusion(h), 'missing_rating')
        h['WhiteElo'] = '500'
        h['BlackTitle'] = 'BOT'
        self.assertEqual(kb.exclusion(h), 'bot')

    def test_incomplete_tail_is_not_a_completed_game(self):
        stream = io.StringIO('[Event "A"]\n\n1. e4 e5 1-0\n\n[Event "B"]\n\n1. d4')
        self.assertEqual([complete for _, complete in kb.records(stream)], [True, False])

    def test_clustered_pairing_cancels_equal_metrics(self):
        rows = [dict(game_id=str(i), speed='blitz', rating_bin='1000-1249',
                     **{piece+'_'+metric: float(i) for piece in ('knight', 'bishop')
                        for metric in kb.METRICS}) for i in range(5) for _ in range(2)]
        summary = kb.clustered_summary(rows, repetitions=100, minimum_games=1)
        all_games = next(x for x in summary if x['speed']=='all' and x['rating_bin']=='all')
        self.assertEqual(all_games['games'], 5)
        self.assertEqual(all_games['player_games'], 10)
        self.assertEqual(all_games['capture_bishop_minus_knight'], 0)
        self.assertEqual(all_games['capture_ci_low'], 0)
        self.assertEqual(all_games['capture_ci_high'], 0)
        self.assertEqual(all_games['capture_leader'], 'inconclusive')


if __name__ == '__main__':
    unittest.main()

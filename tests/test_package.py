"""Regression checks for portability and command-line behavior."""
import argparse
import contextlib
import importlib
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest

from knight_bishop_study import analysis, cli, outcomes, sampling


class PackageTests(unittest.TestCase):
    def test_workers_zero_is_rejected_before_download(self):
        for run in (sampling.main,outcomes.main):
            with contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit) as error:
                run(['--workers','0'])
            self.assertEqual(error.exception.code,2)

    def test_resume_rejects_a_changed_seed_or_window_size(self):
        with tempfile.TemporaryDirectory() as folder:
            work=Path(folder)/'work'
            work.mkdir()
            saved=dict(months=['2026-04'],strata=8,sample_rate=.06,
                       tasks=[dict(seed=42,window_bytes=16*1024*1024)],archives=[])
            (work/'plan.json').write_text(json.dumps(saved),encoding='utf-8')
            for seed,size in ((43,16),(42,32)):
                args=argparse.Namespace(work=work,out=Path(folder)/'results',months=['2026-04'],
                                        strata=8,sample_rate=.06,seed=seed,window_mib=size)
                with self.assertRaisesRegex(ValueError,'settings differ'):
                    sampling.run(args)

    def test_model_month_controls_follow_the_supplied_cohort(self):
        pawn=dict(passed=0,islands=1,blocked=0,central_pawns=0,king_center=2)
        row=dict(white_pawns=pawn,black_pawns=pawn,bishop_color='white',white_rating=1500,black_rating=1500,
                 side_to_move='white',pawns=3,rooks=0,queens=0,ply=40,rating_band='1500-2000',
                 speed='blitz',result='1-0',window_id='test')
        x,_,_,names=analysis.design([dict(row,month='2025-01'),dict(row,month='2025-02')])
        self.assertIn('month_2025-02',names)
        self.assertFalse(any(name.startswith('month_2026') for name in names))
        self.assertEqual(x[0,names.index('month_2025-02')],0)
        self.assertEqual(x[2,names.index('month_2025-02')],1)

    def test_plotting_imports_do_not_require_results_in_the_current_directory(self):
        previous=Path.cwd()
        with tempfile.TemporaryDirectory() as folder:
            try:
                os.chdir(folder)
                importlib.import_module('knight_bishop_study.reporting')
                importlib.import_module('knight_bishop_study.visuals')
                self.assertEqual(list(Path(folder).iterdir()),[])
            finally:
                os.chdir(previous)

    def test_missing_summary_has_an_actionable_cli_error(self):
        with tempfile.TemporaryDirectory() as folder,contextlib.redirect_stderr(io.StringIO()) as output:
            with self.assertRaises(SystemExit) as error:
                cli.main(['summary','--results',folder])
            self.assertEqual(error.exception.code,2)
            self.assertIn('docs/DATA.md',output.getvalue())

    def test_empty_rating_cells_render_as_missing_without_plotting_failures(self):
        from knight_bishop_study import reporting, visuals
        published=Path(__file__).resolve().parents[1]/'results'
        with tempfile.TemporaryDirectory() as folder,contextlib.redirect_stdout(io.StringIO()):
            target=Path(folder)
            data=json.loads((published/'results.json').read_text(encoding='utf-8'))
            for cohort in ('captures','evaluations','outcomes'):
                data[cohort]=[row for row in data[cohort] if row['rating_band']!='500-750']
            for row in data['outcomes']:
                if row['game_length']!='all':
                    row['matched_games']=min(row['matched_games'],199)
            (target/'results.json').write_text(json.dumps(data),encoding='utf-8')
            for name in ('sampling_manifest.json','clock_normalization.csv'):
                shutil.copy2(published/name,target/name)
            reporting.main(target)
            visuals.main(target)
            self.assertTrue('outcome cohort has 0 games' in (target/'graphs.html').read_text(encoding='utf-8'))
            self.assertIn('| 500-750 | 0 | — / — |',(target/'report.md').read_text(encoding='utf-8'))


if __name__=='__main__':
    unittest.main()

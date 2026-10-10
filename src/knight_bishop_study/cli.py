"""Small command-line front end with no downloads during import or rendering."""
import argparse
import json
from pathlib import Path
import sys

from . import __version__


def main(argv=None):
    argv=list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ('sample','outcomes'):
        if argv[0]=='sample':
            from .sampling import main as run
        else:
            from .outcomes import main as run
        return run(argv[1:])
    parser=argparse.ArgumentParser(prog='kb-study',description='Compare original knights and bishops using Lichess games.')
    parser.add_argument('--version',action='version',version=__version__)
    commands=parser.add_subparsers(dest='command',required=True)
    commands.add_parser('sample',help='Sample distributed archive windows; use sample --help for options.')
    commands.add_parser('outcomes',help='Search every sampled game for balanced outcomes; use outcomes --help.')
    for name,help_text in (
        ('analyze','Aggregate reduced databases and fit the outcome model.'),
        ('render','Build the report, all graphs, and static gallery from retained summaries.'),
        ('validate','Check reduced databases, positions, and source hashes.'),
        ('summary','Print cohort sizes and the main outcome estimate.')):
        command=commands.add_parser(name,help=help_text)
        command.add_argument('--results',type=Path,default=Path('results'),help='Result directory (default: results).')
    args=parser.parse_args(argv)
    try:
        if args.command=='analyze':
            from .analysis import main as run
            return run(args.results)
        if args.command=='validate':
            from .validation import main as run
            return run(args.results)
        if args.command=='render':
            from .reporting import main as report
            from .visuals import main as graphs
            report(args.results)
            return graphs(args.results)
        result=json.loads((args.results/'results.json').read_text(encoding='utf-8'))
        overall=next(r for r in result['outcomes'] if (r['speed'],r['rating_band'],r['game_length'])==('all','all','all'))
        print(json.dumps(dict(metadata=result['metadata'],overall_outcomes=overall),indent=2))
    except FileNotFoundError as error:
        parser.error(f'Missing input: {error.filename}. See docs/DATA.md for the required reduced data or run sample/outcomes first.')

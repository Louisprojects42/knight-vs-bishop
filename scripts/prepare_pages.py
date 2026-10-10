"""Prepare static files for the optional manual Pages deployment."""
import os
from pathlib import Path
import re
import shutil

root=Path(__file__).resolve().parents[1]
site=root/'work/site'
site.mkdir(parents=True,exist_ok=True)
repository=os.environ.get('GITHUB_REPOSITORY','')
if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repository):
    raise SystemExit('Set GITHUB_REPOSITORY to the published OWNER/REPOSITORY for Pages links.')
excluded={'player_games.csv','evaluated_player_games.csv','matched_positions.csv'}
for file in (root/'results').iterdir():
    if file.is_file() and file.suffix in ('.html','.png','.svg','.json','.csv','.md','.txt') and file.name not in excluded:
        if file.stat().st_size>20*1024*1024:
            raise ValueError(f'Unexpectedly large website artifact: {file.name}')
        target=site/file.name
        if file.suffix in ('.html','.md'):
            text=file.read_text(encoding='utf-8').replace('../docs/',f'https://github.com/{repository}/blob/main/docs/')
            target.write_text(text,encoding='utf-8')
        else:
            shutil.copy2(file,target)
print('Prepared static Pages artifact at',site)

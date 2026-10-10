"""Verify and import the published reduced-data archive without unrestricted extraction."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

FILES=('study.sqlite','outcomes.sqlite','player_games.csv','evaluated_player_games.csv','matched_positions.csv','clock_normalization.csv')


def digest(path):
    with path.open('rb') as handle:
        return hashlib.file_digest(handle,'sha256').hexdigest()


def import_data(archive_path,results,manifest_path):
    manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
    if archive_path.stat().st_size!=manifest['archive']['bytes'] or digest(archive_path)!=manifest['archive']['sha256']:
        raise ValueError('Archive size or SHA-256 does not match the published asset.')
    results.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(archive_path) as archive:
        for name in FILES:
            entry='expanded/'+name
            expected=manifest['members'][entry]
            info=archive.getinfo(entry)
            if info.file_size!=expected['bytes']:
                raise ValueError(f'Unexpected size for {name}')
            target=results/name
            if target.exists():
                if target.stat().st_size==expected['bytes'] and digest(target)==expected['sha256']:
                    print('Already verified:',name)
                    continue
                raise FileExistsError(f'Refusing to replace different existing data: {target}')
            temporary=results/(name+'.partial')
            checksum=hashlib.sha256()
            written=0
            # Exclusive creation preserves any unrelated or interrupted partial file.
            handle=temporary.open('xb')
            try:
                with handle,archive.open(entry) as source:
                    while chunk:=source.read(1024*1024):
                        written+=len(chunk)
                        if written>expected['bytes']:
                            raise ValueError(f'Exceeded expected size for {name}')
                        checksum.update(chunk)
                        handle.write(chunk)
                if written!=expected['bytes'] or checksum.hexdigest()!=expected['sha256']:
                    raise ValueError(f'Invalid checksum for {name}')
                temporary.replace(target)
            except BaseException:
                handle.close()
                temporary.unlink(missing_ok=True)
                raise
            print('Imported and verified:',name)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive',type=Path)
    parser.add_argument('--results',type=Path,default=Path('results'))
    parser.add_argument('--manifest',type=Path,default=Path(__file__).resolve().parents[1]/'docs/data_assets.json')
    args=parser.parse_args()
    import_data(args.archive,args.results,args.manifest)


if __name__=='__main__':
    main()

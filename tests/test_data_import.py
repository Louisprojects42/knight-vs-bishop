import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

spec=importlib.util.spec_from_file_location('data_import',Path(__file__).resolve().parents[1]/'scripts/import_reduced_data.py')
importer=importlib.util.module_from_spec(spec)
spec.loader.exec_module(importer)


def fixture(folder):
    archive=folder/'asset.zip'
    members={}
    with zipfile.ZipFile(archive,'w') as zipped:
        for name in importer.FILES:
            content=('synthetic '+name).encode()
            entry='expanded/'+name
            zipped.writestr(entry,content)
            members[entry]=dict(bytes=len(content),sha256=hashlib.sha256(content).hexdigest())
        zipped.writestr('../outside.txt','must never be extracted')
    manifest=folder/'asset.json'
    manifest.write_text(json.dumps(dict(archive=dict(bytes=archive.stat().st_size,sha256=importer.digest(archive)),members=members)),encoding='utf-8')
    return archive,manifest


class DataImportTests(unittest.TestCase):
    def test_import_is_limited_to_verified_members_and_identical_files_are_retained(self):
        with tempfile.TemporaryDirectory() as directory,contextlib.redirect_stdout(io.StringIO()):
            folder=Path(directory)
            archive,manifest=fixture(folder)
            out=folder/'results'
            importer.import_data(archive,out,manifest)
            importer.import_data(archive,out,manifest)
            self.assertEqual({p.name for p in out.iterdir()},set(importer.FILES))
            self.assertFalse((folder/'outside.txt').exists())

    def test_changed_existing_data_is_not_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            archive,manifest=fixture(folder)
            out=folder/'results'
            out.mkdir()
            target=out/'study.sqlite'
            target.write_bytes(b'user data')
            with self.assertRaises(FileExistsError):
                importer.import_data(archive,out,manifest)
            self.assertEqual(target.read_bytes(),b'user data')

    def test_wrong_member_checksum_leaves_no_invalid_or_partial_file(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            archive,manifest=fixture(folder)
            record=json.loads(manifest.read_text(encoding='utf-8'))
            record['members']['expanded/study.sqlite']['sha256']='0'*64
            manifest.write_text(json.dumps(record),encoding='utf-8')
            out=folder/'results'
            with self.assertRaisesRegex(ValueError,'checksum'):
                importer.import_data(archive,out,manifest)
            self.assertEqual(list(out.iterdir()),[])


if __name__=='__main__':
    unittest.main()

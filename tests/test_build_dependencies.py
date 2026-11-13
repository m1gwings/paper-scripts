"""Dependency cache retains live save detection and recorder discovery."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'lib'))
import build

class DependencyTest(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        previous=Path.cwd();os.chdir(self.folder.name);self.addCleanup(os.chdir,previous)
        build._DEPENDENCIES.clear()
        self.source=Path('main.tex');self.source.write_text('source')
        Path('output/.latex').mkdir(parents=True)
        self.recorder=Path('output/.latex/main.fls')
        self.recorder.write_text('INPUT main.tex\nINPUT body.tex\n')
        Path('body.tex').write_text('first')
    def scan(self):
        return build.dependencies(self.source,Path('output'))
    def test_reuses_graph_but_live_stamps_detect_source_changes(self):
        paths=self.scan();old=build.file_stamp(Path('body.tex'))
        with patch.object(Path,'read_text',side_effect=AssertionError('Reparsed unchanged dependency graph')):
            again=self.scan()
        self.assertEqual(paths,again)
        again.clear();self.assertTrue(self.scan())
        Path('body.tex').write_text('second version')
        self.assertNotEqual(old,build.file_stamp(Path('body.tex')))
        self.assertIn(Path('body.tex').resolve(),self.scan())
    def test_recorder_replacement_and_missing_input_invalidate(self):
        self.scan()
        replacement=self.recorder.with_suffix('.tmp')
        replacement.write_text('INPUT main.tex\nINPUT missing/new.tex\n')
        replacement.replace(self.recorder)
        paths=self.scan()
        self.assertIn(Path('missing/new.tex').resolve(),paths)
        self.assertIn(Path('missing').resolve(),paths)
        self.assertNotIn(Path('body.tex').resolve(),paths)
        self.recorder.unlink()
        self.assertNotIn(Path('missing/new.tex').resolve(),self.scan())
    def test_bibtex_database_changes_discover_bibliography(self):
        self.scan()
        Path('output/.latex/main.fdb_latexmk').write_text('  "new.bib" 1\n')
        self.assertIn(Path('new.bib').resolve(),self.scan())

if __name__=='__main__':unittest.main()

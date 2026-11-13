"""Capture, drift rejection and isolated restoration identities."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'lib'))
import tex_environment as tex
LOG = '''This is pdfTeX, Version 3.141592653-2.6-1.40.27 (TeX Live 2025) (preloaded format=pdflatex)
LaTeX2e <2025-06-01> patch level 1
Document Class: article 2025/01/22 v1.4n Standard LaTeX document class
Package: amsmath 2025/05/18 v2.17x AMS math features
'''
RECIPE = dict(repository='https://texlive.info/tlnet-archive/2025/06/15/tlnet', installer_sha256='a'*64,
              catalogue_sha256='b'*64, packages=['latex', 'latexmk'],
              engine_version='pdfTeX 3.141592653-2.6-1.40.27 (TeX Live 2025)')
SCRIPT = Path(__file__).resolve().parents[1]/'paper'
class EnvironmentTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        self.log = self.root/'overleaf.log'
        self.log.write_text(LOG)
        self.recipe = self.root/'recipe.json'
        self.recipe.write_text(json.dumps(RECIPE))
    def paper(self, *args):
        return subprocess.run(['bash', str(SCRIPT), *args], cwd=self.root, capture_output=True, text=True)
    def capture(self):
        r = self.paper('tex', 'capture', '--log', str(self.log), '--recipe', str(self.recipe))
        self.assertEqual(r.returncode, 0, r.stderr)
    def test_capture_drift_and_no_implicit_replacement(self):
        self.capture()
        manifest = self.root/tex.MANIFEST
        original = manifest.read_bytes()
        self.assertIn('class/article', json.loads(original)['baseline'])
        self.assertEqual(self.paper('tex', 'check', str(self.log)).returncode, 0)
        self.log.write_text(LOG.replace('v2.17x', 'v2.17y'))
        changed = self.paper('tex', 'check', str(self.log))
        self.assertEqual(changed.returncode, 1)
        self.assertIn('package/amsmath', changed.stdout)
        retry = self.paper('tex', 'capture', '--log', str(self.log), '--recipe', str(self.recipe))
        self.assertNotEqual(retry.returncode, 0)
        self.assertEqual(manifest.read_bytes(), original)
    def test_reject_console_output_and_unfrozen_recipe(self):
        self.log.write_text('Latexmk: All targets are up-to-date')
        with self.assertRaises(ValueError): tex.environment(self.log)
        with self.assertRaises(ValueError): tex.validate_recipe(dict(RECIPE, repository='https://mirror.ctan.org/tlnet'))
        with self.assertRaises(ValueError): tex.validate_recipe(dict(RECIPE, packages=['--reinstall']))
    def test_recipe_identity(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(tex.installation_root(RECIPE), tex.installation_root(dict(RECIPE)))
            self.assertEqual(tex.installation_root(RECIPE), tex.installation_root(dict(RECIPE, packages=['latex'])))
            self.assertNotEqual(tex.installation_root(RECIPE), tex.installation_root(dict(RECIPE, catalogue_sha256='c'*64)))
    def test_missing_toolchain_fails_without_fallback(self):
        self.capture()
        (self.root/'main.tex').write_text(r'\documentclass{article}\begin{document}Hi\end{document}')
        with patch.dict(os.environ, {'PAPER_TEXLIVE_ROOT': str(self.root/'absent')}): result = self.paper('build')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('paper tex install', result.stderr)
        self.assertEqual(json.loads((self.root/'output/.latex/main.build.json').read_text())['state'], 'failed')
    def test_missing_and_added_packages_are_drift(self):
        baseline = tex.environment(self.log)
        self.log.write_text(LOG.replace('Package: amsmath', 'Package: other'))
        self.assertEqual(len(tex.differences(self.log, {'baseline': baseline})), 2)
    def test_fresh_restore_and_second_install_reuses_cache(self):
        import tarfile
        import tex_install
        root = self.root/'texlive'
        def download(url, destination, expected):
            if url.endswith('.tar.gz'):
                installer = self.root/'install-tl'
                installer.write_text('# placeholder installer for orchestration test')
                with tarfile.open(destination, 'w:gz') as archive:
                    archive.add(installer, arcname='install-tl-fixture/install-tl')
            else:
                destination.write_bytes(b'catalogue')
        def execute(command, **kwargs):
            if command[0] == 'perl':
                binaries = root/'bin/x86_64-linux'
                binaries.mkdir(parents=True)
                (binaries/'tlmgr').touch()
        with patch.object(tex, 'load', return_value={'recipe': RECIPE}), patch.object(tex, 'installation_root', return_value=root), patch.object(tex_install, 'download', side_effect=download) as downloads, patch.object(tex_install.subprocess, 'run', side_effect=execute), patch.object(tex_install.subprocess, 'check_output', return_value=RECIPE['engine_version']+'\n'), patch.object(tex_install.platform, 'system', return_value='Linux'), patch.object(tex_install.platform, 'machine', return_value='x86_64'):
            tex_install.main()
            self.assertEqual(downloads.call_count, 2)
            self.assertEqual(json.loads((root/'.paper-recipe.json').read_text()), RECIPE)
            tex_install.main()
            self.assertEqual(downloads.call_count, 2)

if __name__ == '__main__': unittest.main()

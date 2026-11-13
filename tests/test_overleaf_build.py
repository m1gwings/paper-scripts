"""HTTP failures remain visible without breaking successful local compilation."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'lib'))
import overleaf_build as overleaf
import tex_environment as tex
SCRIPT=Path(__file__).resolve().parents[1]/'paper'
PROJECT='a'*24

class OverleafBuildTest(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name); previous=Path.cwd();os.chdir(self.root);self.addCleanup(os.chdir,previous)
        subprocess.run(['git','init','-q'],check=True)
        subprocess.run(['git','remote','add','overleaf','https://git@git.overleaf.com/'+PROJECT],check=True)
        overleaf._PROJECTS.clear()
    def helper(self,body):
        path=self.root/'helper';path.write_text('#!/usr/bin/env python3\n'+body);path.chmod(0o755);return str(path)
    @unittest.skipUnless(shutil.which('latexmk'),'TeX unavailable')
    def test_missing_cookies_warn_without_blocking_local_pdf(self):
        helper=self.helper('import sys,json\nprint(json.dumps({"code":"cookies_missing","error":"Overleaf session cookies are missing"}),file=sys.stderr)\nsys.exit(1)\n')
        (self.root/'main.tex').write_text(r'\documentclass{article}\begin{document}Local work remains usable.\end{document}')
        state=overleaf.refresh(helper=helper)
        self.assertEqual(state['code'],'cookies_missing')
        result=subprocess.run(['bash',str(SCRIPT),'build'],env=dict(os.environ,PAPER_OVERLEAF_AUTO='0'),capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertTrue((self.root/'output/main.pdf').read_bytes().startswith(b'%PDF-'))
        build=json.loads((self.root/'output/.latex/main.build.json').read_text())
        self.assertEqual(build['state'],'success')
        self.assertIn('cookies are missing',build['warning'])
        self.assertIn('Warning:',result.stderr)
    @unittest.skipUnless(shutil.which('latexmk'),'TeX unavailable')
    def test_nested_include_auxiliary_paths_work_like_overleaf(self):
        (self.root/'appendix').mkdir()
        (self.root/'appendix/part.tex').write_text('Nested appendix source.')
        (self.root/'main.tex').write_text(r'\documentclass{article}\begin{document}\include{appendix/part}\end{document}')
        result=subprocess.run(['bash',str(SCRIPT),'build'],env=dict(os.environ,PAPER_OVERLEAF_AUTO='0'),capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertTrue((self.root/'output/.latex/appendix/part.aux').is_file())

    def test_failed_capture_preserves_last_verified_manifest_and_timestamp(self):
        tex.MANIFEST.parent.mkdir()
        original=b'{"verified":"previous environment"}\n';tex.MANIFEST.write_bytes(original)
        overleaf.write(overleaf.STATUS,{'last_success':123,'warning':''})
        helper=self.helper('import sys,json\nprint(json.dumps({"code":"interface_changed","error":"cached_build route changed"}),file=sys.stderr)\nsys.exit(1)\n')
        state=overleaf.refresh(helper=helper)
        self.assertEqual(tex.MANIFEST.read_bytes(),original)
        self.assertEqual(state['last_success'],123)
        self.assertIn('route changed',state['warning'])
    def test_source_digest_ignores_zip_metadata(self):
        import zipfile
        for name,date in [('one.zip',(2025,1,1,0,0,0)),('two.zip',(2026,1,1,0,0,0))]:
            with zipfile.ZipFile(name,'w') as archive:archive.writestr(zipfile.ZipInfo('main.tex',date),b'same source')
        self.assertEqual(overleaf.source_digest('one.zip'),overleaf.source_digest('two.zip'))
    def test_generated_bitmap_fonts_resolve_to_the_font_package(self):
        log=self.root/'cloud.log';log.write_text('</usr/local/texlive/texmf-local/fonts/pk/ljfour/public/bbm/bbm10.600pk>')
        catalogue='name bbm\nrunfiles size=1\n RELOC/fonts/source/public/bbm/bbm10.mf\n\n'
        self.assertEqual(overleaf.package_names(log,catalogue),{'bbm'})
    def test_future_environment_is_warning_not_silent_repin(self):
        with self.assertRaisesRegex(ValueError,'previous environment'):
            overleaf.recipe_for({'image':'texlive-full:2099.1'},self.root/'unused.log')

if __name__=='__main__':unittest.main()

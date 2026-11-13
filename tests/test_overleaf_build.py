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

    @unittest.skipUnless(shutil.which('latexmk') and shutil.which('pdflatex'),'TeX unavailable')
    def test_declared_shell_mode_and_output_root_alias_are_applied(self):
        source=self.root/'main.tex'
        source.write_text(r'\documentclass{article}\begin{document}Initial.\end{document}')
        base_env=dict(os.environ,PAPER_OVERLEAF_AUTO='0')
        subprocess.run(['bash',str(SCRIPT),'build'],env=base_env,check=True,capture_output=True)
        baseline=tex.environment(self.root/'output/.latex/main.log');baseline['shell_escape']='enabled'
        binaries=self.root/'toolchain/bin/x86_64-linux';binaries.mkdir(parents=True)
        for name in ('latexmk','pdflatex'):(binaries/name).symlink_to(shutil.which(name))
        recipe=json.loads((SCRIPT.parent/'lib/texlive_2025.json').read_text())
        tex.MANIFEST.parent.mkdir(exist_ok=True)
        tex.MANIFEST.write_text(json.dumps(dict(version=1,main='main.tex',compiler='pdflatex',recipe=recipe,baseline=baseline,shell_escape='enabled',jobname='output')))
        source.write_text(r'\documentclass{article}\begin{document}\ifnum\pdfshellescape=1 Enabled.\else\errmessage{Wrong shell mode}\fi\IfFileExists{output.tex}{Alias ready.}{\errmessage{Root alias missing}}\end{document}')
        result=subprocess.run(['bash',str(SCRIPT),'build'],env=dict(base_env,PAPER_TEXLIVE_ROOT=str(self.root/'toolchain')),capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertTrue((self.root/'output/.latex/output.tex').is_symlink())

    @unittest.skipUnless(shutil.which('latexmk') and shutil.which('pdflatex'),'TeX unavailable')
    def test_changed_shell_mode_invalidates_old_outputs_only_once(self):
        source=self.root/'main.tex'
        source.write_text(r'\documentclass{article}\begin{document}Mode check.\end{document}')
        env=dict(os.environ,PAPER_OVERLEAF_AUTO='0')
        subprocess.run(['bash',str(SCRIPT),'build'],env=env,check=True,capture_output=True)
        baseline=tex.environment(self.root/'output/.latex/main.log')
        recipe=json.loads((SCRIPT.parent/'lib/texlive_2025.json').read_text())
        binaries=self.root/'toolchain/bin/x86_64-linux';binaries.mkdir(parents=True)
        for name in ('latexmk','pdflatex'):(binaries/name).symlink_to(shutil.which(name))
        env['PAPER_TEXLIVE_ROOT']=str(self.root/'toolchain')
        tex.MANIFEST.parent.mkdir(exist_ok=True)
        config=dict(version=1,main='main.tex',compiler='pdflatex',recipe=recipe,baseline=baseline,shell_escape='restricted')
        tex.MANIFEST.write_text(json.dumps(config))
        subprocess.run(['bash',str(SCRIPT),'build'],env=env,check=True,capture_output=True)
        config['shell_escape']='enabled';config['baseline']['shell_escape']='enabled'
        tex.MANIFEST.write_text(json.dumps(config))
        rebuilt=subprocess.run(['bash',str(SCRIPT),'build'],env=env,capture_output=True,text=True)
        self.assertEqual(rebuilt.returncode,0,rebuilt.stdout+rebuilt.stderr)
        self.assertEqual(tex.environment(self.root/'output/.latex/main.log')['shell_escape'],'enabled')
        log=self.root/'output/.latex/main.log';stamp=log.stat().st_mtime_ns
        cached=subprocess.run(['bash',str(SCRIPT),'build'],env=env,capture_output=True,text=True)
        self.assertEqual(cached.returncode,0,cached.stdout+cached.stderr)
        self.assertEqual(log.stat().st_mtime_ns,stamp)
        self.assertIn('Nothing to do',cached.stdout)

    @unittest.skipUnless(shutil.which('latexmk'),'TeX unavailable')
    def test_running_watcher_reloads_a_replaced_runtime(self):
        import time
        source=self.root/'main.tex';source.write_text(r'\documentclass{article}\begin{document}Before reload.\end{document}')
        runtime=self.root/'.paper/runtime'
        shutil.copytree(SCRIPT.parent/'lib',runtime/'lib',ignore=shutil.ignore_patterns('__pycache__'))
        output=self.root/'watch.log'
        with output.open('w') as log:
            process=subprocess.Popen([sys.executable,str(runtime/'lib/build.py'),'build','--watch'],env=dict(os.environ,PAPER_OVERLEAF_AUTO='0'),stdout=log,stderr=log)
            try:
                deadline=time.monotonic()+20
                while not (self.root/'output/main.pdf').is_file() and time.monotonic()<deadline:time.sleep(.1)
                self.assertTrue((self.root/'output/main.pdf').is_file())
                file=runtime/'lib/build.py';file.write_text(file.read_text()+'\n# Runtime replacement fixture.\n')
                deadline=time.monotonic()+10
                while 'reloading watcher' not in output.read_text() and time.monotonic()<deadline:time.sleep(.1)
                self.assertIn('reloading watcher',output.read_text())
                self.assertIsNone(process.poll())
            finally:
                process.terminate();process.wait(timeout=5)

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
    def test_cached_recipe_skips_catalogue_scan_and_still_checks_inputs(self):
        import hashlib,lzma
        profile=overleaf.read(SCRIPT.parent/'lib/texlive_2026.json')
        data=lzma.compress(b'name bbm\nrunfiles size=1\n RELOC/fonts/source/public/bbm/bbm10.mf\n\n')
        profile['catalogue_sha256']=hashlib.sha256(data).hexdigest()
        profile['packages']=['base']
        overleaf.CACHE.mkdir(parents=True)
        catalogue=overleaf.CACHE/('catalogue-'+profile['catalogue_sha256']+'.xz');catalogue.write_bytes(data)
        log=self.root/'cloud.log';log.write_text('texmf-dist/fonts/source/public/bbm/bbm10.mf')
        original=overleaf.read
        def read(path, default=None):
            return dict(profile) if Path(path).name=='texlive_2026.json' else original(path,default)
        with patch.object(overleaf,'read',side_effect=read), patch.object(overleaf,'package_names',wraps=overleaf.package_names) as scan:
            first=overleaf.recipe_for({'image':'texlive-full:2026.1'},log)
            self.assertEqual(first,overleaf.recipe_for({'image':'texlive-full:2026.1'},log))
            self.assertEqual(scan.call_count,1)
            log.write_text('changed log')
            overleaf.recipe_for({'image':'texlive-full:2026.1'},log)
            self.assertEqual(scan.call_count,2)
            catalogue.write_bytes(b'corrupted')
            with self.assertRaisesRegex(ValueError,'checksum'):
                overleaf.recipe_for({'image':'texlive-full:2026.1'},log)

    def test_verification_slot_excludes_other_processes_and_releases(self):
        env=dict(os.environ,XDG_CACHE_HOME=str(self.root/'cache'))
        code="import fcntl,sys; f=open(sys.argv[1],'a'); fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)"
        with patch.dict(os.environ,env):
            with overleaf.verification_slot():
                lock=self.root/'cache/paper/overleaf-verification.lock'
                blocked=subprocess.run([sys.executable,'-c',code,str(lock)],capture_output=True)
                self.assertNotEqual(blocked.returncode,0)
            released=subprocess.run([sys.executable,'-c',code,str(lock)],capture_output=True)
            self.assertEqual(released.returncode,0,released.stderr)

    def test_future_environment_is_warning_not_silent_repin(self):
        with self.assertRaisesRegex(ValueError,'previous environment'):
            overleaf.recipe_for({'image':'texlive-full:2099.1'},self.root/'unused.log')

if __name__=='__main__':unittest.main()

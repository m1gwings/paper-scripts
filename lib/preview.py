"""Unprivileged PDF build. This process must never receive publication secrets."""
import json
from pathlib import Path
import shutil
import subprocess
import tex_environment


def main():
    config = json.loads(Path('.paper/config.json').read_text())
    pinned = tex_environment.load() if tex_environment.MANIFEST.exists() else None
    root = Path(pinned['main'] if pinned else config['root_tex'])
    env = tex_environment.build_environment() if pinned else None
    latexmk = str(tex_environment.installation_root(pinned['recipe'])/'bin/x86_64-linux/latexmk') if pinned else 'latexmk'
    mode = tex_environment.COMPILERS[pinned['compiler']] if pinned else '-pdf'
    if root.is_absolute() or '..' in root.parts or str(root).startswith('-') or root.suffix != '.tex':
        raise SystemExit('root_tex must be a relative .tex path inside the repository.')
    if not root.is_file() or not root.resolve().is_relative_to(Path.cwd().resolve()):
        raise SystemExit('Root TeX file missing or outside repository.')
    build_out = Path('output') / root.parent
    if any(path.is_symlink() for path in (build_out, *build_out.parents)):
        raise SystemExit('Refusing symlinked build output directory.')
    build_out.mkdir(parents=True, exist_ok=True)
    subprocess.run([latexmk, '-norc', mode, '-no-shell-escape', '-halt-on-error',
                    '-interaction=nonstopmode', '-file-line-error',
                    f'-outdir={build_out}', f'-auxdir={build_out}', str(root)],
                   check=True, timeout=600, env=env)
    if pinned:
        drift = tex_environment.differences(build_out/(root.stem+'.log'), pinned)
        if drift:
            raise SystemExit('Overleaf environment drift:\n'+'\n'.join(drift))
    pdf = build_out / (root.stem + '.pdf')
    if not pdf.is_file() or pdf.is_symlink():
        raise SystemExit('Expected PDF output is missing.')
    out = Path('.paper-preview')
    if out.is_symlink():
        raise SystemExit('Refusing symlinked preview directory.')
    out.mkdir(exist_ok=True)
    target = out / 'paper.pdf'
    if target.is_symlink():
        raise SystemExit('Refusing symlinked PDF output.')
    shutil.copyfile(pdf, target)


if __name__ == '__main__':
    main()

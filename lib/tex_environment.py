"""Capture and enforce a project-specific Overleaf compilation environment."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

MANIFEST = Path('.paper/tex_environment.json')
COMPILERS = {'pdflatex': '-pdf', 'xelatex': '-xelatex', 'lualatex': '-lualatex', 'latex': '-pdfdvi'}


def environment(path):
    text = Path(path).read_text(errors='replace')
    engine = re.search(r'^This is (.+?)(?: \(preloaded format=|  \d|$)', text, re.M)
    kernel = re.search(r'^LaTeX2e <([^>]+)>(?: patch level (\d+))?', text, re.M)
    if not engine or not kernel:
        raise ValueError(f'{path}: expected a full LaTeX log, not console output')
    result = {'engine': engine[1], 'LaTeX': kernel[1] + ' patch ' + (kernel[2] or '0')}
    for kind, pattern in [('class', 'Document Class'), ('package', 'Package')]:
        for match in re.finditer(r'^' + pattern + r': (\S+) (\d{4}[-/]\d{2}[-/]\d{2})(?: (v\S+))?', text, re.M):
            result[kind+'/'+match[1]] = match[2] + (' '+match[3] if match[3] else '')
    return result


def prepare_auxiliary_tree(auxiliary):
    # TeX writes per-include .aux files but does not create their parent folders.
    # Mirror source directories as Overleaf's compilation setup does.
    for folder, directories, files in os.walk('.'):
        directories[:] = [name for name in directories if not name.startswith('.') and name != 'output']
        if any(name.endswith('.tex') for name in files):
            target = auxiliary/Path(folder)
            if not target.resolve().is_relative_to(Path.cwd().resolve()):
                raise ValueError('Auxiliary source tree must remain inside the project')
            target.mkdir(parents=True, exist_ok=True)


def source_path(value):
    path = Path(value)
    if (path.is_absolute() or '..' in path.parts or path.suffix != '.tex'
            or value.startswith('-') or any(c in value for c in '\n\r')):
        raise ValueError('Main document must be a relative .tex path inside the project')
    return value


def validate_recipe(recipe):
    for key in ('repository', 'installer_sha256', 'catalogue_sha256', 'packages', 'engine_version'):
        if key not in recipe:
            raise ValueError(f'Recipe needs {key}')
    for key in ('repository', 'engine_repository'):
        if key in recipe and not re.fullmatch(r'https://texlive.info/tlnet-archive/\d{4}/\d{2}/\d{2}/tlnet', recipe[key]):
            raise ValueError('Use a dated HTTPS texlive.info archive repository')
    for key in ('installer_sha256', 'catalogue_sha256', 'engine_catalogue_sha256'):
        if key in recipe and not re.fullmatch('[0-9a-f]{64}', recipe[key]):
            raise ValueError(f'Invalid {key}')
    if not isinstance(recipe['packages'], list) or not all(isinstance(x, str) and re.fullmatch('[a-zA-Z0-9_.-]+', x) and not x.startswith('-') for x in recipe['packages']):
        raise ValueError('Invalid TeX Live package names')
    command = recipe.get('engine_command', 'pdftex')
    if command not in ('pdftex', 'xetex', 'luahbtex'):
        raise ValueError('Unsupported engine_command')
    if not isinstance(recipe['engine_version'], str) or not recipe['engine_version'].strip():
        raise ValueError('Recipe needs the exact engine version banner')
    if ('engine_repository' in recipe) != ('engine_catalogue_sha256' in recipe):
        raise ValueError('Engine repository and catalogue checksum must be supplied together')


def load():
    config = json.loads(MANIFEST.read_text())
    if config.get('version') != 1 or config.get('compiler') not in COMPILERS:
        raise ValueError('Unsupported TeX manifest version/compiler')
    source_path(config['main'])
    validate_recipe(config['recipe'])
    if not config.get('baseline', {}).get('engine') or not config['baseline'].get('LaTeX'):
        raise ValueError('Manifest needs a verified Overleaf baseline')
    return config


def installation_root(recipe):
    identity = hashlib.sha256(json.dumps({k: v for k, v in recipe.items() if k != 'packages'}, sort_keys=True).encode()).hexdigest()[:20]
    base = Path(os.environ.get('XDG_DATA_HOME', Path.home()/'.local/share'))
    return Path(os.environ.get('PAPER_TEXLIVE_ROOT', base/'paper/texlive'/identity)).expanduser().resolve()


def build_environment():
    if not MANIFEST.exists():
        return None
    config = load()
    root = installation_root(config['recipe'])
    binaries = root/'bin/x86_64-linux'
    if not (binaries/config['compiler']).is_file() or not (binaries/'latexmk').is_file():
        raise ValueError('Pinned TeX toolchain missing; run paper tex install')
    env = dict(os.environ, PATH=str(binaries)+os.pathsep+os.environ.get('PATH', ''),
               TEXMFHOME=str(root/'texmf-home'), TEXMFVAR=str(root/'user-var'), TEXMFCONFIG=str(root/'user-config'))
    # Do not inherit search paths that could silently shadow the pinned tree.
    for key in list(env):
        if key.startswith(('TEXINPUTS', 'BIBINPUTS', 'BSTINPUTS')) or key in ('TEXMFCNF', 'TEXMF', 'TEXMFLOCAL', 'TEXMFSYSVAR', 'TEXMFSYSCONFIG'):
            env.pop(key)
    return env


def differences(log, config=None, strict=True):
    expected = (config or load())['baseline']
    actual = environment(log)
    keys = (actual.keys() | expected.keys()) if strict else (actual.keys() & expected.keys()) | {'engine', 'LaTeX'}
    return [f'{key}: local={actual.get(key, "MISSING")}; Overleaf={expected.get(key, "MISSING")}'
            for key in sorted(keys) if actual.get(key) != expected.get(key)]


def compare_pdfs(local, reference, dpi):
    if not shutil.which('pdftoppm'):
        raise ValueError('PDF comparison needs Poppler (pdftoppm)')
    with tempfile.TemporaryDirectory(prefix='paper-pdf-parity-') as scratch:
        pages = []
        for index, pdf in enumerate((local, reference)):
            folder = Path(scratch)/str(index)
            folder.mkdir()
            subprocess.run(['pdftoppm', '-r', str(dpi), str(Path(pdf).resolve()), str(folder/'page')], check=True, stdout=subprocess.DEVNULL)
            pages.append({p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.glob('*.ppm')})
        if not pages[0] or not pages[1]:
            raise ValueError('PDF comparison produced no pages')
        return [name for name in sorted(pages[0].keys() | pages[1].keys()) if pages[0].get(name) != pages[1].get(name)]


def run(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    capture = sub.add_parser('capture', help='Import a verified Overleaf log and frozen installation recipe')
    capture.add_argument('--log', type=Path, required=True)
    capture.add_argument('--recipe', type=Path, default=Path(__file__).with_name('texlive_2025.json'), help='Frozen recipe; default is the full verified pdfTeX/Overleaf 2025 snapshot')
    capture.add_argument('--compiler', choices=COMPILERS, default='pdflatex')
    capture.add_argument('--main', default='main.tex')
    for action in ('sync', 'enroll'):
        sync = sub.add_parser(action, help='Automatically capture settings/log/PDF over HTTP and restore the local environment')
        sync.add_argument('--fresh', action='store_true', help='Request a fresh Overleaf compilation')
    sub.add_parser('install')
    sub.add_parser('status')
    check = sub.add_parser('check')
    check.add_argument('log', type=Path)
    compare = sub.add_parser('compare-pdf')
    compare.add_argument('local', type=Path)
    compare.add_argument('overleaf', type=Path)
    compare.add_argument('--dpi', type=int, choices=range(36, 601), default=144, metavar='36..600')
    args = parser.parse_args(argv)
    result = subprocess.run(['git', 'rev-parse', '--show-toplevel'], capture_output=True, text=True)
    if result.returncode:
        parser.error('Not inside a Git repository')
    # Resolve supplied inputs before moving to the project root.
    for key in ('log', 'recipe', 'local', 'overleaf'):
        if getattr(args, key, None) is not None:
            setattr(args, key, getattr(args, key).resolve())
    os.chdir(result.stdout.rstrip('\n'))
    try:
        if args.action in ('sync', 'enroll'):
            import overleaf_build
            return overleaf_build.run(['refresh', '--install']+(['--fresh'] if args.fresh else []))
        if args.action == 'capture':
            if MANIFEST.exists() or MANIFEST.is_symlink():
                raise ValueError(f'{MANIFEST} exists; review/edit it explicitly to change the baseline')
            recipe = json.loads(args.recipe.read_text())
            recipe.pop('overleaf', None)  # Legacy project recipe may contain a project-specific baseline.
            recipe.pop('directory', None)
            validate_recipe(recipe)
            baseline = environment(args.log)
            engine_command = {'pdflatex': 'pdftex', 'latex': 'pdftex', 'xelatex': 'xetex', 'lualatex': 'luahbtex'}[args.compiler]
            if recipe.get('engine_command', 'pdftex') != engine_command:
                raise ValueError('Compiler does not match the recipe engine_command')
            if baseline['engine'] != recipe['engine_version'].removeprefix('This is ').replace('pdfTeX ', 'pdfTeX, Version ', 1).replace('XeTeX ', 'XeTeX, Version ', 1):
                raise ValueError('Overleaf log does not match the restoration recipe engine banner')
            config = dict(version=1, compiler=args.compiler, main=source_path(args.main), recipe=recipe, baseline=baseline)
            if MANIFEST.parent.is_symlink():
                raise ValueError('Refusing symlinked .paper directory')
            MANIFEST.parent.mkdir(exist_ok=True)
            with MANIFEST.open('x') as target:
                target.write(json.dumps(config, indent=2)+'\n')
            print(f'Captured {MANIFEST}; run paper tex install, then paper build')
        elif args.action == 'install':
            from tex_install import main
            main()
        elif args.action == 'check':
            drift = differences(args.log)
            print('\n'.join(drift) if drift else 'Compiler, kernel and declared class/package versions match Overleaf.')
            return int(bool(drift))
        elif args.action == 'compare-pdf':
            drift = compare_pdfs(args.local, args.overleaf, args.dpi)
            print('Different/missing pages: '+', '.join(drift) if drift else f'All rendered pages match at {args.dpi} dpi (PDF metadata excluded).')
            return int(bool(drift))
        elif not MANIFEST.exists():
            import overleaf_build
            print(json.dumps(dict(managed=False, message='Unmanaged local toolchain', verification=overleaf_build.read(overleaf_build.STATUS), warning=overleaf_build.warning()), indent=2))
        else:
            config = load()
            import overleaf_build
            print(json.dumps(dict(manifest=str(MANIFEST), compiler=config['compiler'], main=config['main'], image=config.get('overleaf_image'), installation=str(installation_root(config['recipe'])), baseline_items=len(config['baseline']), verification=overleaf_build.read(overleaf_build.STATUS), warning=overleaf_build.warning()), indent=2))
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        parser.exit(1, f'paper tex: {error}\n')
    return 0


if __name__ == '__main__':
    sys.exit(run())

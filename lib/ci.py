"""Privileged worker. Execute ONLY the copy from the protected default branch.

The feature checkout is Git data: no project hooks, build scripts, config code,
submodules, or feature-provided paper executable are run with credentials.
"""
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent


def checked(args, cwd, env, capture=False):
    result = subprocess.run(args, cwd=cwd, env=env, text=True, capture_output=capture)
    if result.returncode:
        raise RuntimeError('Publication stopped; inspect the Git diagnostics. No force overwrite of Overleaf was attempted.')
    return result.stdout.strip() if capture else ''


def worker(config, operation, branch, sha, root, env, github_url=None, overleaf_url=None):
    base = config['base_branch']
    if operation not in ('sync', 'publish'):
        raise ValueError('Invalid operation.')
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9/_.-]*', base):
        raise ValueError('Invalid base branch.')
    if operation == 'publish' and (not re.fullmatch(r'[0-9a-f]{40}', sha) or not branch or branch.startswith('-')):
        raise ValueError('Publish requires a branch and full commit SHA.')
    env = dict(env, PAPER_EXECUTION='local', PAPER_BASE_BRANCH=base,
               GIT_CONFIG_GLOBAL='/dev/null', GIT_CONFIG_NOSYSTEM='1',
               GIT_TERMINAL_PROMPT='0', GIT_EDITOR='true', GIT_SEQUENCE_EDITOR='true',
               GIT_AUTHOR_NAME='Paper publisher', GIT_AUTHOR_EMAIL='paper@users.noreply.github.com',
               GIT_COMMITTER_NAME='Paper publisher', GIT_COMMITTER_EMAIL='paper@users.noreply.github.com')
    # Exclude environment-injected Git config and repository/worktree overrides.
    for key in list(env):
        if key.startswith('GIT_CONFIG_KEY_') or key.startswith('GIT_CONFIG_VALUE_') or key in (
            'GIT_CONFIG_COUNT', 'GIT_CONFIG_PARAMETERS', 'GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE'):
            env.pop(key)
    repo = Path(root) / 'paper'
    repo.mkdir()
    def git(*args, capture=False):
        return checked(['git', '-c', 'core.hooksPath=/dev/null', '-c', 'core.fsmonitor=false',
                        *args], repo, env, capture)
    git('init', '-q')
    git('config', 'core.hooksPath', '/dev/null')
    git('config', 'core.fsmonitor', 'false')
    git('config', 'credential.helper', '')
    git('remote', 'add', 'github', github_url or f'https://github.com/{env["GITHUB_REPOSITORY"]}.git')
    project = config['overleaf_project_id']
    if not re.fullmatch(r'[a-zA-Z0-9]+', project):
        raise ValueError('Invalid Overleaf project ID.')
    git('remote', 'add', 'overleaf', overleaf_url or f'https://git@git.overleaf.com/{project}')
    git('fetch', 'github')
    git('fetch', 'overleaf')
    git('symbolic-ref', 'refs/remotes/overleaf/HEAD', f'refs/remotes/overleaf/{base}')
    git('switch', '-c', base, f'refs/remotes/github/{base}')
    if operation == 'publish':
        git('check-ref-format', '--branch', branch)
        actual = git('rev-parse', '--verify', f'refs/remotes/github/{branch}', capture=True)
        if actual != sha:
            raise RuntimeError('Requested branch changed since review. Publication refused; review and request again.')
        if branch != base:
            git('switch', '-c', branch, sha)
        # The shell helper repeats the SHA check after its own fetch, and uses
        # exact leases for changes made during the remaining publication window.
        env['PAPER_EXPECTED_BRANCH'] = branch
        env['PAPER_EXPECTED_SHA'] = sha
        checked(['bash', str(HERE.parent / 'paper'), 'publish'], repo, env)
    else:
        checked(['bash', str(HERE.parent / 'paper'), 'sync'], repo, env)
        if env.get('PAPER_TRUSTED_SHA'):
            git('diff', '--exit-code', '--quiet', env['PAPER_TRUSTED_SHA'], base, '--', '.paper', '.github')
        expected = git('rev-parse', f'refs/remotes/github/{base}', capture=True)
        git('push', f'--force-with-lease=refs/heads/{base}:{expected}',
            'github', f'{base}:refs/heads/{base}')
    return git('rev-parse', base, capture=True)


def main():
    config = json.loads(Path(os.environ['PAPER_TRUSTED_CONFIG']).read_text())
    with tempfile.TemporaryDirectory(prefix='paper-publisher-') as root:
        # Askpass restricts each token to its intended HTTPS host. No credential
        # is ever embedded in a URL, Git config, subprocess argument, or log.
        askpass = Path(root) / 'askpass'
        askpass.write_text('''#!/usr/bin/env python3
import os, sys
prompt = sys.argv[1]
if "'https://github.com':" in prompt:
    print('x-access-token' if prompt.startswith('Username') else os.environ['GH_TOKEN'])
elif "'https://x-access-token@github.com':" in prompt:
    print(os.environ['GH_TOKEN'])
elif "'https://git@git.overleaf.com':" in prompt:
    print(os.environ['OVERLEAF_TOKEN'])
else:
    sys.exit(1)
''')
        askpass.chmod(0o700)
        env = dict(os.environ, GIT_ASKPASS=str(askpass))
        result = worker(config, os.environ['PAPER_OPERATION'], os.environ.get('PAPER_BRANCH', ''),
                        os.environ.get('PAPER_SHA', ''), root, env)
        print('Completed at ' + result)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, RuntimeError, KeyError, OSError) as error:
        raise SystemExit(f'paper CI: {error}')

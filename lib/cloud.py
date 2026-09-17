"""GitHub Actions client: dispatch a uniquely identified job and wait for its result."""
import argparse
import json
import os
import re
import subprocess
import time
import uuid


def run(*args, capture=True, data=None):
    result = subprocess.run(args, input=data, text=True, capture_output=capture)
    if result.returncode:
        # Authentication tools can print URLs/credentials; keep diagnostics private.
        raise RuntimeError(f'{args[0]} failed. Check authentication, access, and repository configuration.')
    return result.stdout.strip() if capture else ''


def repository():
    url = run('git', 'remote', 'get-url', 'github')
    match = re.fullmatch(r'(?:https://github\.com/|git@github\.com:)([\w.-]+/[\w.-]+?)(?:\.git)?', url)
    if not match:
        raise RuntimeError('The github remote must be a credential-free github.com URL.')
    return match[1]


def request(operation, branch='', sha='', timeout=1800, api=None, sleep=time.sleep, clock=time.monotonic):
    repo = repository()
    def gh_api(path, body=None):
        args = ['gh', 'api', path]
        if body is not None:
            args += ['--method', 'POST', '--input', '-']
        result = run(*args, data=json.dumps(body) if body is not None else None)
        return json.loads(result) if result else None
    api = api or gh_api
    default = api(f'repos/{repo}')['default_branch']
    request_id = uuid.uuid4().hex
    title = f'paper-{operation}-{request_id}'
    endpoint = f'repos/{repo}/actions/workflows/paper-publish.yml'
    # workflow_dispatch is sent only to the trusted default branch.
    api(endpoint + '/dispatches', {'ref': default, 'inputs': {
        'operation': operation, 'branch': branch, 'sha': sha, 'request_id': request_id}})
    print(f'Requested {operation}; waiting for GitHub Actions ({request_id}).', flush=True)
    deadline = clock() + timeout
    seen = None
    while clock() < deadline:
        if seen is None:
            runs = api(endpoint + '/runs?event=workflow_dispatch&per_page=100')['workflow_runs']
            matches = [r for r in runs if r['display_title'] == title]
            if len(matches) > 1:
                raise RuntimeError('Multiple matching runs found; inspect Actions before retrying.')
            if matches:
                seen = matches[0]
                print(seen['html_url'], flush=True)
        else:
            seen = api(f'repos/{repo}/actions/runs/{seen["id"]}')
        if seen and seen['status'] == 'completed':
            if seen['conclusion'] != 'success':
                raise RuntimeError('CI did not complete successfully. Inspect the run; no local success is assumed.')
            return seen
        sleep(5)
    raise RuntimeError('Timed out waiting for CI. The job may still run; inspect Actions before retrying.')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('operation', choices=['sync', 'publish'])
    parser.add_argument('--branch', default='')
    parser.add_argument('--sha', default='')
    args = parser.parse_args()
    try:
        request(args.operation, args.branch, args.sha)
    except (RuntimeError, OSError, KeyError, ValueError) as exc:
        parser.exit(1, f'paper cloud: {exc}\n')


if __name__ == '__main__':
    main()

"""GitHub Actions client: dispatch a uniquely identified job and wait for its result."""
import argparse
import json
import os
import re
import subprocess
import time
import urllib.parse
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


def github_api(repo):
    def call(path, body=None):
        args = ['gh', 'api', path]
        if body is not None:
            args += ['--method', 'POST', '--input', '-']
        result = run(*args, data=json.dumps(body) if body is not None else None)
        return json.loads(result) if result else None
    return call


def dispatch_and_wait(repo, endpoint, inputs, run_title, operation, timeout, api,
                      sleep=time.sleep, clock=time.monotonic):
    default = api(f'repos/{repo}')['default_branch']
    # workflow_dispatch is sent only to the trusted default branch.
    api(endpoint + '/dispatches', {'ref': default, 'inputs': inputs})
    print(f'Requested {operation}; waiting for GitHub Actions ({inputs["request_id"]}).', flush=True)
    deadline = clock() + timeout
    seen = None
    while clock() < deadline:
        if seen is None:
            runs = api(endpoint + '/runs?event=workflow_dispatch&per_page=100')['workflow_runs']
            matches = [r for r in runs if r['display_title'] == run_title]
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


def request(operation, branch='', sha='', timeout=1800, api=None, sleep=time.sleep, clock=time.monotonic):
    repo = repository()
    api = api or github_api(repo)
    request_id = uuid.uuid4().hex
    return dispatch_and_wait(
        repo,
        f'repos/{repo}/actions/workflows/paper-publish.yml',
        {'operation': operation, 'branch': branch, 'sha': sha, 'request_id': request_id},
        f'paper-{operation}-{request_id}', operation, timeout, api, sleep, clock)


def notification(title, message, url='', timeout=300, api=None, sleep=time.sleep, clock=time.monotonic):
    if not title or len(title) > 250:
        raise ValueError('Notification title must contain 1 to 250 characters.')
    if not message or len(message) > 1024:
        raise ValueError('Notification message must contain 1 to 1024 characters.')
    if len(url) > 512:
        raise ValueError('Notification URL must contain at most 512 characters.')
    if url:
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('Notification URL must be HTTPS without embedded credentials.')
    repo = repository()
    api = api or github_api(repo)
    request_id = uuid.uuid4().hex
    return dispatch_and_wait(
        repo,
        f'repos/{repo}/actions/workflows/paper-notify.yml',
        {'request_id': request_id, 'title': title, 'message': message, 'url': url},
        f'paper-notify-{request_id}', 'notification', timeout, api, sleep, clock)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('operation', choices=['sync', 'publish', 'notify'])
    parser.add_argument('--branch', default='')
    parser.add_argument('--sha', default='')
    parser.add_argument('--title')
    parser.add_argument('--message')
    parser.add_argument('--url', default='')
    args = parser.parse_args()
    try:
        if args.operation == 'notify':
            if args.title is None or args.message is None:
                parser.error('notify requires --title and --message')
            notification(args.title, args.message, args.url)
        else:
            request(args.operation, args.branch, args.sha)
    except (RuntimeError, OSError, KeyError, ValueError) as exc:
        parser.exit(1, f'paper cloud: {exc}\n')


if __name__ == '__main__':
    main()

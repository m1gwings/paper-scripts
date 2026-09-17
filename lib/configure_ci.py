"""Interactive owner-only setup. Secret input goes directly to gh over stdin."""
import argparse
import getpass
import json
import subprocess
from cloud import repository
from infrastructure import config


def api(path, body=None, method=None):
    args = ['gh', 'api', path]
    if body is not None:
        args += ['--method', method or 'POST', '--input', '-']
    result = subprocess.run(args, input=json.dumps(body) if body is not None else None,
                            text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError('GitHub setup failed. Check repository administration access and plan support '
                           'for private environments (Pro/Team/Education). No fallback to repository secrets is made.')
    return json.loads(result.stdout) if result.stdout.strip() else None


def environments(repo, default, call=api):
    endpoint = f'repos/{repo}/environments'
    existing = {x['name'] for x in call(endpoint + '?per_page=100')['environments']}
    for name in ['paper-publish', 'paper-notify']:
        env_path = endpoint + '/' + name
        if name not in existing:
            call(env_path, {'deployment_branch_policy': {
                'protected_branches': False, 'custom_branch_policies': True}}, 'PUT')
            call(env_path + '/deployment-branch-policies', {'name': default, 'type': 'branch'})
        value = call(env_path)
        policy = value.get('deployment_branch_policy') or {}
        rules = call(env_path + '/deployment-branch-policies?per_page=100')['branch_policies']
        if not (policy.get('custom_branch_policies') and not policy.get('protected_branches')
                and len(rules) == 1 and rules[0]['name'] == default and rules[0].get('type') == 'branch'):
            raise RuntimeError(f'Environment {name} must allow only the default branch {default}; '
                               'review its existing restrictions in GitHub settings before adding secrets.')
        print(f'{name}: restricted to {default}.')


def store(repo, environment, name, value):
    result = subprocess.run(['gh', 'secret', 'set', name, '--repo', repo, '--env', environment],
                            input=value, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError('Secret installation failed; retry the setup. Secret values were not logged.')


def main():
    parser = argparse.ArgumentParser(description='Configure protected CI environments; enter secrets privately at a terminal.')
    parser.add_argument('--environments-only', action='store_true')
    args = parser.parse_args()
    try:
        repo = repository()
        default = api(f'repos/{repo}')['default_branch']
        environments(repo, default)
        if args.environments_only:
            return
        settings = config()
        provider = settings['notify_provider']
        for name in ['paper-publish', 'paper-notify']:
            result = subprocess.run(['gh', 'variable', 'set', 'PAPER_NOTIFY_PROVIDER', '--repo', repo,
                                     '--env', name, '--body', provider], capture_output=True)
            if result.returncode:
                raise RuntimeError('Could not configure the notification provider.')
        fields = [('OVERLEAF_TOKEN', ['paper-publish'])]
        if provider == 'pushover':
            fields += [(key, ['paper-publish', 'paper-notify']) for key in
                       ['PAPER_PUSHOVER_USER_KEY', 'PAPER_PUSHOVER_APP_TOKEN']]
        elif provider == 'webhook':
            fields += [('PAPER_NOTIFY_WEBHOOK_URL', ['paper-publish', 'paper-notify'])]
        print('Paste credentials only into these hidden terminal prompts. Enter skips an existing value.')
        for key, targets in fields:
            value = getpass.getpass(key + ': ')
            if value:
                for target in targets:
                    store(repo, target, key, value)
            else:
                for target in targets:
                    secrets = api(f'repos/{repo}/environments/{target}/secrets?per_page=100')['secrets']
                    if key not in {s['name'] for s in secrets}:
                        raise RuntimeError(f'{key} is still missing from {target}; rerun setup to finish.')
        print('CI credentials configured. Commit the generated files to the default branch to activate workflows.')
    except (ValueError, RuntimeError, OSError, KeyError) as error:
        parser.exit(1, f'paper configure-ci: {error}\n')


if __name__ == '__main__':
    main()

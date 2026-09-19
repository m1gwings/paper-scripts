"""Interactive owner-only setup. Secret input goes directly to gh over stdin."""
import argparse
import getpass
import json
import re
import subprocess
import sys
import urllib.parse
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


def set_variable(repo, environment, name, value):
    if value:
        command = ['gh', 'variable', 'set', name, '--repo', repo,
                   '--env', environment, '--body', value]
    else:
        variables = api(f'repos/{repo}/environments/{environment}/variables?per_page=100')['variables']
        if name not in {item['name'] for item in variables}:
            return
        command = ['gh', 'variable', 'delete', name, '--repo', repo, '--env', environment]
    result = subprocess.run(command, capture_output=True)
    if result.returncode:
        raise RuntimeError('Could not configure notification settings.')


def configure_notifications(repositories, provider, device, credentials,
                            call=api, secret_store=store, variable_store=set_variable):
    if provider not in ('discord', 'pushover', 'webhook'):
        raise ValueError('Notification provider must be discord, pushover, or webhook.')
    if device and provider != 'pushover':
        raise ValueError('--device is available only with the Pushover provider.')
    if device and not re.fullmatch(r'[A-Za-z0-9_-]{1,25}(?:,[A-Za-z0-9_-]{1,25})*', device):
        raise ValueError('Invalid Pushover device name.')
    expected = {
        'discord': {'DISCORD_WEBHOOK_URL'},
        'pushover': {'PAPER_PUSHOVER_USER_KEY', 'PAPER_PUSHOVER_APP_TOKEN'},
        'webhook': {'PAPER_NOTIFY_WEBHOOK_URL'},
    }[provider]
    if set(credentials) != expected or any(not value for value in credentials.values()):
        raise ValueError('All notification credentials are required for bulk setup.')
    if provider == 'discord':
        parsed = urllib.parse.urlsplit(credentials['DISCORD_WEBHOOK_URL'])
        if (parsed.scheme != 'https' or parsed.hostname not in ('discord.com', 'www.discord.com')
                or not parsed.path.startswith('/api/webhooks/')
                or parsed.username or parsed.password):
            raise ValueError('DISCORD_WEBHOOK_URL must be a Discord HTTPS incoming-webhook URL.')
    selected = []
    for repo in repositories:
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo):
            raise ValueError(f'Invalid GitHub repository {repo!r}; use OWNER/REPOSITORY.')
        if repo not in selected:
            selected.append(repo)
    if not selected:
        raise ValueError('Provide at least one GitHub repository.')
    for repo in selected:
        default = call(f'repos/{repo}')['default_branch']
        environments(repo, default, call)
        environment = 'paper-notify'
        variable_store(repo, environment, 'PAPER_NOTIFY_PROVIDER', provider)
        variable_store(repo, environment, 'PAPER_PUSHOVER_DEVICE', device if provider == 'pushover' else '')
        for name, value in credentials.items():
            secret_store(repo, environment, name, value)
        print(f'{repo}: notification credentials configured.')


def notification_main(args):
    parser = argparse.ArgumentParser(
        prog='paper configure-notifications',
        description='Prompt once and configure protected notifications for multiple paper repositories.')
    parser.add_argument('--provider', choices=['discord', 'pushover', 'webhook'], default='discord')
    parser.add_argument('--device', default='')
    parser.add_argument('repositories', nargs='+', metavar='OWNER/REPOSITORY')
    parsed = parser.parse_args(args)
    names = {
        'discord': ['DISCORD_WEBHOOK_URL'],
        'pushover': ['PAPER_PUSHOVER_USER_KEY', 'PAPER_PUSHOVER_APP_TOKEN'],
        'webhook': ['PAPER_NOTIFY_WEBHOOK_URL'],
    }[parsed.provider]
    print('Enter notification credentials once. Input is hidden and values are never logged.')
    credentials = {name: getpass.getpass(name + ': ') for name in names}
    configure_notifications(parsed.repositories, parsed.provider, parsed.device, credentials)
    print('Notification credentials installed for every selected repository.')


def main(args=None):
    args = list(sys.argv[1:] if args is None else args)
    if args[:1] == ['notifications']:
        try:
            notification_main(args[1:])
        except (ValueError, RuntimeError, OSError, KeyError) as error:
            raise SystemExit(f'paper configure-notifications: {error}')
        return
    parser = argparse.ArgumentParser(description='Configure protected CI environments; enter secrets privately at a terminal.')
    parser.add_argument('--environments-only', action='store_true')
    parsed = parser.parse_args(args)
    try:
        repo = repository()
        default = api(f'repos/{repo}')['default_branch']
        environments(repo, default)
        if parsed.environments_only:
            return
        settings = config()
        provider = settings['notify_provider']
        for key, value in [('PAPER_NOTIFY_PROVIDER', provider),
                           ('PAPER_PUSHOVER_DEVICE', settings.get('pushover_device', '')
                            if provider == 'pushover' else '')]:
            set_variable(repo, 'paper-notify', key, value)
        fields = [('OVERLEAF_TOKEN', ['paper-publish'])]
        print('Paste the Overleaf credential only into this hidden terminal prompt. Enter preserves an existing value.')
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
        print('CI publication credential configured. Notification credentials are managed with '
              'paper configure-notifications.')
        print('Commit the generated files to the default branch to activate workflows.')
    except (ValueError, RuntimeError, OSError, KeyError) as error:
        parser.exit(1, f'paper configure-ci: {error}\n')


if __name__ == '__main__':
    main()

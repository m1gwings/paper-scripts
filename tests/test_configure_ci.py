import sys
from pathlib import Path
import unittest
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
import configure_ci


class ConfigureTest(unittest.TestCase):
    def test_notification_setup_defaults_to_current_repository(self):
        webhook = 'https://discord.com/api/webhooks/1/token'
        with mock.patch.object(configure_ci, 'repository', return_value='owner/current') as repository:
            with mock.patch.object(configure_ci.getpass, 'getpass', return_value=webhook):
                with mock.patch.object(configure_ci, 'configure_notifications') as configure:
                    configure_ci.notification_main([])
        repository.assert_called_once_with()
        configure.assert_called_once_with(
            ['owner/current'], 'discord', '', {'DISCORD_WEBHOOK_URL': webhook})

    def test_notification_setup_keeps_explicit_bulk_repositories(self):
        webhook = 'https://discord.com/api/webhooks/1/token'
        with mock.patch.object(configure_ci, 'repository') as repository:
            with mock.patch.object(configure_ci.getpass, 'getpass', return_value=webhook):
                with mock.patch.object(configure_ci, 'configure_notifications') as configure:
                    configure_ci.notification_main(['owner/one', 'owner/two'])
        repository.assert_not_called()
        configure.assert_called_once_with(
            ['owner/one', 'owner/two'], 'discord', '', {'DISCORD_WEBHOOK_URL': webhook})

    def test_create_and_verify_restricted_environments(self):
        requests = []
        def api(path, body=None, method=None):
            requests.append((path, body, method))
            if body:
                return {}
            if path.endswith('environments?per_page=100'):
                return {'environments': []}
            if 'deployment-branch-policies?' in path:
                return {'branch_policies': [{'name': 'main', 'type': 'branch'}]}
            return {'deployment_branch_policy': {'protected_branches': False, 'custom_branch_policies': True}}
        configure_ci.environments('owner/paper', 'main', api)
        self.assertEqual(sum(r[2] == 'PUT' for r in requests), 2)

    def test_existing_automatic_environment_is_restricted(self):
        requests = []
        configured = set()
        def api(path, body=None, method=None):
            requests.append((path, body, method))
            name = next((item for item in ('paper-publish', 'paper-notify')
                         if f'environments/{item}' in path), None)
            if body:
                if method == 'PUT':
                    configured.add(name)
                return {}
            if path.endswith('environments?per_page=100'):
                return {'environments': [{'name': 'paper-publish'}, {'name': 'paper-notify'}]}
            if 'deployment-branch-policies?' in path:
                return {'branch_policies': [{'name': 'main', 'type': 'branch'}]}
            if name in configured:
                return {'deployment_branch_policy': {'protected_branches': False,
                                                      'custom_branch_policies': True}}
            return {'deployment_branch_policy': None}
        configure_ci.environments('owner/paper', 'main', api)
        self.assertEqual(configured, {'paper-publish', 'paper-notify'})
        self.assertEqual(sum(r[2] == 'PUT' for r in requests), 2)

    def test_existing_conflicting_environment_refused(self):
        def api(path, body=None, method=None):
            if path.endswith('environments?per_page=100'):
                return {'environments': [{'name': 'paper-publish'}, {'name': 'paper-notify'}]}
            if 'deployment-branch-policies?' in path:
                return {'branch_policies': [{'name': '*', 'type': 'branch'}]}
            return {'deployment_branch_policy': {'protected_branches': False,
                                                  'custom_branch_policies': True}}
        with self.assertRaisesRegex(RuntimeError, 'only the default branch'):
            configure_ci.environments('owner/paper', 'main', api)

    def test_bulk_notification_setup_prompts_once_then_fans_out(self):
        secrets = []
        variables = []
        def api(path, body=None, method=None):
            if path in ('repos/owner/one', 'repos/owner/two'):
                return {'default_branch': 'main'}
            if path.endswith('environments?per_page=100'):
                return {'environments': [{'name': 'paper-publish'}, {'name': 'paper-notify'}]}
            if 'deployment-branch-policies?' in path:
                return {'branch_policies': [{'name': 'main', 'type': 'branch'}]}
            return {'deployment_branch_policy': {'protected_branches': False,
                                                  'custom_branch_policies': True}}
        configure_ci.configure_notifications(
            ['owner/one', 'owner/two'], 'discord', '',
            {'DISCORD_WEBHOOK_URL': 'https://discord.com/api/webhooks/1/token'},
            call=api,
            secret_store=lambda *args: secrets.append(args),
            variable_store=lambda *args: variables.append(args))
        self.assertEqual(len(secrets), 2)
        self.assertEqual(len(variables), 4)
        self.assertIn(('owner/one', 'paper-notify', 'PAPER_NOTIFY_PROVIDER', 'discord'), variables)
        self.assertIn(('owner/one', 'paper-notify', 'DISCORD_WEBHOOK_URL',
                       'https://discord.com/api/webhooks/1/token'), secrets)

    def test_bulk_notification_setup_normalizes_legacy_discord_domain(self):
        secrets = []
        def api(path, body=None, method=None):
            if path == 'repos/owner/paper':
                return {'default_branch': 'main'}
            if path.endswith('environments?per_page=100'):
                return {'environments': [{'name': 'paper-publish'}, {'name': 'paper-notify'}]}
            if 'deployment-branch-policies?' in path:
                return {'branch_policies': [{'name': 'main', 'type': 'branch'}]}
            return {'deployment_branch_policy': {'protected_branches': False,
                                                  'custom_branch_policies': True}}
        configure_ci.configure_notifications(
            ['owner/paper'], 'discord', '',
            {'DISCORD_WEBHOOK_URL': 'https://discordapp.com/api/webhooks/1/token'},
            call=api,
            secret_store=lambda *args: secrets.append(args),
            variable_store=lambda *args: None)
        self.assertIn(('owner/paper', 'paper-notify', 'DISCORD_WEBHOOK_URL',
                       'https://discord.com/api/webhooks/1/token'), secrets)

    def test_bulk_notification_setup_validates_before_writes(self):
        with self.assertRaisesRegex(ValueError, 'OWNER/REPOSITORY'):
            configure_ci.configure_notifications(
                ['not-a-repository'], 'pushover', '',
                {'PAPER_PUSHOVER_USER_KEY': 'user', 'PAPER_PUSHOVER_APP_TOKEN': 'token'})
        with self.assertRaisesRegex(ValueError, 'All notification credentials'):
            configure_ci.configure_notifications(
                ['owner/paper'], 'pushover', '', {'PAPER_PUSHOVER_USER_KEY': 'user'})
        with self.assertRaisesRegex(ValueError, 'Discord HTTPS'):
            configure_ci.configure_notifications(
                ['owner/paper'], 'discord', '', {'DISCORD_WEBHOOK_URL': 'https://example.com/hook'})

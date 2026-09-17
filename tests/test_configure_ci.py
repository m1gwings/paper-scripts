import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
import configure_ci


class ConfigureTest(unittest.TestCase):
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

    def test_existing_unrestricted_environment_refused(self):
        def api(path, body=None, method=None):
            if path.endswith('environments?per_page=100'):
                return {'environments': [{'name': 'paper-publish'}, {'name': 'paper-notify'}]}
            if 'deployment-branch-policies?' in path:
                return {'branch_policies': [{'name': '*', 'type': 'branch'}]}
            return {'deployment_branch_policy': None}
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
            ['owner/one', 'owner/two'], 'pushover', 'phone',
            {'PAPER_PUSHOVER_USER_KEY': 'user', 'PAPER_PUSHOVER_APP_TOKEN': 'token'},
            call=api,
            secret_store=lambda *args: secrets.append(args),
            variable_store=lambda *args: variables.append(args))
        self.assertEqual(len(secrets), 8)
        self.assertEqual(len(variables), 8)
        self.assertIn(('owner/one', 'paper-notify', 'PAPER_NOTIFY_PROVIDER', 'pushover'), variables)

    def test_bulk_notification_setup_validates_before_writes(self):
        with self.assertRaisesRegex(ValueError, 'OWNER/REPOSITORY'):
            configure_ci.configure_notifications(
                ['not-a-repository'], 'pushover', '',
                {'PAPER_PUSHOVER_USER_KEY': 'user', 'PAPER_PUSHOVER_APP_TOKEN': 'token'})
        with self.assertRaisesRegex(ValueError, 'All notification credentials'):
            configure_ci.configure_notifications(
                ['owner/paper'], 'pushover', '', {'PAPER_PUSHOVER_USER_KEY': 'user'})

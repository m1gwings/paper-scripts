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

"""Exercise the actual Bash cloud commands through a simulated Actions service."""
import json
import os
from pathlib import Path
import shutil
import sys
import test_workflow


class CloudLifecycleTest(test_workflow.WorkflowTest):
    def setUp(self):
        super().setUp()
        lib = Path(__file__).resolve().parents[1] / 'lib'
        self.paper('init')
        config = self.repo / '.paper/config.json'
        data = json.loads(config.read_text())
        data.update(base_branch='master', overleaf_project_id='abc123')
        config.write_text(json.dumps(data))
        self.git('add', '.')
        self.git('commit', '-qm', 'infrastructure')
        self.git('push', 'github', 'master')
        self.git('push', 'overleaf', 'master')
        bin_dir = self.root / 'bin'
        bin_dir.mkdir()
        real_git = shutil.which('git')
        wrapper = bin_dir / 'git'
        wrapper.write_text('#!' + sys.executable + '\nimport os, sys\n' +
                           'if sys.argv[1:] == ["remote", "get-url", "github"]:\n' +
                           '    print("https://github.com/owner/paper.git")\nelse:\n' +
                           f'    os.execv({real_git!r}, [{real_git!r}] + sys.argv[1:])\n')
        wrapper.chmod(0o755)
        gh = bin_dir / 'gh'
        gh.write_text('#!' + sys.executable + '\n' + f'LIB = {str(lib)!r}\n' + '''
import json, os, pathlib, sys, tempfile
sys.path.insert(0, LIB)
import ci
path = sys.argv[2]
root = pathlib.Path(os.environ['TEST_ROOT'])
record = root / 'run.json'
if path == 'repos/owner/paper':
    print(json.dumps({'default_branch': 'master'}))
elif path.endswith('/dispatches'):
    os.dup2(2, 1)  # Git worker logs belong to the fake server, not its API body.
    body = json.load(sys.stdin)
    inputs = body['inputs']
    config = {'base_branch': 'master', 'overleaf_project_id': 'abc123'}
    try:
        env = dict(os.environ, PAPER_EXECUTION='local')
        ci.worker(config, inputs['operation'], inputs['branch'], inputs['sha'],
                  tempfile.mkdtemp(dir=root), env, str(root / 'github'), str(root / 'overleaf'))
        outcome = 'success'
    except Exception:
        outcome = 'failure'
    record.write_text(json.dumps({'id': 42, 'display_title': 'paper-' + inputs['operation'] + '-' + inputs['request_id'],
                                 'html_url': 'https://example.com/42', 'status': 'completed', 'conclusion': outcome}))
elif '/runs?' in path:
    print(json.dumps({'workflow_runs': [json.loads(record.read_text())]}))
else:
    print(record.read_text())
''')
        gh.chmod(0o755)
        self.env.update(PATH=str(bin_dir) + os.pathsep + os.environ['PATH'],
                        PAPER_EXECUTION='cloud', TEST_ROOT=str(self.root))

    def test_start_publish_and_return_sync(self):
        self.remote_commit('overleaf', 'coauthor.tex', 'coauthor\n')
        self.paper('start', 'cloud-feature')
        self.assertTrue((self.repo / 'coauthor.tex').exists())
        self.commit(self.repo, 'feature.tex', 'feature\n')
        output = self.paper('publish')
        self.assertIn('CI publication succeeded', output)
        self.assertEqual(self.git('branch', '--show-current'), 'master')
        head = self.git('rev-parse', 'HEAD')
        for remote in ['github', 'overleaf']:
            self.assertEqual(self.git('rev-parse', 'master', cwd=self.root / remote), head)
        self.assertEqual(self.git('rev-parse', 'cloud-feature'), head)
        self.paper('sync')

    def test_conflict_stays_failed_and_preserves_remote_base(self):
        self.paper('start', 'cloud-feature')
        self.commit(self.repo, 'main.tex', 'feature\n')
        oid = self.remote_commit('overleaf', 'main.tex', 'coauthor\n')
        output = self.paper('publish', ok=False)
        self.assertNotIn('CI publication succeeded', output)
        self.assertEqual(self.git('rev-parse', 'master', cwd=self.root / 'overleaf'), oid)
        self.assertEqual(self.git('branch', '--show-current'), 'cloud-feature')

for name in list(test_workflow.WorkflowTest.__dict__):
    if name.startswith('test_'):
        setattr(CloudLifecycleTest, name, None)

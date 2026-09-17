import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
import cloud
import ci
import test_workflow


class CloudClientTest(unittest.TestCase):
    def test_dispatch_waits_for_exact_request_and_reports_success(self):
        captured = {}
        def api(path, body=None):
            if path == 'repos/me/paper':
                return {'default_branch': 'master'}
            if body:
                captured.update(body)
                return
            title = 'paper-publish-' + captured['inputs']['request_id']
            record = {'id': 42, 'display_title': title, 'html_url': 'https://example.com/run',
                      'status': 'completed', 'conclusion': 'success'}
            return {'workflow_runs': [dict(record, display_title='other-request'), record]}
        with patch.object(cloud, 'repository', return_value='me/paper'):
            result = cloud.request('publish', 'feature', 'a' * 40, api=api, sleep=lambda _: None)
        self.assertEqual(result['id'], 42)
        self.assertEqual(captured['ref'], 'master')
        self.assertEqual(captured['inputs']['sha'], 'a' * 40)

    def test_notification_dispatches_to_trusted_workflow(self):
        captured = {}
        def api(path, body=None):
            if path == 'repos/me/paper':
                return {'default_branch': 'main'}
            if body:
                captured.update(body)
                return
            title = 'paper-notify-' + captured['inputs']['request_id']
            return {'workflow_runs': [{'id': 7, 'display_title': title,
                                       'html_url': 'https://example.com/notify',
                                       'status': 'completed', 'conclusion': 'success'}]}
        with patch.object(cloud, 'repository', return_value='me/paper'):
            result = cloud.notification('Done', 'The PDF is ready.', 'https://example.com/paper.pdf',
                                        api=api, sleep=lambda _: None)
        self.assertEqual(result['id'], 7)
        self.assertEqual(captured['ref'], 'main')
        self.assertEqual(captured['inputs']['title'], 'Done')
        self.assertEqual(captured['inputs']['message'], 'The PDF is ready.')
        self.assertEqual(captured['inputs']['url'], 'https://example.com/paper.pdf')

    def test_notification_validates_public_fields(self):
        with self.assertRaisesRegex(ValueError, 'title'):
            cloud.notification('', 'message')
        with self.assertRaisesRegex(ValueError, 'message'):
            cloud.notification('title', '')
        with self.assertRaisesRegex(ValueError, 'HTTPS'):
            cloud.notification('title', 'message', 'file:///tmp/paper.pdf')
        with self.assertRaisesRegex(ValueError, 'embedded credentials'):
            cloud.notification('title', 'message', 'https://secret@example.com/paper.pdf')

    def test_failure_and_timeout_are_not_success(self):
        body = {}
        def api(path, data=None):
            if path == 'repos/me/paper':
                return {'default_branch': 'main'}
            if data:
                body.update(data)
                return
            return {'workflow_runs': [{'id': 1, 'display_title': 'paper-sync-' + body['inputs']['request_id'],
                                       'html_url': 'url', 'status': 'completed', 'conclusion': 'failure'}]}
        with patch.object(cloud, 'repository', return_value='me/paper'):
            with self.assertRaisesRegex(RuntimeError, 'did not complete'):
                cloud.request('sync', api=api)
            with self.assertRaisesRegex(RuntimeError, 'Timed out'):
                cloud.request('sync', timeout=0, api=api)

    def test_remote_parsing_rejects_embedded_credentials(self):
        for url in ['git@github.com:me/paper.git', 'https://github.com/me/paper.git']:
            with patch.object(cloud, 'run', return_value=url):
                self.assertEqual(cloud.repository(), 'me/paper')
        with patch.object(cloud, 'run', return_value='https://secret@github.com/me/paper.git'):
            with self.assertRaises(RuntimeError):
                cloud.repository()


class CIWorkerTest(test_workflow.WorkflowTest):
    # Inherit the real-Git fixtures without rerunning the parent test methods.
    def worker(self, operation='publish', branch='experiment', sha=None, trusted=None):
        config = {'base_branch': 'master', 'overleaf_project_id': 'abc123'}
        root = tempfile.mkdtemp(dir=self.root)
        env = dict(self.env)
        if trusted:
            env['PAPER_TRUSTED_SHA'] = trusted
        return ci.worker(config, operation, branch, sha or self.git('rev-parse', 'HEAD'), root, env,
                         str(self.root / 'github'), str(self.root / 'overleaf'))

    def test_ci_publish_and_sync_use_same_local_implementation(self):
        self.paper('start', 'experiment')
        self.commit(self.repo, 'feature.tex', 'feature\n')
        self.paper('backup')
        self.remote_commit('overleaf', 'collab.tex', 'collab\n')
        oid = self.worker()
        self.assertEqual(self.git('rev-parse', 'master', cwd=self.root / 'github'), oid)
        self.assertEqual(self.git('rev-parse', 'master', cwd=self.root / 'overleaf'), oid)

    def test_ci_sync_mirrors_overleaf_without_publishing(self):
        oid = self.remote_commit('overleaf', 'collab.tex', 'collab\n')
        self.worker('sync')
        self.assertEqual(self.git('rev-parse', 'master', cwd=self.root / 'github'), oid)
        self.assertEqual(self.git('rev-parse', 'master', cwd=self.root / 'overleaf'), oid)

    def test_stale_review_sha_refused(self):
        self.paper('start', 'experiment')
        old = self.git('rev-parse', 'HEAD')
        self.commit(self.repo, 'feature.tex', 'new\n')
        self.paper('backup')
        with self.assertRaisesRegex(RuntimeError, 'changed since review'):
            self.worker(sha=old)

    def test_infrastructure_change_refused_before_any_publish(self):
        trusted = self.git('rev-parse', 'HEAD')
        self.paper('start', 'experiment')
        (self.repo / '.github').mkdir()
        self.commit(self.repo, '.github/malicious', 'do not execute\n')
        self.paper('backup')
        with self.assertRaises(RuntimeError):
            self.worker(trusted=trusted)
        for remote in ['github', 'overleaf']:
            self.assertEqual(self.git('rev-parse', 'master', cwd=self.root / remote), trusted)

    def test_feature_code_is_never_executed(self):
        self.paper('start', 'experiment')
        marker = self.root / 'executed'
        self.commit(self.repo, 'paper', f'#!/bin/sh\ntouch "{marker}"\n')
        self.commit(self.repo, '.latexmkrc', f'system("touch {marker}");\n')
        self.paper('backup')
        self.worker()
        self.assertFalse(marker.exists())


# TestCase inheritance supplies the fixture helpers; avoid duplicate tests.
for name in list(test_workflow.WorkflowTest.__dict__):
    if name.startswith('test_'):
        setattr(CIWorkerTest, name, None)

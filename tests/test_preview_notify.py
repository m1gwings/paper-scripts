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
import preview_notify


class PreviewNotificationTest(unittest.TestCase):
    def run_event(self, provider, credentials=None, conclusion='success', foreign=False):
        event = {'workflow_run': {
            'head_repository': {'full_name': 'other/paper' if foreign else 'owner/paper'},
            'conclusion': conclusion, 'id': 12,
            'html_url': 'https://github.com/owner/paper/actions/runs/12',
            'head_branch': 'main', 'head_sha': 'a' * 40,
        }}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'event.json'
            path.write_text(json.dumps(event))
            env = {'GITHUB_EVENT_PATH': str(path), 'GITHUB_REPOSITORY': 'owner/paper',
                   'PAPER_NOTIFY_PROVIDER': provider, **(credentials or {})}
            output = io.StringIO()
            with patch.dict(os.environ, env, clear=True), contextlib.redirect_stdout(output):
                preview_notify.main()
            return output.getvalue()

    def test_unconfigured_automatic_delivery_skips_without_network_or_secrets(self):
        for provider, credentials in (
                ('none', {}), ('discord', {}), ('webhook', {}),
                ('pushover', {'PAPER_PUSHOVER_APP_TOKEN': 'private-value'})):
            with self.subTest(provider=provider), patch.object(preview_notify, 'send') as send, \
                    patch.object(preview_notify.subprocess, 'run') as api:
                output = self.run_event(provider, credentials)
                self.assertIn('skipped', output)
                self.assertNotIn('private-value', output)
                send.assert_not_called()
                api.assert_not_called()

    def test_configured_delivery_still_fetches_artifact_and_sends(self):
        with patch.object(preview_notify, 'send') as send, \
                patch.object(preview_notify.subprocess, 'run') as api:
            api.return_value.stdout = json.dumps({'artifacts': [
                {'name': 'paper.pdf', 'expired': False, 'id': 34}]})
            self.run_event('discord', {'DISCORD_WEBHOOK_URL': 'private-value'})
            send.assert_called_once_with(
                'discord', 'Paper preview',
                'main (aaaaaaaaaaaa): success. Sign in to GitHub to download the PDF.',
                'https://github.com/owner/paper/actions/runs/12/artifacts/34')

    def test_delivery_failure_is_not_silently_suppressed(self):
        with patch.object(preview_notify, 'send', side_effect=ValueError('delivery failed')):
            with self.assertRaisesRegex(ValueError, 'delivery failed'):
                self.run_event('discord', {'DISCORD_WEBHOOK_URL': 'private-value'},
                               conclusion='failure')

    def test_cancelled_runs_do_not_send_and_foreign_runs_are_rejected(self):
        with patch.object(preview_notify, 'send') as send:
            self.run_event('discord', conclusion='cancelled')
            send.assert_not_called()
            with self.assertRaisesRegex(SystemExit, 'Foreign repository refused'):
                self.run_event('none', foreign=True)

import io
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import urllib.error
import urllib.parse
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
import notify


class NotifyTest(unittest.TestCase):
    def test_none_needs_no_credentials_or_network(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(notify.send('none', 'title', 'message', opener=lambda *a: self.fail()))

    def test_pushover_encoding_and_response(self):
        captured = []
        def opener(request, **kwargs):
            captured.append(request)
            return io.BytesIO(b'{"status":1}')
        with patch.dict(os.environ, PAPER_PUSHOVER_APP_TOKEN='private-token', PAPER_PUSHOVER_USER_KEY='private-key'):
            self.assertTrue(notify.send('pushover', 'A & B', '@file', 'https://example.com', opener))
        fields = urllib.parse.parse_qs(captured[0].data.decode())
        self.assertEqual(fields['message'], ['@file'])
        self.assertEqual(fields['title'], ['A & B'])
        self.assertNotIn('private-token', captured[0].full_url)

    def test_discord_rich_message_and_link(self):
        captured = []
        def opener(request, **kwargs):
            captured.append(request)
            return io.BytesIO(b'')
        environment = {
            'DISCORD_WEBHOOK_URL': 'https://discord.com/api/webhooks/123/private-token',
            'GITHUB_REPOSITORY': 'owner/paper',
        }
        with patch.dict(os.environ, environment, clear=True):
            self.assertTrue(notify.send(
                'discord', 'Proof complete', 'The checked PDF is ready.',
                'https://github.com/owner/paper/actions/runs/1/artifacts/2', opener))
        payload = json.loads(captured[0].data)
        self.assertEqual(payload['allowed_mentions'], {'parse': []})
        self.assertEqual(payload['embeds'][0]['title'], 'Proof complete')
        self.assertEqual(payload['embeds'][0]['footer']['text'], 'owner/paper')
        self.assertEqual(payload['embeds'][0]['url'],
                         'https://github.com/owner/paper/actions/runs/1/artifacts/2')
        self.assertEqual(captured[0].get_header('User-agent'),
                         'DiscordBot (https://github.com/m1gwings/paper-scripts, 1)')
        self.assertNotIn('private-token', captured[0].full_url.rsplit('/', 1)[0])

    def test_discord_legacy_domain_is_canonicalized_without_redirect(self):
        captured = []
        def opener(request, **kwargs):
            captured.append(request)
            return io.BytesIO(b'')
        with patch.dict(os.environ, {
                'DISCORD_WEBHOOK_URL':
                'https://discordapp.com/api/webhooks/123/private-token'}, clear=True):
            self.assertTrue(notify.send('discord', 'Title', 'Message', opener=opener))
        self.assertEqual(captured[0].full_url,
                         'https://discord.com/api/webhooks/123/private-token')

    def test_discord_requires_official_webhook_and_https_link(self):
        with patch.dict(os.environ, DISCORD_WEBHOOK_URL='https://example.com/api/webhooks/1/token'):
            with self.assertRaises(ValueError):
                notify.send('discord', 'title', 'message')
        with patch.dict(os.environ, DISCORD_WEBHOOK_URL='https://discord.com/api/webhooks/1/token'):
            with self.assertRaises(ValueError):
                notify.send('discord', 'title', 'message', 'http://example.com/file.pdf')

    def test_device_targeting_and_default_broadcast(self):
        captured = []
        def opener(request, **kwargs):
            captured.append(urllib.parse.parse_qs(request.data.decode()))
            return io.BytesIO(b'{"status":1}')
        with patch.dict(os.environ, {'PAPER_PUSHOVER_APP_TOKEN': 'private-token',
                                    'PAPER_PUSHOVER_USER_KEY': 'private-key'}, clear=True):
            notify.send('pushover', 'Papers', 'test', opener=opener)
            self.assertNotIn('device', captured[-1])
            with patch.dict(os.environ, PAPER_PUSHOVER_DEVICE='migwings-A25'):
                notify.send('pushover', 'Papers', 'test', opener=opener)
                self.assertEqual(captured[-1]['device'], ['migwings-A25'])
                notify.send('pushover', 'Papers', 'test', opener=opener, device='tablet')
                self.assertEqual(captured[-1]['device'], ['tablet'])
                with self.assertRaises(ValueError):
                    notify.send('pushover', 'Papers', 'test', opener=opener, device='bad device')

    def test_webhook_json_and_https(self):
        def opener(request, **kwargs):
            self.assertEqual(json.loads(request.data)['message'], 'hello')
            return io.BytesIO(b'')
        with patch.dict(os.environ, PAPER_NOTIFY_WEBHOOK_URL='https://example.com/hook'):
            notify.send('webhook', 'title', 'hello', opener=opener)
        with patch.dict(os.environ, PAPER_NOTIFY_WEBHOOK_URL='http://example.com/hook'):
            with self.assertRaises(ValueError):
                notify.send('webhook', 'title', 'hello', opener=opener)

    def test_missing_credentials_and_private_failures(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError):
                notify.send('pushover', 'title', 'message')
            with self.assertRaises(ValueError):
                notify.send('discord', 'title', 'message')
        def opener(*args, **kwargs):
            raise urllib.error.URLError('secret-token-at-private-url')
        with patch.dict(os.environ, PAPER_NOTIFY_WEBHOOK_URL='https://example.com/private'):
            with self.assertRaisesRegex(ValueError, 'delivery failed') as error:
                notify.send('webhook', 'title', 'message', opener=opener)
            self.assertNotIn('secret', str(error.exception))

    def test_redirects_are_rejected(self):
        self.assertIsNone(notify.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://evil.invalid'))

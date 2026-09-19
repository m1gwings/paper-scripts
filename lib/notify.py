"""Small notification adapters. Credentials are read only from the environment."""
import argparse
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def discord_webhook_url(value):
    """Validate a Discord webhook URL and canonicalize Discord's legacy host."""
    parsed = urllib.parse.urlsplit(value.strip())
    if (parsed.scheme != 'https'
            or parsed.hostname not in ('discord.com', 'www.discord.com', 'discordapp.com')
            or not parsed.path.startswith('/api/webhooks/')
            or parsed.username or parsed.password):
        raise ValueError('DISCORD_WEBHOOK_URL must be a Discord HTTPS incoming-webhook URL.')
    if parsed.hostname == 'discordapp.com':
        parsed = parsed._replace(netloc='discord.com')
    return urllib.parse.urlunsplit(parsed)


def send(provider, title, message, url='', opener=None, device=None):
    if provider == 'none':
        return False
    payload = {'title': title, 'message': message, 'url': url}
    if provider == 'discord':
        endpoint = discord_webhook_url(os.environ.get('DISCORD_WEBHOOK_URL', ''))
        if len(title) > 256 or len(message) > 2048:
            raise ValueError('Discord titles are limited to 256 characters and messages to 2048.')
        embed = {'title': title, 'description': message, 'color': 0x5865F2}
        if url:
            link = urllib.parse.urlsplit(url)
            if link.scheme != 'https' or not link.hostname or link.username or link.password:
                raise ValueError('Notification links must be HTTPS URLs without user credentials.')
            embed['url'] = url
        repository = os.environ.get('GITHUB_REPOSITORY', '')
        if repository:
            embed['footer'] = {'text': repository[:2048]}
        data = json.dumps({
            'username': 'Paper workflow',
            'allowed_mentions': {'parse': []},
            'embeds': [embed],
        }).encode()
        content_type = 'application/json'
    elif provider == 'pushover':
        endpoint = 'https://api.pushover.net/1/messages.json'
        payload.update(token=os.environ.get('PAPER_PUSHOVER_APP_TOKEN', ''),
                       user=os.environ.get('PAPER_PUSHOVER_USER_KEY', ''))
        if not payload['token'] or not payload['user']:
            raise ValueError('Set PAPER_PUSHOVER_APP_TOKEN and PAPER_PUSHOVER_USER_KEY privately.')
        target = os.environ.get('PAPER_PUSHOVER_DEVICE', '') if device is None else device
        if target:
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,25}(?:,[A-Za-z0-9_-]{1,25})*', target):
                raise ValueError('Invalid Pushover device name; use the registered device name.')
            payload['device'] = target
        data = urllib.parse.urlencode(payload).encode()
        content_type = 'application/x-www-form-urlencoded'
    elif provider == 'webhook':
        endpoint = os.environ.get('PAPER_NOTIFY_WEBHOOK_URL', '')
        parsed = urllib.parse.urlsplit(endpoint)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('PAPER_NOTIFY_WEBHOOK_URL must be an HTTPS URL without user credentials.')
        data = json.dumps(payload).encode()
        content_type = 'application/json'
    else:
        raise ValueError('Unknown notification provider; use discord, webhook, pushover, or none.')
    headers = {'Content-Type': content_type}
    if provider == 'discord':
        # Discord may block HTTP API clients that omit its required User-Agent.
        headers['User-Agent'] = 'DiscordBot (https://github.com/m1gwings/paper-scripts, 1)'
    request = urllib.request.Request(endpoint, data=data, headers=headers, method='POST')
    # Never follow a redirect carrying credentials; never echo server error bodies/URLs.
    opener = opener or urllib.request.build_opener(NoRedirect()).open
    try:
        with opener(request, timeout=20) as response:
            if provider == 'pushover' and json.load(response).get('status') != 1:
                raise ValueError('Pushover rejected the notification. Check credentials privately.')
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        raise ValueError('Notification delivery failed; check provider connectivity and credentials.') from None
    return True


def main(args=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--provider', default=os.environ.get('PAPER_NOTIFY_PROVIDER', 'none'))
    parser.add_argument('--title', required=True)
    parser.add_argument('--message', required=True)
    parser.add_argument('--url', default='')
    parser.add_argument('--device', default=None, help='Pushover device; default PAPER_PUSHOVER_DEVICE or all devices')
    parsed = parser.parse_args(args)
    try:
        sent = send(parsed.provider, parsed.title, parsed.message, parsed.url, device=parsed.device)
    except ValueError as error:
        parser.exit(1, f'paper notify: {error}\n')
    print('Notification sent.' if sent else 'Notifications disabled (provider: none).')


if __name__ == '__main__':
    main()

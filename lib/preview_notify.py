"""Read trusted GitHub run metadata; never consume build artifacts as instructions."""
import json
import os
from pathlib import Path
import subprocess
from notify import send


def automatic_notification_ready(provider):
    """Missing optional delivery setup must not fail a completed preview."""
    required = {
        'none': (),
        'discord': ('DISCORD_WEBHOOK_URL',),
        'pushover': ('PAPER_PUSHOVER_APP_TOKEN', 'PAPER_PUSHOVER_USER_KEY'),
        'webhook': ('PAPER_NOTIFY_WEBHOOK_URL',),
    }
    if provider == 'none':
        print('Automatic preview notification skipped: notifications are disabled.')
        return False
    if provider in required and any(not os.environ.get(key, '').strip()
                                    for key in required[provider]):
        print('::notice::Automatic preview notification skipped: delivery is not '
              'configured in the paper-notify environment. The preview result '
              'and PDF artifact remain available in Actions. Configure the selected '
              'provider privately to enable delivery.')
        return False
    return True


def main():
    event = json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())
    run = event['workflow_run']
    repo = os.environ['GITHUB_REPOSITORY']
    if run['head_repository']['full_name'] != repo:
        raise SystemExit('Foreign repository refused.')
    if run.get('conclusion') == 'cancelled':
        return
    provider = os.environ.get('PAPER_NOTIFY_PROVIDER', 'none')
    if not automatic_notification_ready(provider):
        return
    status = run['conclusion']
    url = run['html_url']
    if status == 'success':
        result = subprocess.run(['gh', 'api', f'repos/{repo}/actions/runs/{int(run["id"])}/artifacts'],
                                text=True, capture_output=True, check=True)
        artifacts = json.loads(result.stdout)['artifacts']
        for artifact in artifacts:
            if artifact['name'] in ('paper.pdf', 'paper-preview') and not artifact['expired']:
                url = f'https://github.com/{repo}/actions/runs/{int(run["id"])}/artifacts/{int(artifact["id"])}'
                break
        else:
            status = 'PDF artifact missing'
    branch = run['head_branch'][:80]
    sha = run['head_sha'][:12]
    send(provider, 'Paper preview',
         f'{branch} ({sha}): {status}. Sign in to GitHub to download the PDF.', url)


if __name__ == '__main__':
    main()

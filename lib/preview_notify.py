"""Read trusted GitHub run metadata; never consume build artifacts as instructions."""
import json
import os
from pathlib import Path
import subprocess
from notify import send


def main():
    event = json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())
    run = event['workflow_run']
    repo = os.environ['GITHUB_REPOSITORY']
    if run['head_repository']['full_name'] != repo:
        raise SystemExit('Foreign repository refused.')
    if run.get('conclusion') == 'cancelled':
        return
    status = run['conclusion']
    url = run['html_url']
    if status == 'success':
        result = subprocess.run(['gh', 'api', f'repos/{repo}/actions/runs/{int(run["id"])}/artifacts'],
                                text=True, capture_output=True, check=True)
        artifacts = json.loads(result.stdout)['artifacts']
        for artifact in artifacts:
            if artifact['name'] == 'paper-preview' and not artifact['expired']:
                url = f'https://github.com/{repo}/actions/runs/{int(run["id"])}/artifacts/{int(artifact["id"])}'
                break
        else:
            status = 'PDF artifact missing'
    branch = run['head_branch'][:80]
    sha = run['head_sha'][:12]
    send(os.environ.get('PAPER_NOTIFY_PROVIDER', 'none'), 'Paper preview',
         f'{branch} ({sha}): {status}. Sign in to GitHub to download the PDF.', url)


if __name__ == '__main__':
    main()

"""Install command links without replacing unrelated user executables."""
import argparse
from pathlib import Path
import os


COMMANDS = ('paper', 'project-open', 'project-terminal', 'workspace-edit')


def install(source, destination):
    destination.mkdir(parents=True, exist_ok=True)
    # Validate every destination before making changes.
    for name in COMMANDS:
        target = destination / name
        if (target.exists() or target.is_symlink()) and target.resolve() != source / name:
            raise ValueError(f'Review existing command before replacing {target}')
    for name in COMMANDS:
        target = destination / name
        (source / name).chmod((source / name).stat().st_mode | 0o111)
        if not target.exists() and not target.is_symlink():
            target.symlink_to(source / name)
    print(f'Installed command links in {destination}; source remains in {source}.')
    if str(destination) not in os.environ.get('PATH', '').split(os.pathsep):
        print(f'Add {destination} to PATH in your shell profile.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bin-dir', type=Path, default=Path.home() / '.local/bin')
    args = parser.parse_args()
    try:
        install(Path(__file__).resolve().parents[1], args.bin_dir.expanduser().resolve())
    except (OSError, ValueError) as error:
        parser.exit(1, f'paper-scripts install: {error}\n')

#!/usr/local/bin/python3 -I
"""Install a development command from the app's verified cache into this project."""
import argparse
import os
from pathlib import Path

source = Path('/usr/local/share/jarvis/development')
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--list', action='store_true')
parser.add_argument('tools', nargs='*', choices=None)
args = parser.parse_args()
names = sorted(item.name for item in source.iterdir() if item.is_file())
if args.list or not args.tools:
    print(' '.join(names))
else:
    target = Path('/project/.local/bin')
    for name in args.tools:
        if name not in names:
            parser.error(f'{name} is outside the development cache. Request the package through JARVIS.')
    target.mkdir(parents=True, exist_ok=True)
    for name in args.tools:
        path = target / name
        try:
            path.symlink_to(source / name)
        except FileExistsError:
            if not path.is_symlink() or os.readlink(path) != str(source / name):
                parser.error(f'{path} already contains a different file')
        print(path)

"""Decide whether to build and publish verified CI packages using GitHub CLI.

Build identity comes from build.sh. Public releases contain only the three packages;
the workflow artifact retains metadata for retrying a failed publication.
"""

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request


def release_for(tag):
    repo = os.environ['GITHUB_REPOSITORY']
    request = urllib.request.Request(
        f'https://api.github.com/repos/{repo}/releases/tags/{tag}',
        headers={'Authorization': 'Bearer ' + os.environ['GH_TOKEN'],
                 'Accept': 'application/vnd.github+json'})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise


def gh(*args):
    subprocess.run(['gh', *args, '--repo', os.environ['GITHUB_REPOSITORY']], check=True)


def verify(info, directory):
    assets = info['assets']
    expected = {'boot.img', 'boot.img.tar', info['anykernel_name']}
    if len(expected) != 3 or set(assets) != expected:
        raise ValueError('Expected exactly the three kernel packages')
    for name, digest in assets.items():
        if Path(name).name != name or not re.fullmatch(r'[A-Za-z0-9_.-]+', name):
            raise ValueError('Invalid package name')
        path = directory / name
        if path.is_symlink() or not path.is_file():
            raise ValueError('Missing package: ' + name)
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('Package checksum mismatch: ' + name)


def main():
    mode = sys.argv[1]
    if mode == 'decide':
        env = dict(os.environ, E1S_RESOLVE_ONLY='1')
        env.pop('E1S_RESUKISU_SHA', None)
        subprocess.run(['./build.sh'], env=env, check=True)
        info = json.loads(Path('out/resolved.json').read_text())
        tag = 'kernel-' + info['build_key']
        release = release_for(tag)
        needed = release is None or release['draft']
        with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
            output.write(f"sha={info['resukisu_sha']}\nkey={info['build_key']}\nneeded={str(needed).lower()}\n")
        print('Build required:', needed)
    elif mode == 'publish':
        info = json.loads(Path('out/build-info.json').read_text())
        if info['build_key'] != os.environ['EXPECTED_BUILD_KEY']:
            raise ValueError('Artifact build identity mismatch')
        if info['resukisu_sha'] != os.environ['EXPECTED_RESUKISU_SHA']:
            raise ValueError('Artifact ReSukiSU identity mismatch')
        verify(info, Path('release'))
        tag = 'kernel-' + info['build_key']
        existing = release_for(tag)
        if existing and not existing['draft']:
            with tempfile.TemporaryDirectory() as temp:
                gh('release', 'download', tag, '--dir', temp)
                verify(info, Path(temp))
            print('This exact build is already published.')
            return
        notes = (f"Samsung Galaxy S24 SM-S921B (e1s)\n\n"
                 f"Kernel: {info['kernel_release']}\n\n"
                 f"ReSukiSU: `{info['resukisu_sha']}`\n\n"
                 f"Build: `{info['build_key']}`\n\n"
                 "Software checks passed. Device flashing and boot have not been tested.\n\n"
                 "SHA-256:\n```text\n" + ''.join(
                     f'{digest}  {name}\n' for name, digest in info['assets'].items()) + '```\n')
        Path('out/release-notes.md').write_text(notes)
        title = f"e1s {info['kernel_version']} ReSukiSU {info['resukisu_sha'][:7]} ({info['build_timestamp']})"
        if existing is None:
            gh('release', 'create', tag, '--draft', '--target', os.environ['GITHUB_SHA'],
               '--title', title, '--notes-file', 'out/release-notes.md')
        else:
            gh('release', 'edit', tag, '--title', title, '--notes-file', 'out/release-notes.md')
        gh('release', 'upload', tag, *[str(Path('release') / name) for name in info['assets']], '--clobber')
        # Read back uploaded bytes before making the release public.
        with tempfile.TemporaryDirectory() as temp:
            gh('release', 'download', tag, '--dir', temp)
            if {p.name for p in Path(temp).iterdir()} != set(info['assets']):
                raise ValueError('Unexpected files in draft release')
            verify(info, Path(temp))
        gh('release', 'edit', tag, '--draft=false', '--latest')
    else:
        raise ValueError('Expected decide or publish')


if __name__ == '__main__':
    main()

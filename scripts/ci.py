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
    return github_json(f'repos/{repo}/releases/tags/{tag}')


def github_json(path):
    request = urllib.request.Request(
        'https://api.github.com/' + path,
        headers={'Authorization': 'Bearer ' + os.environ['GH_TOKEN'],
                 'Accept': 'application/vnd.github+json'})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise


def manager_or_docs_only(comparison, base, head):
    # GitHub returns at most 300 files. Treat the boundary as incomplete.
    if not comparison or comparison.get('status') != 'ahead':
        return False
    if comparison.get('base_commit', {}).get('sha') != base:
        return False
    if comparison.get('merge_base_commit', {}).get('sha') != base:
        return False
    commits = comparison.get('commits', [])
    if not commits or commits[-1].get('sha') != head:
        return False
    files = comparison.get('files', [])
    if not 0 < len(files) < 300:
        return False
    for item in files:
        paths = [item.get('filename', '')]
        if item.get('status') == 'renamed':
            paths.append(item.get('previous_filename', ''))
        if not all(path.startswith(('manager/', 'docs/')) for path in paths):
            return False
    return True


def can_keep_published_kernel(info):
    repo = os.environ['GITHUB_REPOSITORY']
    latest = github_json(f'repos/{repo}/releases/latest')
    if not latest or latest['draft'] or latest['prerelease']:
        return False
    tag = latest['tag_name']
    match = re.search(r'^ReSukiSU: `([0-9a-f]{40})`$', latest.get('body', ''), re.M)
    if not re.fullmatch(r'kernel-[0-9a-f]{64}', tag) or not match:
        return False
    base = match[1]
    # Reuse build.sh's identity calculation with the published SHA. This proves
    # source, tools, configuration and local automation have not changed.
    env = dict(os.environ, E1S_RESOLVE_ONLY='1', E1S_RESUKISU_SHA=base)
    subprocess.run(['./build.sh'], env=env, check=True)
    previous = json.loads(Path('out/resolved.json').read_text())
    Path('out/resolved.json').write_text(json.dumps(info) + '\n')
    if tag != 'kernel-' + previous['build_key']:
        return False
    comparison = github_json(f"repos/ReSukiSU/ReSukiSU/compare/{base}...{info['resukisu_sha']}")
    return manager_or_docs_only(comparison, base, info['resukisu_sha'])


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
        if needed:
            try:
                if can_keep_published_kernel(info):
                    needed = False
                    print('Only manager/docs changed; keeping the published kernel and its original SHA.')
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
                print(f'Upstream comparison unavailable; building conservatively: {error}')
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

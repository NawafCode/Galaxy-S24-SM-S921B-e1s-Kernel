"""Verify the built Image, root symbols, and kernel configuration.
Inputs: build.sh environment and build output. Writes out/build-info.json."""

import hashlib, json, os, pathlib, re
root, work, dist = (pathlib.Path(os.environ[k]) for k in ('ROOT', 'WORK', 'DIST'))
image = (dist / 'Image').read_bytes()
if image[56:60] != b'ARM\x64':
    raise ValueError('Not an ARM64 Image')
match = re.search(rb'Linux version ([^\s\x00]+)', image)
if not match:
    raise ValueError('Built kernel release missing')
release = match[1].decode()
version = re.match(r'\d+\.\d+\.\d+', release).group()
branch = re.search(r'^BRANCH=android(\d+)-', (work / 'kernel/build.config.constants').read_text(), re.M)
if not branch:
    raise ValueError('Android kernel branch missing')
symbols = (dist / 'System.map').read_text()
for symbol in ('ksu_handle_execveat', 'ksu_handle_setresuid', 'susfs_init'):
    if not re.search(r'\b' + symbol + r'$', symbols, re.M):
        raise ValueError('Root integration missing from built kernel: ' + symbol)
config = (dist / '.config').read_text().splitlines()
for line in (root / 'config/root.config').read_text().splitlines():
    if line.startswith('CONFIG_') and line not in config:
        raise ValueError('Required configuration missing: ' + line)
    if line.startswith('# CONFIG_') and line.endswith(' is not set'):
        key = line.split()[1]
        if any(value.startswith(key + '=') and value != key + '=n' for value in config):
            raise ValueError('Disabled option enabled: ' + key)
info = dict(build_key=os.environ['BUILD_KEY'], build_timestamp=os.environ['BUILD_STARTED'],
            kernel_release=release, kernel_version=version, android_version=branch[1],
            resukisu_sha=os.environ['RESUKISU_SHA'], susfs_sha=os.environ['SUSFS_SHA'],
            image_sha256=hashlib.sha256(image).hexdigest(), hardware_boot_verified=False)
info['source_date_epoch'] = int(os.environ['SOURCE_DATE_EPOCH'])
info['anykernel_sha'] = os.environ['ANYKERNEL_SHA']
(root / 'out/build-info.json').write_text(json.dumps(info, indent=2) + '\n')

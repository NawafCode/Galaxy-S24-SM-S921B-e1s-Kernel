"""Verify the built Image, root symbols, and kernel configuration.
Inputs: build.sh environment and build output. Writes out/build-info.json."""

import hashlib, json, os, pathlib, re, struct
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
required_symbols = ('ksu_handle_execveat', 'ksu_handle_setresuid', 'susfs_init',
                    'ksu_handle_init_module', 'ksu_handle_finit_module', 'ksu_module_blacklist_init',
                    'ksu_setup_preinit_file', 'ksu_preinit_handle_post_execveat',
                    'susfs_set_priority_uid_filter', 'susfs_parse_priority_app_strings',
                    'susfs_add_sus_type', 'susfs_add_sus_avd_allowed_by_type')
for symbol in required_symbols:
    if not re.search(r'\b' + symbol + r'(?:\.llvm\.\d+)?$', symbols, re.M):
        raise ValueError('Root integration missing from built kernel: ' + symbol)
# The in-tree driver resolves this native loader variable by name at boot.
if len(re.findall(r'^\S+\s+[bBdD]\s+module_blacklist$', symbols, re.M)) != 1:
    raise ValueError('Native module_blacklist symbol missing or ambiguous')
# These assembly labels survive LTO and prove that preinit was not silently disabled.
addresses = {name: int(address, 16) for address, name in
             re.findall(r'^([0-9a-fA-F]+)\s+\w\s+(_text|ksu_preinit_runner_start|ksu_preinit_runner_end)$', symbols, re.M)}
if set(addresses) != {'_text', 'ksu_preinit_runner_start', 'ksu_preinit_runner_end'}:
    raise ValueError('Embedded preinit runner symbols missing')
start = addresses['ksu_preinit_runner_start'] - addresses['_text']
end = addresses['ksu_preinit_runner_end'] - addresses['_text']
if not 0 <= start < end <= len(image):
    raise ValueError('Invalid embedded preinit runner range')
runner = image[start:end]
if len(runner) < 64 or runner[:6] != b'\x7fELF\x02\x01' or struct.unpack_from('<HH', runner, 16) != (2, 183):
    raise ValueError('Embedded preinit runner is not an ARM64 executable')
config = (dist / '.config').read_text().splitlines()
for line in (root / 'config/root.config').read_text().splitlines():
    if line.startswith('CONFIG_') and line not in config:
        raise ValueError('Required configuration missing: ' + line)
    if line.startswith('# CONFIG_') and line.endswith(' is not set'):
        key = line.split()[1]
        if any(value.startswith(key + '=') and value != key + '=n' for value in config):
            raise ValueError('Disabled option enabled: ' + key)
# Choice symbols are set indirectly; check the resolved strings as well.
for expected in ('CONFIG_DEFAULT_TCP_CONG="bbr"', 'CONFIG_DEFAULT_NET_SCH="fq"',
                 'CONFIG_ZRAM_DEF_COMP="zstd"', 'CONFIG_NTFS3_FS=y'):
    if expected not in config:
        raise ValueError('Tuning did not resolve: ' + expected)
info = dict(build_key=os.environ['BUILD_KEY'], build_timestamp=os.environ['BUILD_STARTED'],
            kernel_release=release, kernel_version=version, android_version=branch[1],
            resukisu_sha=os.environ['RESUKISU_SHA'], susfs_sha=os.environ['SUSFS_SHA'],
            image_sha256=hashlib.sha256(image).hexdigest(), hardware_boot_verified=False)
info['source_date_epoch'] = int(os.environ['SOURCE_DATE_EPOCH'])
info['anykernel_sha'] = os.environ['ANYKERNEL_SHA']
info['bakasu_tree'] = os.environ['BAKASU_TREE']
info['patches'] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((root / 'patches').glob('*.patch'))}
info['preinit_runner_sha256'] = hashlib.sha256(runner).hexdigest()
info['preinit_runner_size'] = len(runner)
uapi = (work / 'kernel/ReSukiSU/kernel/include/uapi/supercall.h').read_text()
uapi_version = re.search(r'KERNEL_SU_UAPI_VERSION\s*=\s*(\d+)', uapi)
if not uapi_version or int(uapi_version[1]) < 6:
    raise ValueError('BakaSU UAPI v6 or newer is required')
info['ksu_uapi_version'] = int(uapi_version[1])
(root / 'out/build-info.json').write_text(json.dumps(info, indent=2) + '\n')

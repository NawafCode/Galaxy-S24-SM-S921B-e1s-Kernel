"""Create and verify AnyKernel3 ZIP, boot.img, and boot.img.tar.
Inputs: build.sh environment and verified metadata. Updates release/ and metadata; preserves changed releases."""

import datetime, hashlib, io, json, os, pathlib, re, struct, subprocess, tarfile, tempfile, zipfile
root, dist, stage = (pathlib.Path(os.environ[k]) for k in ('ROOT', 'DIST', 'STAGE'))
info = json.loads((root / 'out/build-info.json').read_text())
if info['build_key'] != os.environ['BUILD_KEY'] or info['resukisu_sha'] != os.environ['RESUKISU_SHA']:
    raise ValueError('Build metadata does not match current inputs')
image = (dist / 'Image').read_bytes()
if hashlib.sha256(image).hexdigest() != info['image_sha256']:
    raise ValueError('Image changed since the successful build')
stamp = datetime.datetime.fromisoformat(info['build_timestamp'].replace('Z', '+00:00'))
name = (f"Nawaf-e1s-Kernel-{info['kernel_version']}-android{info['android_version']}"
        f"-Nawaf-BakaSU-{info['resukisu_sha'][:7]}-SuSFS-{stamp:%Y%m%d-%H%M}.zip")
if not re.fullmatch(r'[A-Za-z0-9.-]+\.zip', name):
    raise ValueError('Unsafe package name')
assets = stage / 'assets'
assets.mkdir()
(stage / 'Image').write_bytes(image)
for path in stage.rglob('*'):
    os.utime(path, (stamp.timestamp(), stamp.timestamp()), follow_symlinks=False)
for binary in ('busybox', 'magiskboot', 'magiskpolicy'):
    header = (stage / 'tools' / binary).read_bytes()[:20]
    if header[:5] != b'\x7fELF\x02' or struct.unpack_from('<H', header, 18)[0] != 183:
        raise ValueError('Installer tool is not ARM64: ' + binary)
subprocess.run(['zip', '-q', '-r', '-X', str(assets / name), 'META-INF', 'tools', 'LICENSE', 'anykernel.sh', 'Image'], cwd=stage, check=True)
subprocess.run(['python3', str(pathlib.Path(os.environ['WORK']) / 'tools/mkbootimg/mkbootimg.py'),
                '--header_version', '4', '--kernel', str(stage / 'Image'), '--cmdline', '',
                '--os_version', os.environ['BOOT_OS_VERSION'], '--os_patch_level', os.environ['BOOT_OS_PATCH_LEVEL'],
                '--output', str(assets / 'boot.img')], check=True)
with (assets / 'boot.img').open('ab') as f:
    f.write(b'SEANDROIDENFORCE')
boot = (assets / 'boot.img').read_bytes()
if len(boot) > int(os.environ['BOOT_PARTITION_SIZE']):
    raise ValueError('Boot image exceeds partition size')
if boot[:8] != b'ANDROID!' or struct.unpack_from('<I', boot, 40)[0] != 4 or boot[4096:4096+len(image)] != image:
    raise ValueError('Boot image verification failed')
with tarfile.open(assets / 'boot.img.tar', 'w', format=tarfile.USTAR_FORMAT) as t:
    entry = tarfile.TarInfo('boot.img'); entry.size = len(boot); entry.mode = 0o644
    entry.mtime = int(stamp.timestamp()); t.addfile(entry, io.BytesIO(boot))
with zipfile.ZipFile(assets / name) as z:
    if z.testzip() or z.read('Image') != image:
        raise ValueError('AnyKernel verification failed')
with tarfile.open(assets / 'boot.img.tar') as t:
    if t.getnames() != ['boot.img'] or t.extractfile('boot.img').read() != boot:
        raise ValueError('TAR verification failed')
info['assets'] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in assets.iterdir()}
info['anykernel_name'] = name
(stage / 'build-info.json').write_text(json.dumps(info, indent=2) + '\n')
release = root / 'release'
unchanged = (release.is_dir()
             and {p.name for p in release.iterdir()} == set(info['assets'])
             and all((release / name).is_file()
                     and hashlib.sha256((release / name).read_bytes()).hexdigest() == digest
                     for name, digest in info['assets'].items()))
if not unchanged:
    previous = None
    if release.exists():
        previous = pathlib.Path(tempfile.mkdtemp(prefix='previous-release.', dir=root / 'out')) / 'release'
        release.rename(previous)
        print('Previous release saved:', previous)
    try:
        assets.rename(release)
    except OSError:
        if previous is not None:
            previous.rename(release)
        raise
(stage / 'build-info.json').replace(root / 'out/build-info.json')
print('Verified build packages:', release)
print('Hardware flashing/boot tests: NOT performed.')

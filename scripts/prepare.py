"""Extract the Samsung source/update and add the e1s config fragment.
Inputs: source ZIP and workspace paths as arguments. Writes only to the workspace."""

import io, pathlib, sys, tarfile, zipfile
work = pathlib.Path(sys.argv[2])
with zipfile.ZipFile(sys.argv[1]) as outer:
    with zipfile.ZipFile(io.BytesIO(outer.read('SM-S921B_16_Opensource.zip'))) as base:
        with base.open('Kernel.tar.gz') as stream, tarfile.open(fileobj=stream, mode='r|gz') as source:
            source.extractall(work, filter='data')
        (work / 'README_Kernel.txt').write_bytes(base.read('README_Kernel.txt'))
    name = 'SM-S921B_16_Opensource_S921BXXSFDZF2_S921BXXSFDZF3_S921BXXSGDZG1.zip'
    with zipfile.ZipFile(io.BytesIO(outer.read(name))) as update:
        for entry in update.infolist():
            if entry.filename.startswith('Kernel/') and not entry.is_dir():
                target = work / entry.filename.removeprefix('Kernel/')
                if not target.resolve().is_relative_to(work.resolve()):
                    raise ValueError('Unsafe update path')
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(update.read(entry))

p = work / 'projects/s5e9945/s5e9945.bzl'
text = p.read_text()
anchor = '            strip_modules = True,\n'
if text.count(anchor) != 1:
    raise ValueError('Samsung build definition changed; review the fragment integration')
text = text.replace(anchor, anchor + '            defconfig_fragments = ["//kernel:arch/arm64/configs/nawaf.config"] if name == "s5e9945_user" else [],\n')
p.write_text(text)

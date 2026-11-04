# Galaxy S24 — SM-S921B (e1s)

[Arabic README](README.AR.MD)

Kernel for the Samsung Galaxy S24 SM-S921B, based on Samsung's DZG1 source. It includes [BakaSU](https://github.com/Baka-SU/BakaSU) (formerly ReSukiSU) and SuSFS, and uses Samsung's Bazel/Kleaf build system.

**Tested on SM-S921B with firmware `S921BXXSGDZG1`.** Boot, root permissions, preinit, and module checks passed on 2026-11-02. See [Validation](#validation) for the results and remaining checks.

Source and tool files are available in the `build-inputs-v1` release. See [Automatic builds](#automatic-builds) to set up GitHub Actions in a fork.

## Build

Requirements: Linux x86_64, Python 3.12+, Git, curl, tar, zstd, zip, unzip, make, util-linux, and coreutils. Allow about 100 GiB of free space.

```bash
git clone https://github.com/NawafCode/Galaxy-S24-SM-S921B-e1s-Kernel.git
cd Galaxy-S24-SM-S921B-e1s-Kernel
./build.sh
```

This command downloads and checks the inputs, adds root support, builds the kernel, and saves the packages locally. Flashing the phone is a separate step; publishing is handled by GitHub Actions.

- `./build.sh --prepare`: prepare the source and tools only.
- `./build.sh --config`: generate the kernel configuration.
- `./build.sh --build`: build and package (the default).
- `./build.sh --package`: repackage the last successful build using the same build inputs.
- `./build.sh --help`: show the available options.

## Output

The `release/` folder contains three files: an AnyKernel3 ZIP, `boot.img`, and `boot.img.tar`.

```text
Nawaf-e1s-Kernel-<KERNEL_VERSION>-android<ANDROID_VERSION>-Nawaf-BakaSU-<SHA7>-SuSFS-<YYYYMMDD-HHMM>.zip
```

The ZIP name includes the kernel version, the source's Android branch, the first seven characters of the BakaSU commit ID, and the build time in UTC. Repackaging keeps the original name and timestamp.

## Inputs

- **Samsung source and tools:** downloaded from this repository's `build-inputs-v1` release and checked against their SHA-256 hashes.
- **BakaSU:** each build selects the latest commit from its default branch and uses that commit for the whole run. If the lookup fails, the build stops. Repackaging uses the saved commit.
- **SuSFS and AnyKernel3:** fixed commit IDs in `config/inputs.env`.

The Magisk APK supplies the ARM64 installer tools. BakaSU provides root. Original licenses are included with the source and tool packages.

The tested BakaSU revision supports the BakaSU, official KernelSU, and KOWSU managers. Install a compatible manager separately; a manager APK is not included in the kernel packages.

Kernel settings are in `config/root.config`; patches are in `patches/`. Review boot image settings in `config/inputs.env` when changing firmware.

## Root integration

The device tests used these revisions:

- BakaSU: `516d3e87fbc986ccefdde2c2765f1700612441a9`.
- SuSFS: `0d5b1ceb4ca4cddbe59d04233f4425a83030aa71`, from `gki-android14-6.1`.

New builds still select the latest BakaSU commit. Its compatibility patch must apply successfully. SuSFS still reports `v2.3.0`, so use its full commit ID to identify this revision.

| Patch | Purpose |
| --- | --- |
| `patches/susfs.patch` | Add SuSFS, preinit hooks, and SELinux integration to Samsung's source tree. |
| `patches/bakasu-susfs.patch` | Add policy tracking and app UID filter commands, refresh filters when apps change, and fix the `module_blacklist` name conflict. |
| `patches/susfs-types.patch` | Fix a lookup error that could hide unrelated SELinux types. |
| `patches/module-blacklist.patch` | Connect both kernel module-loading calls to BakaSU's blocklist support. |
| `patches/bazel-local.patch` | Fix WLAN source paths for local Bazel/Kleaf builds. |

SELinux tracking records allowed permissions, not audit rules. No vendor-specific kernel module blocklist is configured.

`CONFIG_HEADERS_INSTALL=y` provides the kernel headers needed to build the ARM64 preinit program embedded in `Image`. Before packaging, the build checks that program, the required kernel symbols, and the kernel settings.

The build checks the patched BakaSU source before and after compilation. `out/build-info.json` records the source revisions, patched source tree ID, patch hashes, UAPI version, and preinit program hash. The `-dirty` suffix in BakaSU's version comes from the local compatibility patch.

### Feature requirements

Use a compatible BakaSU Manager and `ksud` that support UAPI v6, the interface used to communicate with the kernel. These are installed separately from the kernel packages.

- **Preinit** runs a module's early actions before SELinux policy is loaded.
- **Hot installation** lets a compatible module apply changes without rebooting. Preinit actions still run on the next boot.
- **App UID filtering** limits what certain process-priority queries reveal about selected app IDs (UIDs). It requires the updated `ksu_susfs` tool or module from the selected SuSFS revision.
- **`shell_su_adb_only`** is optional. When shell already has root permission, this setting also checks that its process comes from ADB or a trusted KSU root process. It was disabled during the device tests.

For this built-in kernel (`CONFIG_KSU=y`), forced feature values use kernel boot parameters, such as `kernelsu.force_feature=shell_su_adb_only:1`. The upstream `/ksu_config` ramdisk file is for the module-based root loader. This project does not force feature values or add boot parameters.

## Tuning and hiding

These kernel settings differ from the Samsung default:

| Setting | Effect |
| --- | --- |
| `CONFIG_TCP_CONG_BBR` and `CONFIG_DEFAULT_BBR` | BBR is the default congestion control. CUBIC stays available. |
| `CONFIG_DEFAULT_FQ` | `fq` is the default queue discipline, which BBR uses for pacing. |
| `CONFIG_ZRAM_DEF_COMP_ZSTD` | New zram devices default to zstd instead of lzo-rle. Userspace can still choose another algorithm. |
| `CONFIG_NTFS3_FS=y` | Read and write NTFS drives over USB OTG. |

BBR can behave differently from CUBIC on lossy mobile links. Battery use and
throughput have not been measured yet.

All SuSFS kernel switches are enabled. Their settings are not stored in the
kernel: a root tool adds paths and identifiers while the phone runs, and a
reboot restores the defaults. The usual entries are the KSU state directories
(`/data/adb/modules`, `/data/adb/ksu`, `/data/adb/modules_update`), `sus_map`
for files loaded from a stored path, `hide_sus_mnts_for_non_su_procs 1`, a
spoofed `uname` release, and a bootconfig copy without the unlocked-boot
markers. The `selinux_hide` feature is separate and is toggled through `ksud`.

These entries only affect app processes at UID 10000 and above, so check hiding
from an app, not from root or ADB shell. Nothing is forced at boot; a module or
script has to apply the entries again after each reboot. The local test tooling
builds an optional `e1s-susfs-hide` module that re-applies them after
`post-fs-data`. It uses `add_sus_path_loop` for paths because f2fs can drop a
cold inode flag; `sus_map` has no loop variant, so the module also refreshes it
after boot.

## Validation

### Device hiding checks — 2026-11-04

Checked on the tuning build with the test app at UID 10382 from the
`untrusted_app` domain:

| Check | Result |
| --- | --- |
| App sees the sus_path probe file | `ENOENT` |
| Mapped sample in `/proc/self/maps` | 0 lines |
| `uname -r` | stock-style release, no `-nawaf-bakasu` |
| `susfs_init` / `ksu_handle_execveat` in `kallsyms` | hidden |
| `linux_banner` in `kallsyms` (control) | still present |
| `orange` marker in `bootconfig` | 0 |

`selinux_hide` was enabled through `ksud` during the run and disabled again
after it. The same checks passed from a fresh boot with the optional module
installed, which shows the entries are restored automatically. Long-running
inode eviction is handled by `add_sus_path_loop` plus the module's periodic
`sus_map` refresh.

The test module, app, and device-side files were removed afterwards. SELinux
was Enforcing after the final reboot.

### Local checks — 2026-11-01

- The full Samsung kernel build and all eight local regression tests passed.
- Repackaging produced identical copies of all three packages without creating another backup.
- Ten offline checks of the test APK and module packages passed before testing on the phone.

The build reported `depmod` warnings for 87 symbols. All 87 were found in the combined `Module.symvers` file.

### Device checks — 2026-11-02

The tested kernel was `6.1.157-android14-11-DZG1-nawaf-bakasu`, running on SM-S921B with firmware `S921BXXSGDZG1`.

| Check | Result |
| --- | --- |
| App root permissions | Denying, granting, and revoking root all worked. |
| Test module | Installation, disabling, re-enabling, and removal worked. |
| Preinit | Ran before `post-fs-data` on each boot with the test module enabled. |
| Hot installation | Updated the test module without a reboot. |
| Reboots | Five reboots completed; SELinux was Enforcing after each one. |
| Cleanup | The test app, module, and device-side test files were removed. |

These results apply to the tested build and a small test module. Filesystem mounting, kernel module (`.ko`) loading, app UID filtering, and SELinux hiding still need separate tests. Calls, Wi-Fi, the camera, battery use, temperature, and long-term stability also need further checks.

Development tests and device logs are kept locally in Git-ignored directories. The build script records `hardware_boot_verified=false` because it only checks build output; the device results above are recorded separately.

## Local files

These paths are excluded from Git:

| Path | Contents |
| --- | --- |
| `.cache/` | Downloaded files and copies of upstream repositories |
| `out/bazel-workspace/` | Source, tools, and build output |
| `out/build.log` | Build log |
| `out/build-info.json` | Build details and checksums |
| `out/device-validation/` | Local test tools and device reports |
| `out/previous-build.*/` | Workspaces saved when inputs change |
| `out/previous-release.*/` | Previous packages saved when results change |
| `release/` | The three packages ready for flashing |
| `tests/` | Local regression tests |

Temporary packaging files are removed automatically. Existing packages are backed up only when their contents change. Saved builds and backups remain until you remove them.

## Code layout

`build.sh` controls the local build. It handles downloads, commit checks, logs, root integration, and Bazel/Kleaf. A lock prevents two builds from running at the same time.

| File | Responsibility |
| --- | --- |
| `scripts/prepare.py` | Extract Samsung source and update its build definition |
| `scripts/verify_kernel.py` | Check the built kernel and save build metadata |
| `scripts/package.py` | Create and verify the three packages |
| `scripts/ci.py` | Decide whether CI needs a build and publish verified packages |

Settings are in `config/`, and source patches are in `patches/`. The build ID (`BUILD_KEY`) covers the build scripts, settings, patches, workflow, and BakaSU commit. This prevents reuse of a workspace or build metadata from different inputs.

Some cache paths and metadata keys still use the old ReSukiSU name for compatibility with saved builds. The repository has no project-level `LICENSE` file; upstream components keep their own licenses.

## Automatic builds

`.github/workflows/build.yml` runs the same build script on GitHub Actions. When enabled, it checks BakaSU every six hours, when build-related files are pushed to `main`, or when you select **Run workflow**. A published build with the same build ID is skipped. Each run uses the same selected BakaSU commit from preparation through compilation.

To enable it in a new repository:

1. Create a `build-inputs-v1` release containing `SM-S921B.zip`, `tools-core.tar.zst`, `tools-clang.tar.zst`, `tools-ndk.tar.zst`, and `Magisk-v30.7.apk`. Do not mark this input release as Latest. Update the download URL and hashes in `config/` for your repository.
2. In repository **Settings → Secrets and variables → Actions → Variables**, add `ENABLE_KERNEL_CI` with value `true`.
3. Run **Build e1s kernel** manually and review the logs and packages. The same variable enables scheduled and push-triggered runs. Builds that pass all checks are published automatically.

The default runner is `ubuntu-24.04`. On GitHub-hosted runners, the workflow removes unused Android, .NET, GHC, and Boost SDK directories to free space. It then checks for at least 60 GiB of free space. If more space is needed, set the `KERNEL_RUNNER` repository variable to the label of an available Linux x64 runner. Larger hosted runners may cost money. Build time and resource use depend on the inputs and runner.

The cache stores downloaded input files. Each build checks their SHA-256 hashes and extracts them when preparing a workspace. Missing files are downloaded from the input release. Compiled objects and the full build workspace are not cached between workflow runs.

Only the release job has write access to the repository. It checks the package hashes, uploads all three files to a draft release, downloads them to check the uploaded bytes, and then marks the release as Latest. If a build fails, the previous release remains available. Build metadata and logs are saved as Actions artifacts; public releases contain the three kernel packages.

If publishing fails after the package artifact is saved, use **Re-run failed jobs** within 14 days to retry publishing without rebuilding. Starting a new workflow run does not reuse artifacts from an older run. A later trigger can retry a failed build. GitHub may delay scheduled runs.

`scripts/ci.py` uses Python's standard library and the GitHub CLI provided on hosted runners. Passing a preselected BakaSU commit to `build.sh` is reserved for Actions. Normal local builds select the latest commit themselves. CI can read both ReSukiSU and BakaSU release notes.

### When CI rebuilds

CI compares the latest BakaSU commit with the commit used by the last published kernel. If this project's build inputs are unchanged and all upstream changes are inside `manager/` or `docs/`, CI keeps the published kernel. Any other change, an incomplete comparison, or a different commit history triggers a build.

Skipped manager or documentation updates do not change the published kernel's recorded commit or version. Local `./build.sh` builds still select the latest commit.

# Galaxy S24 — SM-S921B (e1s)

[Arabic README](README.MD.AR)

Samsung DZG1 kernel with [BakaSU](https://github.com/Baka-SU/BakaSU) (formerly ReSukiSU) and SuSFS, built using Samsung's Bazel/Kleaf target.

Local builds and package checks pass. GitHub Actions has also built and published kernel packages successfully. Flashing and booting on the phone have not been tested.
Source and tool archives are provided in the `build-inputs-v1` release. Automatic builds are enabled in this repository; forks must enable them in their own settings.

## Build

Requirements: Linux x86_64, Python 3.12+, Git, curl, tar, zstd, zip, unzip, make, util-linux, and coreutils. Allow about 100 GiB of free space.

```bash
git clone https://github.com/NawafCode/Galaxy-S24-SM-S921B-e1s-Kernel.git
cd Galaxy-S24-SM-S921B-e1s-Kernel
./build.sh
```

One command downloads and checks the inputs, integrates root support, builds, and packages the kernel. It does not flash the phone or publish files.

- `./build.sh --prepare`: prepare the source and tools only.
- `./build.sh --config`: generate the kernel configuration.
- `./build.sh --build`: build and package (the default).
- `./build.sh --package`: repackage the last successful build.
- `./build.sh --help`: show the available options.

## Output

The `release/` folder contains AnyKernel3 ZIP, `boot.img`, and `boot.img.tar`.

```text
Nawaf-e1s-Kernel-<KERNEL_VERSION>-android<ANDROID_VERSION>-Nawaf-BakaSU-<SHA7>-SuSFS-<YYYYMMDD-HHMM>.zip
```

The ZIP name uses the built kernel version, source Android branch, verified BakaSU SHA, and build time in UTC. Repackaging keeps that name and timestamp.

## Inputs

- Samsung source and tool archives: this repository's `build-inputs-v1` release, checked against their SHA-256 hashes.
- BakaSU: the latest default-branch commit at each build startup, verified and fixed for that run. An upstream lookup failure stops the build. Repackaging uses the saved commit.
- SuSFS and AnyKernel3: fixed commits in `config/inputs.env`.

The Magisk APK supplies ARM64 installer tools only; BakaSU provides root. Original licenses remain with the source and tool packages.

Upstream now supports the BakaSU, official KernelSU, and KOWSU managers. Its built-in support for MKSU, RKSU, and SukiSU-Ultra managers was removed. This repository does not build or bundle a manager APK.

Kernel settings are in `config/root.config`; patches are in `patches/`. Review boot image settings in `config/inputs.env` when changing firmware.

## Local files

| Path | Contents |
| --- | --- |
| `.cache/` | Reusable downloads and upstream checkouts |
| `out/bazel-workspace/` | Source, tools, and build output |
| `out/build.log` | Build log |
| `out/build-info.json` | Build details and checksums |
| `out/previous-build.*/` | Workspaces saved when inputs change |
| `out/previous-release.*/` | Previous packages saved when results change |

Temporary packaging files are cleaned up automatically. Identical repackaging creates no extra backup. Saved builds and releases remain until you remove them.

## Code layout

`build.sh` is the entry point. It handles downloads, commit checks, locking, logs, root integration, and Bazel/Kleaf. Three Python helpers hold the existing preparation, verification, and packaging logic:

| File | Responsibility |
| --- | --- |
| `scripts/prepare.py` | Extract Samsung source and update its build definition |
| `scripts/verify_kernel.py` | Check the built kernel and save build metadata |
| `scripts/package.py` | Create and verify the three packages |

Configuration stays in `config/`, and source patches stay in `patches/`. Changes to helpers and the workflow affect `BUILD_KEY`, so incompatible workspaces and metadata cannot be reused. No project `LICENSE` has been selected yet; bundled upstream licenses still apply to their respective components.

## Automatic builds

`.github/workflows/build.yml` runs the same build script on GitHub Actions. It checks BakaSU every six hours, on relevant pushes to `main`, or through **Run workflow**. Identical published build keys are skipped. The selected full BakaSU SHA stays fixed throughout preparation and compilation.

To enable it in a new repository:

1. Publish the five input archives as `build-inputs-v1`, without marking that input release Latest. Keep the URLs and hashes in `config/` correct for your repository.
2. In repository **Settings → Secrets and variables → Actions → Variables**, add `ENABLE_KERNEL_CI` with value `true`.
3. Run **Build e1s kernel** manually and review the logs and packages. Enabling this variable also enables the scheduled and push triggers, and a successful run publishes automatically.

The default runner is `ubuntu-24.04`. The workflow removes unused Android/.NET/GHC/Boost SDK directories on GitHub-hosted runners, then requires 60 GiB free. If the check fails, set the `KERNEL_RUNNER` repository variable to a suitable Linux x64 runner label available to the repository. Larger hosted runners can incur charges. Build time and resource use vary with the inputs and runner.

The cache stores compressed input archives, not the compiled workspace. Restoring it still transfers data; extraction runs again, and SHA-256 checks always run. A cache miss falls back to the input release. No compiler cache is configured yet.

Only the release job has write access. It verifies the saved package checksums, uploads all three packages to a draft, downloads them for verification, then publishes the release as Latest. Failed builds leave the previous release available. Internal metadata and logs stay in Actions artifacts rather than public release assets.

If publication fails after the package artifact was saved, use **Re-run failed jobs** within its 14-day retention period to retry publication without recompiling. A new workflow run does not automatically recover artifacts from older runs. Failed builds can be retried on the next trigger; only published successful builds are deduplicated. Schedules may be delayed by GitHub.

`scripts/ci.py` handles the publication decision and release verification. It uses Python's standard library and the GitHub CLI already available on hosted runners. The internal commit handoff is restricted to Actions; normal local builds still resolve the latest upstream commit themselves. Legacy metadata keys and cache paths are retained, and CI can read both ReSukiSU and BakaSU release notes. Neither the workflow nor the script flashes a phone.

### When CI rebuilds

CI compares the latest selected BakaSU commit with the last published kernel. If local build inputs are unchanged and the complete upstream diff touches only `manager/` or `docs/`, it keeps the existing kernel. Changes elsewhere, renamed kernel files, divergent history or incomplete comparisons trigger a build. Git-derived version numbers alone do not trigger a rebuild for manager/docs-only commits; the published kernel retains its actual SHA and version. Local `./build.sh` still builds the newest commit.

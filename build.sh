#!/usr/bin/env bash
# Build Samsung e1s with the latest BakaSU commit, then verify/package three boot assets.
# Downloads go to .cache/downloads; sources, logs and metadata go to out/.
# Previous builds and changed release files are retained in out/.
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
cd "$ROOT"
mode=${1:---build}
case "$mode" in
    --help) printf 'Usage: ./build.sh [--prepare|--config|--build|--package]\nDefault: build and package. No flashing or GitHub publishing.\n'; exit 0 ;;
    --prepare|--config|--build|--package) ;;
    *) printf 'Unknown option: %s\n' "$mode" >&2; exit 2 ;;
esac
[[ $# -le 1 ]] || exit 2
fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
for tool in git curl python3 tar zstd unzip zip flock sha256sum; do
    command -v "$tool" >/dev/null || fail "Missing tool: $tool"
done
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else "Python 3.12 or newer is required")'
export TZ=UTC
[[ $(uname -m) == x86_64 && $(uname -s) == Linux ]] || fail 'The pinned tools require Linux x86_64.'
source "$ROOT/config/inputs.env"
mkdir -p out .cache/downloads
exec 9>out/build.lock
flock -n 9 || fail 'Another build or packaging operation is running.'
exec > >(tee -a "$ROOT/out/build.log") 2>&1
trap 'printf "ERROR at line %s; see out/build.log\n" "$LINENO" >&2' ERR
WORK="$ROOT/out/bazel-workspace"
DIST="$WORK/out/s5e9945_user/dist"
DOWNLOADS="$ROOT/.cache/downloads"
# Resolve the build inputs. Packaging uses the saved build identity.
# Keep legacy SHA keys and checkout paths compatible with saved metadata and caches.
BAKASU_REPO=https://github.com/Baka-SU/BakaSU.git
if [[ $mode == --package ]]; then
    [[ -f out/build-info.json ]] || fail 'No successful build metadata. Run --build first.'
    RESUKISU_SHA=$(python3 -c 'import json; print(json.load(open("out/build-info.json"))["resukisu_sha"])')
elif [[ -n ${E1S_RESUKISU_SHA:-} ]]; then
    # CI resolves once before deciding whether this exact build already exists.
    [[ ${GITHUB_ACTIONS:-} == true ]] || fail 'Pinned CI input is only supported in GitHub Actions.'
    RESUKISU_SHA=$E1S_RESUKISU_SHA
else
    # Resolve once, even with a cached checkout. Never fall back to stale code.
    upstream=$(git ls-remote "$BAKASU_REPO" HEAD)
    RESUKISU_SHA=${upstream%%$'\t'*}
fi
[[ $RESUKISU_SHA =~ ^[0-9a-f]{40}$ ]] || fail 'Invalid BakaSU commit.'
printf 'BakaSU commit for this build: %s\n' "$RESUKISU_SHA"
BUILD_KEY=$({
    sha256sum build.sh config/inputs.env config/tools.sha256 config/root.config config/anykernel.sh patches/*.patch scripts/*.py .github/workflows/build.yml
    printf '%s\n' "$RESUKISU_SHA"
} | sha256sum | cut -d ' ' -f1)
export ROOT WORK DIST RESUKISU_SHA SUSFS_SHA ANYKERNEL_SHA BUILD_KEY
export BOOT_OS_VERSION BOOT_OS_PATCH_LEVEL BOOT_PARTITION_SIZE
if [[ ${E1S_RESOLVE_ONLY:-0} == 1 ]]; then
    [[ ${GITHUB_ACTIONS:-} == true && $mode == --build ]] || fail 'Resolution mode is reserved for CI builds.'
    python3 -c 'import json, os; print(json.dumps({k.lower(): os.environ[k] for k in ("RESUKISU_SHA", "BUILD_KEY")}))' > out/resolved.json
    exit 0
fi

download() {
    local name=$1 expected=$2
    if [[ ! -f $DOWNLOADS/$name ]]; then
        curl --fail --location --retry 3 --connect-timeout 30 \
            "$DOWNLOAD_BASE/$name" -o "$DOWNLOADS/$name.part"
        printf '%s  %s\n' "$expected" "$DOWNLOADS/$name.part" | sha256sum -c -
        mv "$DOWNLOADS/$name.part" "$DOWNLOADS/$name"
    fi
    printf '%s  %s\n' "$expected" "$DOWNLOADS/$name" | sha256sum -c -
}

checkout() {
    local url=$1 sha=$2 directory=$3
    [[ $sha =~ ^[0-9a-f]{40}$ ]] || fail "Invalid commit: $sha"
    if [[ ! -d $directory ]]; then
        git clone "$url" "$directory"
    fi
    [[ -z $(git -C "$directory" status --porcelain) ]] || fail "Modified checkout: $directory"
    if ! git -C "$directory" cat-file -e "$sha^{commit}" 2>/dev/null; then
        git -C "$directory" fetch --no-tags "$url" "$sha"
    fi
    git -C "$directory" cat-file -e "$sha^{commit}"
    git -C "$directory" -c advice.detachedHead=false checkout --detach "$sha"
    [[ $(git -C "$directory" rev-parse HEAD) == "$sha" ]] || fail "Commit mismatch: $directory"
}

download Magisk-v30.7.apk "$MAGISK_SHA256"
checkout https://github.com/osm0sis/AnyKernel3.git "$ANYKERNEL_SHA" "$ROOT/.cache/anykernel3"

# Prepare the source and run Samsung's build target.
if [[ $mode != --package ]]; then
    download SM-S921B.zip "$SOURCE_SHA256"
    while read -r sha name; do download "$name" "$sha"; done < config/tools.sha256
    checkout "$BAKASU_REPO" "$RESUKISU_SHA" "$ROOT/.cache/resukisu"
    checkout https://gitlab.com/simonpunk/susfs4ksu.git "$SUSFS_SHA" "$ROOT/.cache/susfs"
    if [[ -f $WORK/.prepared && $(cat "$WORK/.prepared") != "$BUILD_KEY" ]]; then
        # Keep the previous build while preparing a clean workspace for new inputs.
        (exec 9>&-; cd "$WORK"; tools/bazel shutdown)
        previous=$(mktemp -d "$ROOT/out/previous-build.XXXXXXXX")
        mv "$WORK" "$previous/workspace"
        if [[ -f out/build-info.json ]]; then cp out/build-info.json "$previous/"; fi
        printf 'Previous build preserved in: %s\n' "$previous"
    fi
    if [[ ! -f $WORK/.prepared ]]; then
        [[ ! -e $WORK ]] || fail 'Incomplete workspace exists. Move out/bazel-workspace aside and rerun.'
        mkdir -p "$WORK"
        python3 "$ROOT/scripts/prepare.py" "$DOWNLOADS/SM-S921B.zip" "$WORK"
        while read -r sha name; do tar --zstd -xf "$DOWNLOADS/$name" -C "$WORK"; done < config/tools.sha256
        git clone --no-hardlinks "$ROOT/.cache/resukisu" "$WORK/kernel/ReSukiSU"
        # Running outside the parent Git repository prevents silently skipped paths.
        # The WLAN patch uses source-relative paths for local Kleaf builds.
        for patch in susfs.patch bazel-local.patch; do
            git -C / apply --check --unsafe-paths --directory="$WORK/kernel" "$ROOT/patches/$patch"
            git -C / apply --unsafe-paths --directory="$WORK/kernel" "$ROOT/patches/$patch"
            git -C / apply --reverse --check --unsafe-paths --directory="$WORK/kernel" "$ROOT/patches/$patch"
        done
        cp "$ROOT/.cache/susfs/kernel_patches/fs/susfs.c" "$WORK/kernel/fs/"
        cp "$ROOT/.cache/susfs/kernel_patches/include/linux/"susfs*.h "$WORK/kernel/include/linux/"
        ln -s ../ReSukiSU/kernel "$WORK/kernel/drivers/kernelsu"
        printf '\nobj-$(CONFIG_KSU) += kernelsu/\n' >> "$WORK/kernel/drivers/Makefile"
        printf '\nsource "drivers/kernelsu/Kconfig"\n' >> "$WORK/kernel/drivers/Kconfig"
        cp config/root.config "$WORK/kernel/arch/arm64/configs/nawaf.config"
        printf '%s\n' "$BUILD_KEY" > "$WORK/.prepared"
    fi
    [[ $(git -C "$WORK/kernel/ReSukiSU" rev-parse HEAD) == "$RESUKISU_SHA" ]] || fail 'Integrated BakaSU commit changed.'
    [[ -z $(git -C "$WORK/kernel/ReSukiSU" status --porcelain) ]] || fail 'Integrated BakaSU source changed.'
    if [[ $mode == --prepare ]]; then
        printf 'Prepared: %s\n' "$WORK"
        exit 0
    fi
    export SOURCE_DATE_EPOCH=$(stat -c %Y "$WORK/kernel/Makefile")
    # The archived kernel must not inherit a parent repository's commit identity.
    export GIT_CEILING_DIRECTORIES="$WORK"
    # This workspace is assembled from verified archives rather than repo sync.
    printf '<manifest><project path="kernel" /></manifest>\n' > "$WORK/source-manifest.xml"
    export KLEAF_REPO_MANIFEST="$WORK/source-manifest.xml"
    target=s5e9945_user_dist
    action=run
    if [[ $mode == --config ]]; then target=s5e9945_user_config; action=build; fi
    export BUILD_STARTED=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    (
        # The persistent Bazel server must not retain the script's build lock.
        exec 9>&-
        cd "$WORK"
        tools/bazel "$action" --nocheck_bzl_visibility --config=stamp --config=local \
            --sandbox_debug --verbose_failures --debug_make_verbosity=I \
            --lto=thin --jobs="${JOBS:-12}" "//projects/s5e9945:$target"
    )
    [[ $mode != --config ]] || exit 0
    [[ $(git -C "$WORK/kernel/ReSukiSU" rev-parse HEAD) == "$RESUKISU_SHA" ]] || fail 'BakaSU changed during build.'
    python3 "$ROOT/scripts/verify_kernel.py"
fi

# Package the verified Image in all three formats.
stage=$(mktemp -d "$ROOT/out/package.XXXXXXXX")
export STAGE="$stage"
# Only this run's temporary packaging directory is removed. Backups live separately.
trap 'rm -rf -- "$stage"' EXIT
git -C "$ROOT/.cache/anykernel3" archive "$ANYKERNEL_SHA" META-INF tools/ak3-core.sh LICENSE | tar -x -C "$stage"
for binary in busybox magiskboot magiskpolicy; do
    unzip -p "$DOWNLOADS/Magisk-v30.7.apk" "lib/arm64-v8a/lib$binary.so" > "$stage/tools/$binary"
    chmod 755 "$stage/tools/$binary"
done
cp config/anykernel.sh "$stage/anykernel.sh"
chmod 755 "$stage/anykernel.sh"
python3 "$ROOT/scripts/package.py"

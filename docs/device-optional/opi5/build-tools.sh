#!/bin/sh
# Build the native tools on the board (native aarch64 build; no cross-compiling needed).
#
#   sh build-tools.sh [--repo DIR] [--out DIR] [--no-python] [--dry-run]
#
# Produces, under --out (default <repo>/build/opi5):
#   axis_memlab_virtual_camera   the virtual CCTV pipeline (probe + ledger + sampler + new hook)
#   axis_memlab_sampler_demo     known allocation sites, for checking symbolization
# and installs the host CLI into <repo>/.venv unless --no-python. The binaries are built with
# symbols and frame pointers and a build-id, and are NOT stripped: keep them; the host needs the
# very same files to resolve addresses (docs/12-allocation-sampling.md).
# Not run on real hardware by its author: use --dry-run to see the commands first.
set -eu

REPO=""
OUT=""
PYTHON=1
DRY_RUN=0

while [ $# -gt 0 ]; do
  case "$1" in
    --repo) REPO="${2:?--repo needs a directory}"; shift 2 ;;
    --out) OUT="${2:?--out needs a directory}"; shift 2 ;;
    --no-python) PYTHON=0; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

if [ -z "$REPO" ]; then
  REPO="$(cd "$(dirname "$0")/../../../.." && pwd)"
fi
[ -f "$REPO/CMakeLists.txt" ] || { echo "not the repository root: $REPO" >&2; exit 2; }
OUT="${OUT:-$REPO/build/opi5}"

run() {
  if [ "$DRY_RUN" -eq 1 ]; then printf 'would run: %s\n' "$*"; else printf '+ %s\n' "$*"; "$@"; fi
}

if [ "$DRY_RUN" -eq 0 ]; then
  for tool in cmake c++; do
    command -v "$tool" >/dev/null 2>&1 || { echo "missing: $tool (run provision-host.sh first)" >&2; exit 1; }
  done
fi

# RelWithDebInfo: optimized like a real build, with -g. The linker flag guarantees a build-id.
run cmake -S "$REPO" -B "$OUT" \
  -DCMAKE_BUILD_TYPE=RelWithDebInfo \
  -DAXMEM_LEDGER=ON -DAXMEM_SAMPLER=ON \
  -DCMAKE_EXE_LINKER_FLAGS=-Wl,--build-id
run cmake --build "$OUT" --parallel "$(nproc 2>/dev/null || echo 2)" \
  --target axis_memlab_virtual_camera axis_memlab_sampler_demo
run ctest --test-dir "$OUT" --output-on-failure -R "virtual_camera_smoke|test_new_hook|test_sampler"

if [ "$PYTHON" -eq 1 ]; then
  run python3 -m venv "$REPO/.venv"
  run "$REPO/.venv/bin/python" -m pip install --upgrade pip
  run "$REPO/.venv/bin/python" -m pip install -e "$REPO"
  run "$REPO/.venv/bin/axis-memlab" --version
fi

echo ""
echo "built: $OUT/native/axis_memlab_virtual_camera"
echo "check the build-id (needed for symbolization): readelf -n $OUT/native/axis_memlab_virtual_camera | grep -A1 'Build ID'"

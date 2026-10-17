#!/bin/sh
# Tier 1: run the virtual camera as the lab user under a hard memory limit (systemd + cgroup v2).
#
#   sudo sh run-virtual-camera.sh [--user axmem-lab] [--memory 512M] [--cpus 2] [--name NAME] \
#        [--binary PATH] [--outdir DIR] -- <virtual camera options>
#   sudo sh run-virtual-camera.sh --dry-run -- --defect release_miss --seconds 600
#
# The process runs as the unprivileged lab user, so an SSH session of that user can read its
# /proc entries exactly as the collector will on a camera. The limit is applied to the unit's
# cgroup (MemoryMax, no swap), so a runaway pipeline is killed by the kernel instead of taking the
# board down; `memory.events` in the unit's cgroup records the OOM kill.
#
# Fidelity note: /proc/meminfo inside Tier 1 still shows the WHOLE BOARD's memory, not the limit.
# For camera-like system-wide numbers use Tier 2 (the VM). Not run on hardware by its author.
set -eu

USER_NAME="axmem-lab"
MEMORY="512M"
CPUS=""
NAME="axmem-virtual-camera"
BINARY=""
OUTDIR=""
DRY_RUN=0

while [ $# -gt 0 ]; do
  case "$1" in
    --user) USER_NAME="${2:?}"; shift 2 ;;
    --memory) MEMORY="${2:?}"; shift 2 ;;
    --cpus) CPUS="${2:?}"; shift 2 ;;
    --name) NAME="${2:?}"; shift 2 ;;
    --binary) BINARY="${2:?}"; shift 2 ;;
    --outdir) OUTDIR="${2:?}"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    --) shift; break ;;
    *) echo "unknown option: $1 (put camera options after --)" >&2; exit 2 ;;
  esac
done

case "$MEMORY" in
  *[!0-9KMGkmg]*|"") echo "--memory must look like 512M or 1G" >&2; exit 2 ;;
esac
case "$NAME" in
  *[!A-Za-z0-9_.-]*|"") echo "--name may contain letters, digits, . _ -" >&2; exit 2 ;;
esac
[ "$USER_NAME" != "root" ] || { echo "refusing to run the camera as root" >&2; exit 2; }

REPO="$(cd "$(dirname "$0")/../../../.." && pwd)"
BINARY="${BINARY:-$REPO/build/opi5/native/axis_memlab_virtual_camera}"
OUTDIR="${OUTDIR:-/home/$USER_NAME/runs/$(date +%Y%m%d-%H%M%S)}"

if [ "$DRY_RUN" -eq 0 ]; then
  [ "$(id -u)" -eq 0 ] || { echo "run with sudo (or --dry-run)" >&2; exit 2; }
  [ -x "$BINARY" ] || { echo "binary not found: $BINARY (run build-tools.sh)" >&2; exit 1; }
  grep -qw memory /sys/fs/cgroup/cgroup.controllers 2>/dev/null || {
    echo "cgroup v2 with the memory controller is required (see the README)" >&2; exit 1; }
  id "$USER_NAME" >/dev/null 2>&1 || { echo "no such user: $USER_NAME (run provision-host.sh)" >&2; exit 1; }
fi

PROPS="-p MemoryMax=$MEMORY -p MemorySwapMax=0 -p TasksMax=64 -p NoNewPrivileges=yes"
PROPS="$PROPS -p ProtectSystem=strict -p ReadWritePaths=$OUTDIR"
[ -z "$CPUS" ] || PROPS="$PROPS -p CPUQuota=$((CPUS * 100))%"

# Probe and sampler outputs go to the output directory unless the caller chose their own.
EXTRA="--probe-out $OUTDIR/probe.jsonl --sampler-out $OUTDIR/allocs.jsonl"
for arg in "$@"; do
  case "$arg" in --probe-out|--sampler-out) EXTRA="" ;; esac
done

if [ "$DRY_RUN" -eq 1 ]; then
  echo "would run: install -d -m 755 -o $USER_NAME -g $USER_NAME $OUTDIR"
  echo "would run: systemd-run --unit=$NAME --uid=$USER_NAME --collect $PROPS $BINARY $EXTRA $*"
  exit 0
fi

install -d -m 755 -o "$USER_NAME" -g "$USER_NAME" "$OUTDIR"
# shellcheck disable=SC2086
systemd-run --unit="$NAME" --uid="$USER_NAME" --collect $PROPS "$BINARY" $EXTRA "$@"

echo ""
echo "unit:      $NAME   (limit $MEMORY, no swap)"
echo "outputs:   $OUTDIR"
echo "watch:     sudo systemctl status $NAME"
echo "stop:      sudo systemctl stop $NAME"
echo "OOM check: cat /sys/fs/cgroup/system.slice/$NAME.service/memory.events"
echo "collect from your workstation (as the lab user):"
echo "  axis-memlab discover --ssh $USER_NAME@<board> --app axis_memlab_vir"

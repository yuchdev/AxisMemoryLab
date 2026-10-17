#!/bin/sh
# Tier 2: start the virtual camera VM with camera-like RAM and a loopback-only SSH port.
#
#   sh run-vm.sh [--dir ~/axmem-vm] [--ram 512M] [--cpus 2] [--port 2222] [--background]
#   sh run-vm.sh --stop [--dir ~/axmem-vm]
#   sh run-vm.sh --dry-run                          # print the QEMU command only
#
# The guest has its own kernel, so its /proc/meminfo, PSI, and cgroups describe a small machine
# like a camera does, which is what Tier 2 is for. SSH is forwarded to 127.0.0.1 on the board only;
# reach it from a workstation through the board (ProxyJump, see the README). Uses KVM when
# /dev/kvm is usable, otherwise software emulation (TCG), which is several times slower and changes
# timing but not memory behaviour. Not run on real hardware by its author.
set -eu

DIR="$HOME/axmem-vm"
RAM="512M"
CPUS="2"
PORT="2222"
BACKGROUND=0
STOP=0
DRY_RUN=0

while [ $# -gt 0 ]; do
  case "$1" in
    --dir) DIR="${2:?}"; shift 2 ;;
    --ram) RAM="${2:?}"; shift 2 ;;
    --cpus) CPUS="${2:?}"; shift 2 ;;
    --port) PORT="${2:?}"; shift 2 ;;
    --background) BACKGROUND=1; shift ;;
    --stop) STOP=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

case "$RAM" in *[!0-9GMgm]*|"") echo "--ram must look like 512M" >&2; exit 2 ;; esac
case "$CPUS$PORT" in *[!0-9]*|"") echo "--cpus and --port must be numbers" >&2; exit 2 ;; esac
[ "$PORT" -ge 1024 ] && [ "$PORT" -le 65535 ] || { echo "--port must be 1024-65535" >&2; exit 2; }

if [ "$STOP" -eq 1 ]; then
  if [ -f "$DIR/qemu.pid" ]; then
    kill "$(cat "$DIR/qemu.pid")" && rm -f "$DIR/qemu.pid" && echo "VM stopped"
  else
    echo "no $DIR/qemu.pid: nothing to stop" >&2
  fi
  exit 0
fi

FIRMWARE="/usr/share/qemu-efi-aarch64/QEMU_EFI.fd"
if [ -r /dev/kvm ] && [ -w /dev/kvm ]; then
  ACCEL="-machine virt,gic-version=host,accel=kvm -cpu host"
  ACCEL_NOTE="KVM"
else
  ACCEL="-machine virt,gic-version=3,accel=tcg -cpu max"
  ACCEL_NOTE="software emulation (TCG): /dev/kvm is not usable; expect it to be slow"
fi

CMD="qemu-system-aarch64 $ACCEL -m $RAM -smp $CPUS -bios $FIRMWARE"
CMD="$CMD -drive if=virtio,format=qcow2,file=$DIR/disk.qcow2"
CMD="$CMD -drive if=virtio,format=raw,readonly=on,file=$DIR/seed.img"
CMD="$CMD -netdev user,id=net0,hostfwd=tcp:127.0.0.1:$PORT-:22 -device virtio-net-pci,netdev=net0"
CMD="$CMD -device virtio-rng-pci -display none"
if [ "$BACKGROUND" -eq 1 ]; then
  CMD="$CMD -daemonize -pidfile $DIR/qemu.pid -serial file:$DIR/console.log"
else
  CMD="$CMD -nographic"
fi

echo "accelerator: $ACCEL_NOTE"
if [ "$DRY_RUN" -eq 1 ]; then
  echo "would run: $CMD"
  exit 0
fi

command -v qemu-system-aarch64 >/dev/null 2>&1 || { echo "missing qemu-system-aarch64 (provision-host.sh --with-vm)" >&2; exit 1; }
[ -r "$FIRMWARE" ] || { echo "missing UEFI firmware $FIRMWARE (package qemu-efi-aarch64)" >&2; exit 1; }
[ -f "$DIR/disk.qcow2" ] && [ -f "$DIR/seed.img" ] || { echo "run make-image.sh first" >&2; exit 1; }
[ ! -f "$DIR/qemu.pid" ] || { echo "a VM may already be running ($DIR/qemu.pid)" >&2; exit 1; }

# shellcheck disable=SC2086
exec $CMD

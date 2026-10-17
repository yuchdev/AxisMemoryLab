#!/bin/sh
# Prepare an Orange Pi 5 (aarch64 Debian/Ubuntu-family image) as a host for the virtual CCTV board.
#
#   sudo sh provision-host.sh --pubkey /path/to/axmem_ed25519.pub [--user axmem-lab] [--with-vm]
#   sh provision-host.sh --dry-run --skip-arch-check --pubkey KEY.pub     # print the plan only
#
# What it does (and nothing else):
#   1. installs build tools and the OpenSSH server (and QEMU tools with --with-vm) with apt;
#   2. creates ONE unprivileged lab user with a locked password and your public key;
#   3. restricts that user's SSH sessions (keys only, no forwarding) with a Match block, leaving
#      every other account's SSH settings alone;
#   4. enables systemd "linger" for the user so its services survive logout.
# It never touches the root account, never opens a firewall port, never enables password login,
# and never edits /etc/ssh/sshd_config itself (only a drop-in file, after `sshd -t` passes).
# This script has NOT been run on real hardware by its author: read the plan with --dry-run first.
set -eu

USER_NAME="axmem-lab"
PUBKEY=""
WITH_VM=0
DRY_RUN=0
SKIP_ARCH=0

usage() {
  sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-2}"
}

while [ $# -gt 0 ]; do
  case "$1" in
    --user) USER_NAME="${2:?--user needs a name}"; shift 2 ;;
    --pubkey) PUBKEY="${2:?--pubkey needs a file}"; shift 2 ;;
    --with-vm) WITH_VM=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    --skip-arch-check) SKIP_ARCH=1; shift ;;
    -h|--help) usage 0 ;;
    *) echo "unknown option: $1" >&2; usage 2 ;;
  esac
done

say() { printf '%s\n' "$*"; }
run() {
  if [ "$DRY_RUN" -eq 1 ]; then
    printf 'would run: %s\n' "$*"
  else
    printf '+ %s\n' "$*"
    "$@"
  fi
}

# ---- checks ------------------------------------------------------------------------------------
case "$USER_NAME" in
  *[!a-z0-9_-]*|"") echo "user name must be lower-case letters, digits, - or _" >&2; exit 2 ;;
esac
[ "$USER_NAME" != "root" ] || { echo "refusing to use root as the lab user" >&2; exit 2; }
[ -n "$PUBKEY" ] || { echo "--pubkey is required (a PUBLIC key file)" >&2; exit 2; }
[ -f "$PUBKEY" ] || { echo "no such file: $PUBKEY" >&2; exit 2; }
if grep -q 'PRIVATE KEY' "$PUBKEY"; then
  echo "that file contains a PRIVATE key; pass the .pub file and keep the private key off the board" >&2
  exit 2
fi
ssh-keygen -l -f "$PUBKEY" >/dev/null 2>&1 || { echo "not a valid OpenSSH public key: $PUBKEY" >&2; exit 2; }

if [ "$SKIP_ARCH" -eq 0 ]; then
  [ "$(uname -m)" = "aarch64" ] || { echo "expected aarch64 (Orange Pi 5); use --skip-arch-check to override" >&2; exit 2; }
fi
if [ "$DRY_RUN" -eq 0 ] && [ "$(id -u)" -ne 0 ]; then
  echo "run with sudo (or use --dry-run to only print the plan)" >&2
  exit 2
fi
if [ -r /etc/os-release ]; then
  # shellcheck disable=SC1091
  . /etc/os-release
  say "host OS: ${PRETTY_NAME:-unknown}"
fi

# ---- 1. packages ---------------------------------------------------------------------------------
PACKAGES="build-essential cmake git python3 python3-venv python3-pip openssh-server openssh-client"
if [ "$WITH_VM" -eq 1 ]; then
  PACKAGES="$PACKAGES qemu-system-arm qemu-utils qemu-efi-aarch64 cloud-image-utils curl"
fi
run apt-get update
run apt-get install -y --no-install-recommends $PACKAGES

# ---- 2. the lab user -------------------------------------------------------------------------------
if [ "$DRY_RUN" -eq 0 ] && id "$USER_NAME" >/dev/null 2>&1; then
  say "user $USER_NAME already exists; leaving it as is"
else
  run useradd --create-home --shell /bin/bash --user-group "$USER_NAME"
  run passwd --lock "$USER_NAME"
fi
HOME_DIR="/home/$USER_NAME"
run install -d -m 700 -o "$USER_NAME" -g "$USER_NAME" "$HOME_DIR/.ssh"
run install -m 600 -o "$USER_NAME" -g "$USER_NAME" "$PUBKEY" "$HOME_DIR/.ssh/authorized_keys"
run install -d -m 755 -o "$USER_NAME" -g "$USER_NAME" "$HOME_DIR/runs"

# ---- 3. SSH restrictions for this user only --------------------------------------------------------
DROPIN="/etc/ssh/sshd_config.d/90-axmem-$USER_NAME.conf"
DROPIN_BODY="# Managed by axis-memory-lab provision-host.sh. Applies to the lab user only.
Match User $USER_NAME
    PasswordAuthentication no
    KbdInteractiveAuthentication no
    PubkeyAuthentication yes
    AllowTcpForwarding no
    AllowAgentForwarding no
    X11Forwarding no
    PermitTunnel no"
if [ "$DRY_RUN" -eq 1 ]; then
  say "would write $DROPIN:"
  printf '%s\n' "$DROPIN_BODY" | sed 's/^/    | /'
elif grep -Rqs '^[[:space:]]*Include[[:space:]]\+/etc/ssh/sshd_config.d' /etc/ssh/sshd_config; then
  printf '%s\n' "$DROPIN_BODY" > "$DROPIN.new"
  mv "$DROPIN.new" "$DROPIN"
  chmod 644 "$DROPIN"
  if sshd -t; then
    if systemctl is-active --quiet ssh 2>/dev/null; then systemctl reload ssh
    else systemctl reload sshd; fi
  else
    rm -f "$DROPIN"
    echo "sshd rejected the configuration; the drop-in was removed" >&2
    exit 1
  fi
else
  echo "NOTE: /etc/ssh/sshd_config has no 'Include /etc/ssh/sshd_config.d'; not editing it." >&2
  echo "Add this block yourself at the END of sshd_config, then run 'sshd -t' and reload sshd:" >&2
  printf '%s\n' "$DROPIN_BODY" >&2
fi

# ---- 4. linger -----------------------------------------------------------------------------------------
run loginctl enable-linger "$USER_NAME"

# ---- report ----------------------------------------------------------------------------------------------
say ""
say "Next steps (see docs/device-optional/README.md):"
say "  - note the host key fingerprint to verify from your workstation:"
say "      ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub"
say "  - cgroup v2 with the memory controller is needed for the memory-limited run:"
say "      cat /sys/fs/cgroup/cgroup.controllers   (expect 'memory' in the list)"
say "  - build the tools: sh docs/device-optional/opi5/build-tools.sh"

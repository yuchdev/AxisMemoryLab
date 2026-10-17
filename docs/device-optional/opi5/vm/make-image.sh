#!/bin/sh
# Tier 2: prepare the virtual camera VM disk (a copy-on-write overlay of a Debian cloud image).
#
#   sh make-image.sh --pubkey KEY.pub [--dir ~/axmem-vm] [--disk 4G] [--image-url URL]
#   sh make-image.sh --dry-run --pubkey KEY.pub          # print the plan and the rendered user-data
#
# 1. downloads the base image over HTTPS and VERIFIES it against the SHA512SUMS published next to
#    it (the sums come from the same server, so this detects corruption, not a malicious server;
#    compare against a source you trust if that matters to you);
# 2. creates an overlay disk, so the base image is never modified and a reset is `rm disk.qcow2`;
# 3. builds a cloud-init seed with ONE user (`camera`), key-only SSH, no password, no root login.
# Not run on real hardware by its author. The default URL is the Debian 12 generic cloud image
# for arm64; check it is still current before relying on it.
set -eu

DIR="$HOME/axmem-vm"
PUBKEY=""
DISK="4G"
IMAGE_URL="https://cloud.debian.org/images/cloud/bookworm/latest/debian-12-genericcloud-arm64.qcow2"
DRY_RUN=0
HERE="$(cd "$(dirname "$0")" && pwd)"

while [ $# -gt 0 ]; do
  case "$1" in
    --dir) DIR="${2:?}"; shift 2 ;;
    --pubkey) PUBKEY="${2:?}"; shift 2 ;;
    --disk) DISK="${2:?}"; shift 2 ;;
    --image-url) IMAGE_URL="${2:?}"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

[ -n "$PUBKEY" ] && [ -f "$PUBKEY" ] || { echo "--pubkey must name a public key file" >&2; exit 2; }
if grep -q 'PRIVATE KEY' "$PUBKEY"; then echo "that is a PRIVATE key; pass the .pub file" >&2; exit 2; fi
ssh-keygen -l -f "$PUBKEY" >/dev/null 2>&1 || { echo "not a valid OpenSSH public key" >&2; exit 2; }
case "$IMAGE_URL" in https://*) ;; *) echo "the image URL must be https://" >&2; exit 2 ;; esac
case "$DISK" in *[!0-9GMgm]*|"") echo "--disk must look like 4G" >&2; exit 2 ;; esac

# Only the key type and material go into the VM; the comment field (often an e-mail) does not.
KEYLINE="$(awk 'NR==1 {print $1 " " $2}' "$PUBKEY")"
[ "${#KEYLINE}" -gt 20 ] || { echo "could not read the key" >&2; exit 2; }
RENDERED="$(sed "s|@@PUBKEY@@|$KEYLINE|" "$HERE/user-data.template")"
BASE_NAME="$(basename "$IMAGE_URL")"
SUMS_URL="$(dirname "$IMAGE_URL")/SHA512SUMS"

if [ "$DRY_RUN" -eq 1 ]; then
  echo "would create directory: $DIR"
  echo "would download:         $IMAGE_URL"
  echo "would download:         $SUMS_URL   and verify $BASE_NAME against it"
  echo "would run: qemu-img create -f qcow2 -F qcow2 -b $BASE_NAME disk.qcow2 $DISK"
  echo "would run: cloud-localds seed.img user-data meta-data"
  echo "user-data that would be used:"
  printf '%s\n' "$RENDERED" | sed 's/^/    | /'
  exit 0
fi

for tool in curl qemu-img cloud-localds sha512sum; do
  command -v "$tool" >/dev/null 2>&1 || { echo "missing: $tool (provision-host.sh --with-vm)" >&2; exit 1; }
done

mkdir -p "$DIR"
cd "$DIR"
if [ ! -f "$BASE_NAME" ]; then
  curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 -o "$BASE_NAME.part" "$IMAGE_URL"
  curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 -o SHA512SUMS "$SUMS_URL"
  grep " $BASE_NAME\$" SHA512SUMS > "$BASE_NAME.sum" || { echo "no checksum for $BASE_NAME in SHA512SUMS" >&2; rm -f "$BASE_NAME.part"; exit 1; }
  # The sums file names the final file name, so verify under that name.
  mv "$BASE_NAME.part" "$BASE_NAME"
  if ! sha512sum -c "$BASE_NAME.sum"; then
    rm -f "$BASE_NAME"
    echo "checksum mismatch; the download was deleted" >&2
    exit 1
  fi
fi

if [ -f disk.qcow2 ]; then
  echo "disk.qcow2 already exists; remove it to reset the VM" >&2
else
  qemu-img create -f qcow2 -F qcow2 -b "$BASE_NAME" disk.qcow2 "$DISK"
fi

printf '%s\n' "$RENDERED" > user-data
printf 'instance-id: virtual-camera-%s\nlocal-hostname: virtual-camera\n' "$(date +%Y%m%d)" > meta-data
rm -f seed.img
cloud-localds seed.img user-data meta-data
echo "ready in $DIR: disk.qcow2 (overlay), seed.img (cloud-init). Start it with run-vm.sh."

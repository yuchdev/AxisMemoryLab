# Virtual CCTV board on an Orange Pi 5

**Status:** a procedure and a set of scripts, **not yet run on real hardware by their author**.
Every script has a `--dry-run` that prints what it would do, and the checks in section 8 tell you
whether your board behaves as the guide assumes. Where something needs a camera attached to the
board or a real AXIS camera, it is listed in section 11 as **Optional** or **TODO** and is not
implemented.

## 1. What this is, and what it is not

An Orange Pi 5 (Rockchip RK3588S, aarch64, 4-32 GB RAM) is used as a stand-in for a camera's
compute board so that the whole toolset can be exercised on real Linux hardware without an AXIS
camera: SSH collection of `/proc`, the in-app probe and ledger, the allocation sampler and
symbolizer, analysis, advanced-diagnostics gating, and evidence bundles.

* The "camera application" is `axis_memlab_virtual_camera`, a synthetic pipeline (capture,
  conversion, inference stub, result queue, publisher) with injectable defects. It uses no AXIS
  SDK, VDO, or Larod, and no real video.
* It does **not** reproduce AXIS OS, its kernel, its C library, its permission model, ARTPEC
  hardware, video or DMA-buffer drivers, or camera timing. Findings about AXIS-specific
  behaviour (which `/proc` files a restricted account can read, whether `perf` works, DDH
  payloads, VDO/Larod buffer semantics) **cannot** come from this board.
* Use it to prove that the tools work end to end, to rehearse the investigation workflow
  (`docs/11-investigation-workflow.md`), and to produce reproducible demonstrations.

## 2. Two tiers

```text
 Workstation                       Orange Pi 5 (aarch64 Linux)
 ───────────                       ──────────────────────────────────────────────────────────
 axis-memlab ──── SSH (keys) ────► Tier 1: lab user `axmem-lab`
  discover / collect / snapshot      └─ systemd unit: virtual camera, MemoryMax=512M, no swap
  analyze / compare / report
  symbolize  (host only)           Tier 2: QEMU VM `virtual-camera` (own kernel, 512M RAM)
  advanced / bundle                  └─ user `camera`: virtual camera; SSH on 127.0.0.1:2222
                                       reached through the board with ProxyJump
```

| | Tier 1: confined process | Tier 2: virtual machine |
| --- | --- | --- |
| Effort | Low | Higher (image, cloud-init, QEMU) |
| Process `/proc/PID/*`, smaps_rollup, fd, cgroup | Real, readable by a non-root SSH user | Real, inside the guest |
| `/proc/meminfo`, PSI, `vmstat` | Describe the **whole board** (not the limit) | Describe a **small machine** like a camera |
| Memory limit | Per-unit cgroup (`MemoryMax`), OOM kill of the unit | Guest RAM; guest OOM behaviour |
| Collector abort thresholds (`MemAvailable`) | Not exercised (board has GBs free) | Exercised with 256-512 MB guests |
| Needs | systemd, cgroup v2 with the memory controller | `qemu-system-aarch64`, UEFI firmware, ideally KVM |

Start with Tier 1. Use Tier 2 when you need camera-like system-wide numbers.

## 3. Requirements (outside this repository)

| Requirement | Detail |
| --- | --- |
| Board | Orange Pi 5 (any RAM size; 8 GB or more is comfortable for Tier 2), power supply, cooling, microSD or NVMe storage |
| OS | A Debian/Ubuntu-family aarch64 image: Orange Pi's own, Armbian, or Ubuntu for Rockchip. `systemd`, `apt`, and cgroup v2 with the `memory` controller are assumed (check in section 8) |
| Network | The board reachable from your workstation over SSH. Keep it on a trusted lab network; nothing here opens another port |
| Workstation | `axis-memlab` installed (README), an OpenSSH client, and a dedicated SSH key for this lab |
| Toolchain on the board | Installed by `provision-host.sh`: `build-essential`, `cmake` 3.20 or newer, `git`, Python 3.11 or newer. **Check the versions**: some board images ship older CMake or Python, in which case install newer ones yourself |
| Tier 2 only | `qemu-system-arm` (provides `qemu-system-aarch64`), `qemu-utils`, `qemu-efi-aarch64`, `cloud-image-utils`, `curl`; `/dev/kvm` usable by your account for acceleration (see below) |

**KVM is not guaranteed.** Whether `/dev/kvm` exists depends on the board's kernel. Vendor kernels
for RK3588 boards often lack it; newer mainline-based kernels may have it. Check
`ls -l /dev/kvm` and `dmesg | grep -i kvm`. Without it, Tier 2 still works under software
emulation but several times slower, which changes timing, not memory behaviour.

## 4. One-time setup

On your **workstation**, create a key used only for this lab:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/axmem_ed25519 -C "axmem-lab"      # set a passphrase if you can
```

Copy the **public** key (`axmem_ed25519.pub`) to the board; never the private one.

On the **board**, get the repository (clone or copy it), then:

```bash
# Read the plan first, then run it:
sh docs/device-optional/opi5/provision-host.sh --dry-run --pubkey ~/axmem_ed25519.pub
sudo sh docs/device-optional/opi5/provision-host.sh --pubkey ~/axmem_ed25519.pub [--with-vm]
```

This installs packages, creates the unprivileged user `axmem-lab` (password locked, your key
only), restricts **that user's** SSH sessions (no password login, no forwarding) through a
drop-in file after `sshd -t` passes, and enables systemd "linger" for the user. It does not touch
root, other users, the firewall, or `sshd_config` itself.

Still on the board, build the tools natively (about 10-20 minutes on first build):

```bash
sh docs/device-optional/opi5/build-tools.sh
```

The binaries keep their symbols, frame pointers, and a build-id, and must **not** be stripped:
the host resolves allocation addresses against these very files (`docs/12-allocation-sampling.md`).

### Trust the board's host key (workstation)

The collector refuses unknown or changed host keys. Verify the fingerprint on the board's console
and compare it before trusting the key:

```bash
# on the board:
ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
# on the workstation:
ssh-keyscan -t ed25519 <board> > ~/.ssh/known_hosts_axmem
ssh-keygen -lf ~/.ssh/known_hosts_axmem        # must show the same fingerprint
```

## 5. Tier 1: a confined virtual camera

On the board:

```bash
sudo sh docs/device-optional/opi5/run-virtual-camera.sh --memory 512M --cpus 2 -- \
     --seconds 900 --defect release_miss --defect-every 40 --reconnect-seconds 60
```

The unit runs as `axmem-lab` under `MemoryMax=512M` with swap disabled, writes
`probe.jsonl` (record-v1) and `allocs.jsonl` (allocation samples) to `~axmem-lab/runs/<time>/`, and
prints how to watch, stop, and check for an OOM kill. Add `--dry-run` to see the exact
`systemd-run` command.

From the **workstation**. Pick one run id and one device pseudonym and give them to both the
camera (on the board) and the collector, so the application's own records can be imported into the
collected run. The process command name is truncated by Linux to 15 characters, hence
`axis_memlab_vir`:

```bash
RUN=$(python3 -c "import uuid; print(uuid.uuid4())")      # or uuidgen
# On the board, start the camera with:  -- --run-id $RUN --device-id opi5-vcam-1 ...

KEY=~/.ssh/axmem_ed25519; KH=~/.ssh/known_hosts_axmem
axis-memlab discover --ssh axmem-lab@<board> --ssh-identity $KEY --ssh-known-hosts $KH \
    --app axis_memlab_vir

axis-memlab collect --ssh axmem-lab@<board> --ssh-identity $KEY --ssh-known-hosts $KH \
    --app axis_memlab_vir --config configs/default.toml --out runs/ --run-id $RUN \
    --device-id opi5-vcam-1 --scenario T2-release-miss --test-case-id T2 \
    --camera-model "virtual camera (Orange Pi 5, Tier 1)" --soc RK3588S \
    --firmware-version "<board OS and kernel>" --sdk-generation none --libc glibc \
    --privacy-classification synthetic --duration-seconds 600
```

Then bring in the application's own records and analyse the combined run:

```bash
scp -i $KEY axmem-lab@<board>:runs/<time>/probe.jsonl .
axis-memlab import --input probe.jsonl --run runs/$RUN       # same run id and device id
axis-memlab analyze --run runs/$RUN --config configs/default.toml --out report.json
axis-memlab report --input report.json --format markdown
```

`import` accepts only records whose `run_id` and `device_id` equal the run's; anything else is
rejected line by line and reported. (Without a shared id you can import into a separate run:
`axis-memlab import --input probe.jsonl --run runs/probe-run --device-id opi5-vcam-1 --scenario T2`.)

Resolve allocation sites (the board built the binary; keep a copy off the board):

```bash
mkdir -p symbols && scp -i $KEY axmem-lab@<board>:<repo>/build/opi5/native/axis_memlab_virtual_camera symbols/
scp -i $KEY axmem-lab@<board>:runs/<time>/allocs.jsonl .
axis-memlab symbolize --samples allocs.jsonl --symbols symbols/ --top 10
```

The workstation can be x86: the ELF reader handles aarch64 binaries, so this is a genuine
cross-architecture check of build-id matching and resolution.

## 6. Tier 2: a virtual machine with camera-like RAM

On the board (needs `--with-vm` in the provisioning step):

```bash
sh docs/device-optional/opi5/vm/make-image.sh --dry-run --pubkey ~/axmem_ed25519.pub   # read it
sh docs/device-optional/opi5/vm/make-image.sh --pubkey ~/axmem_ed25519.pub --disk 4G
sh docs/device-optional/opi5/vm/run-vm.sh --ram 512M --cpus 2 --port 2222 --background
```

`make-image.sh` downloads a Debian cloud image over HTTPS, verifies it against the `SHA512SUMS`
published beside it, and builds an overlay disk plus a cloud-init seed with one user (`camera`),
key-only SSH, no password, no root login. Resetting the VM is `rm disk.qcow2` and running the
script again. `run-vm.sh` forwards the guest's SSH to **127.0.0.1 on the board only** and tells
you whether it found KVM or fell back to software emulation. Stop it with `run-vm.sh --stop`.
The first boot takes a minute or more (several minutes under emulation); watch
`~/axmem-vm/console.log`.

From the workstation, reach the guest **through the board** with an SSH alias (the collector
passes the alias to `ssh`, so `~/.ssh/config` applies):

```text
Host opi5-vcam
    HostName 127.0.0.1
    Port 2222
    User camera
    ProxyJump axmem-lab@<board>
    IdentityFile ~/.ssh/axmem_ed25519
    IdentitiesOnly yes
    UserKnownHostsFile ~/.ssh/known_hosts_axmem
    StrictHostKeyChecking yes
```

Add the guest's host key to `known_hosts_axmem` only after checking its fingerprint on the guest
console (`~/axmem-vm/console.log` or an interactive run without `--background`). Then copy the
binary in, start it as `camera`, and collect exactly as in Tier 1:

```bash
scp symbols/axis_memlab_virtual_camera opi5-vcam:
RUN=$(python3 -c "import uuid; print(uuid.uuid4())")
ssh opi5-vcam "nohup ./axis_memlab_virtual_camera --seconds 900 --defect queue_growth \
    --run-id $RUN --device-id opi5-vcam-2 --publisher-hz 5 \
    --probe-out probe.jsonl --sampler-out allocs.jsonl > summary.json 2>&1 &"
axis-memlab collect --ssh opi5-vcam --app axis_memlab_vir --config configs/default.toml \
    --out runs/ --run-id $RUN --device-id opi5-vcam-2 --scenario T2-queue \
    --privacy-classification synthetic \
    --camera-model "virtual camera (Orange Pi 5, Tier 2 VM)" --soc RK3588S \
    --firmware-version "<guest OS and kernel>" --duration-seconds 600
```

Inside the guest, `/proc/meminfo` and PSI describe a 512 MB machine. To see the collector's
memory-pressure behaviour, start a guest with `--ram 256M` and a `queue_growth` run with
`--publisher-hz 1`: when `MemAvailable` falls below the configured thresholds the run records
`sparse_skipped` and then `abort_memory_pressure` (`docs/05-collecting-on-axis.md`).

## 7. Experiments

All use the virtual camera's options. "Expected" is what the tools should show; if they do not,
that is a finding about the tools or the setup.

| Experiment | Virtual camera options | Expected |
| --- | --- | --- |
| Healthy baseline (T2) | defaults, `--seconds 900` | In-flight counts, queue depth: flat. Plateau after warm-up |
| Missed release | `--defect release_miss --defect-every 40` | `app.resource.frame.in_flight_count` and `_bytes` rising; sampler: live bytes at the frame allocation site |
| Undrained queue | `--defect queue_growth --publisher-hz 5` | `app.queue.results_depth_count` rising; frame in-flight flat; `H-RETENTION` if process memory also rises |
| Bounded queue | `--queue-max 8 --publisher-hz 5` | depth flat, `app.queue.results_dropped_count` rising |
| Reconnect leak (T4) | `--defect reconnect_leak --reconnect-seconds 30` | `app.resource.session.in_flight_count` rising by one per reconnect |
| Cache growth | `--defect cache_growth` | `app.cache.entries_count` rising |
| Higher load (T3) | `--fps 30` vs `--fps 15` | Compare slopes with `axis-memlab compare` |
| Memory limit (Tier 1) | `run-virtual-camera.sh --memory 96M` with `queue_growth` | The unit is OOM-killed; `memory.events` `oom_kill` increments; the collector records `process_missing` |
| Sampler | add `--sampler-out` (default in the script) | `symbolize` ranks the leaking site first by live bytes; cumulative dwarfs live for the churning sites |
| Evidence bundle | n/a | `axis-memlab bundle --run ... --config ... --out bundle/` then `--verify` |
| Gate rehearsal | n/a | `advanced evidence`, then `advanced check`: everything blocked until you record a tested result |

Not supported by the virtual camera yet (**TODO**): a runtime control channel (for example,
draining a queue mid-run for T5 "recovery") and a second firmware to compare (T7).

Use `configs/stress-lab.toml` for shorter intervals when a run is only a few minutes.

## 8. Is the board set up correctly?

| Check | Command (on the board) | Expected |
| --- | --- | --- |
| Architecture | `uname -m` | `aarch64` |
| Tools | `cmake --version`, `c++ --version`, `python3 --version` | CMake >= 3.20, C++17 compiler, Python >= 3.11 |
| cgroup v2 + memory | `cat /sys/fs/cgroup/cgroup.controllers` | contains `memory` |
| systemd | `systemctl --version \| head -1` | present |
| Lab user | `id axmem-lab; sudo -l -U axmem-lab` | exists; no sudo rights |
| SSH restrictions | `sudo sshd -T -C user=axmem-lab,host=x,addr=127.0.0.1 \| grep -E 'passwordauth\|allowtcp'` | `passwordauthentication no`, `allowtcpforwarding no` |
| ptrace policy (informational) | `cat /proc/sys/kernel/yama/ptrace_scope` | any; reading `smaps_rollup` of your own user's process works at 0 or 1 |
| KVM (Tier 2) | `ls -l /dev/kvm` | present and readable by your user, or accept emulation |
| Build-id | `readelf -n build/opi5/native/axis_memlab_virtual_camera \| grep -A1 'Build ID'` | a hex id |
| Tests | `ctest --test-dir build/opi5 --output-on-failure -R 'virtual_camera\|sampler\|new_hook'` | all pass |
| Collector reads | from the workstation: `axis-memlab discover ...` | `process_status`, `process_stat`, `process_smaps_rollup`, `process_fd`, `cgroup_memory` `available` |

Record the results in the log in section 10.

## 9. Security notes

* The lab user has a locked password, your key only, no sudo, and no forwarding. The collector
  connects with strict host-key checking, batch mode, and no forwarding.
* The VM's SSH is forwarded to the board's loopback only. Do not change it to `0.0.0.0`.
* Nothing here sends data off the board or the workstation. The virtual camera processes no video
  and the outputs contain no personal data; they are still run archives, so keep the
  `privacy_classification` honest (`synthetic` for this lab).
* The scripts are conservative but unaudited on hardware. Read the dry-run output; do not run them
  on a board that holds anything you care about without a backup.

## 10. Verification log (fill in on your board)

| Date | Board / RAM | OS and kernel | KVM | Tier | Result | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| *(none recorded yet)* | | | | | | |

This log is **not** AXIS compatibility evidence and must not be copied into
`docs/01-axis-compatibility.md`.

## 11. Optional and TODO (needs a camera attached to the board, or a real camera)

Nothing in this list is implemented or required.

| Item | Status | What it would involve |
| --- | --- | --- |
| Real capture on the board | **TODO / optional** | Attach a USB (UVC) or MIPI-CSI camera and add a V4L2 capture source to the virtual camera, so frame buffers come from a driver. Study `process.fd_dmabuf_count` and driver-side buffers |
| Hardware codec and RGA | **TODO / optional** | Use Rockchip MPP/RGA through GStreamer or FFmpeg; compare shared and DMA-buffer memory with `H-SHARED-BUFFERS`. Needs the vendor media stack |
| RTSP ingest from an IP camera, including an AXIS camera | **TODO / optional** | Pull a real stream (GStreamer/FFmpeg) into the pipeline to get real decode memory behaviour and bitrates |
| NPU inference | **TODO / optional** | RKNN runtime memory on the RK3588 NPU; **not** equivalent to Larod semantics, so conclusions do not transfer |
| Kernel-side accounting on the board | **optional** | `slabinfo` and DMA-BUF debugfs need root and a mounted debugfs; useful to learn the *procedure*, not AXIS behaviour |
| Flash-like constraints | **optional** | Read-only root filesystem and tmpfs-only writes to imitate camera storage; measure write volume |
| Long soak | **optional** | 24 h Tier 1 and Tier 2 runs with the collector; confirm bounded host memory and valid JSONL after a network drop |
| Thermal and CPU-frequency effects | **optional** | Pin governors, log throttling, see whether timing changes alter trends |
| Anything AXIS-specific | **TODO (needs a real camera)** | Compatibility rows (`docs/01`), `discover` on a real account, SSH overhead, DDH capture, every diagnostic in `docs/13-advanced-diagnostics.md`, ACAP packaging, VDO and Larod integration. VDO/Larod and AXIS OS cannot run on this board |

## 12. Cleanup

```bash
sh docs/device-optional/opi5/vm/run-vm.sh --stop        # stop the VM
rm -rf ~/axmem-vm                                       # delete the VM and its overlay
sudo systemctl stop axmem-virtual-camera                # stop a Tier 1 run
sudo rm -f /etc/ssh/sshd_config.d/90-axmem-axmem-lab.conf && sudo systemctl reload ssh
sudo loginctl disable-linger axmem-lab
sudo userdel --remove axmem-lab                         # also deletes its runs/ directory
```

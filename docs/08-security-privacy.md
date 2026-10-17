# Security and privacy

Never collect or check in images, video, plate strings, customer identifiers,
credentials, or unredacted device archives. Redact pseudonymous identity and
process arguments, keep artifacts local, and exclude raw sensitive input.
Secrets must never be logged. Configuration is parsed locally with no shell
expansion, external includes, environment interpolation, network, or subprocess.

Future collection requires the least privilege, explicit user authorization,
bounded snapshots and buffers, retention controls, and secure archive handling.
The scaffold defaults deny root, mutation, ptrace, deep snapshots, image data,
plate text, and camera-flash writes.

## Host collection controls (M0001)

- **Read-only allowlist.** Readers accept only the paths in `docs/05-collecting-on-axis.md`
  and build remote commands from fixed templates; no user text reaches a remote shell, and
  the local `ssh` is started without a shell.
- **SSH.** Host keys are always verified, login is non-interactive, forwarding is disabled,
  and the target is validated (no option injection). Key material is passed by file path and
  never stored; the host name is not written to the archive or the logs.
- **Identity.** `--device-id` must be a pseudonym; addresses and serial numbers are refused.
  A salted helper exists (`axis_memlab.collection.identity.pseudonym`); keep the salt outside
  the repository.
- **What is not stored.** Command lines, environment, memory contents, fd targets and paths,
  log text, and `/proc/version`. fd targets are counted by class and discarded.
- **Deep captures** (`smaps`, allocator reports) are blocked: `snapshot --level deep` exits 3 and
  `allow_deep_snapshot=true` is rejected by the configuration. Enabling them needs a separate
  safety review (see the M0005 scope).
- **Retention.** Runs are local; `purge` lists old runs and deletes only with `--confirm`, only
  direct children that contain a manifest, never through symlinks. `--compress` makes a run
  read-only.
- **Import** validates every line before copying it, rejects other runs' ids and other
  devices, and never writes rejected lines.
- **Limits not covered.** There is no separate audit log of SSH sessions beyond the device's
  own logs, and the archive is not encrypted at rest; use disk encryption.

## Advanced diagnostics and bundles (M0005)

* The gate for Level 3-4 diagnostics fails closed per firmware and is advisory; the toolset runs
  none of them and never enables Developer Mode or changes device settings.
* Deep captures remain blocked (`docs/decisions/0003-advanced-diagnostics.md`); the evidence
  bundle has no option for core dumps.
* Bundles are minimized, scanned for identifying text, and refused rather than leaked; sensitive
  runs need a review confirmation; `--verify` detects later changes. Redaction is best-effort and
  a person must read the result.
* The virtual-board guide (`docs/device-optional/`) creates a locked-password, key-only,
  no-forwarding lab user and a loopback-only VM SSH port; it opens no other port.

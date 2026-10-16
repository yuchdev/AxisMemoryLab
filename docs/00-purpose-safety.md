# Purpose and safety

This project will support reproducible memory diagnostics for AXIS OS
applications through optional in-app counters and host-side offline tooling.
M0000 is only a scaffold: it does not discover devices, collect metrics, or
profile a camera.

Excluded at this stage are camera mutations, root access, ptrace, deep
snapshots, image/plate data, and network/device I/O. All profile safety flags
remain false; synthetic fixtures are not device measurements. Later collection
must establish least privilege, bounded work, explicit consent, and privacy
controls before implementation.

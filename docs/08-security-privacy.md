# Security and privacy

Never collect or check in images, video, plate strings, customer identifiers,
credentials, or unredacted device archives. Redact pseudonymous identity and
process arguments, keep artifacts local, and exclude raw sensitive input.
Secrets must never be logged. Configuration is parsed locally with no shell
expansion, external includes, environment interpolation, network, or subprocess.

Future collection requires least privilege, explicit user authorization,
bounded snapshots and buffers, retention controls, and secure archive handling.
The scaffold defaults deny root, mutation, ptrace, deep snapshots, image data,
plate text, and camera-flash writes.

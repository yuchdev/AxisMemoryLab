# Metric semantics

RSS is resident memory mapped by a process and can count shared pages in more
than one process. PSS apportions shared pages among processes; USS is the
process's unique resident pages. Anonymous and file-backed memory differ and
must not be conflated. Availability and kernel interfaces vary by platform;
unsupported or unreadable metrics must be marked unavailable with a reason,
not represented as zero.

Internal byte counts use bytes, not decimal kB or binary KiB. Names should state
the measured scope and unit. M0001 will define normalization and source parsing
semantics before collectors are implemented.

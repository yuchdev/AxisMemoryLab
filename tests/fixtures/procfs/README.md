# Synthetic procfs fixtures

`basic/` is a made-up device laid out like `/` (`proc/`, `sys/`): a 256 MiB system, one
process `synthetic_app` (pid 4242) and a second `other_app` (pid 4243), cgroup v2 files,
and `proc/4242/fd.ls`, a saved `ls -l /proc/4242/fd` (fixtures cannot hold symlinks on every
platform, so the local reader falls back to this file). Nothing here comes from a real
device. Tests copy and edit it to model missing or denied sources.

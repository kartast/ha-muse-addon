# Vendored SDK

This is the **Linux Device SDK** from
[facebookincubator/muse-gadget-sdk](https://github.com/facebookincubator/muse-gadget-sdk),
`linux/` directory, at commit `f60347aeb851a1fe9438cfc388721776aa24f275`
(2026-10-16), Apache-2.0 (see the LICENSE at the repository root of the SDK
project; each source file also carries its license header).

Vendored rather than fetched at image-build time so the add-on build is
reproducible and reviewable: what pairs with Muse is exactly what is in
this folder.

Changes versus upstream:

- `src/musegadget/executor.py` — the only modified file. Adds four commands
  (`ha.get_states`, `ha.call_service`, `ha.get_config`, `ha.camera_snapshot`)
  in `COMMAND_SPECS` plus handler branches in `Executor.run`, an audit log
  for service calls, and a module-docstring note. Everything upstream in the
  file is untouched; the additions are marked "Home Assistant bridge".
- `.gitignore` was dropped. Nothing else was added, removed, or changed.

Upstream's `install.sh` is kept for reference; the add-on does not run it
(the Dockerfile performs the equivalent steps, minus systemd and the host
BlueZ reconfiguration, which an add-on cannot and should not do).

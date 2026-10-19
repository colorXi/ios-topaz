#!/bin/bash
# civi: turn on XNU's own bsd_init() tracing.
#
# bsd/kern/bsd_init.c carries a complete step-by-step trace of bsd_init()
# (47 markers) behind DEBUG_BSDINIT, but it ships disabled:
#
#     #define DEBUG_BSDINIT 0
#     #if DEBUG_BSDINIT
#     #define bsd_init_kprintf(x, ...) kprintf("bsd_init: " x, ## __VA_ARGS__)
#     #else
#     #define bsd_init_kprintf(x, ...)
#     #endif
#
# On the Civi the console stops right after the last Mach IPC "subsystem is
# initialized" line, which is immediately before IOKitBSDInit()/bsd_init(), and
# the UFS bisect markers in bsd/dev/sweet_ufs.c never print -- so bsd_init() is
# either never reached or dies early inside it.  This turns on XNU's own
# markers, which is far more informative than hand-written printfs and cannot
# drift: it is a compile-time constant in one source file.
#
# NB: the file is bsd/kern/bsd_init.c in xnu-8796, not bsd/kern/init.c.
#
# Also worth knowing from that same file: bsd_init() wraps the root mount in
#
#     while (TRUE) {
#             ...
#             printf("cannot mount root, errno = %d\n", err);
#     }
#
# so once the root device really is probed and fails, it retries forever
# instead of panicking.  Absence of "cannot mount root" means we never got
# that far.
#
# dxb runs patches/*.sh from the XNU source root before applying *.patch.
set -euo pipefail

[[ "${MACHINE_CONFIG:-}" == SWEET ]] || exit 0

python3 - <<'PY'
from pathlib import Path

path = Path('bsd/kern/bsd_init.c')
old = '#define DEBUG_BSDINIT 0'
new = '#define DEBUG_BSDINIT 1'
if not path.exists():
    raise SystemExit(f'{path} does not exist')
text = path.read_text()
if text.count(old) != 1:
    if text.count(new) == 1:
        print('civi: DEBUG_BSDINIT already 1')
        raise SystemExit(0)
    raise SystemExit(f'expected one "{old}", found {text.count(old)}')
path.write_text(text.replace(old, new))
print('civi: DEBUG_BSDINIT -> 1 (XNU bsd_init() tracing enabled)')
PY
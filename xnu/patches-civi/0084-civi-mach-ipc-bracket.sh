#!/bin/bash
# civi: bracket the Mach IPC startup phase.
#
# The console stops right after
#     mlg_table_max_displ = 54 mach_kobj_count = 374
#     * core zlib memory 0x8000
# with no bsd_init() marker, so the hang is somewhere in the MACH_IPC startup
# phase.  kernel_startup_initialize_upto() calls every __startup_func in phase
# order, and kernel_bootstrap_log() only prints when the phase *changes*, so it
# cannot show which function inside the phase is running.  These markers print
# unconditionally around the phase call, which the stock log has no equivalent
# for, and inside ipc_init() to separate it from the rest of the phase.
#
# Line-based on purpose: Apple ships some files with CRLF, so substring
# matching with "\n" silently finds nothing.
#
# DXB runs patches/*.sh from the XNU source root before applying *.patch, so
# osfmk/kern/startup.c and osfmk/ipc/ipc_init.c are still pristine here.
set -euo pipefail

[[ "${MACHINE_CONFIG:-}" == SWEET ]] || exit 0

python3 - <<'PY'
from pathlib import Path


def insert_after(path, needle, lines):
    """Insert `lines` right after the single line equal to `needle`."""
    p = Path(path)
    raw = p.read_text()
    crlf = '\r\n' in raw
    src = raw.replace('\r\n', '\n').split('\n')
    hits = [i for i, l in enumerate(src) if l == needle]
    if len(hits) != 1:
        raise SystemExit(f'{path}: expected exactly one {needle!r}, found {len(hits)}')
    src[hits[0] + 1:hits[0] + 1] = lines
    out = '\n'.join(src)
    p.write_text(out.replace('\n', '\r\n') if crlf else out)
    print(f'civi: {path}: inserted after {needle.strip()[:48]!r}')


insert_after(
    'osfmk/kern/startup.c',
    '\tkernel_startup_initialize_upto(STARTUP_SUB_MACH_IPC);',
    ['\tkprintf("civi: MACH_IPC phase done\\n");'])

insert_after(
    'osfmk/ipc/ipc_init.c',
    'ipc_init(void)',
    ['{', '\tkprintf("civi: ipc_init entered\\n");'])
PY
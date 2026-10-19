#!/bin/bash
# civi: bracket the Mach IPC startup phase.
#
# The console stops right after
#     mlg_table_max_displ = 54 mach_kobj_count = 374
#     * core zlib memory 0x8000
# with no bsd_init: marker at all, so the hang is somewhere in the MACH_IPC
# startup phase.  kernel_startup_initialize_upto() runs every __startup_func in
# phase order, and kernel_bootstrap_log() only prints when the phase *changes*,
# so the stock log cannot show which function inside the phase is running.
# These markers print unconditionally around the phase call, which the stock
# log has no equivalent for, and inside ipc_init() to separate it from the
# rest of the phase.
#
# Line-based on purpose: Apple ships some files with CRLF, so a "\n"-joined
# substring match finds nothing in those.
#
# DXB runs patches/*.sh from the XNU source root before applying *.patch, so
# osfmk/kern/startup.c and osfmk/ipc/ipc_init.c are still pristine here.
set -euo pipefail

[[ "${MACHINE_CONFIG:-}" == SWEET ]] || exit 0

python3 - <<'PY'
from pathlib import Path


def load(path):
    p = Path(path)
    raw = p.read_text()
    crlf = '\r\n' in raw
    return p, raw.replace('\r\n', '\n').split('\n'), crlf


def save(p, src, crlf):
    out = '\n'.join(src)
    p.write_text(out.replace('\n', '\r\n') if crlf else out)


def insert_after_line(path, needle, lines):
    """Insert `lines` right after the single line equal to `needle`."""
    p, src, crlf = load(path)
    hits = [i for i, l in enumerate(src) if l == needle]
    if len(hits) != 1:
        raise SystemExit(f'{path}: expected exactly one {needle!r}, found {len(hits)}')
    src[hits[0] + 1:hits[0] + 1] = lines
    save(p, src, crlf)
    print(f'civi: {path}: inserted after {needle.strip()[:48]!r}')


def insert_after_block_open(path, func_sig, lines):
    """Insert `lines` right after the '{' that opens the block of `func_sig`.

    The function signature and its opening brace are on separate lines, and the
    brace must be kept exactly where it is -- emitting another one would
    unbalance the file and break the build.
    """
    p, src, crlf = load(path)
    hits = [i for i, l in enumerate(src) if l.strip() == func_sig]
    if len(hits) != 1:
        raise SystemExit(f'{path}: expected exactly one {func_sig!r}, found {len(hits)}')
    i = hits[0]
    if i + 1 >= len(src) or src[i + 1].strip() != '{':
        raise SystemExit(f'{path}: {func_sig!r} is not followed by an opening brace')
    src[i + 2:i + 2] = lines
    save(p, src, crlf)
    print(f'civi: {path}: inserted into {func_sig!r}')


insert_after_line(
    'osfmk/kern/startup.c',
    '\tkernel_startup_initialize_upto(STARTUP_SUB_MACH_IPC);',
    ['\tkprintf("civi: MACH_IPC phase done\\n");'])

insert_after_block_open(
    'osfmk/ipc/ipc_init.c',
    'ipc_init(void)',
    ['\tkprintf("civi: ipc_init entered\\n");'])
PY

#!/bin/bash
# civi: force XNU's per-startup-function trace on.
#
# kernel_startup_initialize_upto() already prints one line per startup entry
# before calling it:
#
#     kprintf("%s[%d, rank %d]: %p(%p)\n", __func__, cur->subsystem,
#             cur->rank, cur->func, cur->arg);
#
# which is exactly the trace we need -- the last line printed before the hang
# names the function that never returns.  It is gated on
#
#     (startup_debug & STARTUP_DEBUG_VERBOSE) && startup_phase >= STARTUP_SUB_KPRINTF
#
# and the console shows no such line at all, so startup_debug is 0 on this
# build: the boot arg "startup_debug=0x1" is not parsed as 1.
#
# Rather than fight the boot-arg parser, force the bit here.  Three gates use
# it: the per-entry trace, kernel_bootstrap_log()'s phase markers and the
# "reached phase" line.  All three are the same condition on the same line, so
# one line-based rewrite covers them.
#
# The pointer values are enough: llvm-nm on the kernel image resolves them to
# names offline.
#
# Line-neutral on purpose (the dxb patch pipeline shifts lines silently):
# one line in, one line out.
set -euo pipefail

[[ "${MACHINE_CONFIG:-}" == SWEET ]] || exit 0

python3 - <<'PY'
import re
from pathlib import Path

path = Path('osfmk/kern/startup.c')
raw = path.read_text()
crlf = '\r\n' in raw
src = raw.replace('\r\n', '\n').split('\n')

# "        if ((startup_debug & STARTUP_DEBUG_VERBOSE) &&"
pat = re.compile(r'^(\t+)if \(\(startup_debug & STARTUP_DEBUG_VERBOSE\) &&$')

hits = 0
for i, line in enumerate(src):
    m = pat.match(line)
    if m:
        src[i] = m.group(1) + 'if (((startup_debug | STARTUP_DEBUG_VERBOSE) != 0) &&'
        hits += 1

if hits == 0:
    raise SystemExit('startup.c: no startup_debug gate found -- refusing to continue')
if hits != 4:
    # kernel_bootstrap_log, kernel_bootstrap_thread_log, the per-entry trace
    # and the "reached phase" line.  A different count means the source
    # changed under us; fail loudly instead of half-patching.
    raise SystemExit('startup.c: expected 4 startup_debug gates, found %d' % hits)

out = '\n'.join(src)
path.write_text(out.replace('\n', '\r\n') if crlf else out)
print('civi: startup.c: forced STARTUP_DEBUG_VERBOSE in %d gates (line-neutral)' % hits)
PY

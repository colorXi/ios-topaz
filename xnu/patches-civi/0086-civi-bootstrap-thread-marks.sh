#!/bin/bash
# civi: mark every step of kernel_bootstrap_thread() so the hang is named.
#
# What the QEMU run established (tools/qemu-sweet.py, not a phone photo):
#   * the whole startup table ran: _startup_entry_cur points one past the end
#     of __init_entry_set (4076 entries), and _startup_phase is 0xffffffff,
#     which is what kernel_startup_initialize_upto(STARTUP_SUB_LOCKDOWN) sets
#     at startup.c:747 -- so line 747 was reached and returned.
#   * the console's last message ("kdp_core zlib memory 0x8000") comes from
#     kdp_init() at startup.c:655.
#   * bsd_init() (startup.c:790) never ran.
#
# So the hang is between startup.c:747 and startup.c:790.  The candidate
# calls in that window are:
#     OSKextRemoveKextBootstrap, machine_lockdown, kernel_do_post (XNUPOST),
#     PE_lockdown_iokit, vm_set_restrictions, kperf_init_early, bsd_init.
#
# Each marker is inserted *after* its call, so the last marker that appears
# is the last step that returned; the step right after it is the one that
# hangs.  Markers are also added along the earlier path so the run can be
# read end to end.
#
# No *.patch touches osfmk/kern/startup.c (checked), so adding lines here
# cannot shift a later patch.
set -euo pipefail

[[ "${MACHINE_CONFIG:-}" == SWEET ]] || exit 0

python3 - <<'PY'
import sys
from pathlib import Path

path = Path('osfmk/kern/startup.c')
raw = path.read_text()
crlf = '\r\n' in raw
src = raw.replace('\r\n', '\n').split('\n')

# (line to insert after, marker text)
MARKS = [
    # --- kernel_bootstrap(): the path up to the bootstrap thread ---
    ('\tkernel_startup_initialize_upto(STARTUP_SUB_MACH_IPC);', 'civi: MACH_IPC phase done'),
    ('\tmachine_init();', 'civi: machine_init done'),
    ('\tthread_machine_init_template();', 'civi: thread_machine_init_template done'),
    ('\tclock_init();', 'civi: clock_init done'),
    ('\ttask_init();', 'civi: task_init done'),
    ('\tthread_init();', 'civi: thread_init done'),
    ('\tworkq_init();', 'civi: workq_init done'),
    ('\tturnstiles_init();', 'civi: turnstiles_init done'),
    ('\texception_init();', 'civi: exception_init done'),

    # --- kernel_bootstrap_thread(): the interesting window ---
    ('\tkdp_init();', 'civi: kdp_init done'),
    ('\tkernel_startup_initialize_upto(STARTUP_SUB_THREAD_CALL);', 'civi: THREAD_CALL phase done'),
    ('\tkernel_startup_initialize_upto(STARTUP_SUB_SYSCTL);', 'civi: SYSCTL phase done'),
    ('\tPE_init_iokit();', 'civi: PE_init_iokit done'),
    ('\tkernel_startup_initialize_upto(STARTUP_SUB_EARLY_BOOT);', 'civi: EARLY_BOOT phase done'),
    ('\tinitialize_screen(NULL, kPEAcquireScreen);', 'civi: initialize_screen done'),
    ('\tvm_commpage_init();', 'civi: vm_commpage_init done'),
    ('\tmac_policy_initmach();', 'civi: mac_policy_initmach done'),
    ('\tvnguard_policy_init();', 'civi: vnguard_policy_init done'),
    ('\tdtrace_early_init();', 'civi: dtrace_early_init done'),
    ('\tload_static_trust_cache();', 'civi: load_static_trust_cache done'),
    ('\tkernel_startup_initialize_upto(STARTUP_SUB_LOCKDOWN);', 'civi: LOCKDOWN phase done'),
    ('\tOSKextRemoveKextBootstrap();', 'civi: OSKextRemoveKextBootstrap done'),
    ('\tmachine_lockdown();', 'civi: machine_lockdown done'),
    ('\tresult = kernel_do_post();', 'civi: kernel_do_post done'),
    ('\tPE_lockdown_iokit();', 'civi: PE_lockdown_iokit done'),
    ('\tvm_set_restrictions(machine_info.max_cpus);', 'civi: vm_set_restrictions done'),
    ('\tkperf_init_early();', 'civi: kperf_init_early done'),
    ('\tbsd_init();', 'civi: bsd_init done'),
]

missing = []
inserted = 0
skipped = 0
for needle, text in MARKS:
    hits = [i for i, l in enumerate(src) if l == needle]
    if len(hits) != 1:
        missing.append((needle, len(hits)))
        continue
    i = hits[0]
    marker = '\tkprintf("%s\\n");' % text
    if i + 1 < len(src) and src[i + 1] == marker:
        skipped += 1
        continue
    src.insert(i + 1, marker)
    inserted += 1

if missing:
    for needle, n in missing:
        print('MISSING (%d): %r' % (n, needle), file=sys.stderr)
    raise SystemExit('startup.c: %d marker anchors not found' % len(missing))

out = '\n'.join(src)
path.write_text(out.replace('\n', '\r\n') if crlf else out)
print('civi: startup.c: %d markers inserted, %d already present' % (inserted, skipped))
PY

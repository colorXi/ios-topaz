#!/bin/bash
# civi: do not write CNTP_CTL_EL0 from EL1.
#
# _enable_virtual_timer() in osfmk/arm64/machine_routines.c is inlined into
# fiq_context_init() and writes CNTP_CTL_EL0 right after enabling the virtual
# timer:
#
#     __builtin_arm_wsr64("CNTV_CTL_EL0", cntvctl);
#     /* disable the physical timer as a precaution ... */
#     __builtin_arm_wsr64("CNTP_CTL_EL0", CNTP_CTL_EL0_IMASKED);
#
# CNTP_CTL_EL0 is EL0-permission: an EL1 write is architecturally UNDEFINED.
# On the Civi's Cortex-A55 it traps and XNU dies before any output:
#
#     panic(cpu 0 ...): Undefined kernel instruction:
#       pc=0xfffffe0007491360 instr=d51be228 @sleh.c:951
#
# 0xd51be228 disassembles to `msr cntp_ctl_el0, x8`, and 0xfffffe0007491360 is
# _wfe_timeout_init + 0x4, i.e. the instruction immediately after that write.
# sleh.c:515 reads `instr = *((uint32_t *)get_saved_state_pc(state))`, so pc
# and instr are the same word.
#
# On Qualcomm the physical counter belongs to TrustZone and XNU drives the
# virtual timer (sweet_vtimer_intid, PPI 19), so masking it from EL1 is both
# impossible and unnecessary.  Guard the write out instead of removing it, so
# the change is a no-op on any non-SWEET config.
#
# dxb runs patches/*.sh from the XNU source root before applying *.patch.
set -euo pipefail

[[ "${MACHINE_CONFIG:-}" == SWEET ]] || exit 0

python3 - <<'PY'
from pathlib import Path
import sys

path = Path('osfmk/arm64/machine_routines.c')
text = path.read_text()
write = '\t__builtin_arm_wsr64("CNTP_CTL_EL0", CNTP_CTL_EL0_IMASKED);\n'
if text.count(write) != 1:
    raise SystemExit(f'expected exactly one CNTP_CTL_EL0 write, found '
                     f'{text.count(write)} in {path}')
guarded = (
    '\t/* civi: CNTP_CTL_EL0 is EL0-permission; an EL1 write is\n'
    '\t * architecturally UNDEFINED and traps on the Cortex-A55.\n'
    '\t * TrustZone owns the physical counter and XNU uses the virtual\n'
    '\t * timer, so there is nothing useful to do here. */\n'
    '#if !defined(ARM64_BOARD_CONFIG_SWEET)\n'
    + write +
    '#endif\n')
path.write_text(text.replace(write, guarded))
print('civi: CNTP_CTL_EL0 write guarded out of _enable_virtual_timer()')
PY
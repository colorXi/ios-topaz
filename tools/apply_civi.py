#!/usr/bin/env python3
"""Apply the Civi (Xiaomi Civi / SM7325 "yupik") hardware constants to the shim.

The shim carries its SoC constants as #defines at the top of a few files. The
Civi values below were read off the live phone (device tree + root /proc/iomem),
not guessed:

  GICD/GICR  0x17a00000 / 0x17a60000   soc/interrupt-controller@17a00000/reg
                                        (identical to sweet's SM7150 values)
  FB         0x0e1000000               reserved-memory/splash_region
                                        soc/disp_rdump_region@e1000000
  UFS        0x01d84000                soc/ufshc@1d84000
  cpufreq-hw 0x18591000                iomem `18591000.qcom,cpufreq-hw`
  MPIDR      cpu@0,100..700/reg -> Aff1 = core index, Aff0 = 0, so MPIDR = i<<8
             (cpu0-3 = A55 @1.8048GHz, cpu4-7 = A78 @2.4GHz)

Still unknown, needs one probe boot to confirm (both only used by reset(), the
"reboot into fastboot" helper -- a wrong value only makes the shim hang instead
of rebooting, it does not block the boot itself):
  IMEM_RESTART_REASON / PSHOLD

Usage:
    python3 tools/apply_civi.py --check     # show what would change
    python3 tools/apply_civi.py             # apply (idempotent)
    python3 tools/apply_civi.py --dir shim-civi
"""
import os, re, sys

DEFAULT_DIR = 'shim'

# (file, regex, replacement, human note)
RULES = [
    ('console.h',
     r'(#define\s+FB_BASE\s+)0x[0-9a-fA-F]+UL',
     r'\g<1>0x0e1000000UL',
     'framebuffer 0x5c000000 -> 0x0e1000000 (splash_region / disp_rdump_region)'),

    ('mmu.h',
     r'(#define\s+FB_PHYS\s+)0x[0-9a-fA-F]+UL',
     r'\g<1>0x0e1000000UL',
     'same framebuffer for the MMU probe'),

    ('shim.c',
     r'(#define\s+GICD_BASE\s+)0x[0-9a-fA-F]+UL',
     r'\g<1>0x17a00000UL',
     'GICD 0x0f200000 -> 0x17a00000'),

    ('shim.c',
     r'(#define\s+GICR_BASE\s+)0x[0-9a-fA-F]+UL',
     r'\g<1>0x17a60000UL',
     'GICR 0x0f300000 -> 0x17a60000'),

    ('shim.c',
     r'static inline uint64_t cpu_mpidr\(int i\)\s*\{[^}]*\}',
     'static inline uint64_t cpu_mpidr(int i) { return (uint64_t)i << 8; }',
     'MPIDR: civi Aff1 = core index (same formula shape as sweet)'),

    ('shim.c',
     r'uintptr_t b = 0x[0-9a-fA-F]+;',
     'uintptr_t b = 0x18591000;',
     'cpufreq-hw domain 0x0f523000 -> 0x18591000 (best-effort clock raise)'),

    # The Silver->Gold hand-off only runs when the boot core has no 16K granule.
    # Every civi core is ARMv8.2, so this is very unlikely to trigger; point it
    # at the first A78 (cpu4, MPIDR 0x400) anyway instead of topaz's 0x100.
    ('shim.c',
     r'smc\(PSCI_CPU_ON, 0x100,',
     'smc(PSCI_CPU_ON, 0x400,',
     'fallback hand-off target 0x100 -> 0x400 (first A78)'),
    ('shim.c',
     r'for \(uint32_t aff = 0x101; aff <= 0x103; aff\+\+\)',
     'for (uint32_t aff = 0x401; aff <= 0x407; aff++)',
     'prepare the A78 redistributors instead of the A73s'),
    ('shim.c',
     r'hand(?:ing)? off to gold CPU 0x100',
     'handing off to big CPU 0x400',
     'console string'),

    ('ufs.c',
     r'(#define\s+UFS_BASE\s+)0x[0-9a-fA-F]+UL',
     r'\g<1>0x01d84000UL',
     'UFS host 0x04804000 -> 0x01d84000 (standard UFSHCI, only the base differs)'),
]

WARNINGS = [
    'shim.c IMEM_RESTART_REASON and PSHOLD are still topaz values.',
    '  They are only used by reset() to bounce back into fastboot. A wrong value',
    '  means the shim hangs instead of rebooting -- it does not block booting.',
    '  Find them on the phone with: adb shell su -c "ls /proc/device-tree/soc | grep -i imem"',
]


def main():
    check = '--check' in sys.argv
    d = DEFAULT_DIR
    if '--dir' in sys.argv:
        d = sys.argv[sys.argv.index('--dir') + 1]
    if not os.path.isdir(d):
        sys.exit(f'{d}: not a directory')

    changed = 0
    for fname, pat, rep, note in RULES:
        path = os.path.join(d, fname)
        if not os.path.exists(path):
            print(f'  skip  {fname}: file not found')
            continue
        src = open(path, encoding='utf-8').read()
        new, n = re.subn(pat, rep, src)
        if n == 0 or new == src:
            print(f'  ----  {fname}: already civi ({note.split(":")[0]})')
            continue
        if not check:
            open(path, 'w', encoding='utf-8', newline='').write(new)
        changed += 1
        print(f'  {"????" if check else "ok  "}  {fname}: {note}')

    print()
    if not changed:
        print('Nothing to do -- the shim already carries the civi constants.')
    elif check:
        print(f'{changed} change(s) pending. Re-run without --check to apply.')
    else:
        print(f'Applied {changed} change(s) to {d}/')
    print()
    for w in WARNINGS:
        print(w)


if __name__ == '__main__':
    main()

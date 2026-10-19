#!/usr/bin/env python3
"""Civi probe #3: find the real MPIDR of all eight cores by brute force.

Probe #2 answered everything the GIC could tell us:

    GICR frames at 0x17a60000 + 0x20000*n, eight of them, Last=1 on frame 7
    GICR_TYPER[63:32] = 0x000, 0x100, ... 0x700   (Aff1 = core, Aff2/Aff3 = 0)

but the boot core reads MPIDR_EL1 = 0x81000000 (Aff3 = 0x81), so Qualcomm's GIC
simply does not report Aff3 in TYPER. sweet hit the same wall ("MPIDR 0x81000n00"
in their notes) and solved it with PSCI_CPU_ON probing.

So: try CPU_ON over candidate MPIDRs. The TZ validates the target, so only the
real ones return 0 -- and secondary_main() records the MPIDR the woken core
reads for itself, which is the value XNU will compare against the device tree.

Usage: python3 tools/civi_probe3.py --dir shim [--check]   (idempotent)
"""
import os, re, sys

FUNC = r'''
/*
 * CIVI PROBE 3: brute-force the MPIDR of every core.
 *
 * Probe #2: GICR_TYPER affinities are 0x000..0x700 (Aff1 = core index) but the
 * boot core's MPIDR_EL1 is 0x81000000, i.e. Qualcomm's GIC never reports Aff3.
 * The TrustZone validates CPU_ON targets, so whatever the TZ accepts is what the
 * hardware really is, and the woken core reports its own MPIDR via
 * secondary_main() -> sec_mpidr[].
 */
static const uint64_t g_sweep_bases[] = {
	0x81000000ULL, 0x80000000ULL, 0x82000000ULL, 0x00000000ULL,
	0x81001000ULL, 0x81010000ULL, 0x01000000ULL, 0x00100000ULL,
};

static void sweep_mpidrs(void)
{
	uint32_t hits = 0;

	con_str("SWEEP", "brute-force MPIDR via PSCI CPU_ON");
	for (unsigned b = 0; b < sizeof(g_sweep_bases) / sizeof(g_sweep_bases[0]); b++) {
		uint32_t okmask = 0;
		for (int i = 0; i < 8; i++) {
			uint64_t cand = g_sweep_bases[b] | ((uint64_t)i << 8);
			sec_mpidr[i] = 0;
			int64_t r = smc(PSCI_CPU_ON, cand, (uintptr_t)secondary_entry, i);
			/* -38 RETARGET_INVALID / -37 RETARGET_NOT_PRESENT are "wrong
			 * address"; anything else is worth printing. */
			if (r != 0 && (uint32_t)r != 0xffffffdaU && (uint32_t)r != 0xffffffdbU) {
				con_hex2("  SWEEP ret", "cand=", (uint32_t)cand, "r=", (uint32_t)r);
			}
			if (r == 0)
				okmask |= 1U << i;
		}
		delay_ms(200);
		if (okmask) {
			uint32_t n = 0;
			for (int i = 0; i < 8; i++)
				if (okmask & (1U << i))
					n++;
			hits++;
			con_hex("  SWEEP base", (uint32_t)g_sweep_bases[b]);
			con_hex2("  SWEEP ok", "mask=", okmask, "n=", n);
			for (int i = 0; i < 8; i++) {
				if (sec_mpidr[i]) {
					con_hex("    core idx", i);
					con_hex2("    MPIDR", "lo=", (uint32_t)sec_mpidr[i],
					    "hi=", (uint32_t)(sec_mpidr[i] >> 32));
				}
			}
			con_skip();
		}
	}
	con_hex2("SWEEP done", "bases_hit=", hits, "done=", 1);
	con_skip();
}
'''

RULES = [
    ('shim.c',
     r'\nvoid shim_main\(uint64_t dtb\)\n',
     '\n' + FUNC + '\nvoid shim_main(uint64_t dtb)\n',
     'insert sweep_mpidrs()'),
    ('shim.c',
     r'(\tstage = "loader";\n\tcon_clear\(RED\);\n)',
     r'\1\tsweep_mpidrs();\n\tcon_skip();\n',
     'call sweep_mpidrs() right after the banner clears the screen'),
]


def main():
    check = '--check' in sys.argv
    d = 'shim'
    if '--dir' in sys.argv:
        d = sys.argv[sys.argv.index('--dir') + 1]
    n = 0
    for fname, pat, rep, note in RULES:
        path = os.path.join(d, fname)
        if not os.path.exists(path):
            print(f'  skip  {fname}: not found')
            continue
        src = open(path, encoding='utf-8').read()
        new, c = re.subn(pat, rep, src)
        if c == 0 or new == src:
            print(f'  ----  {fname}: already injected ({note})')
            continue
        if not check:
            open(path, 'w', encoding='utf-8', newline='').write(new)
        n += 1
        print(f'  {"????" if check else "ok  "}  {fname}: {note}')
    print()
    print('probe #3 is one-shot; rebuild from the clean shim to drop it')


if __name__ == '__main__':
    main()

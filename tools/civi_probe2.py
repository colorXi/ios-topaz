#!/usr/bin/env python3
"""Inject the Civi probe #2 into the shim: enumerate every core's real MPIDR.

Probe #1 answered the big questions (tg16=1, A55 boot core, UFS ready, framebuffer
0x0e1000000 correct) but also showed one thing that will bite us:

    MIDR mpidr = 81000000        <- Aff3 = 0x81
    device tree cpus/cpu@0 reg  = 0x00000000

XNU's topology code compares the hardware MPIDR against the device tree `reg` and
bails out ("invalid topology") when they differ, so the ADT needs the real values.
The GICv3 redistributor frames hold them: GICR_TYPER[63:32] is the
Aff3:Aff2:Aff1:Aff0 of the PE that owns the frame, and there are exactly 8 frames
(0x17a60000 + 0x20000*n, GICR_SIZE 1 MiB / stride 0x20000 == 8).

Usage:
    python3 tools/civi_probe2.py --dir shim      # inject
    python3 tools/civi_probe2.py --dir shim --check
Idempotent.
"""
import os, re, sys

FUNC = r'''
/*
 * CIVI PROBE 2: dump every GICv3 redistributor frame so we can read the real
 * MPIDR of all eight cores. Probe #1 showed the boot core at 0x81000000 while
 * the device tree says reg=0x0, and XNU compares those two and panics.
 * GICR_TYPER[63:32] = Aff3:Aff2:Aff1:Aff0 of the PE behind that frame.
 */
static void dump_gicr_aff(void)
{
	uint32_t gdtyper_lo = rd32(GICD_BASE + 0x04);
	uint32_t gdtyper_hi = rd32(GICD_BASE + 0x08);
	uint32_t i = 0;

	con_hex2("GICD TYPER", "lo=", gdtyper_lo, "hi=", gdtyper_hi);
	for (uintptr_t off = 0; off < GICR_SIZE; off += GICR_PE_SIZE, i++) {
		uint64_t t = rd64(GICR_BASE + off + GICR_TYPER);
		uint64_t aff = t >> 32;
		uint32_t last = (uint32_t)((t >> 4) & 1);

		con_hex2("  GICR", "off=", off, "typer=", (uint32_t)t);
		con_hex2("  aff", "lo=", (uint32_t)aff, "hi=", (uint32_t)(aff >> 32));
		con_hex2("  frame", "i=", i, "last=", last);
		con_skip();
		if (last)
			break;
	}
}
'''

RULES = [
    # 1) the function, right before shim_main()
    ('shim.c',
     r'\nvoid shim_main\(uint64_t dtb\)\n',
     '\n' + FUNC + '\nvoid shim_main(uint64_t dtb)\n',
     'insert dump_gicr_aff()'),
    # 2) the call: right AFTER the banner's con_clear(RED) (anchored on the
    #    preceding `stage = "loader"` so the other con_clear(RED) in the file
    #    -- the mmu failure path -- does not get a second copy), otherwise the
    #    dump is wiped before anybody sees it.
    ('shim.c',
     r'(\tstage = "loader";\n\tcon_clear\(RED\);\n)',
     r'\1\tdump_gicr_aff();\n\tcon_skip();\n',
     'call dump_gicr_aff() right after the banner clears the screen'),
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
    print('probe #2 is a one-shot diagnostic; remove it with `git checkout -- shim`'
          if not check else 're-run without --check to apply')


if __name__ == '__main__':
    main()

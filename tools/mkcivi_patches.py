#!/usr/bin/env python3
"""Generate the Civi kernel patch set from the sweet base + topaz's patches.

The sweet tree (dipa-studio/ios-sweet) and topaz share one patch directory; the
topaz patches encode topaz's hardware. For Civi we need:

  0001-0079  sweet's base series, unchanged
  0080       topaz's, with the MPIDR check and CPU name rewritten
  0081       topaz's 0082 (boot CPU) with the real Civi boot MPIDR
  -- skip 0081 (ARMv8.0: -mcpu=cortex-a53, commpage casa, the LSE/LDAPR
     emulator) -- Civi is ARMv8.2, LSE and PAN are available
  -- skip 0083-0103 (FT5452 touch and topaz's display scanout; Civi has a
     Synaptics TCM over SPI and a different panel)

Every replacement keeps the line count identical so the unified-diff hunk
headers stay valid.

Usage: python3 tools/mkcivi_patches.py [--check]
"""
import os, re, shutil, sys

SRC = 'xnu/patches'
DST = 'xnu/patches-civi'
BASE_LAST = 79

# (source patch, [(old, new), ...], output name)
PATCHES = [
    ('0080-topaz-cpu-topology-skip-sweet-hw.patch', [
        # MPIDR check: topaz validated Aff1=cluster/Aff0=core for 0x0-0x3 and
        # 0x100-0x103. Civi is 0x81000000 | (core << 8) for cores 0..7, so the
        # only thing to validate is that Aff3:Aff2 and Aff0 are what we expect
        # (the Aff1 range is implied by the DT having eight cpu nodes).
        ('+	if ((cpu->phys_id >> 8) > 1 || (cpu->phys_id & 0xff) > 3 ||',
         '+	if ((cpu->phys_id & ~0x7ffU) != 0x81000000U ||'),
        ('+	cpuName = OSSymbol::withCStringNoCopy("Kryo 260");',
         '+	cpuName = OSSymbol::withCStringNoCopy("Kryo 670");'),
    ], '0080-civi-cpu-topology.patch'),

    # topaz's 0082 is "boot on the gold CPU because ABL starts on a Silver core
    # with no 16K granule". Civi's ABL starts on CPU 0 (Cortex-A55) which does
    # have 16K (probe #1: tg16=1), so the boot core is just CPU 0 -- but its
    # MPIDR is 0x81000000, not 0, so the expectation changes.
    ('0082-topaz-boot-on-gold-cpu.patch', [
        ('+	 * topaz: the ADT lists only the A73 (gold) cores and the shim boots xnu',
         '+	 * civi: the ADT lists all eight cores and the shim boots xnu'),
        ('+	 * on gold CPU 0x100 (the silver cluster has no 16K granule).',
         '+	 * on CPU 0 (MPIDR 0x81000000, a Cortex-A55 with a 16K granule).'),
        ('+	if (topology->boot_cpu->cpu_id != 0 || topology->boot_cpu->phys_id != 0x100) {',
         '+	if (topology->boot_cpu->cpu_id != 0 || topology->boot_cpu->phys_id != 0x81000000U) {'),
        ('+		panic("SWEET CPU: expected boot MPIDR 0x100 and logical CPU 0, got 0x%x/%u",',
         '+		panic("SWEET CPU: expected boot MPIDR 0x81000000 and logical CPU 0, got 0x%x/%u",'),
    ], '0081-civi-boot-cpu-mpidr.patch'),
]


def main():
    check = '--check' in sys.argv
    if check:
        out = {}
        for src, reps, name in PATCHES:
            out[name] = [sum(open(os.path.join(SRC, src)).read().count(a) for a, _ in reps),
                         len(reps)]
        for k, v in out.items():
            print(f'  {k}: replacements found {v[0]}/{v[1]}')
        print(f'  base: 0001-{BASE_LAST:04d} copied verbatim')
        return

    if os.path.isdir(DST):
        shutil.rmtree(DST)
    os.makedirs(DST)

    n = 0
    for f in sorted(os.listdir(SRC)):
        m = re.match(r'^(\d{4})-', f)
        if not m or f.endswith('.sh'):
            continue
        if int(m.group(1)) <= BASE_LAST:
            shutil.copyfile(os.path.join(SRC, f), os.path.join(DST, f))
            n += 1
    print(f'  copied {n} base patches (0001-{BASE_LAST:04d})')

    for src, reps, name in PATCHES:
        text = open(os.path.join(SRC, src), encoding='utf-8').read()
        for old, new in reps:
            if old not in text:
                raise SystemExit(f'{src}: pattern not found:\n  {old}')
            text = text.replace(old, new)
        # retitle the patch so the series reads as one coherent port
        text = re.sub(r'^topaz[:(].*$', 'civi: see below', text, flags=re.M)
        open(os.path.join(DST, name), 'w', encoding='utf-8', newline='\n').write(text)
        print(f'  wrote {name}')

    files = sorted(os.listdir(DST))
    print(f'\n  {DST}: {len(files)} files, last = {files[-1]}')
    print('  skipped on purpose: 0081 armv8.0 (no LSE emulator needed),'
          ' 0083-0103 (FT5452 + topaz display)')


if __name__ == '__main__':
    main()

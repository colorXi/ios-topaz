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

# Sweet's early framebuffer console hardcodes sweet's splash FB physical address.
# On Civi that address (0x9c000000) is not RAM at all -- System RAM starts at
# 0xdff00000 -- so the very first `str w1, [x5], #4` in osfmk/arm64/start.s is a
# data abort before the exception vectors are even installed: XNU dies silently
# and the panel keeps showing the shim's own console.  This is what made every
# phone boot of the Civi port look like "nothing happened" while QEMU booted to
# SWEET EARLY 20 (QEMU has RAM everywhere, so 0x9c000000 was harmless there).
#
# Civi's ABL splash buffer is 0x0e1000000 (reserved-memory/splash_region,
# disp_rdump_region@e1000000 +20M).  Five sites, all of them `+` lines except
# 0012's `-#define EARLY_FB ...` line, which has to change with them or 0012
# will no longer match the tree that 0010 produced.
#
#   0010 osfmk/arm64/start.s        MOV64 x0, (FB + 2368*4320)   stage-0 band
#   0010 osfmk/arm64/start.s        MOV64 x10, FB               bootstrap VA=PA
#   0010 osfmk/arm64/sweet_early.c  #define EARLY_FB ... FB
#   0012 osfmk/arm64/arm_vm_init.c  *slot = FB|ARM_TTE_*        final VA alias
#   0012 osfmk/arm64/sweet_early.c  static ... *early_fb = ... FB
BASE_SUBS = {
    '0010-sweet-early-framebuffer-debug.patch': [('0x9c000000', '0x0e1000000')],
    '0012-sweet-keep-debug-console-after-ttbr0.patch': [('0x9c000000', '0x0e1000000')],
}


def main():
    check = '--check' in sys.argv
    if check:
        for src, reps, name in PATCHES:
            found = sum(open(os.path.join(SRC, src), encoding='utf-8').read().count(a) for a, _ in reps)
            print(f'  {name}: replacements found {found}/{len(reps)}')
        for f, reps in BASE_SUBS.items():
            text = open(os.path.join(SRC, f), encoding='utf-8').read()
            for old, new in reps:
                n = text.count(old)
                flag = 'ok' if n else 'MISSING'
                print(f'  base {f}: {old} -> {new}  ({n} site(s)) {flag}')
        print(f'  base: 0001-{BASE_LAST:04d} copied verbatim')
        return

    if os.path.isdir(DST):
        shutil.rmtree(DST)
    os.makedirs(DST)

    n = 0
    for f in sorted(os.listdir(SRC)):
        m = re.match(r'^(\d{4})-', f)
        if not m or int(m.group(1)) > BASE_LAST:
            continue
        # .patch AND the .sh stage scripts (0019/0020/0026) -- blacktop's
        # build.sh runs the stage scripts by name, so they must come along or
        # the "Fetch build script" step fails on a non-matching glob.
        src_path, dst_path = os.path.join(SRC, f), os.path.join(DST, f)
        subs = BASE_SUBS.get(f)
        if subs:
            text = open(src_path, encoding='utf-8').read()
            hits = 0
            for old, new in subs:
                c = text.count(old)
                if not c:
                    raise SystemExit(f'{f}: pattern not found:\n  {old}')
                text = text.replace(old, new)
                hits += c
            open(dst_path, 'w', encoding='utf-8', newline='\n').write(text)
            print(f'  {f}: rewrote {hits} framebuffer address(es)')
        else:
            shutil.copyfile(src_path, dst_path)
        n += 1
    print(f'  copied {n} base files (0001-{BASE_LAST:04d}, patches + stage scripts)')

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

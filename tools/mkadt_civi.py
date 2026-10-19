#!/usr/bin/env python3
"""Build the minimal Apple Device Tree that the CIVI xnu needs to boot.

Civi port of tools/mkadt.py. Every MMIO value below was read off a live Civi
(xiaomi Civi / SM7325 "yupik" / Snapdragon 778G), not guessed:

  GICD/GICR  /proc/device-tree/soc/interrupt-controller@17a00000/reg
             -> 0x17a00000 (64K) + 0x17a60000 (1M). Identical to sweet (SM7150).
  UFS        /proc/device-tree/soc/ufshc@1d84000        (iomem `1d84000.ufshc`)
  FB         /proc/device-tree/reserved-memory/splash_region  0x0e1000000
             /proc/device-tree/soc/disp_rdump_region@e1000000 (0x0e1000000+20M)
  RAM        /proc/device-tree/memory/reg -> banks
             <0x80000000 0x39700000> <0xc0000000 0xc0000000> <0x180000000 0x100000000>
             every reserved-memory carve-out is below 0xe3400000, so the 4 GiB
             high bank is clean: that is what --highmem style placement uses.
  MPIDR      /proc/device-tree/cpus/cpu@{0,100..700}/reg -> Aff1 = core index,
             Aff0 = 0: cpu_n is at MPIDR (n << 8).
             cpu0-3 = Cortex-A55 (0xd05, 1.8048 GHz), cpu4-7 = A78 (0xd41, 2.4 GHz).
  Root       /proc/device-tree/compatible -> qcom,yupik-idp | qcom,yupik | qcom,idp

Still UNKNOWN, only the probe shim on real hardware can answer them:
  - which core ABL hands control to (MPIDR) and its TGran16
  - whether ABL leaves the UFS host enabled and the splash framebuffer lit

Usage: mkadt_civi.py OUT.adt [--dump] [--qemu] [--lowmem] [--native]
"""
import hashlib, os, struct, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import adt  # noqa: E402

# ---------------------------------------------------------------- RAM
# High DDR bank from the live DT: <0x180000000 0x100000000>. All
# reserved-memory carve-outs observed live below 0xe3400000, so this 4 GiB
# window is free of XPU reservations -- same trick topaz uses with --highmem.
#
# Verified with root /proc/iomem on the phone (2026-10-19):
#   System RAM 0xdff00000-0x27fffffff
#   reserved   0xe1000000-0xe33fffff   <- splash / display buffer (our fb)
#   reserved   0xe5000000-0xffbfffff
#   reserved   0x276000000-0x27fffffff <- NOT in the DT reserved-memory list,
#                                         so the window stops BELOW it.
HIGH_PHYS_BASE = 0x180000000
HIGH_MEM_SIZE = 0x0f600000          # -> ends at 0x276000000, ~3.86 GiB
# Low/medium banks carry the carve-outs; kept only for --lowmem experiments.
PHYS_BASE = 0xe3400000
MEM_SIZE = 0x180000000 - 0xe3400000

# /arm-io children are relative to this; it must not be 0 (serial_init bails)
SOC_BASE = 0x01000000

# interrupt-controller@17a00000: GICD 0x17a00000/64K, GICR 0x17a60000/1M.
# Sweet measured GICR_PE_SIZE 0x20000 with 8 PEs; 1M/32K == 8 PEs fits exactly.
GICD, GICD_SIZE = 0x17a00000, 0x10000
GICR, GICR_SIZE = 0x17a60000, 0x100000

# ABL cont splash / display rdump buffer (reserved-memory/splash_region)
FB, FB_SIZE = 0x0e1000000, 0x1400000
SWEET_ECID = 0x4349564900000001  # 'CIVI' + 1, synthetic
FB_W, FB_H, FB_STRIDE = 1080, 2400, 1080 * 4

# Internal UFS host (soc/ufshc@1d84000)
UFS, UFS_SIZE = 0x01d84000, 0x3000

# Qualcomm standard; verified on sweet, still to confirm on Civi by the shim
TIMEBASE = 19200000
VTIMER_INTID = 19

# QEMU virt (-M virt,gic-version=3 -cpu cortex-a76)
QEMU_GICD, QEMU_GICR, QEMU_TIMEBASE = 0x08000000, 0x080a0000, 62500000
QEMU_VTIMER_INTID = 27

# cpufreq-hw (iomem `18591000.qcom,cpufreq-hw`); only used by the shim probe
CPUFREQ_HW = 0x18591000
# GENI SPI (soc/spi@980000, compatible qcom,spi-geni) -- Synaptics TCM lives here
SPI0, SPI0_SIZE = 0x00980000, 0x4000
# DSI: ctrl 0xae94000, phy 0xae94900, DP 0xae90000 (iomem / DT node names).
# /proc/cmdline: msm_drm.dsi_display0=qcom,mdss_dsi_k9b_42_02_0a_dsc_cmd --
# Samsung K9B AMOLED, DSI *command* mode with DSC. /sys/class/drm modes:
#   1080x2400x60x110807cmd / 1080x2400x120x110807cmd
DSI_CTRL, DSI_PHY, DP = 0x0ae94000, 0x0ae94900, 0x0ae90000
PANEL_W, PANEL_H, PANEL_HZ = 1080, 2400, 60

BOOT_MANIFEST_HASH = hashlib.sha384(b'civi boot manifest').digest()

# The iOS userland is the iPhone X (iPhone10,3 / D22AP) IPSW. MobileGestalt
# derives product type, device class, home-button-less UI, artwork etc. from
# the root identity and /product of the real D22AP device tree. That tree is an
# Apple artifact (kept out of git): extract it from the IPSW with
#   tools/remotezip.py URL DeviceTree.d22ap.im4p DIR
#   ipsw img4 im4p extract DIR/Firmware/all_flash/DeviceTree.d22ap.im4p -o d22ap.adt
D22AP_ADT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../research/ipsw-x/d22ap.adt')


def d22ap_product(path=D22AP_ADT):
    """/product properties of the real D22AP tree, without the syscfg
    placeholders iBoot would fill in (flag bit set) and the node bookkeeping."""
    if not os.path.exists(path):
        print(f'warning: {path} missing, no /product node', file=sys.stderr)
        return None
    root, _ = adt.parse(open(path, 'rb').read())
    for c in root.children:
        if dict((k, v) for k, f, v in c.props).get('name') == b'product\0':
            return [(k, v) for k, f, v in c.props if not f and k not in ('name', 'AAPL,phandle')]
    raise SystemExit(f'{path}: no /product node')

u32 = lambda *v: struct.pack('<%dI' % len(v), *v)
u64 = lambda *v: struct.pack('<%dQ' % len(v), *v)
cstr = lambda s: s.encode() + b'\0'


def node(name, props=(), children=()):
    n = adt.Node()
    n.props = [('name', 0, cstr(name))] + [(k, 0, v) for k, v in props]
    n.children = list(children)
    return n


# civi: eight cores. Real MPIDRs measured on the phone by probe #3
# (PSCI CPU_ON brute force; every woken core reported its own MPIDR_EL1):
#
#     core N  ->  MPIDR_EL1 = 0x81 << 32 | (N << 8)
#
# core0-3 are Cortex-A55 (CPU part 0xd05, 1.8048 GHz), core4-7 are A78
# (0xd41, 2.4 GHz).
#
# IMPORTANT: the DT `reg` below is Aff1:Aff0 ONLY (N << 8), NOT the full
# MPIDR_EL1.  XNU's phys_id is a uint32 and ml_get_cpu_number() does
#     phys_id &= MPIDR_AFF1_MASK | MPIDR_AFF0_MASK;     /* 0xff00 | 0xff */
#     for (...) if (topology_info.cpus[i].phys_id == phys_id) return i;
# while ml_get_cpu_number_local() feeds it `(uint32_t)MPIDR_EL1`.  Aff3 lives
# in MPIDR_EL1 bits [39:32], so after the uint32 cast it becomes 0x81 << 24 --
# outside the Aff1:Aff0 mask -- and a reg of 0x81000000 can never match the
# lookup.  Every lookup then returns -1 and
# `assert(cpu_id <= ml_get_max_cpu_number())` in machine_routines.c fires
# right after kernel_startup_bootstrap; that is why cpus=1 and cpus=8 both
# panicked identically.  Aff3 = 0x81 is not in the Android device tree either
# (reg 0x0..0x700) and not in GICR_TYPER -- Qualcomm's GIC never reports it.
CIVI_CORES = [
    (0x00000000, 1804800000), (0x00000100, 1804800000),
    (0x00000200, 1804800000), (0x00000300, 1804800000),
    (0x00000400, 2400000000), (0x00000500, 2400000000),
    (0x00000600, 2400000000), (0x00000700, 2400000000),
]


def build(seed=None, qemu=False, lowmem=False, native=False, bootonly=False):
    """qemu=True: QEMU virt GIC addresses and CNTFRQ (tools/qemu-sweet.py).
    lowmem=True: the carve-out-riddled low banks instead of the clean high one."""
    phys_base, mem_size = (PHYS_BASE, MEM_SIZE) if lowmem else (HIGH_PHYS_BASE, HIGH_MEM_SIZE)
    gicd, gicr, timebase = (QEMU_GICD, QEMU_GICR, QEMU_TIMEBASE) if qemu else (GICD, GICR, TIMEBASE)
    seed = seed if seed is not None else os.urandom(64)
    phandle = iter(range(1, 1000))
    ph = lambda: ('AAPL,phandle', u32(next(phandle)))

    chosen = node('chosen', [
        ph(),
        ('dram-base', u64(phys_base)),
        ('dram-size', u64(mem_size)),
        ('random-seed', seed),
        ('debug-enabled', u32(1)),
        ('firmware-version', cstr('civi-shim')),
        ('system-firmware-version', cstr('civi-shim')),
        # iBoot's SHA-384 of the boot manifest; /sbin/mount -P 1 exits unless
        # it exists (bind mounts /private/preboot/<hex>/usr/standalone/firmware,
        # tolerating a missing directory). Fixed stand-in value.
        ('boot-manifest-hash', BOOT_MANIFEST_HASH),
        # libimg4 (cryptexd) aborts "failed to get crypto algorithm" without it.
        ('crypto-hash-method', cstr('sha2-384')),
        # 1080x2400 @3x = 360x800 points (iPhone X class). Scale 0 makes
        # SpringBoard's FBSDisplayMode "infxinf@0x" invalid.
        ('display-scale', u32(3)),
        # XNU derives IOPlatformUUID from these on arm; without them
        # CFPreferences cannot use kCFPreferencesCurrentHost, so e.g.
        # DataMigration never records LastSystemVersion and runs every boot.
        ('unique-chip-id', struct.pack('<Q', SWEET_ECID)),
        ('chip-id', u32(0x8015)),
        # Dev-fused, undemoted board (tuple 0,0,1,1): mobileactivationd takes its
        # native "Hactivation" branch (no SEP, no baseband here).
        ('certificate-production-status', u32(0)),
        ('effective-production-status-ap', u32(0)),
        ('certificate-security-mode', u32(1)),
        ('effective-security-mode-sep', u32(1)),
    ], [node('memory-map', [ph()]),
        # SIP relaxed like `csrutil disable` (lp-sip0: untrusted kexts,
        # unrestricted FS, task_for_pid, kernel debugger, dtrace, nvram),
        # lp-sip1: unauthenticated (unsealed) root.
        node('asmb', [ph(), ('lp-sip0', u64(0x6f)), ('lp-sip1', u32(1))])])

    cpu_nodes = []
    cores = [(i, 0) for i in range(1)] if qemu else CIVI_CORES
    if bootonly:
        # Only the core ABL actually hands control to.  Bisects "XNU dies before
        # its first kprintf": if the tree lists a single core with the real
        # MPIDR of the boot core, nothing about cpu_start / MPIDR matching /
        # cluster topology can be the cause.  The boot core is Civi cpu0
        # (Cortex-A55, MPIDR 0x81000000), confirmed by the shim probe.
        cores = [(CIVI_CORES[0][0], CIVI_CORES[0][1])]
    for n, (mpidr, clk) in enumerate(cores):
        cpu_nodes.append(node(f'cpu{n}', [
            ph(),
            ('device_type', cstr('cpu')),
            # 'qcom,kryo' is what the live Civi DT says; 'ARM,v8' keeps the
            # XNU IONameMatch working.
            ('compatible', cstr('qcom,kryo') + cstr('ARM,v8')),
            ('reg', u32(mpidr if not qemu else n)),  # MPIDR Aff1:Aff0, NOT logical ID
            ('cpu-id', u32(n)),   # descriptive: XNU assigns IDs by DT order
            ('cluster-id', u32(0)),
            ('cluster-type', u32(0)),  # homogeneous CLUSTER_TYPE_SMP, not AMP
            ('die-cluster-id', u32(0)),
            ('cluster-core-id', u32(n)),
            ('l2-cache-id', u32(0 if n < 4 else 1)),
            ('l3-cache-id', u32(0)),
            ('state', cstr('running' if n == 0 else 'stopped')),
            ('timebase-frequency', u32(timebase)),
            ('clock-frequency', u32(clk)),
            ('bus-frequency', u32(100000000)),
            ('memory-frequency', u32(1866000000)),
            ('peripheral-frequency', u32(timebase)),
            ('fixed-frequency', u32(timebase)),
        ]))
    cpus = node('cpus', [ph(), ('#address-cells', u32(1)),
                         ('#size-cells', u32(0))], cpu_nodes)

    gic = node('gic', [
        ph(),
        ('compatible', cstr('arm,gic-v3')),
        ('interrupt-controller', b''),
        ('virtual-timer-intid', u32(QEMU_VTIMER_INTID if qemu else VTIMER_INTID)),
        ('reg', u64(gicd - SOC_BASE, GICD_SIZE, gicr - SOC_BASE, GICR_SIZE)),
    ])
    arm_io = node('arm-io', [
        ph(),
        ('device_type', cstr('sweet-io')),
        ('compatible', cstr('sweet-io') + cstr('arm-io')),
        ('#address-cells', u32(2)),
        ('#size-cells', u32(2)),
        ('ranges', u64(0, SOC_BASE, 0x100000000 - SOC_BASE)),
    ], [gic,
        # No hardware: watchdogd checks IODeviceTree:/arm-io/wdt for no-pmu and
        # otherwise crashes trying to set the PMU boot stage.
        node('wdt', [ph(), ('no-pmu', u32(1))]),
        # IOMobileFramebuffer counts /arm-io children with this device_type and
        # reads the canvas size from the node; the kernel's AppleCLCD matches
        # the compatible string.
        node('disp0', [
            ph(),
            ('device_type', cstr('display-subsystem')),
            ('compatible', cstr('sweet,display')),
            # --native: present the real 1080x2400 panel (needed for direct MDP
            # scanout, which must match the canvas).
            ('canvas-width', u32(1080 if native else 1125)),
            ('canvas-height', u32(2400 if native else 2436)),
        ])])

    fbcon = node('sweet-fbcon', [
        ph(),
        ('reg', u64(FB, FB_SIZE)),
        ('width', u32(FB_W)),
        ('height', u32(FB_H)),
        ('stride', u32(FB_STRIDE)),
    ])

    # bsd/dev/sweet_ufs.c: the UFS host ABL leaves running (absolute physical reg).
    ufs = node('sweet-ufs', [
        ph(),
        ('compatible', cstr('qcom,ufshc')),
        ('reg', u64(UFS, UFS_SIZE)),
    ])

    # pmap_compute_max_asids requires the node even with no overrides. No
    # effaceable storage: keybagd then reads systembag.kb as a plain plist.
    defaults = node('defaults', [ph(), ('no-effaceable-storage', u32(1))])

    # MobileGestalt HomeButtonType: D22AP = 2 (no Home button, gesture UI).
    buttons = node('buttons', [
        ph(),
        ('button-names', cstr('volup') + cstr('voldown') + cstr('hold')),
        ('home-button-type', u32(2)),
        ('opposed-power-vol-buttons', u32(1)),
    ])

    product_props = d22ap_product()
    product = [node('product', [ph()] + product_props)] if product_props else []

    # Identity of the iPhone X whose userland runs here: compatible[0] is
    # hw.model/hw.target (D22AP), model is hw.machine/hw.product (iPhone10,3).
    # 'xiaomi,sweet' stays because SweetPlatformExpert and the CPU IONameMatch
    # still use it; qcom,yupik is the real SoC compatible from the live DT.
    return node('device-tree', [
        ph(),
        ('compatible', cstr('D22AP') + cstr('iPhone10,3') + cstr('xiaomi,civi') +
                       cstr('xiaomi,sweet') + cstr('qcom,yupik') + cstr('AppleARM')),
        ('model', cstr('iPhone10,3')),
        ('target-type', cstr('D22')),
        ('target-sub-type', cstr('D22AP')),
        ('manufacturer', cstr('Apple Inc.')),
        ('#address-cells', u32(2)),
        ('#size-cells', u32(2)),
    ], [chosen, defaults, cpus, arm_io, fbcon, buttons] + product + ([] if qemu else [ufs]))


if __name__ == '__main__':
    root = build(qemu='--qemu' in sys.argv, lowmem='--lowmem' in sys.argv,
                 native='--native' in sys.argv, bootonly='--bootonly' in sys.argv)
    blob = adt.serialize(root)
    open(sys.argv[1], 'wb').write(blob)
    if '--dump' in sys.argv:
        adt.dump(adt.parse(blob)[0])
    print(f'{sys.argv[1]}: {len(blob)} bytes', file=sys.stderr)
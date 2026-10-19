#!/usr/bin/env python3
"""Wrap the shim Image + ramdisk into a boot.img the phone's ABL will take.

Why this exists: the shim's build.sh calls an external mkbootimg, and the one
available in this WSL (Debian's apt build) writes a different header field
order than the images this project is known to boot: it leaves page_size = 0
and puts os_version where ramdisk_size belongs, so tools/unpack_bootv2.py
(the project's own checker, which mirrors what the ABL parses) rejects it.

So build the header here instead, in the exact layout that layout-checker
expects:

    0x000  magic "ANDROID!"
    0x008  10 x u32: kernel_size, kernel_addr, ramdisk_size, ramdisk_addr,
           second_size, second_addr, tags_addr, page_size, header_version(=4),
           os_version(version<<11 | patch)
    0x030  name[16]
    0x040  cmdline[512]
    0x240  extra_cmdline[1024]
    0x660  recovery_dtbo_size u32, recovery_dtbo_offset u64, header_size u32
    0x670  dtb_size u32, dtb_addr u64
    (header padded to page_size, then kernel page-aligned, then ramdisk)

Usage: mkciviboot.py Image ramdisk.bin out-boot.img [--page 4096]
"""
import struct, sys

PAGE = 4096
KERNEL_ADDR = 0x00000058      # what mkbootimg uses for androidboot
RAMDISK_ADDR = 0x01000000
CMDLINE = b'console=null'
NAME = b'civi-shim'
# Android 13.0.0, patch level 2025-01, packed the way AOSP does it
OS_VERSION = (13 << 14) | (0 << 7) | 0
OS_PATCH = (2025 << 4) | 1


def rnd(n, ps):
    return (n + ps - 1) // ps * ps


def build(kernel, ramdisk, out, ps=PAGE):
    h = bytearray(ps)
    h[0:8] = b'ANDROID!'
    struct.pack_into('<10I', h, 8,
                     len(kernel), KERNEL_ADDR,
                     len(ramdisk), RAMDISK_ADDR,
                     0, 0,                    # second_size, second_addr
                     0,                       # tags_addr
                     ps,                      # page_size
                     4,                       # header_version
                     (OS_VERSION << 11) | OS_PATCH)
    h[0x30:0x40] = NAME + b'\0' * (16 - len(NAME))
    h[0x40:0x240] = CMDLINE + b'\0' * (512 - len(CMDLINE))
    # extra_cmdline[1024] stays zero
    struct.pack_into('<IQI', h, 1632, 0, 0, 1648)   # recovery_dtbo + header_size
    struct.pack_into('<IQ', h, 1648, 0, 0)          # dtb

    blob = bytes(h)
    blob += kernel + b'\0' * (rnd(len(kernel), ps) - len(kernel))
    blob += ramdisk + b'\0' * (rnd(len(ramdisk), ps) - len(ramdisk))
    open(out, 'wb').write(blob)
    return len(blob)


def main():
    if len(sys.argv) < 4:
        sys.exit(__doc__)
    ps = PAGE
    if '--page' in sys.argv:
        ps = int(sys.argv[sys.argv.index('--page') + 1])
    kernel = open(sys.argv[1], 'rb').read()
    ramdisk = open(sys.argv[2], 'rb').read()
    n = build(kernel, ramdisk, sys.argv[3], ps)
    print(f'{sys.argv[3]}: {n} bytes '
          f'(page {ps}, kernel {len(kernel)}, ramdisk {len(ramdisk)})')


if __name__ == '__main__':
    main()

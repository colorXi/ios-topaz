# CIVI HANDOFF - iOS 16.7.16 on Xiaomi Civi (SM7325)

Written 2026-10-22 09:50 by the previous agent. Read this first, then
`NOTES.md` (the long chronological log, newest at the top).

## 1. Goal

Boot iOS 16.7.16 (iPhone X userland, build 20H392) on a **Xiaomi Civi**
(SM7325 "yupik", 4x Cortex-A55 + 4x Cortex-A78, 8 GiB) and **see the UI**.
The work is a port of dipa-studio/ios-sweet, forked as
`colorXi/ios-topaz` (branch `main`), with all port-specific changes living in
`xnu/patches-civi/*.patch` (currently 0001..0129).

## 2. Hardware / environment state

- Bootloader unlocked, `fastboot` works, **only `fastboot boot <img>` is used**
  (nothing is ever written to boot partitions).
- Android is gone. **userdata holds the iOS root filesystem**: a 20 GiB
  journaled case-sensitive HFS+ image (`/private/var` inside it), built by
  `tools/mkiosroot.sh` from a 12 GiB payload. XNU finds it through
  `rd=ufsroot0` -> `IOFindBSDRoot` -> `sweet_ufs_rootdev` -> GPT partition
  named `userdata`.
- To recover the phone from any state: hold power ~10 s, it returns to fastboot.
- Windows host: `C:\Users\BUFF\ios-civi\` (images, scripts, artifacts),
  `C:\Users\BUFF\ios-topaz\` (fork; worktree must be committed from Windows,
  the CI applies the patches on a macOS runner).
- WSL `Ubuntu` (root) holds the toolchains: `/root/ios-topaz` (sweet tree),
  `/root/xt` (local replay of the CI tree), `/root/ios-vm/ios16-root-20H392.img`
  (the 20 GiB image), `/root/kbuild` (a kernel with HFS+ module so WSL can mount
  the image), and `/tmp/pc` (the dxb patch set used for reference).

## 3. How to build and boot (the only loop that works)

1. Edit a file in `/root/xt/...` (this tree is a replay of what CI builds).
2. Regenerate the patch: `diff -u --label a/<path> --label b/<path> <backup> <file>`
   into `xnu/patches-civi/NNNN-civi-<name>.patch` (see the many
   `C:\Users\BUFF\ios-civi\wsl-mkpatch*.sh` scripts for the exact pattern).
3. Commit + push from Windows: `git push mine HEAD:main` (user `colorXi`).
4. Watch CI: `ci-watch*.ps1` (run id from the GitHub API), artifact
   `xnu-kernel-civi` -> `kernel.development.sweet`. **The artifact download
   sometimes fails with "unexpected EOF"; retry 2-3 times.**
5. Repack: `wsl ... bash /mnt/c/Users/BUFF/ios-civi/wsl-repack*.sh` which calls
   `repack.sh "<cmdline>" <out.img>`.
6. `fastboot boot CIVI\<img>` via `boot-when-ready*.ps1` (they wait for fastboot
   in a loop, so they can be queued before the user power-cycles).

The full command line used everywhere (order matters, keep it identical when
comparing runs):

```
debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=ufsroot0
unentitled_ios_sim_launch=1 ignition_level=1 wdt_test=no_user_checkin
ufsrw=1 rootrw=1 launchd_unsecure_cache=1 wdt=-1 sweetfb_hz=30
sweetlog=0 sweetsample=- sweetfb_blink=1
```

## 4. What is verified working (as of 2026-10-22)

| Layer | State |
| --- | --- |
| Root filesystem | 20 GiB HFS+ on `userdata`, mounts read-write, journal replay completes ("jnl: journal replay done") |
| UFS driver | host takeover, GPT parse, read/write/sync all return `ocs 0` |
| Kernel | `bsd_init` runs to completion, devfs, vfsinit, IOKit init |
| Userland | **launchd runs** (`Darwin Bootstrapper 7.0.0`, boot-args echoed verbatim), FIPS POST passes |
| Boot tasks | walks `xpcroleaccountd`, `init_featureflags`, `auearlyboot` (finishes), `tzinit`, `keybag`, `usermanagerd`, `dirs_cleaner`, `mount-phase-2` (passes: "data volume missing, but not required"), `init-with-data-volume`, `MSUEarlyBootTask` |
| Keybag | **MKB_INIT completes**: `System Keybag Loaded`, `****** DONE MKB_INIT ****` |
| Display | IOMobileFramebuffer driver registers, but **no userland frame has ever been presented** |

## 5. The current blocker (in one paragraph)

The boot gets through the launchd boot-task chain and then the **console goes
silent** at a task that varies between runs (`usermanagerd`, `tzinit`,
`dirs_cleaner`, `MSUEarlyBootTask`). At that point the panel still shows the
last text (or gets cleared to black), and **nothing** prints afterwards - not
the sampler, not the 60 s report. Two candidates remain: the console lock is
wedged by a thread stuck inside a framebuffer write, or the kernel really stops.
No userland frame has ever reached `present()`: the string `SWEET FB: swap %u
layer` (printed for the first 16 presents) has never appeared on any boot.

## 6. Instrumentation that exists (use it, it works)

- **Console line filter** (0101, boot-args `sweetnull=...`, `sweetscan=...`,
  `sweetiolog=...`): drops whole lines so a log storm cannot hide the tail.
- **Process sampler** (0114-0117): `sweetsample=*` lists every process as
  `PS name[pid]`; `sweetsample=launchd` prints user stacks
  (`SMP name[pid] t0 pc .. lr .. bt ..`). First sample at 90 s, then every
  120 s. It waits with `tsleep`, which **does** work on this port.
- **FB probes** (0125): `SWEET FB: args hz=.. blink=..` at start and
  `SWEET FB: vsync N` every 300 ticks.
- **thread_call self-test** (0126): logs `SWEET FB: thread_call fired` 2 s after
  start.
- **Delayed report** (0127): at +60 s prints
  `SWEET FB: report vsync=N test=0/1 blink=1` and it stays on the panel.
- **Sampler-side FB status** (0128): prints
  `SMP FB started=.. vsync=.. swaps=.. test=..` with each sample.
- **Sampler paints a marker** (0129): the sampler draws a 96x96 square at the
  centre of the panel (white/red alternating) **without using the console**, so
  a wedged console cannot hide it.
- Persistent log (0103-0113): a 4 MiB ring flushed to the last 4100 KiB of
  `userdata`, readable at boot with `sweetlogdump=N`. It works, but the writer
  perturbs the boot (see 16:35 note) - keep `sweetlog=0` unless debugging it.

## 7. Hard-won facts - do not relearn these

1. **`kprintf` never reaches the panel; only `printf` does.** All markers must
   use `printf`.
2. **`delay()` never returns on this port.** Use `ufs_spin_us()` or a
   `mach_absolute_time` loop. `tsleep` **does** work (the sampler proves it).
3. **A kernel thread that busy-spins starves the single-CPU boot** (A/B proven:
   spinning sampler -> boot never leaves `vfs_mountroot`). Never spin for
   seconds in a kernel thread.
4. **CI silently skips patches.** `git apply` is atomic per patch; the log has
   `Skipping patch .../dxb/patches/NNNN`. 24 dxb patches are skipped by design
   now; **no patch in `xnu/patches-civi/` is skipped**. Always check.
5. The framebuffer console **scrolls by clearing the whole panel** (0087), so
   early text is unrecoverable - use the delayed report or the painted marker.
6. AKS (AppleKeyStore) selector recipe that made keybagd succeed:
   `0,4,5,9,12,13,26,27,55,101,102` -> success, no outputs;
   `6 (load_bag)`, `2 (create_bag)`, `3 (save_bag)` -> success with a handle;
   `14 (get_system)` -> `kIOReturnNotFound` **only until a bag is loaded**, then
   handle 0; `7` -> lock state with bit 2 set ("unlocked since boot");
   `17/35` -> DER state set (UniXNU's NativeKeyStoreEvents has a reference
   encoder for this).
7. `0122` removed a real bug: `vsyncFired()` unlocked `fLock` twice.
8. The image's `/tmp` is a symlink to `private/var/tmp`; launchd's `dc_reset`
   logs `EINVAL` for it and `tzinit` logs "Bad zoneinfo link". Both are
   filesystem-semantics issues on `/private/var`, still unexplained.
9. Linux-built HFS+ hardlinks lack `kHFSHasLinkChainBit`; the driver repairs
   them **in memory only**, so every boot pays again (0041 just mutes the log).

## 8. Images on disk (`C:\Users\BUFF\ios-civi\`)

| Image | Kernel | What it demonstrates |
| --- | --- | --- |
| `civi-aks.img` | 0102 | reaches `mount-phase-1`; shows the dyld shared-cache "not in trust cache" flood |
| `civi-nosmp.img` | 0116 | reaches `dirs_cleaner` with the console filter on |
| `civi-fbst.img` | 0128 | sampler + FB status line |
| `civi-paint.img` | 0129 | sampler paints the marker square (latest) |
| `civi-rp.img` | 0127 | +60 s delayed report |
| `civi-probe.img` / `civi-tc.img` | 0125/0126 | FB arg probe, thread_call self-test |

## 9. Recommended next steps

1. **Settle whether `AppleCLCD::start()` runs and whether the vsync timer
   ticks** - boot `civi-paint.img` (`sweetsample=*`) and look for the centre
   square; if it appears, the console is the problem, not the system; then read
   `SMP FB started=.. vsync=..`.
2. If `started=0`: the driver is not matching `/arm-io/disp0`. Check the ADT
   node and `IOMobileFramebuffer` matching (the iOS framework counts
   `device_type = "display-subsystem"` children and waits for that many
   services).
3. If `started=1, vsync=0`: the timer never fires. Our timer lives on
   `IOWorkLoop::workLoop()`; **UniXNU's NativeMobileDisplay (github.com/UniXNU)
   attaches its `IOTimerEventSource` to `getWorkLoop()` of the service and arms
   it with `wakeAtTime()` only when a client enables vsync (selector 72)**. Try
   switching to `getWorkLoop()`/provider workloop, and check the 0126
   thread_call self-test result.
4. If `vsync>0` and `swaps=0`: userland never swaps -> CoreAnimation/backboardd.
   The sweet notes' CPU-renderer path (patches 0059-0071 in `dxb/patches`) is
   the reference.
5. For the boot-task stalls: `usermanagerd` and `tzinit` both touch
   `/private/var` symlinks. Fixing `dc_reset`/`tzinit` may need an image change
   (rebuild with `tools/mkiosroot.sh` and reflash userdata - 12 GiB, ~5 min, and
   it destroys nothing else on the phone).

## 10. Reference material

- `C:\Users\BUFF\unixnu\UniXNU-main\` (docs) plus the cloned drivers:
  `/root/nmd` (`NativeMobileDisplay`), `/root/nkse` (`NativeKeyStoreEvents`).
  UniXNU is a different boot chain (UEFI/DarwinBoot) but its driver code is the
  best reference for MobileDisplay vsync and AKS semantics.
- `C:\Users\BUFF\ios-topaz\NOTES.md` - 15 handoff sections in reverse
  chronological order with every measurement.

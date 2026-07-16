# openpowerlink

Talk to B&R POWERLINK peripherals (e.g. an X20 BC0083 bus coupler) **from Python,
in userspace** — with the compiled openPOWERLINK Managing-Node stack **bundled in
the wheel**. Install and run; nothing else to build or configure on the target
(except, on Windows, the Npcap runtime — see below).

```python
from openpowerlink import PowerlinkStack, PowerlinkIO

with PowerlinkStack(iface="eth0", cdc="mnobd.cdc", xap="xap.xml") as stack:
    # The MN needs up to a few seconds to climb the NMT state machine to
    # Operational. Gate on this instead of a fixed sleep — reading the process
    # image before the MN is Operational legitimately returns zeros.
    if not stack.wait_operational(timeout=10.0):
        raise SystemExit("Managing Node did not reach Operational")

    io = PowerlinkIO(stack)
    io.write_do(0, True)              # set digital output 0
    io.write_ao_volts(1, 4.5)         # set analog output 1 to 4.5 V
    print(io.read_di())               # list[bool]
    print(io.read_ai_volts())         # list[float]
    if not io.status().cn_operational:
        print("controlled node not operational!")
```

> The MN reaching Operational and the *controlled node* reaching Operational are
> two separate things: `wait_operational()` waits for the MN; the CN joining is
> reported by `io.status().cn_operational`. A CN that never becomes operational
> while the MN is healthy is a wiring / node-id / CDC issue on the CN side — see
> **Troubleshooting** below.

## How it works

The package bundles two native libraries per platform under
`openpowerlink/_native/<platform>/`:

* `oplkmn` — the complete openPOWERLINK **Managing-Node** stack (userspace,
  direct-link), built as a shared library;
* `oplkwrap` — a thin C shim exposing a small, stable ctypes ABI over it.

`openpowerlink._loader` picks the right binary for the running OS/architecture and
loads it in-process via `ctypes` — no separate daemon, no shared memory. The
per-cycle PDO exchange runs inside the stack's own sync context; Python reads
inputs / writes outputs through the process image described by your `xap.xml`.

The inputs are the artifacts produced by **openCONFIGURATOR-Studio**:

* `mnobd.cdc` — the concise device configuration (boots the CN);
* `xap.xml` — the process-image description (channel offsets/sizes).

## Install

The CI builds a wheel per platform and attaches them to a **GitHub Release** on
each `vX.Y.Z` tag. To install on another machine, `pip install` the matching
release asset directly (public repo — no token needed):

```bash
# pick the line for your platform (bump the version to match the release tag)
# Linux x86_64
pip install https://github.com/oe7set/openpowerlink-py/releases/download/v0.1.5/openpowerlink-0.1.5-py3-none-manylinux_2_34_x86_64.whl
# Linux aarch64 (Raspberry Pi 4/5, Jetson, …)
pip install https://github.com/oe7set/openpowerlink-py/releases/download/v0.1.5/openpowerlink-0.1.5-py3-none-manylinux_2_34_aarch64.whl
# Windows x86_64  (install Npcap first: https://npcap.com)
pip install https://github.com/oe7set/openpowerlink-py/releases/download/v0.1.5/openpowerlink-0.1.5-py3-none-win_amd64.whl
```

Or grab the latest without hardcoding the version (needs the GitHub CLI):

```bash
gh release download --repo oe7set/openpowerlink-py --pattern '*manylinux_2_34_x86_64.whl'
pip install ./openpowerlink-*.whl
```

Prebuilt wheels are provided for:

| Platform | Ethernet driver | Notes |
|----------|-----------------|-------|
| Linux x86_64 (`manylinux_2_34`)  | raw `PF_PACKET` socket | needs glibc ≥ 2.34 (RHEL 9 / Debian 12 / Ubuntu 22.04+) |
| Linux aarch64 (`manylinux_2_34`) | raw `PF_PACKET` socket | Raspberry Pi 4/5, Jetson, …; glibc ≥ 2.34 |
| Windows x86_64 | Npcap | **install [Npcap](https://npcap.com) once** |

## Runtime requirements

Userspace raw Ethernet needs elevated privileges and a dedicated POWERLINK NIC:

* **Linux**: run as root, or grant the process `CAP_NET_RAW` (and `CAP_NET_ADMIN`):
  ```bash
  sudo setcap cap_net_raw,cap_net_admin+eip "$(readlink -f "$(which python3)")"
  ```
* **Windows**: install the **Npcap** runtime (WinPcap-compatible mode). The wheel
  ships `oplkmn.dll` + `oplkwrap.dll`, but Npcap is a signed kernel driver and
  cannot be bundled — install it once from https://npcap.com.

Use a NIC dedicated to POWERLINK (the stack takes over raw frames on it).

### Troubleshooting: `plw_init failed (oplk error 0x0008)`

`0x0008` is `kErrorNoResource` and, on Linux, almost always means the stack
could not (re)create its POSIX IPC objects in `/dev/shm`. The usual cause is
**mixed privileges**: an earlier run as `root` (e.g. via `sudo`) left
`sem.semUserEvent`, `sem.semKernelEvent`, `sem.semCircbuf-*` and `shmCircbuf-*`
owned by `root`, and a later unprivileged run cannot reopen or unlink them
(`/dev/shm` is sticky, so a non-owner cannot remove them).

* **Fix / avoid it:** run the stack **consistently as root** (raw Ethernet needs
  it anyway) so it owns and cleans up its own objects. The bundled stack now
  creates these objects owner-writable and unlinks them on clean shutdown, so
  same-user reruns no longer collide.
* **One-time cleanup** of stale root-owned leftovers from an earlier run:
  ```bash
  sudo rm -f /dev/shm/sem.semUserEvent /dev/shm/sem.semKernelEvent \
             /dev/shm/sem.semCircbuf-* /dev/shm/shmCircbuf-*
  ```

### Troubleshooting: MN or CN not reaching Operational

Two maintainer scripts under `scripts/` diagnose a stack that comes up but does
not deliver data. Copy them next to your `mnobd.cdc` / `xap.xml` and run them
with the same interface as your app. They need `cap_net_raw` on the interpreter
(the raw-socket edrv and the sniffer both open `AF_PACKET`).

* `scripts/diag.py <iface> [cdc] [xap] [seconds]` — starts the stack and prints a
  timestamped NMT-state trace plus a verdict. Use it to confirm the **Managing
  Node** reaches Operational and that the cycle counter advances.
* `scripts/cndiag.py <iface> [cdc] [xap] [seconds]` — runs the MN *and* a
  POWERLINK wire sniffer in one process; tells apart "the MN isn't transmitting",
  "the **controlled node** is silent", and "the CN answers but with a different
  node-id than the CDC expects".
* `scripts/dump_cdc.py <mnobd.cdc>` — decodes the concise device configuration
  and lists which node-ids are configured as pollable CNs (`0x1F81` with
  `NODE_EXISTS | NODE_IS_CN`), so you can check the CDC node-id matches the
  coupler's node-id switch.

NMT state codes (raw `mn_nmt_state` / `cn_nmt_state`): the high byte is the role
— `0x02xx` = MN, `0x01xx` = CN. The states to recognise: `0x021D`/`0x011D`
PreOperational1, `0x025D`/`0x015D` PreOperational2, `0x02FD` MsOperational,
`0x01FD` CsOperational. An MN parked at `0x021D` with `cycle_count == 0` means
the isochronous cycle is not running; a CN stuck at `0x0000` while the MN is
Operational means the coupler never joined.

## CLI

```bash
pl ifaces                                        # list interfaces
pl run   --iface eth0 --cdc mnobd.cdc --xap xap.xml
pl read  --iface eth0 --cdc mnobd.cdc --xap xap.xml
pl watch --iface eth0 --cdc mnobd.cdc --xap xap.xml
pl do 0 1 --iface eth0 --cdc mnobd.cdc --xap xap.xml
pl ao 1 --volts 4.5 --iface eth0 --cdc mnobd.cdc --xap xap.xml
```

## Building the native binaries (maintainers)

The bundled binaries are produced from a sibling `openPOWERLINK_V2` source tree:

```bash
# Linux (native on glibc >= 2.34, or in a manylinux_2_34 container; aarch64 via docker buildx/QEMU)
scripts/build_stack.sh   /path/to/openPOWERLINK_V2
scripts/build_wrapper.sh /path/to/openPOWERLINK_V2   # -> _native/linux_<arch>/

# Windows (MSVC + the WinPcap SDK bundled in openPOWERLINK_V2/contrib/pcap)
powershell scripts/build_windows.ps1 -OplkBaseDir C:\path\to\openPOWERLINK_V2

# All platform wheels
python scripts/build_wheels.py
```

`scripts/patch_aarch64.sh` widens the stack's CMake processor check to accept
`aarch64`/`arm64` (upstream only matches x86 and 32-bit `arm*`).

## Releasing (CI)

`.github/workflows/wheels.yml` builds all three platform wheels and publishes
them as GitHub Release assets. The openPOWERLINK C source comes from **your fork**
(`env.OPLK_REPO` = `oe7set/openPOWERLINK_V2`), pinned to the exact **V2.7.2 commit
SHA** in `env.OPLK_REF` — no upstream repo is referenced.

> Note: forking on GitHub does **not** copy tags, so the workflow pins the commit
> SHA (`048650a8…`, upstream tag `V2.7.2`) rather than the tag name. To use a
> different revision, either push that tag to your fork and set `OPLK_REF` to it,
> or update the SHA.

Cut a release:

```bash
# Trigger the build + release (the wheel version is derived from the tag):
git tag v0.1.0
git push origin v0.1.0
```

The tag build produces `openpowerlink-0.1.0-…` wheels and attaches them to the
`v0.1.0` release. `ci.yml` runs the fast host tests on every push/PR.

## License

openPOWERLINK is BSD-2-Clause (some target-specific parts GPLv2); this package's
own code is BSD-2-Clause. See `LICENSE` / `NOTICE`.

# openpowerlink

Talk to B&R POWERLINK peripherals (e.g. an X20 BC0083 bus coupler) **from Python,
in userspace** — with the compiled openPOWERLINK Managing-Node stack **bundled in
the wheel**. Install and run; nothing else to build or configure on the target
(except, on Windows, the Npcap runtime — see below).

```python
from openpowerlink import PowerlinkStack, PowerlinkIO

with PowerlinkStack(iface="eth0", cdc="mnobd.cdc", xap="xap.xml") as stack:
    io = PowerlinkIO(stack)
    io.write_do(0, True)              # set digital output 0
    io.write_ao_volts(1, 4.5)         # set analog output 1 to 4.5 V
    print(io.read_di())               # list[bool]
    print(io.read_ai_volts())         # list[float]
    if not io.status().cn_operational:
        print("controlled node not operational!")
```

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
# pick the line for your platform; replace <owner> and the version
# Linux x86_64
pip install https://github.com/<owner>/openpowerlink-py/releases/download/v0.1.0/openpowerlink-0.1.0-py3-none-manylinux2014_x86_64.whl
# Linux aarch64 (Raspberry Pi 4/5, Jetson, …)
pip install https://github.com/<owner>/openpowerlink-py/releases/download/v0.1.0/openpowerlink-0.1.0-py3-none-manylinux2014_aarch64.whl
# Windows x86_64  (install Npcap first: https://npcap.com)
pip install https://github.com/<owner>/openpowerlink-py/releases/download/v0.1.0/openpowerlink-0.1.0-py3-none-win_amd64.whl
```

Or grab the latest without hardcoding the version (needs the GitHub CLI):

```bash
gh release download --repo <owner>/openpowerlink-py --pattern '*manylinux2014_x86_64.whl'
pip install ./openpowerlink-*.whl
```

Prebuilt wheels are provided for:

| Platform | Ethernet driver | Notes |
|----------|-----------------|-------|
| Linux x86_64 (`manylinux2014`)  | raw `PF_PACKET` socket | no external lib needed |
| Linux aarch64 (`manylinux2014`) | raw `PF_PACKET` socket | Raspberry Pi 4/5, Jetson, … |
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
# Linux (native or in a manylinux2014 container; aarch64 via docker buildx/QEMU)
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
(`env.OPLK_REPO` = `<owner>/openPOWERLINK_V2`, pinned to `env.OPLK_REF` = `V2.7.2`)
— no upstream repo is referenced.

One-time setup, then cut a release:

```bash
# 1) On GitHub, fork OpenAutomationTechnologies/openPOWERLINK_V2 into your account.
# 2) Create a public repo for this package and push it:
git remote add origin https://github.com/<owner>/openpowerlink-py.git
git push -u origin HEAD
# 3) Tag to trigger the build + release (version is derived from the tag):
git tag v0.1.0
git push origin v0.1.0
```

The tag build produces `openpowerlink-0.1.0-…` wheels and attaches them to the
`v0.1.0` release. `ci.yml` runs the fast host tests on every push/PR.

## License

openPOWERLINK is BSD-2-Clause (some target-specific parts GPLv2); this package's
own code is BSD-2-Clause. See `LICENSE` / `NOTICE`.

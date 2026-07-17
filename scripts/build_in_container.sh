#!/usr/bin/env bash
#
# Build oplkmn + oplkwrap for the CURRENT container's architecture and drop the
# binaries into /out. Intended to run inside an ubuntu:22.04 image (x86_64 or,
# via QEMU, aarch64). Expects:
#   /src   = the openPOWERLINK_V2 source tree (read-only ok, copied to /work)
#   /pkg   = the openpowerlink-py repo (for the shim sources + patch scripts)
#   /out   = where to place liboplkmn.so + liboplkwrap.so
#
# Why ubuntu:22.04 and NOT the manylinux_2_34 image: the manylinux image builds
# with Red Hat's gcc-toolset-14 on glibc-2.34 headers, and that toolchain
# MISCOMPILES openPOWERLINK's raw-frame RX / CN-discovery path -- the resulting
# MN reaches MsOperational but the controlled node never joins (0 frames received
# back), proven on real B&R X20 hardware. The SAME fork source built with a stock
# distro GCC (Ubuntu 22.04 GCC 11 / glibc 2.35, or Debian GCC on the target) works
# and brings the CN to CsOperational. Disabling strict aliasing did NOT help, so
# it is the toolchain/glibc-header combo, not an optimization flag. Ubuntu 22.04's
# glibc 2.35 also keeps a low enough floor for modern targets (RHEL9/Debian12/
# Ubuntu22.04+), and its POSIX timers resolve to timer_create@GLIBC_2.34 from libc
# (the original PreOperational1 timer bug is fixed there too).
set -euo pipefail

ARCH="$(uname -m)"
echo ">> Building for ${ARCH} in $(. /etc/os-release 2>/dev/null && echo "$PRETTY_NAME" || echo container)"

# Toolchain: Ubuntu 22.04 ships GCC 11 + CMake 3.22 (>= 3.5 and < 4.0, so it
# accepts the vendored stack's CMP0043 OLD policy without a pin). Install the
# build tools non-interactively.
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq git cmake make gcc g++ patchelf >/dev/null
echo ">> using $(gcc --version | head -1)"
echo ">> using cmake $(cmake --version | head -1)"

WORK=/work
rm -rf "$WORK"; mkdir -p "$WORK"
cp -r /src "$WORK/openPOWERLINK_V2"
OPLK="$WORK/openPOWERLINK_V2"

# aarch64: widen the CMake CPU guard.
if [[ "$ARCH" == "aarch64" || "$ARCH" == "arm64" ]]; then
    bash /pkg/scripts/patch_aarch64.sh "$OPLK"
fi

# 1) stack (shared MN, raw-socket edrv, no pcap). Default distro flags -- see the
#    header note: it is the manylinux toolchain, not any -f flag, that breaks CN
#    discovery, so we build with stock Ubuntu GCC and default Release flags.
mkdir -p "$OPLK/stack/build/linux"; cd "$OPLK/stack/build/linux"
cmake -DCMAKE_POLICY_VERSION_MINIMUM=3.5 -DCMAKE_BUILD_TYPE=Release \
      -DCFG_COMPILE_LIB_MN=ON -DCFG_COMPILE_LIB_CN=OFF \
      -DCFG_COMPILE_SHARED_LIBRARY=ON -DCFG_USE_PCAP_EDRV=OFF ../..
make oplkmn -j"$(nproc)"
LIBDIR="$OPLK/stack/lib/linux/$ARCH"; mkdir -p "$LIBDIR"
find . -name liboplkmn.so -exec cp -v {} "$LIBDIR/" \;

# 2) shim
mkdir -p "$WORK/oplkwrap"; cp /pkg/native/oplkwrap/* "$WORK/oplkwrap/"
cd "$WORK/oplkwrap"; mkdir -p build; cd build
cmake -DCMAKE_BUILD_TYPE=Release -DOPLK_BASE_DIR="$OPLK" -DOPLK_LIB_DIR="$LIBDIR" ..
make -j"$(nproc)"
patchelf --set-rpath '$ORIGIN' liboplkwrap.so || true

# 3) deliver
mkdir -p /out
cp -v liboplkwrap.so /out/
cp -v "$LIBDIR/liboplkmn.so" /out/
echo ">> Done: $(ls /out)"

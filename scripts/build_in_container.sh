#!/usr/bin/env bash
#
# Build oplkmn + oplkwrap for the CURRENT container's architecture and drop the
# binaries into /out. Intended to run inside a manylinux_2_34 image (x86_64 or,
# via QEMU, aarch64). Expects:
#   /src   = the openPOWERLINK_V2 source tree (read-only ok, copied to /work)
#   /pkg   = the openpowerlink-py repo (for the shim sources + patch scripts)
#   /out   = where to place liboplkmn.so + liboplkwrap.so
#
# Why manylinux_2_34 (glibc 2.34) and NOT manylinux2014 (glibc 2.17): on glibc
# 2.17 the POSIX interval-timer functions (timer_create/timer_settime) live in
# librt, and the stack's CMake does not link -lrt, so they end up as UNVERSIONED
# undefined symbols in liboplkmn.so. On a modern target (glibc >= 2.34, where
# librt was folded into libc) those unversioned refs bind to the oldest compat
# symbol, which does not drive SIGEV_SIGNAL timers -- so the high-resolution
# timer never fires and the MN hangs in NMT PreOperational1. Building on glibc
# 2.34 makes them resolve to timer_create@GLIBC_2.34 from libc, which works.
set -euo pipefail

ARCH="$(uname -m)"
echo ">> Building for ${ARCH} in $(cat /etc/system-release 2>/dev/null || echo container)"

# The vendored stack sets CMake policy CMP0043 OLD, which CMake >= 4.0 rejects;
# install a compatible CMake 3.22 and use it regardless of what the image ships.
PYBIN=/opt/python/cp312-cp312/bin
"$PYBIN/pip" install -q "cmake==3.22.6" 2>/dev/null || true
export PATH="$PYBIN:$PATH"
# manylinux_2_34 is AlmaLinux 9 (dnf); fall back to yum for older images.
command -v patchelf >/dev/null || dnf install -y patchelf >/dev/null 2>&1 || \
    yum install -y patchelf >/dev/null 2>&1 || true
echo ">> using cmake $(cmake --version | head -1)"

WORK=/work
rm -rf "$WORK"; mkdir -p "$WORK"
cp -r /src "$WORK/openPOWERLINK_V2"
OPLK="$WORK/openPOWERLINK_V2"

# aarch64: widen the CMake CPU guard.
if [[ "$ARCH" == "aarch64" || "$ARCH" == "arm64" ]]; then
    bash /pkg/scripts/patch_aarch64.sh "$OPLK"
fi

# 1) stack (shared MN, raw-socket edrv, no pcap)
#
# -fno-strict-aliasing is REQUIRED: openPOWERLINK is old C (its CMake still sets
# CMP0043 OLD) that type-puns the raw Ethernet frame buffers heavily. GCC >= 14
# (shipped by the manylinux_2_34 / AlmaLinux 9 image) optimizes strict-aliasing
# aggressively at -O2 and miscompiles the MN's frame RX / CN-discovery path, so
# the built stack reaches MsOperational but never finds the controlled node (0
# frames received back). Proven on real hardware: a GCC-13 build (Ubuntu 24.04)
# brings the CN to CsOperational; the GCC-14 build with default flags does not.
# Disabling strict aliasing restores the GCC-13 behaviour on GCC 14.
mkdir -p "$OPLK/stack/build/linux"; cd "$OPLK/stack/build/linux"
cmake -DCMAKE_POLICY_VERSION_MINIMUM=3.5 -DCMAKE_BUILD_TYPE=Release \
      -DCMAKE_C_FLAGS_RELEASE="-O2 -DNDEBUG -fno-strict-aliasing" \
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

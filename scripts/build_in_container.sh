#!/usr/bin/env bash
#
# Build oplkmn + oplkwrap for the CURRENT container's architecture and drop the
# binaries into /out. Intended to run inside a manylinux2014 image (x86_64 or,
# via QEMU, aarch64). Expects:
#   /src   = the openPOWERLINK_V2 source tree (read-only ok, copied to /work)
#   /pkg   = the openpowerlink-py repo (for the shim sources + patch scripts)
#   /out   = where to place liboplkmn.so + liboplkwrap.so
#
set -euo pipefail

ARCH="$(uname -m)"
echo ">> Building for ${ARCH} in $(cat /etc/system-release 2>/dev/null || echo container)"

# manylinux2014 now ships CMake 4.x, which drops policies the vendored stack
# still sets (e.g. CMP0043 OLD). Install a compatible CMake 3.22 and use it.
PYBIN=/opt/python/cp312-cp312/bin
"$PYBIN/pip" install -q "cmake==3.22.6" 2>/dev/null || true
export PATH="$PYBIN:$PATH"
command -v patchelf >/dev/null || yum install -y patchelf >/dev/null 2>&1 || true
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

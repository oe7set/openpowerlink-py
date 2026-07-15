#!/usr/bin/env bash
#
# Build the openPOWERLINK complete MN library as a SHARED library on Linux, using
# the default raw-socket Edrv (PF_PACKET) -- no libpcap runtime dependency. This
# is the stack half of the self-contained package.
#
# Usage:
#   scripts/build_stack.sh /path/to/openPOWERLINK_V2
#
# Env:
#   CMAKE_BUILD_TYPE   Release (default) | Debug
#
set -euo pipefail

OPLK_BASE_DIR="${1:-${OPLK_BASE_DIR:-}}"
BUILD_TYPE="${CMAKE_BUILD_TYPE:-Release}"

if [[ -z "${OPLK_BASE_DIR}" || ! -f "${OPLK_BASE_DIR}/stack/include/oplk/oplk.h" ]]; then
    echo "error: pass the openPOWERLINK_V2 path as \$1 (or set OPLK_BASE_DIR)." >&2
    exit 1
fi

# Modern CMake rejects the vendored cmake_minimum_required(2.8.7); the policy
# override lets it configure without editing the upstream tree. The aarch64
# processor-regex patch (scripts/aarch64.patch) is applied by the caller/CI when
# building for arm64.
POLICY_ARGS="-DCMAKE_POLICY_VERSION_MINIMUM=3.5"

echo ">> Building liboplkmn (SHARED, ${BUILD_TYPE}) in ${OPLK_BASE_DIR}"
mkdir -p "${OPLK_BASE_DIR}/stack/build/linux"
cd "${OPLK_BASE_DIR}/stack/build/linux"

cmake ${POLICY_ARGS} \
      -DCMAKE_BUILD_TYPE="${BUILD_TYPE}" \
      -DCFG_COMPILE_LIB_MN=ON \
      -DCFG_COMPILE_LIB_CN=OFF \
      -DCFG_COMPILE_SHARED_LIBRARY=ON \
      -DCFG_USE_PCAP_EDRV=OFF \
      ../..
make -j"$(nproc)"
make install

ARCH="$(uname -m)"
echo ">> Done. liboplkmn.so installed under stack/lib/linux/${ARCH}"

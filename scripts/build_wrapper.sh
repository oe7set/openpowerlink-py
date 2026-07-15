#!/usr/bin/env bash
#
# Build the oplkwrap ctypes shim against a freshly built liboplkmn, then bundle
# liboplkmn.so + liboplkwrap.so into src/openpowerlink/_native/<platform>/.
#
# Usage:
#   scripts/build_wrapper.sh /path/to/openPOWERLINK_V2 [platform_tag]
#
# platform_tag defaults to linux_<arch> (e.g. linux_x86_64, linux_aarch64).
#
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OPLK_BASE_DIR="${1:-${OPLK_BASE_DIR:-}}"
ARCH="$(uname -m)"
PLATFORM_TAG="${2:-linux_${ARCH}}"
BUILD_TYPE="${CMAKE_BUILD_TYPE:-Release}"

if [[ -z "${OPLK_BASE_DIR}" || ! -f "${OPLK_BASE_DIR}/stack/include/oplk/oplk.h" ]]; then
    echo "error: pass the openPOWERLINK_V2 path as \$1 (or set OPLK_BASE_DIR)." >&2
    exit 1
fi

OPLK_LIB_DIR="${OPLK_BASE_DIR}/stack/lib/linux/${ARCH}"
if ! ls "${OPLK_LIB_DIR}"/liboplkmn* >/dev/null 2>&1; then
    echo "error: liboplkmn not found in ${OPLK_LIB_DIR}; run build_stack.sh first." >&2
    exit 1
fi

BUILD_DIR="${HERE}/native/oplkwrap/build"
echo ">> Building oplkwrap (${BUILD_TYPE}) against ${OPLK_LIB_DIR}"
mkdir -p "${BUILD_DIR}"
cd "${BUILD_DIR}"
cmake -DCMAKE_BUILD_TYPE="${BUILD_TYPE}" \
      -DOPLK_BASE_DIR="${OPLK_BASE_DIR}" \
      -DOPLK_LIB_DIR="${OPLK_LIB_DIR}" \
      ..
make -j"$(nproc)"

DEST="${HERE}/src/openpowerlink/_native/${PLATFORM_TAG}"
mkdir -p "${DEST}"
cp -v "${BUILD_DIR}/liboplkwrap.so" "${DEST}/"
# Bundle the stack shared lib next to the shim so the loader finds it.
cp -v "${OPLK_LIB_DIR}"/liboplkmn.so* "${DEST}/" 2>/dev/null || \
    cp -v "${OPLK_LIB_DIR}"/liboplkmn* "${DEST}/"

# Set an rpath so liboplkwrap.so finds liboplkmn.so in the same directory.
if command -v patchelf >/dev/null 2>&1; then
    patchelf --set-rpath '$ORIGIN' "${DEST}/liboplkwrap.so" || true
fi

echo ">> Bundled into ${DEST}:"
ls -1 "${DEST}"

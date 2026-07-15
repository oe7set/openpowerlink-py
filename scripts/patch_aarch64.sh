#!/usr/bin/env bash
#
# Widen openPOWERLINK's CMake CPU check to accept aarch64/arm64.
#
# Upstream selects the optimized x86 AMI (amix86.c) for x86, the generic
# little-endian AMI (ami.c) for `arm*`, and FATAL_ERRORs otherwise. 64-bit ARM
# (`aarch64`/`arm64`) matches neither, so it fails to configure. This rewrites
# the `ELSEIF(CMAKE_SYSTEM_PROCESSOR MATCHES arm*)` guard to also match 64-bit
# ARM, routing it to the generic little-endian path (correct for AArch64).
#
# Usage: scripts/patch_aarch64.sh /path/to/openPOWERLINK_V2
#
set -euo pipefail

OPLK_BASE_DIR="${1:-${OPLK_BASE_DIR:-}}"
if [[ -z "${OPLK_BASE_DIR}" ]]; then
    echo "error: pass the openPOWERLINK_V2 path as \$1." >&2
    exit 1
fi

# Every complete-library project shares the same guard.
mapfile -t files < <(grep -rl 'CMAKE_SYSTEM_PROCESSOR MATCHES arm\*' \
    "${OPLK_BASE_DIR}/stack/proj" 2>/dev/null || true)

if [[ ${#files[@]} -eq 0 ]]; then
    echo ">> No files to patch (already patched or layout changed)."
    exit 0
fi

for f in "${files[@]}"; do
    sed -i 's/CMAKE_SYSTEM_PROCESSOR MATCHES arm\*/CMAKE_SYSTEM_PROCESSOR MATCHES "arm*|aarch64|arm64"/' "$f"
    echo ">> patched $f"
done

"""Build one platform-specific wheel per bundled native target.

Each wheel must ship ONLY its own ``_native/<platform>`` subdirectory and carry
the matching platform tag (``manylinux2014_x86_64`` / ``manylinux2014_aarch64`` /
``win_amd64``) so pip installs the correct binaries. This script builds a pure
wheel with ``hatch``/``build`` for each platform whose binaries are present,
temporarily hiding the other platforms' ``_native`` subdirs, then re-tags the
wheel filename.

Prerequisite: the native binaries must already be built into
``src/openpowerlink/_native/<platform>/`` (see scripts/build_stack.sh,
build_in_container.sh, build_windows.ps1).

Usage:
    python scripts/build_wheels.py                # all present platforms
    python scripts/build_wheels.py linux_x86_64   # a specific one
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "src" / "openpowerlink" / "_native"
DIST = ROOT / "dist"

# Map our _native platform dir -> the wheel platform tag.
PLATFORM_TAGS = {
    "linux_x86_64": "manylinux2014_x86_64",
    "linux_aarch64": "manylinux2014_aarch64",
    "linux_armhf": "manylinux2014_armv7l",
    "windows_amd64": "win_amd64",
}


def _shared_files(plat_dir: Path) -> list[Path]:
    return [p for p in plat_dir.iterdir()
            if p.suffix in (".so", ".dll") or ".so." in p.name]


def build_one(platform: str) -> Path:
    plat_dir = NATIVE / platform
    if not plat_dir.is_dir() or not _shared_files(plat_dir):
        raise SystemExit(f"no native binaries in {plat_dir}; build them first")

    tag = PLATFORM_TAGS.get(platform)
    if tag is None:
        raise SystemExit(f"unknown platform '{platform}'")

    # Hide every other platform's binaries so only this one lands in the wheel.
    hidden: list[tuple[Path, Path]] = []
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        for other in NATIVE.iterdir():
            if other.is_dir() and other.name != platform and other.name in PLATFORM_TAGS:
                dest = tmp_path / other.name
                shutil.move(str(other), str(dest))
                hidden.append((dest, other))
        try:
            subprocess.run([sys.executable, "-m", "build", "--wheel",
                            "--outdir", str(DIST), str(ROOT)], check=True)
        finally:
            for dest, original in hidden:
                shutil.move(str(dest), str(original))

    # Re-tag the just-built (py3-none-any) wheel to the platform tag.
    return _retag_latest_wheel(tag)


def _retag_latest_wheel(platform_tag: str) -> Path:
    wheels = sorted(DIST.glob("openpowerlink-*-py3-none-any.whl"),
                    key=lambda p: p.stat().st_mtime)
    if not wheels:
        raise SystemExit("build produced no wheel to re-tag")
    src = wheels[-1]
    # openpowerlink-<ver>-py3-none-any.whl -> ...-py3-none-<platform_tag>.whl
    new_name = src.name.replace("-py3-none-any.whl", f"-py3-none-{platform_tag}.whl")
    dst = src.with_name(new_name)
    shutil.move(str(src), str(dst))
    print(f">> {dst.name}")
    return dst


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    DIST.mkdir(exist_ok=True)
    if argv:
        targets = argv
    else:
        targets = [p.name for p in NATIVE.iterdir()
                   if p.is_dir() and p.name in PLATFORM_TAGS and _shared_files(p)]
    if not targets:
        raise SystemExit("no built native platforms found under src/openpowerlink/_native")
    for platform in targets:
        print(f"== building wheel for {platform} ==")
        build_one(platform)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

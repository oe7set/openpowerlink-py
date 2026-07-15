"""Locate and load the bundled native ``oplkwrap`` shim via ctypes.

Selects the right ``_native/<platform>/`` subdirectory from the running
interpreter's OS/architecture, ensures the sibling ``oplkmn`` library next to it
is resolvable, and returns a loaded :class:`ctypes.CDLL`. All the ugly
platform-specific loader details live here so the rest of the package is clean.
"""

from __future__ import annotations

import ctypes
import os
import platform
import sys
from pathlib import Path

_NATIVE_ROOT = Path(__file__).resolve().parent / "_native"


class NativeLoadError(RuntimeError):
    """Raised when the bundled native stack cannot be located or loaded."""


def platform_tag() -> str:
    """Return the ``_native`` subdirectory name for the current platform."""
    system = platform.system()
    machine = platform.machine().lower()

    if system == "Linux":
        if machine in ("x86_64", "amd64"):
            return "linux_x86_64"
        if machine in ("aarch64", "arm64"):
            return "linux_aarch64"
        if machine.startswith("arm"):
            return "linux_armhf"
        return f"linux_{machine}"
    if system == "Windows":
        if machine in ("amd64", "x86_64"):
            return "windows_amd64"
        return f"windows_{machine}"
    if system == "Darwin":
        return f"macos_{machine}"
    return f"{system.lower()}_{machine}"


def _shim_filename() -> str:
    if sys.platform == "win32":
        return "oplkwrap.dll"
    if sys.platform == "darwin":
        return "liboplkwrap.dylib"
    return "liboplkwrap.so"


def native_dir() -> Path:
    """The directory holding this platform's native binaries."""
    return _NATIVE_ROOT / platform_tag()


def load() -> ctypes.CDLL:
    """Load and return the ``oplkwrap`` shared library for this platform.

    Raises :class:`NativeLoadError` with actionable guidance if the platform is
    unsupported, the bundle is missing, or a dependency (oplkmn / pcap) fails to
    resolve.
    """
    directory = native_dir()
    shim = directory / _shim_filename()
    if not shim.is_file():
        raise NativeLoadError(
            f"No bundled openPOWERLINK binary for this platform "
            f"({platform_tag()}).\nExpected: {shim}\n"
            "This wheel may be for a different OS/architecture, or the native "
            "build has not been run (see scripts/build_stack.sh).")

    # Make the sibling oplkmn library and any bundled runtime DLLs resolvable
    # when the shim is loaded.
    if sys.platform == "win32":
        if hasattr(os, "add_dll_directory"):
            os.add_dll_directory(str(directory))
            # oplkmn.dll depends on Npcap's wpcap.dll / Packet.dll. Npcap keeps
            # them in the System32\Npcap subdirectory (unless installed in
            # "WinPcap compatible mode"), which is not on the default DLL search
            # path. Register it so the stack's pcap edrv can be loaded.
            npcap = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "Npcap"
            if npcap.is_dir():
                os.add_dll_directory(str(npcap))
        os.environ["PATH"] = str(directory) + os.pathsep + os.environ.get("PATH", "")
    else:
        # RTLD_GLOBAL so oplkmn's symbols (and the shim's dependency on it via a
        # relative rpath / same dir) resolve; prepend dir to the loader path.
        ld = "LD_LIBRARY_PATH" if sys.platform != "darwin" else "DYLD_LIBRARY_PATH"
        existing = os.environ.get(ld, "")
        if str(directory) not in existing.split(os.pathsep):
            os.environ[ld] = str(directory) + os.pathsep + existing

    try:
        if sys.platform == "win32":
            return ctypes.CDLL(str(shim))
        return ctypes.CDLL(str(shim), mode=ctypes.RTLD_GLOBAL)
    except OSError as exc:
        hint = ""
        if sys.platform == "win32":
            hint = ("\nOn Windows the userspace stack needs the Npcap runtime "
                    "installed (https://npcap.com). Install it once, then retry.")
        else:
            hint = ("\nEnsure the process may open raw sockets (run as root or "
                    "grant CAP_NET_RAW), and that libc/libpthread are available.")
        raise NativeLoadError(
            f"Failed to load the native stack from {shim}: {exc}{hint}") from exc

# Bundled native binaries

The per-platform openPOWERLINK MN stack + `oplkwrap` shim are placed here by the
build scripts (`scripts/build_*.sh` / `build_wheels.py`):

```
_native/linux_x86_64/   liboplkmn.so   liboplkwrap.so
_native/linux_aarch64/  liboplkmn.so   liboplkwrap.so
_native/windows_amd64/  oplkmn.dll     oplkwrap.dll
```

A platform wheel ships only its own subdirectory. `openpowerlink._loader`
selects the right one at import time from `platform.system()`/`machine()`.

These files are build artifacts; they are produced from the sibling
`openPOWERLINK_V2` source tree and are not edited by hand.

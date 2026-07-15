<#
.SYNOPSIS
    Build oplkmn.dll + oplkwrap.dll on Windows (MSVC) and bundle them into
    src/openpowerlink/_native/windows_amd64/.

.DESCRIPTION
    Builds the complete openPOWERLINK MN stack as a DLL (pcap edrv, linking the
    WinPcap SDK bundled in the openPOWERLINK contrib tree), then the ctypes shim
    against it. Requires Visual Studio 2022 Build Tools + CMake.

    The resulting package needs the Npcap runtime installed on the target
    (https://npcap.com); the SDK here is only for linking.

.PARAMETER OplkBaseDir
    Path to the openPOWERLINK_V2 source tree.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts/build_windows.ps1 `
        -OplkBaseDir D:\Projekte\Rauchkammer\openPOWERLINK_V2
#>
param(
    [Parameter(Mandatory = $true)] [string] $OplkBaseDir,
    [string] $Config = "Release",
    [string] $Generator = "Visual Studio 17 2022",
    # The vendored stack sets CMP0043 OLD, which CMake >= 4.0 rejects. Point this
    # at a CMake 3.x (e.g. `pip install cmake==3.22.6`) when your default is 4.x.
    [string] $CMakeExe = "cmake"
)
$ErrorActionPreference = "Stop"
Set-Alias cmake $CMakeExe -Scope Script

$here = Split-Path -Parent $PSScriptRoot
$arch = "x64"

if (-not (Test-Path "$OplkBaseDir\stack\include\oplk\oplk.h")) {
    throw "openPOWERLINK not found at $OplkBaseDir (missing stack/include/oplk/oplk.h)"
}

# CMAKE_POLICY_VERSION_MINIMUM lets modern CMake accept the vendored
# cmake_minimum_required(2.8.7).
$policy = "-DCMAKE_POLICY_VERSION_MINIMUM=3.5"

Write-Host ">> Building oplkmn.dll ($Config)"
$stackBuild = "$OplkBaseDir\stack\build\windows"
New-Item -ItemType Directory -Force -Path $stackBuild | Out-Null
Push-Location $stackBuild
cmake $policy -G $Generator -A $arch `
    -DCFG_COMPILE_LIB_MN=ON -DCFG_COMPILE_LIB_CN=OFF `
    -DCFG_WINDOWS_DLL=ON ..\..
cmake --build . --config $Config --target oplkmn
Pop-Location

# Locate the produced import lib (search the build tree; we build the target
# without running `install`, so it stays under stack/build/windows/...).
$libFile = Get-ChildItem -Path "$OplkBaseDir\stack" -Recurse -Filter "oplkmn.lib" |
    Select-Object -First 1
if (-not $libFile) { throw "oplkmn.lib not found under $OplkBaseDir\stack after build" }
$libDir = $libFile.DirectoryName
Write-Host ">> found oplkmn import lib in $libDir"

Write-Host ">> Building oplkwrap.dll ($Config) against $libDir"
$wrapBuild = "$here\native\oplkwrap\build_win"
New-Item -ItemType Directory -Force -Path $wrapBuild | Out-Null
Push-Location $wrapBuild
cmake $policy -G $Generator -A $arch `
    -DOPLK_BASE_DIR="$OplkBaseDir" -DOPLK_LIB_DIR="$libDir" ..
cmake --build . --config $Config
Pop-Location

$dest = "$here\src\openpowerlink\_native\windows_amd64"
New-Item -ItemType Directory -Force -Path $dest | Out-Null
Copy-Item "$wrapBuild\$Config\oplkwrap.dll" $dest -Force
Get-ChildItem -Path "$OplkBaseDir\stack" -Recurse -Filter "oplkmn.dll" |
    Select-Object -First 1 | ForEach-Object { Copy-Item $_.FullName $dest -Force }

Write-Host ">> Bundled into $dest :"
Get-ChildItem $dest | Select-Object Name, Length | Format-Table

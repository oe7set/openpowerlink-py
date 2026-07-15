################################################################################
# oplkwrap — thin ctypes ABI shim over the openPOWERLINK MN stack.
#
# Builds a shared library (liboplkwrap.so / oplkwrap.dll) that links the complete
# MN library (oplkmn) built from the sibling openPOWERLINK_V2 tree. Point the
# build at that tree with:
#   -DOPLK_BASE_DIR=/path/to/openPOWERLINK_V2
#   -DOPLK_LIB_DIR=/path/to/openPOWERLINK_V2/stack/lib/<system>/<arch>
################################################################################
cmake_minimum_required(VERSION 3.13)
project(oplkwrap C)

set(CMAKE_C_STANDARD 99)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_VISIBILITY_PRESET hidden)

if(NOT DEFINED OPLK_BASE_DIR)
    message(FATAL_ERROR "Set -DOPLK_BASE_DIR to the openPOWERLINK_V2 source tree")
endif()
if(NOT DEFINED OPLK_LIB_DIR)
    message(FATAL_ERROR "Set -DOPLK_LIB_DIR to the directory containing liboplkmn")
endif()

# Normalise to forward slashes so Windows backslash paths don't produce invalid
# escape sequences when interpolated into source-file lists.
file(TO_CMAKE_PATH "${OPLK_BASE_DIR}" OPLK_BASE_DIR)
file(TO_CMAKE_PATH "${OPLK_LIB_DIR}" OPLK_LIB_DIR)

# The object dictionary to compile in. CiA302-4_MN is the standard MN OD and
# provides the generic (project-independent) obdpi_setupProcessImage().
set(OBJDICT "CiA302-4_MN" CACHE STRING "openPOWERLINK object dictionary")
set(COMMON_SRC ${OPLK_BASE_DIR}/apps/common/src)
set(OBJDICT_DIR ${OPLK_BASE_DIR}/apps/common/objdicts/${OBJDICT})

# openPOWERLINK public + contrib headers, plus the app-common obdcreate/obd
# sources the MN needs (these live under apps/common, not in liboplkmn).
include_directories(
    ${OPLK_BASE_DIR}/stack/include
    ${OPLK_BASE_DIR}/stack/proj
    ${OPLK_BASE_DIR}/contrib
    ${COMMON_SRC}
    ${COMMON_SRC}/obdcreate
    ${OBJDICT_DIR}
)

add_library(oplkwrap SHARED
    oplkwrap.c
    ${COMMON_SRC}/obdcreate/obdcreate.c
    ${OBJDICT_DIR}/obdpi.c
)

# Stack feature configuration for a Managing Node with CFM (CDC download) and
# PDO/SDO, matching the demo_mn_console build. These drive the object dictionary
# (objdict.h) and API compilation.
target_compile_definitions(oplkwrap PRIVATE
    NMT_MAX_NODE_ID=254
    CONFIG_INCLUDE_PDO
    CONFIG_INCLUDE_SDO_ASND
    CONFIG_INCLUDE_CFM
    CONFIG_INCLUDE_NMT_MN
)

# Locate the complete MN library produced by build_stack.
find_library(OPLKMN_LIB NAMES oplkmn liboplkmn PATHS ${OPLK_LIB_DIR} NO_DEFAULT_PATH)
if(NOT OPLKMN_LIB)
    message(FATAL_ERROR "oplkmn library not found in ${OPLK_LIB_DIR}")
endif()

target_link_libraries(oplkwrap ${OPLKMN_LIB})

if(WIN32)
    # openPOWERLINK on Windows uses the pcap edrv (Npcap/WinPcap) + iphlpapi.
    # Link against the WinPcap SDK bundled in the openPOWERLINK contrib tree,
    # by absolute path so it does not depend on link_directories ordering.
    set(WPDPACK ${OPLK_BASE_DIR}/contrib/pcap/windows/WpdPack)
    if(CMAKE_SIZEOF_VOID_P EQUAL 8)
        set(WPCAP_LIBDIR ${WPDPACK}/Lib/x64)
    else()
        set(WPCAP_LIBDIR ${WPDPACK}/Lib)
    endif()
    target_include_directories(oplkwrap PRIVATE ${WPDPACK}/Include)
    target_link_libraries(oplkwrap
        ${WPCAP_LIBDIR}/wpcap.lib
        ${WPCAP_LIBDIR}/Packet.lib
        iphlpapi ws2_32)
else()
    # Linux userspace stack: pthreads + realtime clock; libpcap only if the
    # stack was built with the pcap edrv (default here is the raw-socket edrv).
    target_link_libraries(oplkwrap pthread rt)
endif()

# Put the artifact where the bundler picks it up.
set_target_properties(oplkwrap PROPERTIES
    LIBRARY_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}
    RUNTIME_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR})

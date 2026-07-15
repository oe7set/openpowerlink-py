/**
 * @file    oplkwrap.h
 * @brief   Flat, ctypes-friendly ABI over the openPOWERLINK MN stack.
 *
 * This thin shim links against the complete openPOWERLINK MN library (oplkmn)
 * and exposes a small, stable C ABI that a Python ctypes layer can drive without
 * having to mirror the large tOplkApiInitParam struct or install a C function
 * pointer as the event callback. The stack runs IN-PROCESS (direct link): the
 * shim owns the process image and a fixed, versioned I/O struct (plw_io_t) that
 * mirrors the proven layout of the sibling powerlinkd daemon; Python reads/writes
 * that struct through the accessors below.
 *
 * All entry points return 0 on success or a negative value carrying the
 * openPOWERLINK tOplkError code (negated) on failure, except where noted.
 */

#ifndef OPLKWRAP_H_
#define OPLKWRAP_H_

#include <stdint.h>
#include <stddef.h>

#if defined(_WIN32)
  #define PLW_EXPORT __declspec(dllexport)
#else
  #define PLW_EXPORT __attribute__((visibility("default")))
#endif

#ifdef __cplusplus
extern "C" {
#endif

/* Status flags (plw_status_t.flags). */
#define PLW_FLAG_CN_OPERATIONAL  0x0001u
#define PLW_FLAG_MN_OPERATIONAL  0x0002u
#define PLW_FLAG_STACK_RUNNING   0x0004u

/**
 * @brief Snapshot of stack/network status, filled by plw_status().
 */
typedef struct
{
    uint32_t heartbeat;      /**< ++ every processed POWERLINK cycle */
    uint32_t flags;          /**< PLW_FLAG_* bit field */
    uint16_t mn_nmt_state;   /**< raw MN NMT state code */
    uint16_t cn_nmt_state;   /**< raw CN NMT state code */
    uint64_t cycle_count;    /**< total processed cycles */
} plw_status_t;

/**
 * @brief One enumerated network interface (for plw_enum_ifaces()).
 */
typedef struct
{
    uint8_t mac[6];
    char    name[128];       /**< system name / \Device\NPF_{...} on Windows */
    char    description[256];
} plw_iface_t;

/* ---- lifecycle ------------------------------------------------------------ */

/** Version string of the linked openPOWERLINK stack. */
PLW_EXPORT const char* plw_version(void);

/**
 * Initialise + create the MN stack on interface @p devName.
 * @param nodeId   MN node id (usually 0xF0/240).
 * @param cycleUs  cycle-length hint in us (CDC 0x1006 is authoritative).
 * @param devName  interface name (Linux "eth0"; Windows "\Device\NPF_{GUID}").
 * @param mac      6-byte MAC, or all-zero to use the interface's real MAC.
 */
PLW_EXPORT int plw_init(uint8_t nodeId, uint32_t cycleUs,
                        const char* devName, const uint8_t mac[6]);

/** Load the concise device configuration (mnobd.cdc) from memory. */
PLW_EXPORT int plw_load_cdc(const uint8_t* buf, size_t len);

/** Load the concise device configuration from a file path. */
PLW_EXPORT int plw_load_cdc_file(const char* path);

/**
 * Allocate + link the MN process image.
 *
 * @p inSize / @p outSize come from the project's xap.xml (the ``size`` of the
 * ``type="input"`` / ``type="output"`` ProcessImage). Linking uses the stack's
 * generic ``obdpi_setupProcessImage()`` for the CiA302-4 MN object dictionary,
 * which is project-INDEPENDENT: it links each aggregate PI object (0xA040,
 * 0xA4C0, ...) at offset 0 of its image. openCONFIGURATOR maps the whole image
 * as a contiguous byte array into those aggregate objects, so channel access is
 * done by byte offset (from xap.xml) on the Python side.
 *
 * @param inSize   size of the output image (MN->CN), i.e. PI_IN size.
 * @param outSize  size of the input image (CN->MN), i.e. PI_OUT size.
 */
PLW_EXPORT int plw_alloc_pi(size_t inSize, size_t outSize);

/** Start the NMT state machine (kNmtEventSwReset) -> boots the CN. */
PLW_EXPORT int plw_start(void);

/** Background stack processing; call periodically from the supervisor. */
PLW_EXPORT int plw_process(void);

/** TRUE (1) if the kernel part of the stack is still alive. */
PLW_EXPORT int plw_check_stack(void);

/** Stop the NMT state machine (kNmtEventSwitchOff). */
PLW_EXPORT int plw_stop(void);

/** Destroy + exit the stack, releasing all resources. */
PLW_EXPORT void plw_shutdown(void);

/* ---- I/O ------------------------------------------------------------------ */
/*
 * The process image is exchanged as two raw byte buffers whose channel layout is
 * described by the openCONFIGURATOR xap.xml (parsed in Python). The shim does NOT
 * hardcode a channel map: it exposes the buffer sizes and thread-safe byte-level
 * read/write, so any project's layout works without recompiling. A per-cycle
 * mutex keeps reads/writes consistent against the stack's sync context.
 *
 *   "out" image = oplk_getProcessImageOut() = inputs the MN reads FROM the CN
 *   "in"  image = oplk_getProcessImageIn()  = outputs the MN writes TO   the CN
 */

/** Copy the current status snapshot into @p out. */
PLW_EXPORT void plw_status(plw_status_t* out);

/** Size in bytes of the input (PI_OUT) image; 0 before plw_setup_pi(). */
PLW_EXPORT size_t plw_pi_out_size(void);

/** Size in bytes of the output (PI_IN) image; 0 before plw_setup_pi(). */
PLW_EXPORT size_t plw_pi_in_size(void);

/**
 * Copy @p len bytes of the input image (CN->MN) at @p offset into @p dst.
 * Returns bytes copied (0 on out-of-range). Consistent under the cycle mutex.
 */
PLW_EXPORT size_t plw_read_pi_out(size_t offset, uint8_t* dst, size_t len);

/**
 * Write @p len bytes from @p src into the output image (MN->CN) at @p offset.
 * Returns bytes written (0 on out-of-range). Consistent under the cycle mutex.
 */
PLW_EXPORT size_t plw_write_pi_in(size_t offset, const uint8_t* src, size_t len);

/** Read back @p len bytes of the output image at @p offset (commanded values). */
PLW_EXPORT size_t plw_read_pi_in(size_t offset, uint8_t* dst, size_t len);

/* ---- interfaces ----------------------------------------------------------- */

/**
 * Enumerate network interfaces. On entry *count is the capacity of @p arr; on
 * return it is the number written. Returns 0 on success.
 */
PLW_EXPORT int plw_enum_ifaces(plw_iface_t* arr, size_t* count);

#ifdef __cplusplus
}
#endif

#endif /* OPLKWRAP_H_ */

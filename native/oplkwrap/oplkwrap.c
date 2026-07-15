/**
 * @file    oplkwrap.c
 * @brief   Flat ctypes ABI over the openPOWERLINK MN stack (implementation).
 *
 * Runs the complete MN library (oplkmn, direct link) in-process. The init/CDC/
 * process-image/NMT sequence mirrors the proven sibling daemon
 * (openPowerlink-python/daemon/src/{powerlinkd,app}.c) and the upstream
 * demo_mn_console. The process image is exchanged each cycle from the stack's
 * own sync callback; a mutex guards the raw image buffers so the Python side can
 * read inputs / write outputs consistently between cycles.
 */

#include "oplkwrap.h"

#include <oplk/oplk.h>
#include <obdcreate/obdcreate.h>
#include <obdpi.h>          /* generic CiA302-4 MN process-image linking */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <limits.h>

#if defined(_WIN32)
  #include <windows.h>
  typedef CRITICAL_SECTION plw_mutex_t;
  static void plw_mutex_init(plw_mutex_t* m)    { InitializeCriticalSection(m); }
  static void plw_mutex_lock(plw_mutex_t* m)    { EnterCriticalSection(m); }
  static void plw_mutex_unlock(plw_mutex_t* m)  { LeaveCriticalSection(m); }
  static void plw_mutex_destroy(plw_mutex_t* m) { DeleteCriticalSection(m); }
#else
  #include <pthread.h>
  typedef pthread_mutex_t plw_mutex_t;
  static void plw_mutex_init(plw_mutex_t* m)    { pthread_mutex_init(m, NULL); }
  static void plw_mutex_lock(plw_mutex_t* m)    { pthread_mutex_lock(m); }
  static void plw_mutex_unlock(plw_mutex_t* m)  { pthread_mutex_unlock(m); }
  static void plw_mutex_destroy(plw_mutex_t* m) { pthread_mutex_destroy(m); }
#endif

/* Default identity/timing, taken from the sibling daemon's init params. */
#define PLW_IP_ADDR        0xC0A86401u   /* 192.168.100.1  */
#define PLW_SUBNET_MASK    0xFFFFFF00u   /* 255.255.255.0  */
#define PLW_DEFAULT_GW     0xC0A864FEu   /* 192.168.100.254 */

/* Return a negated tOplkError as the ABI's negative error code. */
#define PLW_ERR(ret)  (-(int)(ret))

//------------------------------------------------------------------------------
// module-local state
//------------------------------------------------------------------------------
static char          devName_l[128];
static void*         pPiIn_l   = NULL;      /* MN -> CN (outputs) */
static void*         pPiOut_l  = NULL;      /* CN -> MN (inputs)  */
static size_t        piInSize_l  = 0;
static size_t        piOutSize_l = 0;
static plw_mutex_t   ioMutex_l;
static int           mutexReady_l = 0;

static volatile plw_status_t status_l;      /* updated from event + sync */

//------------------------------------------------------------------------------
// callbacks
//------------------------------------------------------------------------------
/**
 * Stack event callback. We only latch NMT-state / operational information into
 * status_l so the Python side can poll it (no Python callback into C is needed).
 */
static tOplkError processEvents(tOplkApiEventType eventType,
                                const tOplkApiEventArg* pEventArg,
                                void* pUserArg)
{
    (void)pUserArg;

    switch (eventType)
    {
        case kOplkApiEventNmtStateChange:
            status_l.mn_nmt_state = (uint16_t)pEventArg->nmtStateChange.newNmtState;
            if (pEventArg->nmtStateChange.newNmtState == kNmtMsOperational)
                status_l.flags |= PLW_FLAG_MN_OPERATIONAL;
            else
                status_l.flags &= ~PLW_FLAG_MN_OPERATIONAL;

            if (pEventArg->nmtStateChange.newNmtState == kNmtGsOff)
                status_l.flags &= ~PLW_FLAG_STACK_RUNNING;
            else
                status_l.flags |= PLW_FLAG_STACK_RUNNING;
            break;

        case kOplkApiEventNode:
            /* Track the controlled node reaching OPERATIONAL. The stack reports
             * CN NMT-state transitions via kNmtNodeEventNmtState; there is no
             * dedicated "operational" node event. */
            if (pEventArg->nodeEvent.nodeEvent == kNmtNodeEventNmtState)
            {
                status_l.cn_nmt_state = (uint16_t)pEventArg->nodeEvent.nmtState;
                if (pEventArg->nodeEvent.nmtState == kNmtCsOperational)
                    status_l.flags |= PLW_FLAG_CN_OPERATIONAL;
                else
                    status_l.flags &= ~PLW_FLAG_CN_OPERATIONAL;
            }
            else if (pEventArg->nodeEvent.nodeEvent == kNmtNodeEventError)
            {
                status_l.flags &= ~PLW_FLAG_CN_OPERATIONAL;
            }
            break;

        default:
            break;
    }
    return kErrorOk;
}

/**
 * Synchronous data callback (direct link). Called by the stack once per cycle;
 * exchanges the process image under the I/O mutex. The raw image content is
 * left as-is: Python reads inputs / writes outputs directly into these buffers.
 */
static tOplkError processSync(void)
{
    tOplkError ret;

    ret = oplk_waitSyncEvent(100000);
    if (ret != kErrorOk)
        return ret;

    plw_mutex_lock(&ioMutex_l);

    ret = oplk_exchangeProcessImageOut();   /* fetch CN inputs -> pPiOut_l */
    if (ret == kErrorOk)
        ret = oplk_exchangeProcessImageIn(); /* push pPiIn_l -> CN outputs */

    status_l.heartbeat++;
    status_l.cycle_count++;

    plw_mutex_unlock(&ioMutex_l);
    return ret;
}

//------------------------------------------------------------------------------
// lifecycle
//------------------------------------------------------------------------------
const char* plw_version(void)
{
    return oplk_getVersionString();
}

int plw_init(uint8_t nodeId, uint32_t cycleUs,
             const char* devName, const uint8_t mac[6])
{
    tOplkError        ret;
    tOplkApiInitParam initParam;

    if (!mutexReady_l)
    {
        plw_mutex_init(&ioMutex_l);
        mutexReady_l = 1;
    }
    memset((void*)&status_l, 0, sizeof(status_l));

    strncpy(devName_l, devName ? devName : "", sizeof(devName_l) - 1);
    devName_l[sizeof(devName_l) - 1] = '\0';

    memset(&initParam, 0, sizeof(initParam));
    initParam.sizeOfInitParam = sizeof(initParam);
    initParam.hwParam.pDevName = devName_l;
    initParam.nodeId           = nodeId;
    initParam.ipAddress        = (0xFFFFFF00u & PLW_IP_ADDR) | nodeId;

    if (mac != NULL)
        memcpy(initParam.aMacAddress, mac, 6);
    /* else: all-zero MAC -> Edrv uses the interface's real hardware address */

    initParam.fAsyncOnly           = FALSE;
    initParam.featureFlags         = UINT_MAX;
    initParam.cycleLen             = cycleUs;   /* CDC 0x1006 is authoritative */
    initParam.isochrTxMaxPayload   = 256;
    initParam.isochrRxMaxPayload   = 1490;
    initParam.presMaxLatency       = 50000;
    initParam.preqActPayloadLimit  = 36;
    initParam.presActPayloadLimit  = 36;
    initParam.asndMaxLatency       = 150000;
    initParam.multiplCylceCnt      = 0;
    initParam.asyncMtu             = 1500;
    initParam.prescaler            = 2;
    initParam.lossOfFrameTolerance = 500000;
    initParam.asyncSlotTimeout     = 3000000;
    initParam.waitSocPreq          = 1000;
    initParam.deviceType           = UINT_MAX;
    initParam.vendorId             = UINT_MAX;
    initParam.productCode          = UINT_MAX;
    initParam.revisionNumber       = UINT_MAX;
    initParam.serialNumber         = UINT_MAX;
    initParam.subnetMask           = PLW_SUBNET_MASK;
    initParam.defaultGateway       = PLW_DEFAULT_GW;
    sprintf((char*)initParam.sHostname, "%02x-%08x", nodeId, initParam.vendorId);
    initParam.syncNodeId           = C_ADR_SYNC_ON_SOA;
    initParam.fSyncOnPrcNode       = FALSE;

    initParam.pfnCbEvent = processEvents;
    initParam.pfnCbSync  = processSync;

    ret = obdcreate_initObd(&initParam.obdInitParam);
    if (ret != kErrorOk)
        return PLW_ERR(ret);

    ret = oplk_initialize();
    if (ret != kErrorOk)
        return PLW_ERR(ret);

    ret = oplk_create(&initParam);
    if (ret != kErrorOk)
        return PLW_ERR(ret);

    return 0;
}

int plw_load_cdc(const uint8_t* buf, size_t len)
{
    tOplkError ret = oplk_setCdcBuffer((void*)buf, len);
    return (ret == kErrorOk) ? 0 : PLW_ERR(ret);
}

int plw_load_cdc_file(const char* path)
{
    tOplkError ret = oplk_setCdcFilename(path);
    return (ret == kErrorOk) ? 0 : PLW_ERR(ret);
}

int plw_alloc_pi(size_t inSize, size_t outSize)
{
    tOplkError ret;
    UINT       errorIndex;

    ret = oplk_allocProcessImage(inSize, outSize);
    if (ret != kErrorOk)
        return PLW_ERR(ret);

    pPiIn_l  = oplk_getProcessImageIn();
    pPiOut_l = oplk_getProcessImageOut();
    if (pPiIn_l == NULL || pPiOut_l == NULL)
        return PLW_ERR(kErrorApiPINotAllocated);

    /* Generic CiA302-4 MN linking: aggregate PI objects (0xA040, 0xA4C0, ...)
     * are linked at offset 0 of their image, independent of the project. The
     * openCONFIGURATOR CDC maps the payload as a contiguous byte array into these
     * objects, so we (and Python) address channels by byte offset. */
    errorIndex = obdpi_setupProcessImage();
    if (errorIndex != 0)
        return PLW_ERR(kErrorApiPINotAllocated);

    piInSize_l  = inSize;
    piOutSize_l = outSize;
    return 0;
}

int plw_start(void)
{
    tOplkError ret = oplk_execNmtCommand(kNmtEventSwReset);
    return (ret == kErrorOk) ? 0 : PLW_ERR(ret);
}

int plw_process(void)
{
    tOplkError ret = oplk_process();
    return (ret == kErrorOk) ? 0 : PLW_ERR(ret);
}

int plw_check_stack(void)
{
    return (oplk_checkKernelStack() != FALSE) ? 1 : 0;
}

int plw_stop(void)
{
    tOplkError ret = oplk_execNmtCommand(kNmtEventSwitchOff);
    return (ret == kErrorOk) ? 0 : PLW_ERR(ret);
}

void plw_shutdown(void)
{
    oplk_freeProcessImage();
    oplk_destroy();
    oplk_exit();
    pPiIn_l = pPiOut_l = NULL;
    piInSize_l = piOutSize_l = 0;
    if (mutexReady_l)
    {
        plw_mutex_destroy(&ioMutex_l);
        mutexReady_l = 0;
    }
}

//------------------------------------------------------------------------------
// I/O
//------------------------------------------------------------------------------
void plw_status(plw_status_t* out)
{
    if (out == NULL)
        return;
    /* status_l fields are small scalars updated in the sync/event context; a
     * struct copy is good enough for polling. */
    *out = *(plw_status_t*)&status_l;
}

size_t plw_pi_out_size(void) { return piOutSize_l; }
size_t plw_pi_in_size(void)  { return piInSize_l; }

size_t plw_read_pi_out(size_t offset, uint8_t* dst, size_t len)
{
    if (pPiOut_l == NULL || dst == NULL || offset + len > piOutSize_l)
        return 0;
    plw_mutex_lock(&ioMutex_l);
    memcpy(dst, (const uint8_t*)pPiOut_l + offset, len);
    plw_mutex_unlock(&ioMutex_l);
    return len;
}

size_t plw_write_pi_in(size_t offset, const uint8_t* src, size_t len)
{
    if (pPiIn_l == NULL || src == NULL || offset + len > piInSize_l)
        return 0;
    plw_mutex_lock(&ioMutex_l);
    memcpy((uint8_t*)pPiIn_l + offset, src, len);
    plw_mutex_unlock(&ioMutex_l);
    return len;
}

size_t plw_read_pi_in(size_t offset, uint8_t* dst, size_t len)
{
    if (pPiIn_l == NULL || dst == NULL || offset + len > piInSize_l)
        return 0;
    plw_mutex_lock(&ioMutex_l);
    memcpy(dst, (const uint8_t*)pPiIn_l + offset, len);
    plw_mutex_unlock(&ioMutex_l);
    return len;
}

//------------------------------------------------------------------------------
// interfaces
//------------------------------------------------------------------------------
int plw_enum_ifaces(plw_iface_t* arr, size_t* count)
{
    tOplkError ret;
    size_t     cap;
    tNetIfId*  pList;
    size_t     n;
    size_t     i;

    if (arr == NULL || count == NULL || *count == 0)
        return PLW_ERR(kErrorApiInvalidParam);

    cap = *count;
    pList = (tNetIfId*)calloc(cap, sizeof(tNetIfId));
    if (pList == NULL)
        return PLW_ERR(kErrorNoResource);

    n = cap;
    ret = oplk_enumerateNetworkInterfaces(pList, &n);
    if (ret != kErrorOk)
    {
        free(pList);
        return PLW_ERR(ret);
    }

    if (n > cap)
        n = cap;
    for (i = 0; i < n; i++)
    {
        memcpy(arr[i].mac, pList[i].aMacAddress, 6);
        strncpy(arr[i].name, pList[i].aDeviceName, sizeof(arr[i].name) - 1);
        arr[i].name[sizeof(arr[i].name) - 1] = '\0';
        strncpy(arr[i].description, pList[i].aDeviceDescription,
                sizeof(arr[i].description) - 1);
        arr[i].description[sizeof(arr[i].description) - 1] = '\0';
    }
    *count = n;
    free(pList);
    return 0;
}

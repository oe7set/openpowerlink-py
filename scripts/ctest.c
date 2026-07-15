/*
 * Pure-C smoke test for the bundled openPOWERLINK MN stack (no Python involved).
 *
 * It replicates exactly what PowerlinkStack.start() does through the oplkwrap
 * shim -- init, load CDC, allocate the 32/32 process image, start NMT, then poll
 * plw_process() -- and prints the MN NMT state + heartbeat every 500 ms. If the
 * MN leaves PreOperational1 and the heartbeat advances here but not under
 * Python, the fault is the Python embedding; if it stalls here too, the fault is
 * in the stack / edrv / physical link.
 *
 * Build on the target:
 *   gcc scripts/ctest.c -o /tmp/ctest -ldl
 * Run:
 *   /tmp/ctest <libdir> <iface> <cdcfile>
 */
#include <dlfcn.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <time.h>

typedef struct {
    uint32_t heartbeat;
    uint32_t flags;
    uint16_t mn_nmt_state;
    uint16_t cn_nmt_state;
    uint64_t cycle_count;
} plw_status_t;

int main(int argc, char** argv)
{
    const char* libdir = argc > 1 ? argv[1] : ".";
    const char* iface  = argc > 2 ? argv[2] : "enp0s31f6";
    const char* cdc    = argc > 3 ? argv[3] : "mnobd.cdc";

    char wrap[512], mn[512];
    snprintf(wrap, sizeof(wrap), "%s/liboplkwrap.so", libdir);
    snprintf(mn,   sizeof(mn),   "%s/liboplkmn.so",  libdir);

    /* Load the MN core first (global) so the shim resolves against it. */
    if (!dlopen(mn, RTLD_NOW | RTLD_GLOBAL))
        fprintf(stderr, "warn: dlopen mn: %s\n", dlerror());
    void* h = dlopen(wrap, RTLD_NOW | RTLD_GLOBAL);
    if (!h) { fprintf(stderr, "dlopen wrap: %s\n", dlerror()); return 99; }

    const char* (*plw_version)(void)                                 = dlsym(h, "plw_version");
    int  (*plw_init)(uint8_t, uint32_t, const char*, const uint8_t*) = dlsym(h, "plw_init");
    int  (*plw_load_cdc_file)(const char*)                           = dlsym(h, "plw_load_cdc_file");
    int  (*plw_alloc_pi)(size_t, size_t)                             = dlsym(h, "plw_alloc_pi");
    int  (*plw_start)(void)                                          = dlsym(h, "plw_start");
    int  (*plw_process)(void)                                        = dlsym(h, "plw_process");
    int  (*plw_check_stack)(void)                                    = dlsym(h, "plw_check_stack");
    void (*plw_status)(plw_status_t*)                                = dlsym(h, "plw_status");
    int  (*plw_stop)(void)                                           = dlsym(h, "plw_stop");
    void (*plw_shutdown)(void)                                       = dlsym(h, "plw_shutdown");

    printf("stack version: %s\n", plw_version ? plw_version() : "?");

    uint8_t mac[6] = {0};
    int rc = plw_init(0xF0, 5000, iface, mac);
    printf("plw_init rc=%d\n", rc);
    if (rc) return 1;

    rc = plw_load_cdc_file(cdc);
    printf("plw_load_cdc_file(%s) rc=%d\n", cdc, rc);
    if (rc) return 2;

    rc = plw_alloc_pi(32, 32);
    printf("plw_alloc_pi rc=%d\n", rc);
    if (rc) return 3;

    rc = plw_start();
    printf("plw_start rc=%d\n", rc);
    if (rc) return 4;

    plw_status_t st;
    struct timespec ts = {0, 50 * 1000 * 1000};   /* 50 ms */
    for (int i = 0; i < 200; i++) {                /* ~10 s */
        plw_process();
        if (i % 10 == 0) {                         /* every ~500 ms */
            plw_status(&st);
            printf("t=%4dms  MN=0x%04X CN=0x%04X hb=%u cyc=%llu alive=%d\n",
                   i * 50, st.mn_nmt_state, st.cn_nmt_state,
                   st.heartbeat, (unsigned long long)st.cycle_count,
                   plw_check_stack ? plw_check_stack() : -1);
            fflush(stdout);
        }
        nanosleep(&ts, NULL);
    }

    plw_stop();
    plw_shutdown();
    return 0;
}

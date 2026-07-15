/*
 * ctest3 -- like ctest, but mimics the demo_mn_console direct-link main loop
 * EXACTLY: it never calls oplk_process(). In direct-link mode the demo only
 * sleeps and checks the kernel stack; all processing is done by the stack's own
 * threads. This isolates whether the shim/supervisor calling oplk_process() is
 * what stalls the MN boot.
 *
 * Build: gcc ctest3.c -o ctest3 -ldl
 * Run:   ctest3 <libdir> <iface> <cdcfile> [pin] [pout]
 */
#include <dlfcn.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <time.h>

typedef struct { uint32_t hb; uint32_t flags; uint16_t mn; uint16_t cn; uint64_t cyc; } st_t;

int main(int c, char** v)
{
    const char* libdir = v[1];
    const char* iface  = v[2];
    const char* cdc    = v[3];
    int pin  = c > 4 ? atoi(v[4]) : 32;
    int pout = c > 5 ? atoi(v[5]) : 32;

    char wp[512], mp[512];
    snprintf(wp, sizeof wp, "%s/liboplkwrap.so", libdir);
    snprintf(mp, sizeof mp, "%s/liboplkmn.so", libdir);
    dlopen(mp, RTLD_NOW | RTLD_GLOBAL);
    void* h = dlopen(wp, RTLD_NOW | RTLD_GLOBAL);
    if (!h) { fprintf(stderr, "dlopen: %s\n", dlerror()); return 99; }

    const char* (*ver)(void)                                    = dlsym(h, "plw_version");
    int (*init)(uint8_t, uint32_t, const char*, const uint8_t*) = dlsym(h, "plw_init");
    int (*lcdc)(const char*)                                    = dlsym(h, "plw_load_cdc_file");
    int (*alloc)(size_t, size_t)                                = dlsym(h, "plw_alloc_pi");
    int (*start)(void)                                          = dlsym(h, "plw_start");
    int (*chk)(void)                                            = dlsym(h, "plw_check_stack");
    void (*stat)(st_t*)                                         = dlsym(h, "plw_status");
    void (*sd)(void)                                            = dlsym(h, "plw_shutdown");

    printf("ver %s\n", ver());
    uint8_t mac[6] = {0};
    printf("init %d\n", init(0xF0, 5000, iface, mac));
    printf("cdc %d\n", lcdc(cdc));
    printf("alloc %d\n", alloc(pin, pout));
    printf("start %d\n", start());

    st_t s;
    struct timespec ts = {0, 100 * 1000 * 1000};   /* 100 ms, like demo msleep(100) */
    for (int i = 0; i < 150; i++) {
        /* NO oplk_process() -- exactly like the demo direct-link loop */
        if (chk() == 0) { printf("kernel stack gone!\n"); break; }
        if (i % 5 == 0) {
            stat(&s);
            printf("t=%5dms MN=0x%04X CN=0x%04X hb=%u cyc=%llu\n",
                   i * 100, s.mn, s.cn, s.hb, (unsigned long long)s.cyc);
            fflush(stdout);
        }
        nanosleep(&ts, NULL);
    }
    sd();
    return 0;
}

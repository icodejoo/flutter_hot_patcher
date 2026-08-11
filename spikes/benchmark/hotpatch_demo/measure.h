#pragma once
#include <stdint.h>
#include <sys/resource.h>
#include <mach/mach.h>
#include <sys/time.h>

static inline int64_t measure_rss_kb(void) {
    struct mach_task_basic_info info;
    mach_msg_type_number_t count = MACH_TASK_BASIC_INFO_COUNT;
    kern_return_t kr = task_info(mach_task_self(), MACH_TASK_BASIC_INFO,
                                  (task_info_t)&info, &count);
    if (kr != KERN_SUCCESS) return 0;
    return (int64_t)(info.resident_size / 1024);
}

static inline double measure_cpu_sample_pct(void) {
    struct rusage r0, r1;
    struct timeval t0, t1;
    getrusage(RUSAGE_SELF, &r0);
    gettimeofday(&t0, NULL);
    usleep(100000);
    getrusage(RUSAGE_SELF, &r1);
    gettimeofday(&t1, NULL);
    double cpu_us = (r1.ru_utime.tv_sec  - r0.ru_utime.tv_sec)  * 1e6 +
                    (r1.ru_utime.tv_usec - r0.ru_utime.tv_usec) +
                    (r1.ru_stime.tv_sec  - r0.ru_stime.tv_sec)  * 1e6 +
                    (r1.ru_stime.tv_usec - r0.ru_stime.tv_usec);
    double wall_us = (t1.tv_sec - t0.tv_sec) * 1e6 + (t1.tv_usec - t0.tv_usec);
    return wall_us > 0 ? cpu_us / wall_us * 100.0 : 0.0;
}

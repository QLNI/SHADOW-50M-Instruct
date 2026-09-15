/* f16shim.h — software stand-ins for the two F16C intrinsics the kernel uses, for targets without F16C (WebAssembly).
   Same results, just not a single instruction: the hot K/V is stored half-precision and widened on load, so the browser
   build keeps the same 16-bit hot window and the same memory footprint as the native one. */
#ifndef SHADOW_F16_SHIM_H
#define SHADOW_F16_SHIM_H
#include <immintrin.h>
#include <stdint.h>
#include <string.h>

static inline float shadow_h2f(uint16_t x) {
    uint32_t s = (uint32_t)(x & 0x8000u) << 16, e = (x >> 10) & 0x1f, m = x & 0x3ff, r;
    if (e == 0) {
        if (m == 0) r = s;
        else { e = 127 - 15 + 1; while (!(m & 0x400)) { m <<= 1; e--; } m &= 0x3ff; r = s | (e << 23) | (m << 13); }
    } else if (e == 31) r = s | 0x7f800000u | (m << 13);
    else r = s | ((e + 127 - 15) << 23) | (m << 13);
    float f; memcpy(&f, &r, 4); return f;
}

static inline uint16_t shadow_f2h(float f) {
    uint32_t x; memcpy(&x, &f, 4);
    uint32_t s = (x >> 16) & 0x8000u; int32_t e = (int32_t)((x >> 23) & 0xff) - 127 + 15; uint32_t m = x & 0x7fffff;
    if (e <= 0) {                                     /* subnormal or zero */
        if (e < -10) return (uint16_t)s;
        m |= 0x800000; uint32_t sh = (uint32_t)(14 - e);
        uint32_t h = (m + (1u << (sh - 1))) >> sh;
        return (uint16_t)(s | h);
    }
    if (e >= 31) return (uint16_t)(s | 0x7c00u);      /* overflow to infinity */
    uint32_t h = (uint32_t)e << 10 | (m >> 13);
    if (m & 0x1000) h++;                               /* round to nearest */
    return (uint16_t)(s | h);
}

#define _mm256_cvtph_ps(v)     shadow_cvtph_ps(v)
#define _mm256_cvtps_ph(v, r)  shadow_cvtps_ph(v)

static inline __m256 shadow_cvtph_ps(__m128i h) {
    uint16_t t[8]; memcpy(t, &h, 16);
    float f[8];
    for (int i = 0; i < 8; i++) f[i] = shadow_h2f(t[i]);
    __m256 o; memcpy(&o, f, 32); return o;
}

static inline __m128i shadow_cvtps_ph(__m256 v) {
    float f[8]; memcpy(f, &v, 32);
    uint16_t t[8];
    for (int i = 0; i < 8; i++) t[i] = shadow_f2h(f[i]);
    __m128i o; memcpy(&o, t, 16); return o;
}

#endif

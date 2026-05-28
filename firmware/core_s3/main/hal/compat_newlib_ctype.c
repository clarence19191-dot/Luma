/*
 * ESP-SR prebuilt libraries still reference newlib's historical _ctype_
 * table. ESP-IDF 6 defaults to Picolibc, so provide the ASCII-compatible
 * table expected by that library without switching the whole project libc.
 */

#define LUMA_CTYPE_U 01
#define LUMA_CTYPE_L 02
#define LUMA_CTYPE_N 04
#define LUMA_CTYPE_S 010
#define LUMA_CTYPE_P 020
#define LUMA_CTYPE_C 040
#define LUMA_CTYPE_X 0100
#define LUMA_CTYPE_B 0200

const char _ctype_[257] = {
    [1 ... 9]     = LUMA_CTYPE_C,
    [10 ... 14]   = LUMA_CTYPE_C | LUMA_CTYPE_S,
    [15 ... 32]   = LUMA_CTYPE_C,
    [33]          = LUMA_CTYPE_S | LUMA_CTYPE_B,
    [34 ... 48]   = LUMA_CTYPE_P,
    [49 ... 58]   = LUMA_CTYPE_N | LUMA_CTYPE_X,
    [59 ... 65]   = LUMA_CTYPE_P,
    [66 ... 71]   = LUMA_CTYPE_U | LUMA_CTYPE_X,
    [72 ... 91]   = LUMA_CTYPE_U,
    [92 ... 97]   = LUMA_CTYPE_P,
    [98 ... 103]  = LUMA_CTYPE_L | LUMA_CTYPE_X,
    [104 ... 123] = LUMA_CTYPE_L,
    [124 ... 127] = LUMA_CTYPE_P,
    [128]         = LUMA_CTYPE_C,
};

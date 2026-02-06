// VoxtralBridge.h — Bridging header for Swift ↔ voxtral.c interop
//
// Strategy: We try to include voxtral.h directly. If that causes issues
// with Swift's Clang importer (unlikely but possible), switch to the
// forward-declaration fallback by uncommenting the block below and
// commenting out the #include.

#ifndef VOXTRAL_BRIDGE_H
#define VOXTRAL_BRIDGE_H

// ---- Primary approach: use voxtral.h directly ----
// (Requires -I pointing to voxtral.c source dir during compilation)
#include "voxtral.h"

// Metal acceleration lifecycle (available when voxtral_metal.m is linked)
int vox_metal_init(void);
int vox_metal_available(void);
void vox_metal_shutdown(void);

// ---- Fallback: forward declarations only ----
// Uncomment this block and comment out the #include above if voxtral.h
// causes compilation issues with Swift.
/*
#include <stdio.h>

typedef struct vox_ctx vox_ctx_t;
typedef struct vox_stream vox_stream_t;

vox_ctx_t *vox_load(const char *model_dir);
void vox_free(vox_ctx_t *ctx);

vox_stream_t *vox_stream_init(vox_ctx_t *ctx);
void vox_stream_feed(vox_stream_t *s, float *samples, int n_samples);
void vox_stream_finish(vox_stream_t *s);
int vox_stream_get(vox_stream_t *s, const char **tokens, int max);
void vox_stream_free(vox_stream_t *s);
void vox_set_processing_interval(vox_stream_t *s, float seconds);

float *vox_load_wav(const char *path, int *n_samples);
char *vox_transcribe(vox_ctx_t *ctx, const char *path);
*/

#endif // VOXTRAL_BRIDGE_H

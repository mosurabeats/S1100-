#!/bin/sh
# Build the S1100FX MAME test machine (emu/bin/s1100fx).
#
# Fetches MAME at a pinned release, adds emu/mame/s1100fx.ipp to MAME's
# Akai S1000/S1100 driver, and builds only that driver (SOURCES=), which
# takes roughly 20-40 minutes on 4 cores the first time.
#
#   emu/mame/build.sh            # clone into build/mame and build
#   MAME_DIR=~/mame emu/mame/build.sh
set -eu

MAME_TAG=mame0289
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
MAME_DIR=${MAME_DIR:-$ROOT/build/mame}
JOBS=${JOBS:-$(nproc)}
DRIVER=src/mame/akai/s1000.cpp

if [ ! -d "$MAME_DIR/.git" ]; then
    git clone --depth 1 --branch "$MAME_TAG" https://github.com/mamedev/mame.git "$MAME_DIR"
fi
cd "$MAME_DIR"
have=$(git describe --tags 2>/dev/null || echo unknown)
[ "$have" = "$MAME_TAG" ] || echo "warning: MAME checkout is $have, expected $MAME_TAG" >&2

cp "$ROOT/emu/mame/s1100fx.ipp" src/mame/akai/s1100fx.ipp
if ! grep -q '#include "imagedev/snapquik.h"' "$DRIVER"; then
    # quickload device: included at file scope so MAME's SOURCES= dependency
    # scan links it in
    sed -i 's|^#include "imagedev/floppy.h"|#include "imagedev/floppy.h"\n#include "imagedev/snapquik.h"|' "$DRIVER"
fi
if ! grep -q 's1100fx.ipp' "$DRIVER"; then
    # include our machine inside the driver's anonymous namespace ...
    sed -i 's|^} // anonymous namespace|#include "s1100fx.ipp"\n\n} // anonymous namespace|' "$DRIVER"
    # ... and register it
    printf '%s\n' 'SYST( 1990, s1100fx, 0, 0, s1100fx, s1000, s1100fx_state, empty_init, "S1100FX", "Akai S1100 (ROM-less S1100FX test machine)", MACHINE_NOT_WORKING | MACHINE_NO_SOUND )' >> "$DRIVER"
fi
# MAME builds its driver list from the master index
if ! grep -qx 's1100fx' src/mame/mame.lst; then
    sed -i '/^@source:akai\/s1000.cpp$/,/^$/ s/^s1100$/s1100\ns1100fx/' src/mame/mame.lst
fi
grep -q '#include "s1100fx.ipp"' "$DRIVER" && grep -q '#include "imagedev/snapquik.h"' "$DRIVER" &&
    grep -qx 's1100fx' src/mame/mame.lst || { echo "failed to patch MAME sources" >&2; exit 1; }

make SUBTARGET=s1100fx SOURCES="$DRIVER" REGENIE=1 TOOLS=0 NOWERROR=1 OPTIMIZE=2 SYMBOLS=0 \
     NO_USE_PORTAUDIO=1 NO_USE_PIPEWIRE=1 USE_QTDEBUG=0 -j"$JOBS"

mkdir -p "$ROOT/emu/bin"
cp s1100fx "$ROOT/emu/bin/s1100fx"
echo "built $ROOT/emu/bin/s1100fx"

#!/usr/bin/env bash
set -Eeuo pipefail

GAME_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
GAME_EXE="$GAME_DIR/FA.EXE"
JOYSTICK_DLL="$GAME_DIR/FAJoystick.dll"
JOYSTICK_SOURCE="$GAME_DIR/joystick/FAJoystick.c"
WINEPREFIX="$GAME_DIR/.wine-prefix"

fail() {
    printf 'Error: %s\n' "$*" >&2
    exit 1
}

for command_name in wine wineboot python3; do
    if ! command -v "$command_name" >/dev/null 2>&1; then
        fail "Required command '$command_name' was not found. Install it and try again."
    fi
done

if [[ ! -f "$GAME_EXE" ]]; then
    fail "FA.EXE was not found in $GAME_DIR."
fi

if [[ ! -f "$GAME_DIR/FA.SMS" ]]; then
    fail "Required game data file 'FA.SMS' is missing from $GAME_DIR. The executable may report a misleading 'Not enough memory' error without it."
fi

if [[ ! -f "$JOYSTICK_DLL" || "$JOYSTICK_SOURCE" -nt "$JOYSTICK_DLL" ]]; then
    printf 'Building the per-game joystick adapter...\n'
    "$GAME_DIR/build-joystick-adapter.sh"
fi

for dependency in WAIL32.DLL CDRVDL32.DLL CDRVHF32.DLL msapi.dll; do
    if [[ ! -f "$GAME_DIR/$dependency" ]]; then
        fail "Required game dependency '$dependency' is missing from $GAME_DIR."
    fi
done

printf 'Applying Wine, focus-loss and HD (720p/1080p) patches to FA.EXE...\n'
python3 "$GAME_DIR/patch-fa.py" "$GAME_EXE"

export WINEPREFIX
printf 'Using Wine prefix: %s\n' "$WINEPREFIX"
if [[ ! -f "$WINEPREFIX/system.reg" ]]; then
    printf 'Creating the local Wine prefix...\n'
else
    printf 'Updating the local Wine prefix...\n'
fi
wineboot -u

if ! wine cmd /c ver >/dev/null; then
    fail "Wine could not run a Windows command in the local prefix. Check your Wine installation."
fi

printf 'Starting Fighters Anthology...\n'
cd "$GAME_DIR"
exec wine "$GAME_EXE"

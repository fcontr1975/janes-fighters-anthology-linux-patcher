#!/usr/bin/env bash
set -Eeuo pipefail

GAME_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
COMPILER=i686-w64-mingw32-gcc
SOURCE="$GAME_DIR/joystick/FAJoystick.c"
OUTPUT="$GAME_DIR/FAJoystick.dll"

if ! command -v "$COMPILER" >/dev/null 2>&1; then
    printf 'Error: %s is required to build the joystick adapter.\n' "$COMPILER" >&2
    printf 'Install the 32-bit MinGW-w64 C compiler and retry.\n' >&2
    exit 1
fi

TEMP_DLL="$(mktemp "$GAME_DIR/.FAJoystick.XXXXXX")"
trap 'rm -f -- "$TEMP_DLL"' EXIT
"$COMPILER" -shared -O2 -Wall -Wextra -Werror -o "$TEMP_DLL" "$SOURCE"
mv -f -- "$TEMP_DLL" "$OUTPUT"
trap - EXIT
printf 'Built %s\n' "$OUTPUT"

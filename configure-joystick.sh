#!/usr/bin/env bash
set -Eeuo pipefail

GAME_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"

for command_name in wine python3; do
    if ! command -v "$command_name" >/dev/null 2>&1; then
        printf 'Error: Required command %q was not found. Install it and try again.\n' \
            "$command_name" >&2
        exit 1
    fi
done

export WINEPREFIX="$GAME_DIR/.wine-prefix"
printf 'Opening Wine joystick properties. Use its test page to identify axes and buttons.\n'
printf 'The game-only mappings are applied by FAJoystick.dll, not by joy.cpl itself.\n'
wine control joy.cpl

exec python3 "$GAME_DIR/configure-joystick.py"

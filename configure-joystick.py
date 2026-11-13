#!/usr/bin/env python3
"""Configure FA's per-game WinMM joystick axis and button mappings."""

from __future__ import annotations

import configparser
from pathlib import Path

GAME_DIR = Path(__file__).resolve().parent
CONFIG_PATH = GAME_DIR / "FA-JOYSTICK.INI"
AXES = ("X", "Y", "Z", "R", "U", "V")
DEFAULT_AXIS_MAP = ("X", "Y", "R", "Z", "U", "V")
DEFAULT_BUTTON_MAP = tuple(range(1, 9))


def normalize_axis(value: str) -> str:
    axis = value.strip().upper()
    if axis == "RX":
        axis = "R"
    if axis not in AXES:
        raise ValueError(f"Unknown axis {value!r}; use X, Y, Z, R/Rx, U, or V.")
    return axis


def parse_axis_map(value: str) -> tuple[str, ...]:
    axes = tuple(normalize_axis(item) for item in value.split(","))
    if len(axes) != len(AXES):
        raise ValueError("AxisMap must contain exactly six comma-separated axes.")
    return axes


def parse_axis_list(value: str) -> tuple[str, ...]:
    if not value.strip():
        return ()
    axes = tuple(normalize_axis(item) for item in value.split(","))
    if len(set(axes)) != len(axes):
        raise ValueError("An axis may only appear once in InvertAxes.")
    return axes


def parse_button_map(value: str) -> tuple[int, ...]:
    if not value.strip():
        return ()
    try:
        buttons = tuple(int(item.strip()) for item in value.split(","))
    except ValueError as error:
        raise ValueError("ButtonMap entries must be integers from 0 to 32.") from error
    if len(buttons) > 32 or any(button < 0 or button > 32 for button in buttons):
        raise ValueError("ButtonMap accepts at most 32 entries, each from 0 to 32.")
    return buttons


def read_settings() -> tuple[tuple[str, ...], tuple[str, ...], tuple[int, ...]]:
    parser = configparser.ConfigParser(interpolation=None)
    if CONFIG_PATH.exists():
        with CONFIG_PATH.open(encoding="ascii") as config_file:
            parser.read_file(config_file)
    axis_map = parse_axis_map(parser.get(
        "Mapping", "AxisMap", fallback=",".join(DEFAULT_AXIS_MAP)))
    inverted = parse_axis_list(parser.get("Mapping", "InvertAxes", fallback=""))
    buttons = parse_button_map(parser.get("Mapping", "ButtonMap", fallback=""))
    return axis_map, inverted, buttons


def prompt_axis_map(current: tuple[str, ...]) -> tuple[str, ...]:
    print("\nAxisMap order is logical X,Y,Z,R,U,V; R is shown as Rx in joy.cpl.")
    print("Current mapping: " + ",".join(current))
    print("Enter six source axes in that order, or 'identity' to reset.")
    answer = input("AxisMap [keep current]: ").strip()
    if not answer:
        return current
    if answer.lower() == "identity":
        return AXES
    return parse_axis_map(answer)


def prompt_inverted_axes(current: tuple[str, ...]) -> tuple[str, ...]:
    shown = ",".join(current) if current else "none"
    print("\nCurrent inverted axes: " + shown)
    print("Enter logical axes to invert, or 'none' to clear the setting.")
    answer = input("InvertAxes [keep current]: ").strip()
    if not answer:
        return current
    if answer.lower() == "none":
        return ()
    return parse_axis_list(answer)


def prompt_button_map(current: tuple[int, ...]) -> tuple[int, ...]:
    shown = ",".join(map(str, current)) if current else "identity"
    print("\nButtonMap order is logical button 1, 2, 3, ...")
    print("Each number selects a physical button; 0 disables that logical button.")
    print(f"Current mapping: {shown}")
    print("Enter up to 32 comma-separated numbers, or 'identity' to reset.")
    answer = input("ButtonMap [keep current]: ").strip()
    if not answer:
        return current
    if answer.lower() == "identity":
        return ()
    return parse_button_map(answer)


def write_settings(
    axis_map: tuple[str, ...],
    inverted: tuple[str, ...],
    buttons: tuple[int, ...],
) -> None:
    lines = [
        "[Mapping]",
        "; Logical axes in X,Y,Z,R,U,V order; Rx is WinMM's R axis.",
        "AxisMap=" + ",".join(axis_map),
        "; Optional comma-separated logical axes to invert.",
        "InvertAxes=" + ",".join(inverted),
        "; Each entry maps a logical button to a physical button; 0 disables it.",
        "ButtonMap=" + ",".join(map(str, buttons)),
        "",
    ]
    temporary = CONFIG_PATH.with_suffix(".INI.tmp")
    temporary.write_text("\n".join(lines), encoding="ascii")
    temporary.replace(CONFIG_PATH)


def main() -> int:
    try:
        axis_map, inverted, buttons = read_settings()
        axis_map = prompt_axis_map(axis_map)
        inverted = prompt_inverted_axes(inverted)
        buttons = prompt_button_map(buttons)
        write_settings(axis_map, inverted, buttons)
    except ValueError as error:
        print(f"Invalid joystick mapping: {error}")
        return 1

    print(f"\nSaved mappings to {CONFIG_PATH.name}.")
    print("Restart FA.EXE for the new mappings to take effect.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

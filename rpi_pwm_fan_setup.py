#!/usr/bin/env python3
"""! @file rpi_pwm_fan_setup.py
@brief Interactively create a safe low-to-high temperature/speed fan curve.
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

# The installed command lives in /usr/local/sbin while its shared module lives
# beside the daemon. Source-tree execution already finds the local module.
if not (Path(__file__).resolve().parent / "rpi_pwm_fan.py").exists():
    sys.path.insert(0, "/usr/local/lib/rpi-pwm-fan")

from rpi_pwm_fan import MAX_TEMPERATURE_C, Curve, parse_curve


def read_number(prompt: str, cast, minimum=None, maximum=None):
    """! @brief Prompt until the user supplies a number inside the given bounds.

    @param prompt Text displayed before input.
    @param cast Numeric conversion callable, normally ``float`` or ``int``.
    @param minimum Optional inclusive lower bound.
    @param maximum Optional inclusive upper bound.
    @return A validated numeric value.
    """
    while True:
        try:
            value = cast(input(prompt))
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError
            if minimum is not None and value < minimum:
                raise ValueError
            if maximum is not None and value > maximum:
                raise ValueError
            return value
        except ValueError:
            print("Invalid value; check the allowed range and try again.")


def prompt_curve() -> Curve:
    """! @brief Collect ascending pairs until 85 C or 100% speed is reached.

    @return A curve validated by the same rules used by the daemon.
    """
    pairs: list[tuple[float, int]] = []
    print("Enter temperature/speed steps from low to high.")
    print("The setup stops when temperature reaches 85 C or speed reaches 100%.")
    while True:
        minimum_temp = pairs[-1][0] if pairs else None
        temperature = read_number("Temperature (C): ", float, maximum=MAX_TEMPERATURE_C)
        if minimum_temp is not None and temperature <= minimum_temp:
            print(f"Temperature must be greater than {minimum_temp:g} C.")
            continue

        minimum_speed = pairs[-1][1] if pairs else 0
        speed = read_number("Fan speed (0-100%): ", int, minimum_speed, 100)
        pairs.append((temperature, speed))
        if temperature == MAX_TEMPERATURE_C or speed == 100:
            break

    text = ",".join(f"{temperature:g}:{speed}" for temperature, speed in pairs)
    return parse_curve(text)


def update_environment(path: Path, curve: Curve) -> None:
    """! @brief Replace or append the fan curve in an environment file.

    @param path Destination environment-file path.
    @param curve Validated curve to serialize.
    """
    assignment = "RPI_PWM_FAN_CURVE=" + ",".join(
        f"{temperature:g}:{speed}" for temperature, speed in curve
    )
    lines = path.read_text().splitlines() if path.exists() else []
    output: list[str] = []
    replaced = False
    for line in lines:
        if line.startswith("RPI_PWM_FAN_CURVE="):
            output.append(assignment)
            replaced = True
        else:
            output.append(line)
    if not replaced:
        output.extend(([""] if output else []) + [assignment])
    path.write_text("\n".join(output) + "\n")


def main() -> None:
    """! @brief Parse the output path, collect a curve, and save it."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("/etc/default/rpi-pwm-fan"),
        help="environment file to update (default: /etc/default/rpi-pwm-fan)",
    )
    args = parser.parse_args()
    try:
        curve = prompt_curve()
        update_environment(args.output, curve)
    except (EOFError, KeyboardInterrupt):
        raise SystemExit("\nSetup cancelled; configuration was not changed.")
    print(f"Saved fan curve to {args.output}")
    print("Apply it with: sudo systemctl restart rpi-pwm-fan")


if __name__ == "__main__":
    main()

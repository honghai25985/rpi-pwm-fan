#!/usr/bin/env python3
"""! @file rpi_pwm_fan.py
@brief Control a Raspberry Pi PWM fan from an ordered CPU temperature curve.
"""

from __future__ import annotations

import logging
import math
import os
import signal
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


THERMAL_ZONE = Path("/sys/class/thermal/thermal_zone0/temp")
MAX_TEMPERATURE_C = 85.0
DEFAULT_CURVE = ((40.0, 0), (50.0, 30), (60.0, 60), (70.0, 80), (85.0, 100))
Curve = tuple[tuple[float, int], ...]


def parse_curve(value: str) -> Curve:
    """! @brief Parse and validate comma-separated temperature:speed pairs.

    @param value Curve text such as ``40:0,55:40,70:80,85:100``.
    @return An immutable sequence ordered from low to high temperature.
    @throws ValueError If values, ordering, ranges, or termination are invalid.
    """
    try:
        curve = tuple(
            (float(temperature), int(speed))
            for temperature, speed in (item.strip().split(":") for item in value.split(","))
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("RPI_PWM_FAN_CURVE must contain temperature:speed pairs") from exc

    if not curve:
        raise ValueError("RPI_PWM_FAN_CURVE must contain at least one pair")
    if any(not math.isfinite(temperature) for temperature, _ in curve):
        raise ValueError("curve temperatures must be finite")
    if any(temperature > MAX_TEMPERATURE_C for temperature, _ in curve):
        raise ValueError("curve temperatures must not exceed 85°C")
    if any(not 0 <= speed <= 100 for _, speed in curve):
        raise ValueError("curve speeds must be between 0 and 100")
    if any(right[0] <= left[0] for left, right in zip(curve, curve[1:])):
        raise ValueError("curve temperatures must strictly increase")
    if any(right[1] < left[1] for left, right in zip(curve, curve[1:])):
        raise ValueError("curve speeds must not decrease")
    if curve[-1][0] != MAX_TEMPERATURE_C and curve[-1][1] != 100:
        raise ValueError("curve must stop at 85°C or 100% speed")
    return curve


def fan_duty(temp_c: float, curve: Curve) -> int:
    """! @brief Select the speed at the highest reached temperature step.

    @param temp_c Current CPU temperature in degrees Celsius.
    @param curve Validated temperature/speed pairs.
    @return PWM duty from 0 to 100; always 100 at or above 85 degrees.
    """
    if temp_c >= MAX_TEMPERATURE_C:
        return 100
    duty = 0
    for threshold, speed in curve:
        if temp_c < threshold:
            break
        duty = speed
    return duty


def duty_with_hysteresis(
    temp_c: float, curve: Curve, previous_duty: int, hysteresis_c: float
) -> int:
    """! @brief Delay a downward speed step to prevent rapid fan switching.

    @param temp_c Current CPU temperature in degrees Celsius.
    @param curve Validated temperature/speed pairs.
    @param previous_duty Previously commanded logical duty.
    @param hysteresis_c Temperature drop required below the prior step.
    @return The next logical PWM duty from 0 to 100.
    """
    proposed = fan_duty(temp_c, curve)
    if proposed >= previous_duty:
        return proposed
    prior_thresholds = [temp for temp, speed in curve if speed >= previous_duty]
    if prior_thresholds and temp_c >= prior_thresholds[0] - hysteresis_c:
        return previous_duty
    return proposed


@dataclass(frozen=True)
class Config:
    """! @brief Immutable runtime configuration loaded from the environment."""

    gpio: int = 14
    # Match the 52Pi ZP-0141 vendor example: GPIO.PWM(14, 100).
    frequency: int = 100
    curve: Curve = DEFAULT_CURVE
    interval: float = 5.0
    hysteresis: float = 2.0
    active_low: bool = False

    @classmethod
    def from_env(cls) -> "Config":
        """! @brief Load and validate all ``RPI_PWM_FAN_*`` settings."""

        def setting(name: str, default: object) -> str:
            """! @brief Read an environment setting or its default."""
            return os.getenv(name, str(default))

        def value(name: str, default: object, cast):
            """! @brief Convert one environment setting."""
            return cast(setting(name, default))

        curve_text = setting(
            "RPI_PWM_FAN_CURVE",
            ",".join(f"{temp:g}:{speed}" for temp, speed in cls.curve),
        )
        config = cls(
            gpio=value("RPI_PWM_FAN_GPIO", cls.gpio, int),
            frequency=value("RPI_PWM_FAN_FREQUENCY", cls.frequency, int),
            curve=parse_curve(curve_text),
            interval=value("RPI_PWM_FAN_INTERVAL", cls.interval, float),
            hysteresis=value("RPI_PWM_FAN_HYSTERESIS", cls.hysteresis, float),
            active_low=setting("RPI_PWM_FAN_ACTIVE_LOW", "false").lower()
            in {"1", "true", "yes", "on"},
        )
        if not 0 <= config.gpio <= 53:
            raise ValueError("RPI_PWM_FAN_GPIO must be between 0 and 53")
        if config.frequency <= 0 or config.interval <= 0:
            raise ValueError("frequency and interval must be positive")
        if config.hysteresis < 0:
            raise ValueError("RPI_PWM_FAN_HYSTERESIS must not be negative")
        return config


class RpiGpioAdapter:
    """! @brief Present the PWM interface used by the controller."""

    def __init__(self, gpio_module: Any, gpio: int):
        """! @brief Configure one BCM GPIO output for software PWM."""
        self.gpio_module = gpio_module
        self.gpio = gpio
        self.pwm = None
        self.last_raw_duty = 255
        gpio_module.setwarnings(False)
        gpio_module.setmode(gpio_module.BCM)
        gpio_module.setup(gpio, gpio_module.OUT)

    def set_PWM_frequency(self, gpio: int, frequency: int) -> int:
        """! @brief Start RPi.GPIO PWM at the configured frequency.

        @return The requested frequency, which RPi.GPIO accepts directly.
        """
        if gpio != self.gpio:
            raise ValueError("adapter controls only its configured GPIO")
        self.pwm = self.gpio_module.PWM(gpio, frequency)
        self.pwm.start(100)
        return frequency

    def set_PWM_dutycycle(self, gpio: int, raw_duty: int) -> None:
        """! @brief Convert the controller's 0..255 scale to GPIO's percentage."""
        if gpio != self.gpio or self.pwm is None:
            raise RuntimeError("PWM output is not initialized")
        self.last_raw_duty = raw_duty
        self.pwm.ChangeDutyCycle(raw_duty * 100 / 255)

    def stop(self) -> None:
        """! @brief Stop software PWM while retaining its fail-safe output level."""
        if self.pwm is not None:
            self.pwm.stop()
        level = self.gpio_module.HIGH if self.last_raw_duty >= 128 else self.gpio_module.LOW
        self.gpio_module.output(self.gpio, level)


class FanController:
    """! @brief Read CPU temperature and apply the configured PWM duty."""

    def __init__(self, config: Config, pi: Any):
        """! @brief Initialize a controller using an active GPIO output."""
        self.config = config
        self.pi = pi
        self.running = True
        self.last_duty = 100
        self.has_temperature = False

    def set_duty(self, duty: int) -> None:
        """! @brief Convert logical percent to the adapter's electrical range."""
        electrical_duty = 100 - duty if self.config.active_low else duty
        self.pi.set_PWM_dutycycle(self.config.gpio, round(electrical_duty * 255 / 100))
        self.last_duty = duty

    def run(self) -> None:
        """! @brief Run the blocking temperature-control loop until signalled."""
        actual = self.pi.set_PWM_frequency(self.config.gpio, self.config.frequency)
        logging.info("GPIO %d PWM frequency: %d Hz", self.config.gpio, actual)
        self.set_duty(100)  # Fail safe while waiting for the first sensor reading.

        while self.running:
            try:
                temp_c = int(THERMAL_ZONE.read_text().strip()) / 1000
                duty = fan_duty(temp_c, self.config.curve)
                if self.has_temperature:
                    duty = duty_with_hysteresis(
                        temp_c, self.config.curve, self.last_duty, self.config.hysteresis
                    )
                if duty != self.last_duty:
                    self.set_duty(duty)
                    logging.info("CPU %.1f°C, fan %d%%", temp_c, duty)
                self.has_temperature = True
            except (OSError, ValueError):
                logging.exception("Cannot read CPU temperature; setting fan to 100%%")
                self.set_duty(100)
            time.sleep(self.config.interval)

    def stop(self, _signum=None, _frame=None) -> None:
        """! @brief Request a clean stop after the current polling interval."""
        self.running = False


def main() -> None:
    """! @brief Configure RPi.GPIO and run the fail-safe fan controller."""
    try:
        import RPi.GPIO as GPIO
    except ImportError as exc:
        raise SystemExit("python3-rpi.gpio is not installed") from exc

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    config = Config.from_env()
    pi = RpiGpioAdapter(GPIO, config.gpio)

    controller = FanController(config, pi)
    signal.signal(signal.SIGTERM, controller.stop)
    signal.signal(signal.SIGINT, controller.stop)
    try:
        controller.run()
    finally:
        controller.set_duty(100)  # Preserve cooling if the daemon exits.
        pi.stop()


if __name__ == "__main__":
    main()

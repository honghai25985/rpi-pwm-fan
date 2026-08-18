"""! @file test_rpi_pwm_fan.py
@brief Unit tests for fan-curve parsing, selection, and hysteresis.
"""

import unittest
from unittest.mock import patch

from rpi_pwm_fan import (
    Config,
    RpiGpioAdapter,
    duty_with_hysteresis,
    fan_duty,
    parse_curve,
)


class FakePwm:
    """! @brief Record PWM operations without Raspberry Pi hardware."""

    def __init__(self):
        self.started = None
        self.duty = None
        self.stopped = False

    def start(self, duty):
        """! @brief Record the initial duty."""
        self.started = duty

    def ChangeDutyCycle(self, duty):
        """! @brief Record a duty-cycle update."""
        self.duty = duty

    def stop(self):
        """! @brief Record PWM shutdown."""
        self.stopped = True


class FakeGpio:
    """! @brief Provide the RPi.GPIO surface used by the adapter."""

    BCM = "BCM"
    OUT = "OUT"
    HIGH = 1
    LOW = 0

    def __init__(self):
        self.pwm = FakePwm()
        self.output_level = None

    def setwarnings(self, _enabled):
        """! @brief Accept warning configuration."""

    def setmode(self, _mode):
        """! @brief Accept BCM numbering configuration."""

    def setup(self, _gpio, _mode):
        """! @brief Accept output configuration."""

    def PWM(self, _gpio, _frequency):
        """! @brief Return the recording PWM object."""
        return self.pwm

    def output(self, _gpio, level):
        """! @brief Record the retained shutdown level."""
        self.output_level = level


class FanCurveTests(unittest.TestCase):
    """! @brief Verify hardware-independent fan-curve behavior."""

    def setUp(self):
        """! @brief Create the representative curve used by selection tests."""
        self.curve = parse_curve("40:0,50:30,60:60,70:80,85:100")

    def test_speed_changes_at_configured_steps(self):
        """! @brief Use the last reached pair and zero below the first pair."""
        self.assertEqual(fan_duty(39.9, self.curve), 0)
        self.assertEqual(fan_duty(50, self.curve), 30)
        self.assertEqual(fan_duty(69.9, self.curve), 60)

    def test_thermal_ceiling_forces_full_speed(self):
        """! @brief Override a lower configured endpoint at 85 C for safety."""
        curve = parse_curve("40:0,85:80")
        self.assertEqual(fan_duty(85, curve), 100)

    def test_hysteresis_delays_downward_step(self):
        """! @brief Hold prior duty until temperature clears its hysteresis."""
        self.assertEqual(duty_with_hysteresis(59, self.curve, 60, 2), 60)
        self.assertEqual(duty_with_hysteresis(57.9, self.curve, 60, 2), 30)

    def test_curve_requires_safe_endpoint(self):
        """! @brief Reject a curve that reaches neither endpoint maximum."""
        with self.assertRaises(ValueError):
            parse_curve("40:0,70:80")

    def test_curve_requires_increasing_values(self):
        """! @brief Reject decreasing temperature or fan-speed steps."""
        with self.assertRaises(ValueError):
            parse_curve("50:50,40:100")
        with self.assertRaises(ValueError):
            parse_curve("40:50,85:40")

    def test_curve_rejects_non_finite_temperature(self):
        """! @brief Reject NaN even though it evades ordinary comparisons."""
        with self.assertRaises(ValueError):
            parse_curve("nan:0,85:100")

    def test_default_frequency_is_100_hz(self):
        """! @brief Keep the default aligned with the target fan protocol."""
        self.assertEqual(Config().frequency, 100)

    def test_gpio_adapter_retains_full_speed_on_stop(self):
        """! @brief Preserve a high output after normal-active PWM shuts down."""
        gpio = FakeGpio()
        adapter = RpiGpioAdapter(gpio, 14)
        self.assertEqual(adapter.set_PWM_frequency(14, 100), 100)
        adapter.set_PWM_dutycycle(14, 255)
        adapter.stop()
        self.assertTrue(gpio.pwm.stopped)
        self.assertEqual(gpio.output_level, gpio.HIGH)

    def test_environment_overrides_defaults(self):
        """! @brief Load project-prefixed configuration from the environment."""
        with patch.dict(
            "os.environ",
            {"RPI_PWM_FAN_GPIO": "22"},
            clear=True,
        ):
            config = Config.from_env()
        self.assertEqual(config.gpio, 22)


if __name__ == "__main__":
    unittest.main()

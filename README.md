# Raspberry Pi PWM Fan Controller

## Overview

`rpi-pwm-fan` keeps a Raspberry Pi cool without making its fan run flat-out all
the time. It watches the CPU temperature and adjusts a three-wire
adjustable-speed fan through software PWM. You can tune the fan curve to suit
your room and workload.

> This project started with the three-wire fan included in a
> [52Pi ZP-0141 case](https://wiki.52pi.com/index.php?title=ZP-0141) that I
> bought on Shopee. The controller itself works with compatible three-wire
> adjustable-speed fans in general.

The default curve is:

- below 40°C: off
- 40°C: 0%, 50°C: 30%, 60°C: 60%, 70°C: 80%
- 85°C and above, or when temperature reading fails: 100%

## Prerequisites

### Hardware

- Raspberry Pi with a three-wire adjustable-speed fan whose control input
  accepts 3.3 V, 100 Hz PWM.
- A suitable Raspberry Pi power supply with enough capacity for the fan and
  any other attached hardware.

### Software

- Raspberry Pi OS
- Python 3
- `python3-rpi.gpio`

## Wiring

GPIO numbers and physical header pin numbers are different. This project uses
BCM GPIO14, available on physical pin 8.

```text
Raspberry Pi 40-pin header            Three-wire PWM fan

Pin 2  (5 V)    -------------------------- Red: +5 V power
Pin 6  (GND)    -------------------------- Black: ground
Pin 8  (GPIO14) -------------------------- Blue: PWM speed control
```

This is the wiring used by the fan that inspired the project: red supplies 5 V,
black is ground, and blue carries the PWM speed-control signal. Check your own
fan's documentation and connector orientation before powering the Pi; wire
colours are not universal.

## Using a Different GPIO

GPIO14 is the default, but it is not the only option. Because `rpi-pwm-fan`
uses software PWM, another unused output-capable GPIO can carry the signal.
Good alternatives on a Pi 4B are:

| BCM GPIO | Physical pin | Notes |
|----------|--------------|-------|
| GPIO17   | Pin 11       | Recommended general-purpose alternative |
| GPIO27   | Pin 13       | General-purpose alternative |
| GPIO22   | Pin 15       | General-purpose alternative |
| GPIO18   | Pin 12       | Also supports hardware PWM; `rpi-pwm-fan` does not require it |

Before moving the wire, check that no HAT or other accessory uses the new pin.
Never use a 5 V, 3.3 V, or ground pin as the control pin. To move from GPIO14
to GPIO17, for example:

1. Stop the service: `sudo systemctl stop rpi-pwm-fan`.
2. Move only the fan's speed-control wire from physical pin 8 to pin 11.
3. Set `RPI_PWM_FAN_GPIO=17` in `/etc/default/rpi-pwm-fan`.
4. Restart it: `sudo systemctl restart rpi-pwm-fan`.
5. Check the result with `systemctl status rpi-pwm-fan`.

## Electrical and GPIO Safety

GPIO14 carries only the speed-control signal; the fan receives power from the
5 V and ground pins. Never connect a fan motor directly between a GPIO and
ground. Confirm that your fan accepts a 3.3 V PWM control signal; otherwise use
the interface circuit recommended by its manufacturer.

GPIO14 is also the UART TX pin. Disable the serial console and UART use of this
pin before using it for fan control, for example with `sudo raspi-config`.

## Raspberry Pi OS Fan Control

Yes—disable
[Raspberry Pi OS's built-in case-fan control](https://www.raspberrypi.com/documentation/configuration/computers/raspberry-pi.html)
while using `rpi-pwm-fan`. The built-in controller is configured through
`raspi-config`, defaults to GPIO14, and provides simple on/off temperature
control. Leaving it enabled on the same GPIO would give the kernel and
`rpi-pwm-fan` competing control of one pin.

Disable it interactively with:

```sh
sudo raspi-config
```

Choose **Performance Options → Fan**, answer **No** to fan temperature control,
then reboot. On Raspberry Pi OS, the equivalent non-interactive command is:

```sh
sudo raspi-config nonint do_fan 1
sudo reboot
```

Here, `1` means disable. If built-in control uses a different GPIO, it will not
directly conflict, but running both controllers for one fan is unnecessary.

## Installation

Install the required Raspberry Pi OS packages and service:

```sh
sudo apt update
sudo apt install -y python3-rpi.gpio
sudo sh ./install.sh
```

The installer preserves an existing `/etc/default/rpi-pwm-fan` configuration.

## Fan-Curve Configuration

Run the interactive setup utility:

```sh
sudo rpi-pwm-fan-setup

sudo systemctl restart rpi-pwm-fan
```

The utility accepts temperature/speed pairs from low to high and stops at 85°C
or 100% speed. Alternatively, edit `/etc/default/rpi-pwm-fan` directly:

```ini
RPI_PWM_FAN_CURVE=40:0,50:30,60:60,70:80,85:100
```

Temperatures must strictly increase, speeds must not decrease, and speeds must
be between 0 and 100. No arbitrary minimum temperature is imposed. At 85°C the
controller always commands 100% for thermal safety.

## Service Operation

Apply configuration changes and inspect the service:

```sh
sudo systemctl restart rpi-pwm-fan
systemctl status rpi-pwm-fan
journalctl -u rpi-pwm-fan -f
```

On service failure or shutdown, the daemon leaves the fan at 100%.

## Uninstallation

```sh
sudo systemctl disable --now rpi-pwm-fan
sudo rm /etc/systemd/system/rpi-pwm-fan.service \
  /usr/local/lib/rpi-pwm-fan/rpi_pwm_fan.py \
  /usr/local/sbin/rpi-pwm-fan-setup
sudo systemctl daemon-reload
```

## Testing

The unit tests exercise fan-curve behavior without accessing GPIO hardware:

```sh
python3 -m unittest -v
```

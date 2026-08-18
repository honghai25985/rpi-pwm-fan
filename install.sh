#!/bin/sh
## @file install.sh
## @brief Install the daemon, curve setup utility, configuration, and units.

set -eu

if [ "$(id -u)" -ne 0 ]; then
    echo "Run this installer as root: sudo ./install.sh" >&2
    exit 1
fi

install -d /usr/local/lib/rpi-pwm-fan
install -m 0755 rpi_pwm_fan.py /usr/local/lib/rpi-pwm-fan/rpi_pwm_fan.py
install -m 0755 rpi_pwm_fan_setup.py /usr/local/sbin/rpi-pwm-fan-setup
if [ ! -e /etc/default/rpi-pwm-fan ]; then
    install -m 0644 rpi-pwm-fan.env /etc/default/rpi-pwm-fan
fi
install -m 0644 rpi-pwm-fan.service /etc/systemd/system/rpi-pwm-fan.service
systemctl daemon-reload
systemctl enable --now rpi-pwm-fan.service

echo "Installed. Configure with: sudo rpi-pwm-fan-setup"
echo "Follow logs with: journalctl -u rpi-pwm-fan -f"

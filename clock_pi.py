#!/usr/bin/env python3
"""
Часы для Raspberry Pi:
- LCD 16x2 по I2C (PCF8574, обычно адрес 0x27)
- Пищалка на GPIO
- Ежедневный будильник

Зависимости:
  pip install RPLCD RPi.GPIO
"""

from datetime import datetime
from time import sleep

import RPi.GPIO as GPIO
from RPLCD.i2c import CharLCD

# --- Настройки железа ---
BUZZER_PIN = 18  # BCM numbering
I2C_ADDRESS = 0x27
I2C_PORT = 1

# --- Настройки будильника ---
ALARM_HOUR = 7
ALARM_MINUTE = 0


def beep(ms_on: int, ms_off: int, times: int) -> None:
    """Подать звуковой сигнал на пищалку."""
    for i in range(times):
        GPIO.output(BUZZER_PIN, GPIO.HIGH)
        sleep(ms_on / 1000.0)
        GPIO.output(BUZZER_PIN, GPIO.LOW)
        if i < times - 1:
            sleep(ms_off / 1000.0)


def main() -> None:
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(BUZZER_PIN, GPIO.OUT, initial=GPIO.LOW)

    lcd = CharLCD(
        i2c_expander="PCF8574",
        address=I2C_ADDRESS,
        port=I2C_PORT,
        cols=16,
        rows=2,
        charmap="A00",
        auto_linebreaks=False,
    )

    alarm_triggered_today = False
    last_day = datetime.now().day

    try:
        lcd.clear()
        lcd.write_string("Clock Pi started")
        beep(120, 80, 2)
        sleep(1)

        while True:
            now = datetime.now()

            if now.day != last_day:
                last_day = now.day
                alarm_triggered_today = False

            line1 = now.strftime("%H:%M:%S").ljust(16)
            line2 = now.strftime("%d.%m.%Y").ljust(16)

            lcd.cursor_pos = (0, 0)
            lcd.write_string(line1)
            lcd.cursor_pos = (1, 0)
            lcd.write_string(line2)

            if (
                not alarm_triggered_today
                and now.hour == ALARM_HOUR
                and now.minute == ALARM_MINUTE
                and now.second < 3
            ):
                alarm_triggered_today = True
                beep(250, 150, 8)

            sleep(0.2)

    finally:
        lcd.clear()
        GPIO.output(BUZZER_PIN, GPIO.LOW)
        GPIO.cleanup()


if __name__ == "__main__":
    main()

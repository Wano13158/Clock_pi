#!/usr/bin/env python3
"""
Часы для Raspberry Pi:
- LCD 16x2 по I2C (PCF8574, обычно адрес 0x27)
- Пищалка на GPIO11
- Ежедневный будильник
- Проверка тревоги в Полтаве (alerts.in.ua API)

Зависимости:
  pip install RPLCD RPi.GPIO requests

Для проверки тревог нужен токен:
  export ALERTS_IN_UA_TOKEN="<your_token>"
"""

import os
from datetime import datetime
from time import sleep, monotonic

import requests
import RPi.GPIO as GPIO
from RPLCD.i2c import CharLCD

# --- Настройки железа ---
BUZZER_PIN = 11  # BCM numbering (GPIO11)
I2C_ADDRESS = 0x27
I2C_PORT = 1

# --- Настройки будильника ---
ALARM_HOUR = 7
ALARM_MINUTE = 0

# --- Настройки проверки тревоги ---
POLTAVA_ALERT_API = "https://api.alerts.in.ua/v1/iot/active_air_raid_alerts_by_oblast.json"
ALERT_CHECK_EVERY_SEC = 30
ALERTS_TOKEN_ENV = "ALERTS_IN_UA_TOKEN"


def beep(ms_on: int, ms_off: int, times: int) -> None:
    for i in range(times):
        GPIO.output(BUZZER_PIN, GPIO.HIGH)
        sleep(ms_on / 1000.0)
        GPIO.output(BUZZER_PIN, GPIO.LOW)
        if i < times - 1:
            sleep(ms_off / 1000.0)


def is_poltava_alert_active(timeout_sec: float = 3.0):
    """Возвращает:
    - True/False: удалось проверить, состояние тревоги
    - None: проверить не удалось (например, нет токена)
    """
    token = os.getenv(ALERTS_TOKEN_ENV)
    if not token:
        return None

    headers = {"Authorization": f"Bearer {token}"}

    try:
        response = requests.get(POLTAVA_ALERT_API, headers=headers, timeout=timeout_sec)
        response.raise_for_status()
        data = response.json()

        states = data.get("states", data)
        candidates = ["Poltava", "Poltava Oblast", "Полтавська область", "Poltavs'ka oblast"]
        for key in candidates:
            if key in states:
                return bool(states[key])
    except Exception:
        return None

    return None


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
    last_alert_check = 0.0
    last_alert_state = False
    alert_status_line = "ALERT: UNKNOWN"

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

            if monotonic() - last_alert_check >= ALERT_CHECK_EVERY_SEC:
                last_alert_check = monotonic()
                state = is_poltava_alert_active()

                if state is None:
                    alert_status_line = "NO ALERT TOKEN"
                elif state:
                    alert_status_line = "POLTAVA ALERT!"
                    if not last_alert_state:
                        beep(120, 80, 10)
                else:
                    alert_status_line = "ALERT: OFF"

                last_alert_state = bool(state)

            line1 = now.strftime("%H:%M:%S").ljust(16)
            if alert_status_line in ("POLTAVA ALERT!", "NO ALERT TOKEN"):
                line2 = alert_status_line.ljust(16)
            else:
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

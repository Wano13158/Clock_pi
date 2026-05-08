#!/usr/bin/env python3
"""
Часы для Raspberry Pi:
- LCD 16x2 по I2C (PCF8574, обычно адрес 0x27)
- Пищалка на GPIO11 (активная или пассивная)
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

BUZZER_PIN = 11
BUZZER_TYPE = os.getenv("BUZZER_TYPE", "active").strip().lower()  # active | passive
PASSIVE_BUZZER_FREQ_HZ = 2000
I2C_ADDRESS = 0x27
I2C_PORT = 1

ALARM_HOUR = 7
ALARM_MINUTE = 0

ALERTS_API_URL = "https://api.alerts.in.ua/v1/alerts/active.json"
ALERT_CHECK_EVERY_SEC = 30  # безопасно ниже лимита 8-10 запросов/мин
ALERTS_TOKEN_ENV = "ALERTS_IN_UA_TOKEN"


def beep(ms_on: int, ms_off: int, times: int) -> None:
    use_passive = BUZZER_TYPE == "passive"
    pwm = None

    if use_passive:
        pwm = GPIO.PWM(BUZZER_PIN, PASSIVE_BUZZER_FREQ_HZ)

    for i in range(times):
        if use_passive and pwm is not None:
            pwm.start(50)  # 50% скважность
        else:
            GPIO.output(BUZZER_PIN, GPIO.HIGH)
        sleep(ms_on / 1000.0)
        if use_passive and pwm is not None:
            pwm.stop()
        else:
            GPIO.output(BUZZER_PIN, GPIO.LOW)
        if i < times - 1:
            sleep(ms_off / 1000.0)


def parse_poltava_state(payload: dict):
    """Пробуем достать состояние тревоги для Полтавской области из разных форматов API."""
    # Формат со states
    states = payload.get("states")
    if isinstance(states, dict):
        for key in ("Poltava", "Poltava Oblast", "Полтавська область", "Poltavs'ka oblast"):
            if key in states:
                return bool(states[key])

    # Формат со списком alerts/active_alerts
    alert_lists = []
    for k in ("alerts", "active_alerts"):
        v = payload.get(k)
        if isinstance(v, list):
            alert_lists.append(v)

    for alerts in alert_lists:
        for item in alerts:
            if not isinstance(item, dict):
                continue
            region_text = " ".join(
                str(item.get(x, "")) for x in ("region", "region_name", "location_title", "title")
            ).lower()
            if "полтав" in region_text or "poltav" in region_text:
                return True

    return False


def is_poltava_alert_active(timeout_sec: float = 3.0):
    """Возвращает кортеж: (state, status)
    state: True/False/None
    status: OK | NOT_MODIFIED | UNAUTHORIZED | FORBIDDEN | RATE_LIMIT | ERROR | NO_TOKEN
    """
    token = os.getenv(ALERTS_TOKEN_ENV)
    if not token:
        return None, "NO_TOKEN"

    if not hasattr(is_poltava_alert_active, "last_modified"):
        is_poltava_alert_active.last_modified = None
        is_poltava_alert_active.cached_state = False

    headers = {"Authorization": f"Bearer {token}"}
    if is_poltava_alert_active.last_modified:
        headers["If-Modified-Since"] = is_poltava_alert_active.last_modified

    params = {"token": token}

    try:
        response = requests.get(ALERTS_API_URL, headers=headers, params=params, timeout=timeout_sec)

        if response.status_code == 304:
            return is_poltava_alert_active.cached_state, "NOT_MODIFIED"
        if response.status_code == 401:
            return None, "UNAUTHORIZED"
        if response.status_code == 403:
            return None, "FORBIDDEN"
        if response.status_code == 429:
            return None, "RATE_LIMIT"

        response.raise_for_status()
        payload = response.json()
        state = parse_poltava_state(payload)

        is_poltava_alert_active.cached_state = state
        last_modified = response.headers.get("Last-Modified")
        if last_modified:
            is_poltava_alert_active.last_modified = last_modified

        return state, "OK"
    except Exception:
        return None, "ERROR"


def main() -> None:
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(BUZZER_PIN, GPIO.OUT, initial=GPIO.LOW)

    lcd = CharLCD(i2c_expander="PCF8574", address=I2C_ADDRESS, port=I2C_PORT, cols=16, rows=2, charmap="A00", auto_linebreaks=False)

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
                state, status = is_poltava_alert_active()

                if status == "NO_TOKEN":
                    alert_status_line = "NO ALERT TOKEN"
                elif status == "UNAUTHORIZED":
                    alert_status_line = "BAD ALERT TOKEN"
                elif status == "FORBIDDEN":
                    alert_status_line = "ALERT FORBIDDEN"
                elif status == "RATE_LIMIT":
                    alert_status_line = "ALERT RATE LIMIT"
                elif state is True:
                    alert_status_line = "POLTAVA ALERT!"
                    if not last_alert_state:
                        beep(120, 80, 10)
                elif state is False:
                    alert_status_line = "ALERT: OFF"
                else:
                    alert_status_line = "ALERT: ERROR"

                if state is not None:
                    last_alert_state = state

            line1 = now.strftime("%H:%M:%S").ljust(16)
            line2 = (alert_status_line if alert_status_line in ("POLTAVA ALERT!", "NO ALERT TOKEN", "BAD ALERT TOKEN", "ALERT FORBIDDEN", "ALERT RATE LIMIT") else now.strftime("%d.%m.%Y")).ljust(16)

            lcd.cursor_pos = (0, 0)
            lcd.write_string(line1)
            lcd.cursor_pos = (1, 0)
            lcd.write_string(line2)

            if (not alarm_triggered_today and now.hour == ALARM_HOUR and now.minute == ALARM_MINUTE and now.second < 3):
                alarm_triggered_today = True
                beep(250, 150, 8)

            sleep(0.2)
    finally:
        lcd.clear()
        GPIO.output(BUZZER_PIN, GPIO.LOW)
        GPIO.cleanup()


if __name__ == "__main__":
    main()

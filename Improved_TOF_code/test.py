import time
import network
import urequests
import json
from machine import SoftI2C, Pin
from vl53l4cd import VL53L4CD

WIFI_SSID        = "naam_van_je_hotspot"
WIFI_WACHTWOORD  = "wachtwoord_van_je_hotspot"
SERVER_URL       = "http://192.168.137.1:5000/meting"

WARMUP_SAMPLES       = 5
OUTLIER_THRESHOLD_CM = 5
INTERVAL_S           = 5

def verbind_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        wlan.connect(WIFI_SSID, WIFI_WACHTWOORD)
        timeout = 15
        while not wlan.isconnected() and timeout > 0:
            time.sleep(1)
            timeout -= 1

def stuur_meting(afstand):
    try:
        data = json.dumps({"afstand": afstand})
        headers = {"Content-Type": "application/json"}
        res = urequests.post(SERVER_URL, data=data, headers=headers)
        res.close()
    except Exception as e:
        print("Versturen mislukt:", e)

verbind_wifi()

i2c = SoftI2C(sda=Pin(0), scl=Pin(1))
vl53 = VL53L4CD(i2c)
vl53.inter_measurement = 0
vl53.timing_budget = 20
vl53.start_ranging()

warmup = []
while len(warmup) < WARMUP_SAMPLES:
    dist = vl53.get_distance()
    if dist is not None:
        warmup.append(dist)

baseline = sum(warmup) / len(warmup)

def get_valid_distance():
    while True:
        dist = vl53.get_distance()
        if dist is not None and abs(dist - baseline) < OUTLIER_THRESHOLD_CM:
            return dist

dist = get_valid_distance()
baseline = baseline * 0.9 + dist * 0.1
stuur_meting(dist)

while True:
    time.sleep(INTERVAL_S)
    dist = get_valid_distance()
    baseline = baseline * 0.9 + dist * 0.1
    stuur_meting(dist)

import network
import urequests
import time
from machine import SoftI2C, Pin
from vl53l4cd import VL53L4CD
from GPS.gps_driver import GPSReceive

# WiFi instellen
WIFI_SSID = "IPAD_HOTSPOT_NAAM"
WIFI_PASSWORD = "IPAD_WACHTWOORD"

# Railway server URL
SERVER_URL = "https://iot-vdw-d3.up.railway.app/data"

# Uniek ID per maaier
DEVICE_ID = "maaier_01"

def verbind_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.connect(WIFI_SSID, WIFI_PASSWORD)
    print("Verbinden met WiFi...")
    while not wlan.isconnected():
        time.sleep(0.5)
        print(".")
    print("WiFi verbonden:", wlan.ifconfig())

# Sensoren instellen
i2c = SoftI2C(sda=Pin(0), scl=Pin(1))
vl53 = VL53L4CD(i2c)
vl53.inter_measurement = 0
vl53.timing_budget = 20
vl53.start_ranging()

gps = GPSReceive(rx_pin_nr=17, tx_pin_nr=16)

# Start
verbind_wifi()

print("GPS wordt geconfigureerd...")
gps.modulesetup()
gps.setrate(2, 1)
print("Klaar, metingen starten...")

while True:
    afstand = vl53.get_distance()

    data = gps.getdata()
    lat = data[0]
    lon = data[1]

    print(f"Afstand: {afstand} cm | GPS: {lat}, {lon}")

    payload = {
        "device_id": DEVICE_ID,
        "gras_hoogte_cm": afstand,
        "latitude": lat if lat != 0 else None,
        "longitude": lon if lon != 0 else None
    }

    try:
        response = urequests.post(
            SERVER_URL,
            json=payload,
            headers={"Content-Type": "application/json"}
        )
        print("Server:", response.text)
        response.close()
    except Exception as e:
        print("Fout bij versturen:", e)

    time.sleep(60)
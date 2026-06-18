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
BASE_URL = "https://iot-vdw-d3.up.railway.app"
SERVER_URL = BASE_URL + "/data"
STATUS_URL = BASE_URL + "/api/pico/status?device_id="

# Uniek ID per maaier (moet overeenkomen met het Pico sensor-ID dat de
# beheerder bij dit machinist-account heeft ingevuld in het dashboard)
DEVICE_ID = "maaier_01"

# Hoe vaak gecontroleerd wordt of de machinist een meting heeft gestart/gestopt
POLL_INTERVAL = 5      # seconden, terwijl er niet gemeten wordt
MEET_INTERVAL = 60     # seconden tussen metingen, terwijl er wel gemeten wordt

def verbind_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.connect(WIFI_SSID, WIFI_PASSWORD)
    print("Verbinden met WiFi...")
    while not wlan.isconnected():
        time.sleep(0.5)
        print(".")
    print("WiFi verbonden:", wlan.ifconfig())

def is_meting_actief():
    """Vraagt het dashboard of de machinist een meting heeft gestart voor
       dit toestel. Geeft False terug als er geen verbinding is, zodat de
       Pico niet per ongeluk blijft meten als de server niet bereikbaar is."""
    try:
        response = urequests.get(STATUS_URL + DEVICE_ID)
        status = response.json()
        response.close()
        return bool(status.get("actief"))
    except Exception as e:
        print("Fout bij ophalen status:", e)
        return False

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
    if not is_meting_actief():
        # Machinist heeft (nog) geen meting gestart voor dit toestel:
        # niet meten, gewoon kort wachten en opnieuw checken.
        print("Geen actieve meting, wacht op start vanuit dashboard...")
        time.sleep(POLL_INTERVAL)
        continue

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

    time.sleep(MEET_INTERVAL)
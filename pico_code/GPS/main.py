from gps_driver import GPSReceive
import time

gps = GPSReceive(rx_pin_nr=17, tx_pin_nr=16)

def start_gps():
    print("GPS wordt geconfigureerd...")
    ready = gps.modulesetup()
    if ready:
        print("Module setup succesvol.")
    
    gps.setrate(2, 1)

def loop():
    print("Wachten op data (zorg voor vrij zicht op de hemel)...")
    while True:
        data = gps.getdata()
        
        lat = data[0]
        lon = data[1]
        timestamp = data[8]
        
        if lat != 0:
            print("-" * 40)
            print(f"Tijd (UTC): {timestamp}")
            print(f"Locatie:    {lat:.6f}, {lon:.6f}")
            print(f"Snelheid:   {data[5]}")
        else:
            print("Fix zoeken...", end="\r")
        
        time.sleep(1)

try:
    start_gps()
    loop()
except KeyboardInterrupt:
    print("\nProgramma gestopt.")
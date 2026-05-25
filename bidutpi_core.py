#!/usr/bin/env python3

import spidev
import time
import math
import csv
import json
from datetime import datetime
import requests
from gpiozero import OutputDevice  # This is the correct library for Pi 5

# ================= USER CONSTANTS =================
MAINS_FREQ = 50.0
SAMPLES_PER_CYCLE = 200
SAMPLE_RATE = int(MAINS_FREQ * SAMPLES_PER_CYCLE)
PHASE_SHIFT_SAMPLES = 18
WINDOW_SEC = 1
COST_PER_KWH = 8000.0

CSV_1 = "buffer_1.csv"
CSV_2 = "buffer_2.csv"


# YOUR FIREBASE LINKS: Update these with actual backend URLs from Firebase Realtime Database
FIREBASE_URL = "YOUR FIREBASEURL HERE"
RELAY_1_CONTROL_URL = "YOUR FIREBASEURL HERE"
RELAY_2_CONTROL_URL = "YOUR FIREBASEURL HERE"
ENERGY_SAVING_MODE_URL = "YOUR FIREBASEURL HERE"
BUDGET_LIMIT_URL = "YOUR FIREBASEURL HERE"
PREPAID_METER_URL = "YOUR FIREBASEURL HERE"
PREPAID_BUDGET_URL = "YOUR FIREBASEURL HERE"



CH_CURRENT = 0
CH_VOLTAGE = 1

# ================= RELAY SETUP =================
# We use gpiozero for Pi 5 compatibility
try:
    # Relay 1 (Main System) - GPIO 17 (Pin 11)
    relay1 = OutputDevice(17, active_high=True, initial_value=False)
    # Relay 2 (New Load) - GPIO 27 (Pin 13)
    relay2 = OutputDevice(27, active_high=True, initial_value=False)
    print("Relays initialized: GPIO 17 (Relay 1) and GPIO 27 (Relay 2)")
except Exception as e:
    print(f"Could not initialize Relays: {e}")

# ================= OLED SETUP =================
from luma.core.interface.serial import i2c
from luma.oled.device import sh1106
from PIL import Image, ImageDraw, ImageFont

try:
    serial = i2c(port=1, address=0x3C)
    oled = sh1106(serial)
    image = Image.new("1", oled.size)
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    print("OLED initialized")
except Exception as e:
    print(f"OLED Error: {e}")

# ================= CALIBRATION =================
def load_calibration():
    try:
        with open("acs712_calibration.json") as f:
            ci = json.load(f)
        with open("zmpt_calibration.json") as f:
            cv = json.load(f)
        return (ci["zero_offset_current"], ci["counts_per_amp"], 
                cv["zero_offset_voltage"], cv["counts_per_volt"])
    except:
        print("Calibration files missing! Using defaults.")
        return (512, 40, 512, 2)

# ================= SPI =================
def init_spi():
    spi = spidev.SpiDev()
    spi.open(0, 0)
    spi.max_speed_hz = 1350000
    spi.mode = 0
    return spi

def read_adc(spi, ch):
    adc = spi.xfer2([1, (8 + ch) << 4, 0])
    return ((adc[1] & 3) << 8) | adc[2]

# ================= CSV LOGGER =================
def log_to_csv(filename, spi):
    with open(filename, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["t", "raw_i", "raw_v"])
        start = time.perf_counter()
        next_t = start
        dt = 1.0 / SAMPLE_RATE
        while time.perf_counter() - start < WINDOW_SEC:
            now = time.perf_counter()
            if now >= next_t:
                writer.writerow([now, read_adc(spi, CH_CURRENT), read_adc(spi, CH_VOLTAGE)])
                next_t += dt

# ================= CALCULATIONS =================
def harmonic_rms(signal, h):
    N = len(signal)
    k = round(h * N * MAINS_FREQ / SAMPLE_RATE)
    if k <= 0 or k >= N // 2: return 0.0
    re = im = 0.0
    for n in range(N):
        ang = 2.0 * math.pi * k * n / N
        re += signal[n] * math.cos(ang)
        im -= signal[n] * math.sin(ang)
    return math.sqrt((re*2/N)**2 + (im*2/N)**2) / math.sqrt(2.0)

def compute_from_csv(filename, cal):
    zi, cpa, zv, cpv = cal
    i_vals = []; v_vals = []
    try:
        with open(filename) as f:
            reader = csv.DictReader(f)
            for r in reader:
                i_vals.append((int(r["raw_i"]) - zi) / cpa)
                v_vals.append((int(r["raw_v"]) - zv) / cpv)
        
        # Zero Crossing Detection
        prev_v = v_vals[0]; zc0 = zc1 = None
        for idx in range(1, len(v_vals)):
            if prev_v < 0 and v_vals[idx] >= 0:
                if zc0 is None: zc0 = idx
                else: zc1 = idx; break
            prev_v = v_vals[idx]
        
        if zc0 is None or zc1 is None: return None

        v_p = v_vals[zc0:]; i_p = i_vals[zc0:]; Np = len(v_p)
        i_s = [i_p[(k + PHASE_SHIFT_SAMPLES) % Np] for k in range(Np)]
        
        Irms = math.sqrt(sum(i*i for i in i_s) / Np)
        Vrms = math.sqrt(sum(v*v for v in v_p) / Np)
        P = sum(v_p[k] * i_s[k] for k in range(Np)) / Np
        S = Vrms * Irms
        PF = P / S if S > 1e-9 else 0.0
        Q = math.sqrt(max(0.0, S*S - P*P))
        
        # THD Logic
        i_c = i_vals[zc0:zc1]; Nc = len(i_c)
        i_cs = [i_c[(k + PHASE_SHIFT_SAMPLES) % Nc] for k in range(Nc)]
        I1 = harmonic_rms([x - (sum(i_cs)/Nc) for x in i_cs], 1)
        harm_sq = sum(harmonic_rms(i_cs, h)**2 for h in range(2, 16))
        ITHD = (math.sqrt(harm_sq) / I1 * 100.0) if I1 > 1e-9 else 0.0
        
        return Vrms, Irms, P, S, Q, PF, ITHD, (P * WINDOW_SEC / 3600.0)
    except: return None

# ================= UPDATED RELAY SYNC =================
def update_relays(current_cost):
    try:
        # Sync Relay 1 (Original Path)
        r1 = requests.get(RELAY_1_CONTROL_URL, timeout=1).json()
        if r1 == 1: relay1.on()
        else: relay1.off()

        # Sync Relay 2 (New Path for GPIO 27)
        r2 = requests.get(RELAY_2_CONTROL_URL, timeout=1).json()

        # Energy Saving Mode Logic
        energy_saving_mode = requests.get(ENERGY_SAVING_MODE_URL, timeout=1).json()
        
        if energy_saving_mode == 1:
            budget_limit = requests.get(BUDGET_LIMIT_URL, timeout=1).json()
            if budget_limit is not None:
                try:
                    budget_limit = float(budget_limit)
                    if budget_limit > 0 and current_cost >= budget_limit:
                        r2 = 0 # Turn off relay internally
                        # Upload '0' state back to Firebase so website updates to OFF!
                        requests.put(RELAY_2_CONTROL_URL, json=0, timeout=1)
                except ValueError:
                    pass

        # Prepaid Meter Logic
        prepaid_meter = requests.get(PREPAID_METER_URL, timeout=1).json()
        
        if prepaid_meter == 1:
            prepaid_budget = requests.get(PREPAID_BUDGET_URL, timeout=1).json()
            if prepaid_budget is not None:
                try:
                    prepaid_budget = float(prepaid_budget)
                    if prepaid_budget > 0 and current_cost >= prepaid_budget:
                        r1 = 0 # Turn off main system relay internally
                        # Upload '0' state back to Firebase so supplier website updates to OFF
                        requests.put(RELAY_1_CONTROL_URL, json=0, timeout=1)
                except ValueError:
                    pass

        # Apply Relay 1 state
        if r1 == 1: relay1.on()
        else: relay1.off()

        # Apply Relay 2 state
        if r2 == 1: relay2.on()
        else: relay2.off()

    except Exception as e:
        # Silently fail if network is slow to avoid disrupting algorithm
        pass

def upload(payload):
    try:
        requests.put(FIREBASE_URL, json=payload, timeout=1.5)
    except:
        pass

# ================= MAIN LOOP =================
def main():
    cal = load_calibration()
    spi = init_spi()
    total_energy = 0.0
    current_cost = 0.0
    toggle = True

    print("Priming CSV buffers...")
    log_to_csv(CSV_1, spi)
    log_to_csv(CSV_2, spi)
    print("System Ready. Starting loop...")

    try:
        while True:
            # 1. Sync BOTH relays with Firebase (pass current_cost for budget checks)
            update_relays(current_cost)

            # 2. Collect Data
            write_file = CSV_1 if toggle else CSV_2
            read_file  = CSV_2 if toggle else CSV_1
            log_to_csv(write_file, spi)
            
            # 3. Process Data
            result = compute_from_csv(read_file, cal)
            toggle = not toggle

            if result:
                Vrms, Irms, P, S, Q, PF, ITHD, e = result
                total_energy += e
                kWh = total_energy / 1000.0
                current_cost = kWh * COST_PER_KWH
                ts = datetime.now().strftime("%H:%M:%S")

                print(f"[{ts}] V: {Vrms:.1f}V | I: {Irms:.2f}A | P: {P:.1f}W | Cost: Rs {current_cost:.2f}")
                print(f"Relay 1: {'ON' if relay1.value else 'OFF'} | Relay 2: {'ON' if relay2.value else 'OFF'}")

                # 4. Upload to Firebase
                upload({
                   "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "Vrms": Vrms, 
                    "Irms": Irms, 
                    "PF": PF, 
                    "P_active": P,
                    "S_apparent": S, 
                    "Q_reactive": Q, 
                    "total_kWh": kWh, 
                    "cost": current_cost,
                    "ITHD": ITHD
                })

                # 5. Update OLED
                try:
                    draw.rectangle((0, 0, 132, 64), fill=0)
                    draw.text((0, 0),  f"V:{Vrms:.1f}V", font=font, fill=255)
                    draw.text((0, 12),  f"I:{Irms:.2f}A", font=font, fill=255)
                    draw.text((0,24), f"P:{P:.1f}W PF:{PF:.2f}", font=font, fill=255)
                    draw.text((0,36), f"Cost: Rs {current_cost:.2f}", font=font, fill=255)
                    draw.text((0,48), f"R1:{'ON' if relay1.value else 'OFF'} R2:{'ON' if relay2.value else 'OFF'}", font=font, fill=255)
                    oled.display(image)
                except: pass

    except KeyboardInterrupt:
        spi.close()
        print("\nStopped by user.")

if __name__ == "__main__":
    main()

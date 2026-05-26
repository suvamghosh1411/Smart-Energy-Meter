# IoT-Enabled Smart Energy Meter

An IoT-driven Smart Energy Meter prototype built on a *Raspberry Pi 5* platform. 
This system measures real-time single-phase AC parameters (voltage, current, power factor, active/reactive/apparent power, total harmonic distortion and voltage sag/swell), 
uploads metrics to a *Firebase Realtime Database* and provides two web-based control dashboards (one for the utility company/supplier and one for the consumer).

The system integrates physical load management using a dual-relay configuration to support prepaid metering and dynamic demand-side load-shedding budget controls.

---

##  Key Features:

* **Real-time AC Monitoring:** High-frequency waveform sampling (10kHz aggregate) of AC Voltage and Current.
* **Power & Harmonic Calculations:** Accurate extraction of V_rms, I_rms, Active Power (P), Apparent Power (S), Reactive Power (Q), Power Factor (PF), and Current Total Harmonic Distortion (ITHD).
* **Prepaid Metering Scheme:** Utility/Supplier can allocate budget credits and cut off the main line via **Relay 1** when the balance is depleted.
* **Demand-Side Load Management:** Consumers can activate an **Energy Saving Mode** with a custom monthly budget. Also, loads can be shed via **Relay 2** remotely for any particular preference of the consumer.
* **On-Meter OLED Display:** Local SH1106 OLED screen displaying live parameters and relay states.
* **Bi-directional Cloud Sync:** Real-time data logging and remote control using Firebase Realtime Database.

---

## 📁 Repository Structure

* **`bidutpi_core.py`**: The core Python script running on the Raspberry Pi 5. Handles data acquisition from the ADC, computation, local OLED rendering, and Firebase synchronization.
* **`demand_side_dashboard.html`**: A glassmorphic web dashboard designed for the consumer to monitor real-time usage, view history, set billing budget limits, and configure Energy Saving settings.
* **`utility_dashboard.HTML`**: The web dashboard for utility operators to monitor grid parameters, issue remote overrides, and manage prepaid budgets.
* **`schematic.png`**: The hardware circuit schematic outlining logic connections, power distribution, and high-voltage AC routing.
* **`hardware newpic.png`**: Visual reference photo showing the physical prototype assembly inside the enclosure box.

---





## 🛠️ Installation & Initial Setup

###  Enable Raspberry Pi Hardware Interfaces
Enable SPI and I2C via the terminal configuration utility:
```bash
sudo raspi-config
# Navigate to: Interface Options -> Enable SPI & I2C.
# Exit and reboot.

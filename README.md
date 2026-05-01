# Inha VIP: Autonomous Waste Sorting Pod (Stationary Prototype)

Project: AI-powered stationary waste-sorting module for indoor recycling facilities.
Course: Vertically Integrated Projects (VIP) - Inha University
Current Phase: Midterm (Stationary Mechanics and Local AI Validation)
Future Phase: Mobile integration with TurtleBot 3 Burger

Hardware: Raspberry Pi 4, Pi Camera V2, Forward-Facing LED Array, Dual MG996R Servos,
HC-SR04 Ultrasonic Sensors, Dedicated 5V External Battery Pack

---

## Overview
This repository contains a Python 3.10+ software stack for a stationary waste-sorting
prototype. The system runs a continuous Sense-Think-Act loop on a Raspberry Pi. It
performs local YOLOv8 inference, controls servos for sorting, monitors bin capacity,
and logs detections locally with optional async upload to IBM Watson IoT.

---

## Software Architecture
The package `waste_sorting_pod` provides a `main.py` entry point that orchestrates
four modules:

1. vision_processor.py
   - Captures frames, turns on the LED array, and runs YOLO inference locally.
   - Classes: Plastic, Paper, Metal
   - Output: Detected label and confidence score

2. servo_controller.py
   - Controls MG996R servos to sweep waste into bins.
   - Plastic -> Left servo, Paper -> Right servo, Metal -> dual sweep (configurable).
   - Uses a worker thread to avoid blocking camera processing.

3. bin_monitor.py
   - Monitors bin capacity with HC-SR04 ultrasonic sensors.
   - If distance < 5 cm, pauses sorting until cleared.

4. async_logger.py
   - Logs every successful sort to sort_log.csv.
   - Optional background uploader publishes to IBM Watson IoT via MQTT.

---

## Model Placement
Place the YOLO model file at:
```
models/yolov8n_waste.pt
```
You can change this path in config.yaml.

---

## Configuration
All runtime settings live in config.yaml. Key options:
- USE_SIMULATION: true/false
- SIMULATED_DETECTION_LABEL: "" or one of Plastic/Paper/Metal
- SIMULATED_DETECTION_INTERVAL_SEC: interval for simulated detections
- SIMULATED_BIN_DISTANCE_CM: distance value for bin simulation
- MODEL_PATH: models/yolov8n_waste.pt
- LED_GPIO: 22
- LEFT_SERVO_GPIO: 17
- RIGHT_SERVO_GPIO: 27
- TRIG_GPIO: 23
- ECHO_GPIO: 24
- BIN_FULL_THRESHOLD_CM: 5.0
- MQTT_ENABLED: false (enable only when IBM Watson IoT is configured)

---

## Run (WSL2 or Windows Simulation)
1. Install dependencies:
```
pip install ultralytics opencv-python gpiozero paho-mqtt pyyaml
```
2. Set simulation in config.yaml:
```
USE_SIMULATION: true
SIMULATED_DETECTION_LABEL: Plastic
```
3. Run:
```
python -m waste_sorting_pod.main --config config.yaml
```

---

## Run (Raspberry Pi Hardware)
1. Install dependencies:
```
pip install ultralytics opencv-python gpiozero paho-mqtt pyyaml
```
2. Set hardware mode in config.yaml:
```
USE_SIMULATION: false
```
3. Run:
```
python -m waste_sorting_pod.main --config config.yaml
```

---

## Quick Verification and Testing
- Simulated detections: set SIMULATED_DETECTION_LABEL in config.yaml and run main.
- Bin full pause: set SIMULATED_BIN_DISTANCE_CM to 3.0 and confirm sorting pauses.
- CSV logging: verify sort_log.csv updates after each detected sort.

---

## Hardware Wiring Notes
- Servos must use a dedicated 5V battery. Do not power servos from Pi 5V.
- Always share a common ground between Pi and external 5V supply.
- Use a voltage divider on HC-SR04 Echo to protect 3.3V GPIO.

### ASCII Wiring Diagram (BCM GPIO)
```
Raspberry Pi 4 (3.3V logic)                 Dedicated 5V Battery Pack
----------------------------------          -------------------------
GND --------------------------------------> GND (common)

[Perception Layer]
Pi Camera Port ---------------------------> Pi Camera V2 (angled down)
GPIO22 -----------------------------------> LED Array Relay/Transistor

[Manipulation Layer]
GPIO17 (PWM) -----------------------------> Left Servo (MG996R) Signal
GPIO27 (PWM) -----------------------------> Right Servo (MG996R) Signal
Servo V+ ---------------------------------> +5V (battery pack)
Servo GND --------------------------------> GND (common)

[Monitoring Layer]
GPIO23 (Trig) ----------------------------> HC-SR04 TRIG
GPIO24 (Echo) <--- [2k] ---+--- GPIO24
                           |
                          [1k]
                           |
                          GND
HC-SR04 VCC ------------------------------> Pi 5V
HC-SR04 GND ------------------------------> GND (common)
```

---

## IBM Watson IoT Notes
If MQTT is enabled, configure these in config.yaml:
- MQTT_HOST, MQTT_PORT, MQTT_TOPIC
- MQTT_CLIENT_ID, MQTT_USERNAME, MQTT_PASSWORD
- MQTT_USE_TLS

The system logs to sort_log.csv first, then uploads asynchronously when MQTT is
available.

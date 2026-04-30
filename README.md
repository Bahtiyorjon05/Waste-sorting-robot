# ♻️ Inha VIP: Autonomous Waste Sorting Hub (CSchool Scavenger)

**Project:** AI-powered mobile waste-sorting robot for the Inha University CSchool 3D Printing Lab.
**Platform:** TurtleBot 3 (Burger/Waffle)
**Middleware:** ROS 2 (Humble)
**Hardware:** Raspberry Pi 4, Pi Camera V2, MG996R Servos (x2), HC-SR04 Ultrasonic Sensors.


## 🤖 AI Agent Coding Instructions (Read First)
**Hello AI Coding Agent!** Your task is to write the ROS 2 Python nodes for this autonomous robotics project. We are using a modern AI-first development workflow. Please adhere to the following architecture and constraints when generating the codebase:
1. **Language:** Python 3.10+ using the `rclpy` library.
2. **AI Framework:** Use `ultralytics` for YOLOv8 inference and `cv2` (OpenCV) for camera handling.
3. **Hardware Control:** Use the `gpiozero` library for servo and ultrasonic sensor GPIO control on the Raspberry Pi.
4. **Style:** Keep nodes modular. Use standard ROS 2 OOP class structures (inheriting from `Node`). Include standard `try/except` blocks for hardware failures.

---

## 🏗️ Software Architecture & Node Breakdown

The system relies on a "Sense-Think-Act" loop. The AI agent must generate the following four independent ROS 2 nodes inside a package named `waste_sorting_hub`:

### 1. Perception Node (`waste_detector_node.py`)
* **Task:** Captures video frames and runs YOLOv8 Nano inference locally.
* **Input:** `/video_frames` (or directly capturing via OpenCV `cv2.VideoCapture(0)`).
* **AI Model:** Load a quantized model `cschool_waste_nano.pt`.
* **Classes to Detect:** `0: PLA_Scrap`, `1: Support_Structure`.
* **Output:** Publishes a `String` (JSON) to the topic `/waste_detection_events`.
    * *Payload example:* `{"class": "PLA_Scrap", "confidence": 0.88, "x_center": 320}`

### 2. Navigation Control Node (`patrol_navigator_node.py`)
* **Task:** Manages a simple forward patrol via `/cmd_vel` and halts the robot when waste is spotted.
* **Input:** Subscribes to `/waste_detection_events`.
* **Output:** Publishes `Twist` messages to `/cmd_vel`.
* **Logic:**
    * Continuously publishes a slow forward patrol velocity.
    * If a message is received on `/waste_detection_events`, immediately publish a `Twist` with `0.0` linear and angular velocity to stop the robot.
    * Wait for a "sorting complete" signal before resuming patrol.

### 3. Actuation Node (`sorting_servo_node.py`)
* **Task:** Controls the dual MG996R servos to sweep the waste into bins.
* **Input:** Subscribes to `/waste_detection_events`.
* **Hardware Setup:** * `Left_Servo` on GPIO 17 (Target: PLA_Scrap)
    * `Right_Servo` on GPIO 27 (Target: Support_Structure)
* **Logic:**
    * When "PLA_Scrap" is received, actuate Left Servo to 90 degrees, wait 1 second, and return to 0.
    * When "Support_Structure" is received, actuate Right Servo to 90 degrees, wait 1 second, and return to 0.
    * Publish a `String` to `/sorting_status` indicating "complete" so the Navigation node can resume.

### 4. Monitoring Node (`bin_monitor_node.py`)
* **Task:** Checks the capacity of the onboard sorting bins.
* **Hardware Setup:** `HC-SR04` sensors on GPIO pins (Trig: 23, Echo: 24).
* **Logic:**
    * Ping sensors every 5 seconds.
    * If distance is `< 5cm` (meaning bin is full), publish an alert to `/system_alerts` and force the Navigation node to halt the robot.

---

## 💻 Local Environment Setup (For Developers)

### Prerequisites
* Ubuntu 22.04 (Native or WSL2)
* ROS 2 Humble installed
* Python 3.10+

### 1. Create the ROS 2 Workspace
```bash
mkdir -p ~/vip_ws/src
cd ~/vip_ws/src
# Clone or copy the waste_sorting_hub package here
```

### 2. Install Dependencies
```bash
cd ~/vip_ws
rosdep install --from-paths src --ignore-src -r -y
pip install ultralytics opencv-python gpiozero
```

### 3. Build the Package
```bash
cd ~/vip_ws
colcon build --packages-select waste_sorting_hub
source install/setup.bash
```

### 4. Run the System
To launch all nodes simultaneously using the provided launch file and default configuration:
```bash
ros2 launch waste_sorting_hub main_launch.py
```

*Note:* For real hardware execution on the Raspberry Pi, ensure you set `use_sim: false` in `config/defaults.yaml` or pass parameters at runtime to enable GPIO access.

---

## 📦 Model Placement
Place the YOLO model file at:
```
waste_sorting_hub/models/cschool_waste_nano.pt
```
If you want a different location, override the `model_path` parameter in the detector node.

---

## ⚙️ Parameters (Quick Reference)
All nodes load defaults from `waste_sorting_hub/config/defaults.yaml`. Key parameters you will likely change:

### waste_detector_node
- `use_camera` (bool): Use `cv2.VideoCapture(0)` when true.
- `image_topic` (string): Topic to subscribe to when `use_camera` is false.
- `model_path` (string): Path to the YOLO model.
- `confidence_threshold` (float): Minimum confidence to publish.

### patrol_navigator_node
- `patrol_linear_speed` (float): Default forward speed while patrolling.
- `patrol_angular_speed` (float): Default turning speed while patrolling.

### sorting_servo_node
- `left_gpio`, `right_gpio`: Servo GPIO pins.
- `use_sim` (bool): True for dev machines without GPIO.

### bin_monitor_node
- `trig_gpio`, `echo_gpio`: Ultrasonic sensor GPIO pins.
- `full_threshold_cm` (float): Distance threshold for bin full alert.
- `use_sim` (bool): True for dev machines without GPIO.

---

## 🧭 Navigation Notes (Simple /cmd_vel Patrol)
This project uses a simple forward patrol on `/cmd_vel`. No Nav2/SLAM is required right now. The robot moves forward slowly, stops immediately on detections or bin alerts, waits for sorting to complete, then resumes forward motion.

---

## 🔌 Hardware Wiring Notes (Summary)
- **Servos (MG996R):** Provide separate 5V power rail and common ground with the Raspberry Pi. Do not power the servos from the Pi 5V pin directly.
- **Camera:** Enable the Pi camera interface and verify `cv2.VideoCapture(0)` works.
- **HC-SR04:** Use a voltage divider on Echo (e.g., 1k and 2k resistors) to drop 5V to ~3.3V, and ensure Trigger/Echo match GPIO 23/24 in the config.

### ASCII Wiring Diagram (BCM GPIO)
```
Raspberry Pi 4 (3.3V logic)                 External 5V Supply
----------------------------------           -------------------
GND ---------------------------------------> GND (common)
5V  (Pi 5V for logic only)   (do NOT power servos from Pi 5V)

Servo Left (MG996R)
    Signal (orange) -------------------------> GPIO17
    V+ (red) --------------------------------> +5V (external)
    GND (brown) -----------------------------> GND (common)

Servo Right (MG996R)
    Signal (orange) -------------------------> GPIO27
    V+ (red) --------------------------------> +5V (external)
    GND (brown) -----------------------------> GND (common)

HC-SR04 Ultrasonic
    VCC -------------------------------------> +5V (external or Pi 5V)
    GND -------------------------------------> GND (common)
    TRIG ------------------------------------> GPIO23
    ECHO -----> [2k] ----+----> GPIO24
                                             |
                                            [1k]
                                             |
                                            GND
    (Voltage divider drops 5V Echo to ~3.3V)
```

---

## ✅ Quick Verification & Testing
1. **Detector output (JSON event):**
    ```bash
    ros2 run waste_sorting_hub waste_detector_node
    ```
    ```bash
    ros2 topic echo /waste_detection_events
    ```
2. **Servo response (sim mode):**
    ```bash
    ros2 run waste_sorting_hub sorting_servo_node --ros-args -p use_sim:=true
    ```
    ```bash
    ros2 topic echo /sorting_status
    ```
3. **Bin monitor alerts (sim mode):**
    ```bash
    ros2 run waste_sorting_hub bin_monitor_node --ros-args -p use_sim:=true -p sim_distance_cm:=3.0
    ```
    ```bash
    ros2 topic echo /system_alerts
    ```
4. **Full system check (patrol stop/resume):**
    ```bash
    ros2 launch waste_sorting_hub main_launch.py
    ```
    ```bash
    ros2 topic echo /cmd_vel
    ```

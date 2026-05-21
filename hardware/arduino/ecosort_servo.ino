/* ===========================================================================
 * EcoSort AI - Arduino tilt-servo firmware
 * ===========================================================================
 * OPTIONAL. Only needed if you set  SERVO_BACKEND: "arduino"  in config.yaml.
 *
 * The Raspberry Pi sends one character over USB serial; this sketch tilts the
 * sorting platform accordingly:
 *
 *     'L'  -> tilt LEFT   (PLASTIC)
 *     'R'  -> tilt RIGHT  (PAPER)
 *     'F'  -> return FLAT / level
 *
 * Wiring:
 *     Servo signal -> Arduino pin 9
 *     Servo V+     -> external 5V supply  (NOT the Arduino 5V pin)
 *     Servo GND    -> common ground (shared with the Arduino GND)
 *
 * Upload with the Arduino IDE, then note the COM port (Windows) or
 * /dev/ttyUSB0 (Linux) and put it in ARDUINO_PORT in config.yaml.
 * =========================================================================== */

#include <Servo.h>

const int SERVO_PIN  = 9;
const int ANGLE_LEFT  = 20;   // tilt left  (PLASTIC)
const int ANGLE_FLAT  = 90;   // level / resting
const int ANGLE_RIGHT = 160;  // tilt right (PAPER)

Servo platform;

void setup() {
  Serial.begin(9600);
  platform.attach(SERVO_PIN);
  platform.write(ANGLE_FLAT);
}

void loop() {
  if (Serial.available() > 0) {
    char cmd = Serial.read();
    switch (cmd) {
      case 'L': platform.write(ANGLE_LEFT);  break;
      case 'R': platform.write(ANGLE_RIGHT); break;
      case 'F': platform.write(ANGLE_FLAT);  break;
      default:  break;  // ignore newlines / unknown characters
    }
  }
}

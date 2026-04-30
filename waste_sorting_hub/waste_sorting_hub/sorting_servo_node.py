import threading
import time

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from .event_utils import parse_detection_event

try:
    from gpiozero import AngularServo
except Exception:
    AngularServo = None


class SortingServoNode(Node):
    def __init__(self) -> None:
        super().__init__("sorting_servo_node")

        self.declare_parameter("detection_topic", "/waste_detection_events")
        self.declare_parameter("status_topic", "/sorting_status")
        self.declare_parameter("left_gpio", 17)
        self.declare_parameter("right_gpio", 27)
        self.declare_parameter("sweep_angle_deg", 90.0)
        self.declare_parameter("hold_sec", 1.0)
        self.declare_parameter("use_sim", True)
        self.declare_parameter("min_pulse_width_sec", 0.0005)
        self.declare_parameter("max_pulse_width_sec", 0.0025)

        detection_topic = str(self.get_parameter("detection_topic").value)
        status_topic = str(self.get_parameter("status_topic").value)

        self.left_gpio = int(self.get_parameter("left_gpio").value)
        self.right_gpio = int(self.get_parameter("right_gpio").value)
        self.sweep_angle_deg = float(self.get_parameter("sweep_angle_deg").value)
        self.hold_sec = float(self.get_parameter("hold_sec").value)
        self.use_sim = bool(self.get_parameter("use_sim").value)
        self.min_pulse_width_sec = float(
            self.get_parameter("min_pulse_width_sec").value
        )
        self.max_pulse_width_sec = float(
            self.get_parameter("max_pulse_width_sec").value
        )

        self.left_servo = None
        self.right_servo = None

        self._init_servos()

        self.status_pub = self.create_publisher(String, status_topic, 10)
        self.create_subscription(String, detection_topic, self._detection_cb, 10)

        self.busy_lock = threading.Lock()

    def _init_servos(self) -> None:
        if self.use_sim:
            self.get_logger().info("Servo node running in simulation mode.")
            return
        if AngularServo is None:
            self.get_logger().warning("gpiozero not available. Switching to sim mode.")
            self.use_sim = True
            return
        try:
            self.left_servo = AngularServo(
                self.left_gpio,
                min_angle=0.0,
                max_angle=self.sweep_angle_deg,
                min_pulse_width=self.min_pulse_width_sec,
                max_pulse_width=self.max_pulse_width_sec,
                initial_angle=0.0,
            )
            self.right_servo = AngularServo(
                self.right_gpio,
                min_angle=0.0,
                max_angle=self.sweep_angle_deg,
                min_pulse_width=self.min_pulse_width_sec,
                max_pulse_width=self.max_pulse_width_sec,
                initial_angle=0.0,
            )
        except Exception as exc:
            self.get_logger().warning("Servo init failed: %s", exc)
            self.left_servo = None
            self.right_servo = None
            self.use_sim = True

    def _detection_cb(self, msg: String) -> None:
        event = parse_detection_event(msg.data)
        if event is None:
            return

        class_name = event.get("class")
        if class_name not in ("PLA_Scrap", "Support_Structure"):
            return

        if not self.busy_lock.acquire(blocking=False):
            self.get_logger().warning("Servo busy. Ignoring detection.")
            return

        thread = threading.Thread(
            target=self._actuation_worker,
            args=(class_name,),
            daemon=True,
        )
        thread.start()

    def _actuation_worker(self, class_name: str) -> None:
        try:
            if class_name == "PLA_Scrap":
                self._sweep_servo(self.left_servo, "left")
            elif class_name == "Support_Structure":
                self._sweep_servo(self.right_servo, "right")
        finally:
            self.busy_lock.release()
            self.status_pub.publish(String(data="complete"))

    def _sweep_servo(self, servo, label: str) -> None:
        if self.use_sim or servo is None:
            self.get_logger().info("Sim sweep %s servo.", label)
            time.sleep(self.hold_sec)
            return
        try:
            servo.angle = self.sweep_angle_deg
            time.sleep(self.hold_sec)
            servo.angle = 0.0
        except Exception as exc:
            self.get_logger().warning("Servo sweep failed (%s): %s", label, exc)


def main(args=None) -> None:
    rclpy.init(args=args)
    node = SortingServoNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()

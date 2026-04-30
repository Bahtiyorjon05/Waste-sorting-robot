from typing import Set

import rclpy
from rclpy.node import Node
from std_msgs.msg import String
from geometry_msgs.msg import Twist

from .event_utils import parse_detection_event


class PatrolNavigatorNode(Node):
    def __init__(self) -> None:
        super().__init__("patrol_navigator_node")

        self.declare_parameter("detection_topic", "/waste_detection_events")
        self.declare_parameter("sorting_status_topic", "/sorting_status")
        self.declare_parameter("system_alerts_topic", "/system_alerts")
        self.declare_parameter("cmd_vel_topic", "/cmd_vel")
        self.declare_parameter("patrol_linear_speed", 0.2)
        self.declare_parameter("patrol_angular_speed", 0.0)
        self.declare_parameter("publish_rate_hz", 5.0)
        self.declare_parameter("alert_clear_keywords", ["clear", "ok", "resolved"])

        detection_topic = str(self.get_parameter("detection_topic").value)
        sorting_status_topic = str(self.get_parameter("sorting_status_topic").value)
        system_alerts_topic = str(self.get_parameter("system_alerts_topic").value)
        cmd_vel_topic = str(self.get_parameter("cmd_vel_topic").value)

        self.patrol_linear_speed = float(
            self.get_parameter("patrol_linear_speed").value
        )
        self.patrol_angular_speed = float(
            self.get_parameter("patrol_angular_speed").value
        )
        self.publish_rate_hz = float(self.get_parameter("publish_rate_hz").value)
        if self.publish_rate_hz <= 0.0:
            self.publish_rate_hz = 5.0

        self.alert_clear_keywords: Set[str] = set(
            self.get_parameter("alert_clear_keywords").value
        )

        self.create_subscription(String, detection_topic, self._detection_cb, 10)
        self.create_subscription(String, sorting_status_topic, self._sorting_cb, 10)
        self.create_subscription(String, system_alerts_topic, self._alerts_cb, 10)

        self.cmd_vel_pub = self.create_publisher(Twist, cmd_vel_topic, 10)

        self.detection_active = False
        self.alert_active = False
        self.last_state = None

        self.timer = self.create_timer(1.0 / self.publish_rate_hz, self._timer_cb)

    def _detection_cb(self, msg: String) -> None:
        event = parse_detection_event(msg.data)
        if event is None:
            return
        if not self.detection_active:
            self.get_logger().info(
                "Waste detected (%s). Halting patrol.", event.get("class")
            )
        self.detection_active = True
        self._publish_stop()

    def _sorting_cb(self, msg: String) -> None:
        if not msg.data:
            return
        if "complete" in msg.data.lower():
            if self.detection_active:
                self.get_logger().info("Sorting complete. Resuming patrol.")
            self.detection_active = False

    def _alerts_cb(self, msg: String) -> None:
        text = (msg.data or "").lower()
        if any(keyword in text for keyword in self.alert_clear_keywords):
            if self.alert_active:
                self.get_logger().info("System alert cleared. Resuming patrol.")
            self.alert_active = False
            return

        if text:
            if not self.alert_active:
                self.get_logger().warning("System alert: %s", msg.data)
            self.alert_active = True
            self._publish_stop()

    def _timer_cb(self) -> None:
        halted = self.detection_active or self.alert_active
        if halted:
            self._publish_stop()
        else:
            self._publish_patrol()

    def _publish_patrol(self) -> None:
        msg = Twist()
        msg.linear.x = self.patrol_linear_speed
        msg.angular.z = self.patrol_angular_speed
        self.cmd_vel_pub.publish(msg)

    def _publish_stop(self) -> None:
        msg = Twist()
        msg.linear.x = 0.0
        msg.angular.z = 0.0
        self.cmd_vel_pub.publish(msg)


def main(args=None) -> None:
    rclpy.init(args=args)
    node = PatrolNavigatorNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()

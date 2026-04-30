import rclpy
from rclpy.node import Node
from std_msgs.msg import String

try:
    from gpiozero import DistanceSensor
except Exception:
    DistanceSensor = None


class BinMonitorNode(Node):
    def __init__(self) -> None:
        super().__init__("bin_monitor_node")

        self.declare_parameter("system_alerts_topic", "/system_alerts")
        self.declare_parameter("trig_gpio", 23)
        self.declare_parameter("echo_gpio", 24)
        self.declare_parameter("poll_interval_sec", 5.0)
        self.declare_parameter("full_threshold_cm", 5.0)
        self.declare_parameter("max_distance_m", 1.0)
        self.declare_parameter("use_sim", True)
        self.declare_parameter("sim_distance_cm", 100.0)

        self.system_alerts_topic = str(
            self.get_parameter("system_alerts_topic").value
        )
        self.trig_gpio = int(self.get_parameter("trig_gpio").value)
        self.echo_gpio = int(self.get_parameter("echo_gpio").value)
        self.poll_interval_sec = float(
            self.get_parameter("poll_interval_sec").value
        )
        self.full_threshold_cm = float(
            self.get_parameter("full_threshold_cm").value
        )
        self.max_distance_m = float(self.get_parameter("max_distance_m").value)
        self.use_sim = bool(self.get_parameter("use_sim").value)

        if self.poll_interval_sec <= 0.0:
            self.poll_interval_sec = 5.0

        self.alert_pub = self.create_publisher(String, self.system_alerts_topic, 10)

        self.sensor = None
        self.alert_active = False
        self._init_sensor()

        self.timer = self.create_timer(self.poll_interval_sec, self._poll_cb)

    def _init_sensor(self) -> None:
        if self.use_sim:
            self.get_logger().info("Bin monitor running in simulation mode.")
            return
        if DistanceSensor is None:
            self.get_logger().warning("gpiozero not available. Switching to sim mode.")
            self.use_sim = True
            return
        try:
            self.sensor = DistanceSensor(
                echo=self.echo_gpio,
                trigger=self.trig_gpio,
                max_distance=self.max_distance_m,
            )
        except Exception as exc:
            self.get_logger().warning("Distance sensor init failed: %s", exc)
            self.sensor = None
            self.use_sim = True

    def _poll_cb(self) -> None:
        distance_cm = self._read_distance_cm()
        if distance_cm is None:
            return

        is_full = distance_cm < self.full_threshold_cm
        if is_full != self.alert_active:
            self.alert_active = is_full
            if is_full:
                self.alert_pub.publish(String(data="bin_full"))
            else:
                self.alert_pub.publish(String(data="bin_clear"))

    def _read_distance_cm(self):
        if self.use_sim:
            try:
                return float(self.get_parameter("sim_distance_cm").value)
            except Exception:
                return None
        if self.sensor is None:
            return None
        try:
            distance_m = float(self.sensor.distance)
            return distance_m * 100.0
        except Exception as exc:
            self.get_logger().warning("Distance read failed: %s", exc)
            return None


def main(args=None) -> None:
    rclpy.init(args=args)
    node = BinMonitorNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()

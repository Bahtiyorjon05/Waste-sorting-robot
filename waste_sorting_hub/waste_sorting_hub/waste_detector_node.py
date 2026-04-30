import os
import threading
import time
from typing import Dict, Optional

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from std_msgs.msg import String
from sensor_msgs.msg import Image

from ament_index_python.packages import get_package_share_directory

from .event_utils import build_detection_event

try:
    import cv2
except Exception:
    cv2 = None

try:
    from cv_bridge import CvBridge
except Exception:
    CvBridge = None

try:
    from ultralytics import YOLO
except Exception:
    YOLO = None


class WasteDetectorNode(Node):
    def __init__(self) -> None:
        super().__init__("waste_detector_node")

        default_model_path = self._get_default_model_path()

        self.declare_parameter("use_camera", True)
        self.declare_parameter("camera_index", 0)
        self.declare_parameter("image_topic", "/video_frames")
        self.declare_parameter("publish_topic", "/waste_detection_events")
        self.declare_parameter("process_rate_hz", 5.0)
        self.declare_parameter("confidence_threshold", 0.5)
        self.declare_parameter("iou_threshold", 0.45)
        self.declare_parameter("min_publish_interval_sec", 1.0)
        self.declare_parameter("model_path", default_model_path)

        self.use_camera = bool(self.get_parameter("use_camera").value)
        self.camera_index = int(self.get_parameter("camera_index").value)
        self.image_topic = str(self.get_parameter("image_topic").value)
        self.publish_topic = str(self.get_parameter("publish_topic").value)
        self.process_rate_hz = float(self.get_parameter("process_rate_hz").value)
        self.conf_threshold = float(self.get_parameter("confidence_threshold").value)
        self.iou_threshold = float(self.get_parameter("iou_threshold").value)
        self.min_publish_interval_sec = float(
            self.get_parameter("min_publish_interval_sec").value
        )
        self.model_path = str(self.get_parameter("model_path").value)

        if self.process_rate_hz <= 0.0:
            self.process_rate_hz = 5.0

        self.class_map: Dict[int, str] = {
            0: "PLA_Scrap",
            1: "Support_Structure",
        }

        self.publisher = self.create_publisher(String, self.publish_topic, 10)

        self.bridge = None
        if CvBridge is not None:
            self.bridge = CvBridge()

        if cv2 is None:
            self.get_logger().error("OpenCV is not available.")
            self.use_camera = False

        self.cap = None
        if self.use_camera:
            self._open_camera()

        self.last_frame = None
        self.frame_lock = threading.Lock()

        if not self.use_camera:
            if self.bridge is None:
                self.get_logger().error("cv_bridge is not available for /video_frames.")
            else:
                qos = QoSProfile(
                    depth=1,
                    history=HistoryPolicy.KEEP_LAST,
                    reliability=ReliabilityPolicy.BEST_EFFORT,
                )
                self.create_subscription(Image, self.image_topic, self._image_cb, qos)

        self.model = None
        self._load_model()

        self.process_lock = threading.Lock()
        self.last_publish_time = 0.0

        timer_period = 1.0 / self.process_rate_hz
        self.timer = self.create_timer(timer_period, self._timer_cb)

    def _get_default_model_path(self) -> str:
        try:
            share_dir = get_package_share_directory("waste_sorting_hub")
            return os.path.join(share_dir, "models", "cschool_waste_nano.pt")
        except Exception:
            return os.path.abspath(
                os.path.join(
                    os.path.dirname(__file__), "..", "models", "cschool_waste_nano.pt"
                )
            )

    def _open_camera(self) -> None:
        try:
            self.cap = cv2.VideoCapture(self.camera_index)
            if not self.cap.isOpened():
                self.get_logger().error("Failed to open camera index %s.", self.camera_index)
                self.cap.release()
                self.cap = None
                self.use_camera = False
        except Exception as exc:
            self.get_logger().error("Camera init failed: %s", exc)
            self.cap = None
            self.use_camera = False

    def _load_model(self) -> None:
        if YOLO is None:
            self.get_logger().error("ultralytics is not available.")
            return
        if not self.model_path or not os.path.isfile(self.model_path):
            self.get_logger().error("Model not found: %s", self.model_path)
            return
        try:
            self.model = YOLO(self.model_path)
        except Exception as exc:
            self.get_logger().error("Failed to load model: %s", exc)

    def _image_cb(self, msg: Image) -> None:
        if self.bridge is None:
            return
        try:
            frame = self.bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
        except Exception as exc:
            self.get_logger().warning("Image conversion failed: %s", exc)
            return
        with self.frame_lock:
            self.last_frame = frame

    def _timer_cb(self) -> None:
        frame = None
        if self.use_camera and self.cap is not None:
            try:
                ok, captured = self.cap.read()
            except Exception as exc:
                self.get_logger().warning("Camera read failed: %s", exc)
                return
            if not ok:
                return
            frame = captured
        else:
            with self.frame_lock:
                if self.last_frame is not None:
                    frame = self.last_frame.copy()

        if frame is None:
            return

        self._process_frame(frame)

    def _process_frame(self, frame) -> None:
        if self.model is None:
            return
        if not self.process_lock.acquire(blocking=False):
            return
        try:
            results = self.model.predict(
                source=frame,
                conf=self.conf_threshold,
                iou=self.iou_threshold,
                verbose=False,
            )
            if not results:
                return
            boxes = results[0].boxes
            if boxes is None or len(boxes) == 0:
                return

            best = None
            for box in boxes:
                cls_id = int(box.cls[0])
                if cls_id not in self.class_map:
                    continue
                conf = float(box.conf[0])
                if conf < self.conf_threshold:
                    continue
                xyxy = box.xyxy[0].tolist()
                x_center = int((xyxy[0] + xyxy[2]) / 2.0)
                if best is None or conf > best["confidence"]:
                    best = {
                        "class": self.class_map[cls_id],
                        "confidence": conf,
                        "x_center": x_center,
                    }

            if best is None:
                return

            now = time.monotonic()
            if now - self.last_publish_time < self.min_publish_interval_sec:
                return

            self.last_publish_time = now
            payload = build_detection_event(
                best["class"], best["confidence"], best["x_center"]
            )
            self.publisher.publish(String(data=payload))
        except Exception as exc:
            self.get_logger().warning("Inference failed: %s", exc)
        finally:
            self.process_lock.release()

    def destroy_node(self) -> bool:
        if self.cap is not None:
            try:
                self.cap.release()
            except Exception:
                pass
            self.cap = None
        return super().destroy_node()


def main(args=None) -> None:
    rclpy.init(args=args)
    node = WasteDetectorNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()

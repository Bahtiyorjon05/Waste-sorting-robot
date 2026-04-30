import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    pkg_share = get_package_share_directory("waste_sorting_hub")
    config_path = os.path.join(pkg_share, "config", "defaults.yaml")

    use_sim = LaunchConfiguration("use_sim")
    use_camera = LaunchConfiguration("use_camera")

    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "use_sim",
                default_value="true",
                description="Run hardware nodes in simulation mode.",
            ),
            DeclareLaunchArgument(
                "use_camera",
                default_value="true",
                description="Use cv2.VideoCapture in the detector node.",
            ),
            Node(
                package="waste_sorting_hub",
                executable="waste_detector_node",
                name="waste_detector_node",
                parameters=[config_path, {"use_camera": use_camera}],
            ),
            Node(
                package="waste_sorting_hub",
                executable="patrol_navigator_node",
                name="patrol_navigator_node",
                parameters=[config_path],
            ),
            Node(
                package="waste_sorting_hub",
                executable="sorting_servo_node",
                name="sorting_servo_node",
                parameters=[config_path, {"use_sim": use_sim}],
            ),
            Node(
                package="waste_sorting_hub",
                executable="bin_monitor_node",
                name="bin_monitor_node",
                parameters=[config_path, {"use_sim": use_sim}],
            ),
        ]
    )

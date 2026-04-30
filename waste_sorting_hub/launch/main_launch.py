import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    pkg_share = get_package_share_directory("waste_sorting_hub")
    config_path = os.path.join(pkg_share, "config", "defaults.yaml")

    return LaunchDescription(
        [
            Node(
                package="waste_sorting_hub",
                executable="waste_detector_node",
                name="waste_detector_node",
                parameters=[config_path],
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
                parameters=[config_path],
            ),
            Node(
                package="waste_sorting_hub",
                executable="bin_monitor_node",
                name="bin_monitor_node",
                parameters=[config_path],
            ),
        ]
    )

from setuptools import setup
from glob import glob
import os

package_name = "waste_sorting_hub"

setup(
    name=package_name,
    version="0.1.0",
    packages=[package_name],
    data_files=[
        (
            "share/ament_index/resource_index/packages",
            ["resource/" + package_name],
        ),
        ("share/" + package_name, ["package.xml"]),
        (os.path.join("share", package_name, "launch"), glob("launch/*.py")),
        (os.path.join("share", package_name, "config"), glob("config/*.yaml")),
        (os.path.join("share", package_name, "models"), glob("models/*")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="TODO",
    maintainer_email="todo@example.com",
    description="ROS 2 nodes for the Inha VIP autonomous waste sorting hub.",
    license="Apache-2.0",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "waste_detector_node = waste_sorting_hub.waste_detector_node:main",
            "patrol_navigator_node = waste_sorting_hub.patrol_navigator_node:main",
            "sorting_servo_node = waste_sorting_hub.sorting_servo_node:main",
            "bin_monitor_node = waste_sorting_hub.bin_monitor_node:main",
        ],
    },
)

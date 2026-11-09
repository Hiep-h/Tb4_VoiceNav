"""Test person detection on a laptop webcam (no robot, no depth camera).

    ros2 launch voice_person_perception webcam_person.launch.py
    ros2 launch voice_person_perception webcam_person.launch.py device:=1 gui:=false

Opens rqt_image_view on /person_detections/image (boxes, distance, bearing)
and voice_gui (radar of people). Distances are rough estimates from box size.
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('device', default_value='0', description='Số thứ tự webcam'),
        DeclareLaunchArgument('hfov_deg', default_value='65.0',
                              description='Góc nhìn ngang của webcam (ước lượng)'),
        DeclareLaunchArgument('gui', default_value='true', description='Mở voice_gui (radar)'),
        DeclareLaunchArgument('view', default_value='true',
                              description='Mở rqt_image_view xem ảnh có khung người'),
        Node(package='voice_person_perception', executable='webcam_node', name='webcam_node',
             output='screen', parameters=[{
                 'device': LaunchConfiguration('device'),
                 'hfov_deg': LaunchConfiguration('hfov_deg'),
             }]),
        Node(package='voice_person_perception', executable='person_detector_node',
             name='person_detector_node', output='screen', parameters=[{
                 'image_topic': '/webcam/image_raw',
                 'camera_info_topic': '/webcam/camera_info',
                 'depth_topic': 'none',
                 'debug_image': True,
             }]),
        Node(package='voice_person_perception', executable='voice_gui', name='voice_gui',
             output='screen', condition=IfCondition(LaunchConfiguration('gui'))),
        ExecuteProcess(cmd=['ros2', 'run', 'rqt_image_view', 'rqt_image_view',
                            '/person_detections/image'],
                       output='screen', condition=IfCondition(LaunchConfiguration('view'))),
    ])

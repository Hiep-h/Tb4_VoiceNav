"""Navigation Client, optionally with the fake Nav2 server (no robot needed).

    ros2 launch navigation_client navigation_client.launch.py stations_file:=$DEST
    ros2 launch navigation_client navigation_client.launch.py stations_file:=$DEST sim:=true
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('stations_file', default_value='auto',
                              description='destinations.yaml; auto = bản của '
                                          'voice_person_perception'),
        DeclareLaunchArgument('sim', default_value='false',
                              description='Chạy Nav2 giả (fake_nav2_server) thay robot thật'),
        DeclareLaunchArgument('speed', default_value='0.4', description='Tốc độ robot giả (m/s)'),
        DeclareLaunchArgument('goal_timeout_s', default_value='0.0',
                              description='Hủy và báo FAILED nếu đi quá lâu; 0 = không giới hạn'),
        Node(package='navigation_client', executable='fake_nav2_server', name='fake_nav2_server',
             output='screen', condition=IfCondition(LaunchConfiguration('sim')),
             parameters=[{'speed': LaunchConfiguration('speed')}]),
        Node(package='navigation_client', executable='navigation_client',
             name='navigation_client', output='screen', parameters=[{
                 'stations_file': LaunchConfiguration('stations_file'),
                 'goal_timeout_s': LaunchConfiguration('goal_timeout_s'),
             }]),
    ])

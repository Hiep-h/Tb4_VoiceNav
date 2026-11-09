"""Simulated inputs for the executor: scripted sentences and a person walking up.

    ros2 launch voice_person_perception fake.launch.py            # gui:=true to watch it
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('gui', default_value='false', description='Mở cửa sổ voice_gui'),
        Node(package='voice_person_perception', executable='fake_voice_node',
             name='fake_voice_node', output='screen'),
        Node(package='voice_person_perception', executable='intent_resolver_node',
             name='intent_resolver_node', output='screen'),
        Node(package='voice_person_perception', executable='fake_person_node',
             name='fake_person_node', output='screen'),
        Node(package='voice_person_perception', executable='voice_gui', name='voice_gui',
             output='screen', condition=IfCondition(LaunchConfiguration('gui'))),
    ])

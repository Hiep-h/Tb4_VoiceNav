"""Simulated inputs for the executor: scripted sentences and a person walking up."""

from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        Node(package='voice_person_perception', executable='fake_voice_node',
             name='fake_voice_node', output='screen'),
        Node(package='voice_person_perception', executable='intent_resolver_node',
             name='intent_resolver_node', output='screen'),
        Node(package='voice_person_perception', executable='fake_person_node',
             name='fake_person_node', output='screen'),
    ])

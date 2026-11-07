import os
from glob import glob

from setuptools import find_packages, setup

package_name = 'voice_person_perception'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.launch.py')),
        (os.path.join('share', package_name, 'config'), glob('config/*.yaml')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Hiep-h',
    maintainer_email='hiepga05102005@gmail.com',
    description='Voice command understanding and person detection for the TB4 delivery robot.',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'asr_node = voice_person_perception.asr_node:main',
            'intent_resolver_node = voice_person_perception.intent_resolver_node:main',
            'person_detector_node = voice_person_perception.person_detector_node:main',
            'fake_voice_node = voice_person_perception.fake_voice_node:main',
            'fake_person_node = voice_person_perception.fake_person_node:main',
            'eval_voice = voice_person_perception.eval_voice:main',
            'waypoint_marker = voice_person_perception.waypoint_marker:main',
            'destination_markers = voice_person_perception.destination_markers:main',
            'nav_goal_cmd = voice_person_perception.waypoints:goal_main',
        ],
    },
)

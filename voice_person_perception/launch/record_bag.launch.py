"""Record the perception output to a rosbag so the executor can replay it offline.

  ros2 launch voice_person_perception record_bag.launch.py
  ros2 launch voice_person_perception record_bag.launch.py name:=test_a raw:=true
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess, OpaqueFunction
from launch.substitutions import LaunchConfiguration

from voice_person_perception.bag_command import build_record_command


def _record(context):
    def arg(name):
        return LaunchConfiguration(name).perform(context)

    command = build_record_command(
        output_dir=arg('output_dir'),
        name=arg('name'),
        raw=arg('raw').lower() == 'true',
        compress=arg('compress').lower() == 'true',
    )
    return [ExecuteProcess(cmd=command, output='screen')]


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('output_dir', default_value='bags',
                              description='Thư mục chứa bag'),
        DeclareLaunchArgument('name', default_value='',
                              description='Tên bag; để trống = perception_<ngày_giờ>'),
        DeclareLaunchArgument('raw', default_value='false',
                              description='true = thu thêm ảnh RGB/depth của camera (rất nặng)'),
        DeclareLaunchArgument('compress', default_value='true',
                              description='Nén zstd để gửi file nhỏ hơn'),
        OpaqueFunction(function=_record),
    ])

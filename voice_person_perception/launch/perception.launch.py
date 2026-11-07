"""Real pipeline: microphone + speech recognition + intent + person detection."""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    args = [
        DeclareLaunchArgument('backend', default_value='google',
                              description='google | whisper | vosk'),
        DeclareLaunchArgument('fallback', default_value='whisper',
                              description='Dùng khi backend lỗi (Google mất mạng); none = không'),
        DeclareLaunchArgument('whisper_model', default_value='small',
                              description='Cỡ model (small, medium) hoặc thư mục model '
                                          'CTranslate2 (vd. PhoWhisper)'),
        DeclareLaunchArgument('model_path', default_value='',
                              description='Thư mục model Vosk (bắt buộc khi backend=vosk)'),
        DeclareLaunchArgument('vosk_grammar', default_value='false',
                              description='Vosk chỉ nhận câu mẫu sinh từ destinations.yaml'),
        DeclareLaunchArgument('whisper_prompt', default_value='false',
                              description='Gợi ý tên điểm đến cho Whisper (initial_prompt)'),
        DeclareLaunchArgument('device_index', default_value='-1',
                              description='Chỉ số micro (sounddevice); -1 = mặc định'),
    ]
    return LaunchDescription(args + [
        Node(package='voice_person_perception', executable='asr_node', name='asr_node',
             output='screen', parameters=[{
                 'backend': LaunchConfiguration('backend'),
                 'fallback': LaunchConfiguration('fallback'),
                 'whisper_model': LaunchConfiguration('whisper_model'),
                 'model_path': LaunchConfiguration('model_path'),
                 'device_index': LaunchConfiguration('device_index'),
                 'vosk_grammar': LaunchConfiguration('vosk_grammar'),
                 'whisper_prompt': LaunchConfiguration('whisper_prompt'),
             }]),
        Node(package='voice_person_perception', executable='intent_resolver_node',
             name='intent_resolver_node', output='screen'),
        Node(package='voice_person_perception', executable='person_detector_node',
             name='person_detector_node', output='screen'),
    ])

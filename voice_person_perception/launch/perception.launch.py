"""Real pipeline: microphone + speech recognition + intent + person detection."""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
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
        DeclareLaunchArgument('model_path', default_value='none',
                              description='Thư mục model Vosk (bắt buộc khi backend=vosk)'),
        DeclareLaunchArgument('destinations_file', default_value='auto',
                              description='destinations.yaml; auto = bản trong install'),
        DeclareLaunchArgument('vosk_grammar', default_value='false',
                              description='Vosk chỉ nhận câu mẫu sinh từ destinations.yaml'),
        DeclareLaunchArgument('whisper_prompt', default_value='false',
                              description='Gợi ý tên điểm đến cho Whisper (initial_prompt)'),
        DeclareLaunchArgument('device_index', default_value='-1',
                              description='Chỉ số micro (sounddevice); -1 = mặc định'),
        DeclareLaunchArgument('push_to_talk', default_value='false',
                              description='Chỉ nghe sau khi bấm nút (voice_gui / /asr_listen)'),
        DeclareLaunchArgument('save_audio_dir', default_value='none',
                              description='Lưu từng câu ra WAV để nghe lại; none = không'),
        DeclareLaunchArgument('gui', default_value='false',
                              description='Mở cửa sổ voice_gui'),
        DeclareLaunchArgument('map_yaml', default_value='none',
                              description='Bản đồ cho voice_gui (map_saver .yaml); none = radar'),
        DeclareLaunchArgument('person', default_value='true',
                              description='Chạy person_detector_node (cần camera OAK-D)'),
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
                 'destinations_file': LaunchConfiguration('destinations_file'),
                 'push_to_talk': LaunchConfiguration('push_to_talk'),
                 'save_audio_dir': LaunchConfiguration('save_audio_dir'),
             }]),
        Node(package='voice_person_perception', executable='intent_resolver_node',
             name='intent_resolver_node', output='screen', parameters=[{
                 'destinations_file': LaunchConfiguration('destinations_file'),
             }]),
        Node(package='voice_person_perception', executable='person_detector_node',
             name='person_detector_node', output='screen',
             condition=IfCondition(LaunchConfiguration('person'))),
        Node(package='voice_person_perception', executable='voice_gui', name='voice_gui',
             output='screen', condition=IfCondition(LaunchConfiguration('gui')),
             parameters=[{
                 'map_yaml': LaunchConfiguration('map_yaml'),
                 'destinations_file': LaunchConfiguration('destinations_file'),
             }]),
    ])

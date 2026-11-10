from glob import glob

from setuptools import setup

package_name = 'navigation_client'

setup(
    name=package_name,
    version='0.1.0',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/launch', glob('launch/*.launch.py')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Hiep-h',
    maintainer_email='hiepga05102005@gmail.com',
    description='Station id to Nav2 NavigateToPose, plus a fake Nav2 server.',
    license='Apache-2.0',
    entry_points={
        'console_scripts': [
            'navigation_client = navigation_client.navigation_client_node:main',
            'fake_nav2_server = navigation_client.fake_nav2_server:main',
            'nav_cmd = navigation_client.nav_cmd:main',
        ],
    },
)

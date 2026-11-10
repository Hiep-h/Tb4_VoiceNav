"""Send one command to the Navigation Client from the terminal (stands in for Mission Manager).

    ros2 run navigation_client nav_cmd go B       # navigate_to("B")
    ros2 run navigation_client nav_cmd cancel     # cancel_navigation()
    ros2 run navigation_client nav_cmd status     # get_navigation_status()
    ros2 run navigation_client nav_cmd watch      # print /navigation/status until Ctrl+C
"""

import json
import sys
import time

from navigation_client import protocol

USAGE = 'Dùng: nav_cmd go <trạm> | cancel | status | watch'


def build_command(argv, request_id):
    """(command dict, None) or (None, error) from command-line words."""
    if not argv:
        return None, USAGE
    word = argv[0].lower()
    if word in ('go', 'goto', 'navigate', 'di'):
        if len(argv) < 2:
            return None, 'Thiếu mã trạm, vd. nav_cmd go B'
        return {'request_id': request_id, 'action': protocol.NAVIGATE_TO,
                'station_id': argv[1]}, None
    if word in ('cancel', 'huy', 'stop'):
        return {'request_id': request_id, 'action': protocol.CANCEL}, None
    if word in ('status', 'trangthai'):
        return {'request_id': request_id, 'action': protocol.GET_STATUS}, None
    return None, USAGE


def describe(msg):
    state = msg.get('state')
    parts = [state or '?']
    if msg.get('station_id'):
        parts.append(f"trạm {msg['station_id']}")
    if msg.get('distance_remaining_m') is not None and state == 'MOVING':
        parts.append(f"còn {msg['distance_remaining_m']:.2f} m")
    if msg.get('eta_s') is not None and state == 'MOVING':
        parts.append(f"~{msg['eta_s']:.0f} s")
    if msg.get('reason'):
        parts.append(f"lý do {msg['reason']}")
    return ', '.join(parts)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    argv = [a for a in argv if not a.startswith('--ros-args')]
    import rclpy
    from rclpy.node import Node
    from std_msgs.msg import String
    rclpy.init()
    node = Node('nav_cmd')
    got = []
    try:
        if argv and argv[0] == 'watch':
            last = [None]

            def on_status(msg):
                text = describe(json.loads(msg.data))
                if text != last[0]:
                    print(time.strftime('%H:%M:%S'), text, flush=True)
                    last[0] = text
            node.create_subscription(String, protocol.STATUS_TOPIC, on_status, 10)
            rclpy.spin(node)
            return 0

        request_id = f'cli-{int(time.time() * 1000) % 100000000}'
        cmd, error = build_command(argv, request_id)
        if cmd is None:
            print(error)
            return 1
        node.create_subscription(
            String, protocol.RESPONSE_TOPIC,
            lambda m: got.append(json.loads(m.data))
            if json.loads(m.data).get('request_id') == request_id else None, 10)
        pub = node.create_publisher(String, protocol.COMMAND_TOPIC, 10)
        end = time.monotonic() + 3.0
        while rclpy.ok() and not pub.get_subscription_count() and time.monotonic() < end:
            rclpy.spin_once(node, timeout_sec=0.1)
        if not pub.get_subscription_count():
            print('Chưa thấy navigation_client đang chạy.')
            return 1
        pub.publish(String(data=protocol.dumps(cmd)))
        end = time.monotonic() + 3.0
        while rclpy.ok() and not got and time.monotonic() < end:
            rclpy.spin_once(node, timeout_sec=0.1)
        if not got:
            print('Không nhận được phản hồi trong 3 s.')
            return 1
        reply = got[0]
        ok = 'Đã nhận' if reply.get('accepted') else 'Bị từ chối'
        print(f"{ok}: {describe(reply)}" + (f", goal {reply['goal_id']}"
                                            if reply.get('goal_id') else ''))
        return 0 if reply.get('accepted') else 2
    except KeyboardInterrupt:
        return 0
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    sys.exit(main())

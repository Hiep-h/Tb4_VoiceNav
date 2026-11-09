"""Microphone -> utterance segmentation -> speech-to-text -> /speech_text."""

import queue
import threading
import time

import rclpy
import yaml
from rclpy.node import Node
from std_msgs.msg import Bool, String

from voice_person_perception import contract
from voice_person_perception import vocab
from voice_person_perception.asr_backends import FallbackBackend, make_backend
from voice_person_perception.intent_resolver_node import _default_destinations_file
from voice_person_perception.vad import EnergyVad, resample_to

TARGET_RATE = 16000


class AsrNode(Node):

    def __init__(self):
        super().__init__('asr_node')
        # backend: google | whisper | vosk. fallback: used only when backend fails
        # (Google without network or quota); '' = no fallback.
        self.declare_parameter('backend', 'google')
        self.declare_parameter('fallback', 'whisper')
        self.declare_parameter('model_path', '')
        self.declare_parameter('whisper_model', 'small')
        self.declare_parameter('language', 'vi')
        self.declare_parameter('device_index', -1)
        self.declare_parameter('min_rms', 250.0)
        self.declare_parameter('end_silence_ms', 700)
        # Bias recognition towards the command vocabulary (see vocab.py).
        self.declare_parameter('destinations_file', '')
        self.declare_parameter('vosk_grammar', False)
        self.declare_parameter('whisper_prompt', False)

        get = lambda name: self.get_parameter(name).value  # noqa: E731
        path = (get('destinations_file') if get('destinations_file') not in ('', 'auto')
                else _default_destinations_file())
        with open(path, encoding='utf-8') as f:
            data = yaml.safe_load(f)
        grammar = prompt = None
        if get('vosk_grammar'):
            grammar = vocab.vosk_grammar(data)
            self.get_logger().info(f'Vosk grammar: {len(grammar)} câu mẫu từ {path}')
        if get('whisper_prompt'):
            prompt = vocab.whisper_prompt(data)
            self.get_logger().info(f'Whisper prompt: "{prompt}"')
        backend, fallback = get('backend'), get('fallback')
        log = self.get_logger()

        def on_backup_ready(error):
            if error:
                log.error(f'Không nạp được {fallback} dự phòng: {error}. Chỉ dùng {backend}.')
            else:
                log.info(f'{fallback} dự phòng đã sẵn sàng')

        # The fallback (Whisper downloads ~500 MB the first time) loads in the
        # background, so the main engine is usable at once.
        self._backend = make_backend(
            backend, get('model_path'), get('whisper_model'),
            get('language'), TARGET_RATE, grammar=grammar, prompt=prompt,
            hints=vocab.destination_phrases(data), fallback=fallback, lazy_fallback=True,
            on_fallback=lambda exc: log.warn(f'{backend} lỗi ({exc}), thử {fallback}'),
            on_backup_ready=on_backup_ready)
        if isinstance(self._backend, FallbackBackend):
            log.info(f'Đang tải/nạp {fallback} dự phòng ở nền (lần đầu có thể vài phút); '
                     f'{backend} dùng được ngay')
        self._vad = EnergyVad(TARGET_RATE, min_rms=float(get('min_rms')),
                              end_silence_ms=int(get('end_silence_ms')))

        self._audio_q = queue.Queue(maxsize=300)
        self._out_q = queue.Queue()
        self._muted = False
        self._capture_rate = TARGET_RATE
        self._stop = threading.Event()
        self._dropped = False

        self._pub = self.create_publisher(String, contract.SPEECH_TEXT_TOPIC, 10)
        self.create_subscription(Bool, contract.ASR_MUTE_TOPIC, self._on_mute, 10)
        self.create_timer(0.05, self._flush)

        self._open_stream(int(get('device_index')))
        self._worker = threading.Thread(target=self._work, daemon=True)
        self._worker.start()
        self.get_logger().info(
            f"asr_node sẵn sàng: backend={get('backend')}, "
            f"dự phòng={get('fallback') or 'không'}, "
            f'mic {self._capture_rate} Hz. Đang nghe...')

    def _open_stream(self, device_index):
        try:
            import sounddevice as sd
        except ImportError as exc:
            raise RuntimeError('Cài sounddevice: pip install sounddevice') from exc
        device = None if device_index < 0 else device_index
        try:
            self._stream = sd.InputStream(
                samplerate=TARGET_RATE, channels=1, dtype='int16', device=device,
                blocksize=1600, callback=self._on_audio)
        except sd.PortAudioError:
            rate = int(sd.query_devices(device, 'input')['default_samplerate'])
            self.get_logger().warn(f'Mic không hỗ trợ 16 kHz, dùng {rate} Hz và resample')
            self._capture_rate = rate
            self._stream = sd.InputStream(
                samplerate=rate, channels=1, dtype='int16', device=device,
                blocksize=int(rate / 10), callback=self._on_audio)
        self._stream.start()

    def _on_audio(self, indata, frames, time_info, status):
        try:
            self._audio_q.put_nowait(indata[:, 0].copy())
        except queue.Full:
            if not self._dropped:
                self._dropped = True
                self.get_logger().warn('Hàng đợi âm thanh đầy, đang bỏ bớt dữ liệu')

    def _on_mute(self, msg):
        self._muted = bool(msg.data)

    def _work(self):
        while not self._stop.is_set():
            try:
                chunk = self._audio_q.get(timeout=0.2)
            except queue.Empty:
                continue
            if self._muted:
                self._vad.reset()
                continue
            chunk = resample_to(chunk, self._capture_rate, TARGET_RATE)
            for utterance in self._vad.feed(chunk):
                started = time.monotonic()
                try:
                    result = self._backend.transcribe(utterance)
                except Exception as exc:  # keep listening after a bad utterance
                    self.get_logger().error(f'Lỗi nhận dạng: {exc}')
                    continue
                if result:
                    text, conf = result
                    engine = getattr(self._backend, 'last_engine', None)
                    self._out_q.put((text, conf, time.monotonic() - started, engine))

    def _flush(self):
        while True:
            try:
                text, conf, latency, engine = self._out_q.get_nowait()
            except queue.Empty:
                return
            stamp = self.get_clock().now().nanoseconds * 1e-9
            via = f', {engine}' if engine else ''
            self.get_logger().info(
                f'Nghe được: "{text}" (conf {conf:.2f}, {latency:.2f}s{via})')
            msg = String()
            msg.data = contract.dumps(contract.make_speech_text(stamp, text, conf, latency))
            self._pub.publish(msg)

    def destroy_node(self):
        self._stop.set()
        stream = getattr(self, '_stream', None)
        if stream is not None:
            stream.stop()
            stream.close()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = AsrNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()

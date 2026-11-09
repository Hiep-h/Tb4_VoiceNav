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
        self.declare_parameter('max_utterance_s', 10.0)
        # Inside a sentence, sound above threshold * release_ratio still counts as speech.
        self.declare_parameter('release_ratio', 0.6)
        # Bias recognition towards the command vocabulary (see vocab.py).
        self.declare_parameter('destinations_file', '')
        self.declare_parameter('vosk_grammar', False)
        self.declare_parameter('whisper_prompt', False)
        # push_to_talk: listen only after /asr_listen True (button in voice_gui), one
        # sentence at a time; give up after ptt_timeout_s without speech.
        self.declare_parameter('push_to_talk', False)
        self.declare_parameter('ptt_timeout_s', 8.0)
        # With push_to_talk the user may pause longer (the button press says a
        # sentence is coming); pressing again sends the sentence at once.
        self.declare_parameter('ptt_end_silence_ms', 1500)

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
            backend, '' if get('model_path') == 'none' else get('model_path'),
            get('whisper_model'),
            get('language'), TARGET_RATE, grammar=grammar, prompt=prompt,
            hints=vocab.destination_phrases(data), fallback=fallback, lazy_fallback=True,
            on_fallback=lambda exc: log.warn(f'{backend} lỗi ({exc}), thử {fallback}'),
            on_backup_ready=on_backup_ready)
        if isinstance(self._backend, FallbackBackend):
            log.info(f'Đang tải/nạp {fallback} dự phòng ở nền (lần đầu có thể vài phút); '
                     f'{backend} dùng được ngay')
        end_silence = int(get('ptt_end_silence_ms') if get('push_to_talk')
                          else get('end_silence_ms'))
        self._vad = EnergyVad(TARGET_RATE, min_rms=float(get('min_rms')),
                              end_silence_ms=end_silence,
                              max_utterance_s=float(get('max_utterance_s')),
                              release_ratio=float(get('release_ratio')))

        self._audio_q = queue.Queue(maxsize=300)
        self._out_q = queue.Queue()
        self._muted = False
        self._ptt = bool(get('push_to_talk'))
        self._ptt_timeout = float(get('ptt_timeout_s'))
        self._armed_at = None  # push-to-talk: monotonic time the button was pressed
        self._recognizing = False
        self._finish_now = False  # push-to-talk: second press ends the sentence
        self._names = (backend, fallback)
        self._capture_rate = TARGET_RATE
        self._stop = threading.Event()
        self._dropped = False

        self._pub = self.create_publisher(String, contract.SPEECH_TEXT_TOPIC, 10)
        self.create_subscription(Bool, contract.ASR_MUTE_TOPIC, self._on_mute, 10)
        self.create_subscription(Bool, contract.ASR_LISTEN_TOPIC, self._on_listen, 10)
        self._status_pub = self.create_publisher(String, contract.ASR_STATUS_TOPIC, 10)
        self.create_timer(0.05, self._flush)
        self.create_timer(0.1, self._publish_status)

        self._open_stream(int(get('device_index')))
        self._worker = threading.Thread(target=self._work, daemon=True)
        self._worker.start()
        self.get_logger().info(
            f"asr_node sẵn sàng: backend={get('backend')}, "
            f"dự phòng={get('fallback') or 'không'}, "
            f'mic {self._capture_rate} Hz. '
            + ('Bấm nút trong voice_gui (hoặc /asr_listen true) để nói.' if self._ptt
               else 'Đang nghe...'))

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

    def _on_listen(self, msg):
        if msg.data:
            self._armed_at = time.monotonic()
            if not self._ptt:
                self._muted = False  # always-on mode: the button simply unmutes
        elif self._ptt and self._armed_at is not None and self._vad.in_speech:
            self._finish_now = True  # second press while talking: send what was said
        else:
            self._armed_at = None
            if not self._ptt:
                self._muted = True

    def _listening(self):
        if self._muted:
            return False
        if not self._ptt:
            return True
        if self._armed_at is None:
            return False
        if (time.monotonic() - self._armed_at > self._ptt_timeout
                and not self._vad.in_speech):
            self._armed_at = None  # nobody spoke
            return False
        return True

    def state(self):
        if self._recognizing:
            return contract.ASR_RECOGNIZING
        if self._muted:
            return contract.ASR_MUTED
        if not self._listening():
            return contract.ASR_IDLE
        if self._vad.calibrating:
            return contract.ASR_CALIBRATING
        if self._vad.in_speech:
            return contract.ASR_SPEECH
        return contract.ASR_LISTENING

    def _publish_status(self):
        fallback = self._names[1] if self._names[1] not in ('', 'none', self._names[0]) else ''
        ready = getattr(self._backend, 'backup_ready', None) if fallback else None
        msg = String()
        msg.data = contract.dumps(contract.make_asr_status(
            self.get_clock().now().nanoseconds * 1e-9, self.state(),
            self._vad.last_level, self._vad.threshold, self._names[0], fallback,
            ready, self._ptt))
        self._status_pub.publish(msg)

    def _work(self):
        while not self._stop.is_set():
            if self._finish_now:
                self._finish_now = False
                utterance = self._vad.flush()
                self._armed_at = None
                if utterance is not None:
                    self._recognize(utterance)
            try:
                chunk = self._audio_q.get(timeout=0.1)
            except queue.Empty:
                continue
            chunk = resample_to(chunk, self._capture_rate, TARGET_RATE)
            if not self._listening():
                self._vad.clear()
                if not self._muted:
                    # Push-to-talk idle: the room is quiet, keep the noise floor fresh.
                    self._vad.observe_noise(chunk)
                continue
            for utterance in self._vad.feed(chunk):
                if self._ptt:
                    self._armed_at = None  # one sentence per button press
                self._recognize(utterance)

    def _recognize(self, utterance):
        started = time.monotonic()
        self._recognizing = True
        try:
            result = self._backend.transcribe(utterance)
        except Exception as exc:  # keep listening after a bad utterance
            self.get_logger().error(f'Lỗi nhận dạng: {exc}')
            return
        finally:
            self._recognizing = False
        if result:
            text, conf = result
            engine = getattr(self._backend, 'last_engine', None)
            self._out_q.put((text, conf, time.monotonic() - started, engine))
        else:
            self.get_logger().info(
                f'Không nghe ra chữ nào ({len(utterance) / TARGET_RATE:.1f} s âm thanh)')

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

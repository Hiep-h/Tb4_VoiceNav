"""Energy-based utterance segmenter and resampling helper (no ROS)."""

from __future__ import annotations

from collections import deque

import numpy as np


def rms(frame):
    return float(np.sqrt(np.mean(frame.astype(np.float64) ** 2))) if len(frame) else 0.0


def resample_to(audio, src_rate, dst_rate):
    """Resample int16 mono audio. Uses scipy when available, else linear."""
    if src_rate == dst_rate or len(audio) == 0:
        return audio
    try:
        from math import gcd

        from scipy.signal import resample_poly
        g = gcd(src_rate, dst_rate)
        out = resample_poly(audio.astype(np.float64), dst_rate // g, src_rate // g)
    except ImportError:
        n_out = int(len(audio) * dst_rate / src_rate)
        out = np.interp(np.linspace(0, len(audio) - 1, n_out),
                        np.arange(len(audio)), audio.astype(np.float64))
    return np.clip(np.rint(out), -32768, 32767).astype(np.int16)


class EnergyVad:
    """Collects speech between silences into complete utterances.

    The speech threshold follows the measured noise floor, so it adapts to
    fan noise or a quiet room without hand tuning.
    """

    def __init__(self, sample_rate=16000, frame_ms=30, min_rms=250.0,
                 noise_ratio=3.0, start_ms=90, end_silence_ms=700,
                 min_utterance_ms=300, max_utterance_s=6.0, preroll_ms=300,
                 calibration_ms=450, release_ratio=1.0, tail_ms=150):
        self.sample_rate = sample_rate
        self.frame_len = int(sample_rate * frame_ms / 1000)
        self.min_rms = min_rms
        self.noise_ratio = noise_ratio
        # Inside an utterance, a frame still counts as speech above
        # threshold * release_ratio, so soft syllables do not end the sentence.
        self.release_ratio = release_ratio
        # Audio kept after the last loud frame. Soft endings ("sạc", "khách")
        # can sit below the threshold and must not be trimmed as silence.
        self.tail_frames = max(0, tail_ms // frame_ms)
        self.start_frames = max(1, start_ms // frame_ms)
        self.end_frames = max(1, end_silence_ms // frame_ms)
        self.min_frames = max(1, min_utterance_ms // frame_ms)
        self.max_frames = int(max_utterance_s * 1000 // frame_ms)
        self.calibration_frames = max(1, calibration_ms // frame_ms)
        self._preroll = deque(maxlen=max(1, preroll_ms // frame_ms))
        self._tail = np.zeros(0, dtype=np.int16)
        self.reset()

    def reset(self):
        self._noise_floor = None
        self._calibrating = self.calibration_frames
        self.last_level = 0.0
        self._voiced = 0
        self._in_speech = False
        self._speech_run = 0
        self._silence_run = 0
        self._frames = []
        self._preroll.clear()
        self._tail = np.zeros(0, dtype=np.int16)

    def clear(self):
        """Drop any half-collected utterance but keep the measured noise floor."""
        self._voiced = 0
        self._in_speech = False
        self._speech_run = 0
        self._silence_run = 0
        self._frames = []
        self._preroll.clear()
        self._tail = np.zeros(0, dtype=np.int16)

    def observe_noise(self, chunk):
        """Update the noise floor from audio known to be background (not listening)."""
        data = chunk.astype(np.int16)
        for i in range(len(data) // self.frame_len):
            level = rms(data[i * self.frame_len:(i + 1) * self.frame_len])
            self.last_level = level
            if self._calibrating > 0:
                self._calibrating -= 1
                weight = 0.2
            else:
                weight = 0.05
            self._noise_floor = (level if self._noise_floor is None
                                 else (1 - weight) * self._noise_floor + weight * level)

    @property
    def in_speech(self):
        return self._in_speech

    @property
    def calibrating(self):
        return self._calibrating > 0

    @property
    def threshold(self):
        floor = self._noise_floor if self._noise_floor is not None else 0.0
        return max(self.min_rms, floor * self.noise_ratio)

    def feed(self, chunk):
        """Add int16 samples; return a list of finished utterances."""
        data = np.concatenate([self._tail, chunk.astype(np.int16)])
        n_frames = len(data) // self.frame_len
        self._tail = data[n_frames * self.frame_len:]
        utterances = []
        for i in range(n_frames):
            frame = data[i * self.frame_len:(i + 1) * self.frame_len]
            done = self._step(frame)
            if done is not None:
                utterances.append(done)
        return utterances

    def _step(self, frame):
        level = rms(frame)
        self.last_level = level
        if self._calibrating > 0:
            # Assume nobody is speaking right after start-up.
            self._calibrating -= 1
            self._noise_floor = (level if self._noise_floor is None
                                 else 0.8 * self._noise_floor + 0.2 * level)
            return None
        is_speech = level > self.threshold
        if not self._in_speech:
            if not is_speech:
                self._noise_floor = (level if self._noise_floor is None
                                     else 0.95 * self._noise_floor + 0.05 * level)
            self._preroll.append(frame)
            self._speech_run = self._speech_run + 1 if is_speech else 0
            if self._speech_run >= self.start_frames:
                self._in_speech = True
                self._frames = list(self._preroll)
                self._voiced = self._speech_run
                self._silence_run = 0
            return None

        is_speech = level > self.threshold * self.release_ratio
        self._frames.append(frame)
        self._voiced += 1 if is_speech else 0
        self._silence_run = 0 if is_speech else self._silence_run + 1
        if self._silence_run >= self.end_frames or len(self._frames) >= self.max_frames:
            return self._finish()
        return None

    def flush(self):
        """End the current utterance now (e.g. button pressed); its audio or None."""
        if not self._in_speech:
            self.clear()
            return None
        audio = self._finish()
        self._tail = np.zeros(0, dtype=np.int16)
        return audio

    def _finish(self):
        keep = len(self._frames) - max(0, self._silence_run - self.tail_frames)
        audio = (np.concatenate(self._frames[:keep])
                 if self._voiced >= self.min_frames else None)
        self._in_speech = False
        self._speech_run = 0
        self._silence_run = 0
        self._frames = []
        self._preroll.clear()
        return audio


def normalize_peak(audio, target=0.7, max_gain=8.0):
    """Scale a quiet utterance up so its peak is `target` of full scale.

    Laptop microphones often record speech at a few percent of full scale;
    recognisers do better on a normal level. Loud audio is left unchanged.
    """
    if len(audio) == 0:
        return audio
    peak = float(np.max(np.abs(audio.astype(np.int32))))
    if peak <= 0:
        return audio
    gain = min(max_gain, target * 32767.0 / peak)
    if gain <= 1.0:
        return audio
    return np.clip(np.rint(audio.astype(np.float64) * gain), -32768, 32767).astype(np.int16)

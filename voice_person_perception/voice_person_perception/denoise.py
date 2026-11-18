"""Background-noise reduction before speech recognition (numpy only, no ROS).

Spectral subtraction: the noise spectrum is measured on audio recorded while
nobody was talking (NoiseProfile), then every frequency of the sentence is
turned down by how much of it is noise. Works on steady noise (fan, air
conditioner, robot motors, room hum); it cannot remove another person talking
at the same time - a close microphone and push-to-talk help with that.
"""

from __future__ import annotations

from collections import deque

import numpy as np

N_FFT = 512   # 32 ms at 16 kHz
HOP = 128


class NoiseProfile:
    """The last `seconds` of background audio (int16)."""

    def __init__(self, sample_rate=16000, seconds=2.0):
        self.sample_rate = sample_rate
        self._buf = deque(maxlen=int(sample_rate * seconds))

    def add(self, chunk):
        self._buf.extend(np.asarray(chunk, dtype=np.int16).tolist())

    def seconds(self):
        return len(self._buf) / self.sample_rate

    def get(self):
        return np.fromiter(self._buf, dtype=np.int16, count=len(self._buf))


def _frames(x, n_fft=N_FFT, hop=HOP):
    pad = (-(len(x) - n_fft) % hop) if len(x) > n_fft else n_fft - len(x)
    x = np.concatenate([x, np.zeros(pad)])
    count = 1 + (len(x) - n_fft) // hop
    idx = np.arange(n_fft)[None, :] + hop * np.arange(count)[:, None]
    return x[idx], len(x)


def _stft(x, window):
    frames, padded = _frames(x)
    return np.fft.rfft(frames * window, axis=1), padded


def _istft(spec, window, length, hop=HOP):
    frames = np.fft.irfft(spec, n=len(window), axis=1) * window
    out = np.zeros(length)
    norm = np.zeros(length)
    for i, frame in enumerate(frames):
        out[i * hop:i * hop + len(window)] += frame
        norm[i * hop:i * hop + len(window)] += window ** 2
    return out / np.maximum(norm, 1e-8)


def spectral_denoise(audio, noise, strength=1.5, floor=0.1, min_noise_s=0.25,
                     sample_rate=16000):
    """Return `audio` (int16) with the noise in `noise` (int16) turned down.

    strength: how hard to subtract (1 = exactly the noise level, more = cleaner
    but more "watery" sound). floor: never turn a frequency down below this
    fraction, which keeps speech natural. Returns audio unchanged when there is
    not enough noise to measure.
    """
    audio = np.asarray(audio, dtype=np.int16)
    noise = np.asarray(noise, dtype=np.int16)
    if len(audio) == 0 or len(noise) < max(N_FFT, int(min_noise_s * sample_rate)):
        return audio
    window = np.hanning(N_FFT + 1)[:-1]
    noise_spec, _ = _stft(noise.astype(np.float64), window)
    noise_mag = np.mean(np.abs(noise_spec), axis=0)
    # pad both ends so the first and last samples get full window overlap
    # (otherwise the overlap-add division blows up at the edges)
    x = np.concatenate([np.zeros(N_FFT), audio.astype(np.float64), np.zeros(N_FFT)])
    spec, padded = _stft(x, window)
    mag = np.abs(spec)
    gain = np.maximum(1.0 - strength * noise_mag[None, :] / np.maximum(mag, 1e-8), floor)
    # smooth over time so single frames do not flicker ("musical noise")
    kernel = np.ones(3) / 3.0
    gain = np.apply_along_axis(lambda g: np.convolve(g, kernel, mode='same'), 0, gain)
    out = _istft(spec * gain, window, padded)[N_FFT:N_FFT + len(audio)]
    return np.clip(np.rint(out), -32768, 32767).astype(np.int16)

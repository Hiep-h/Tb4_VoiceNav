"""Speech-to-text backends. Both take one finished utterance (int16, 16 kHz)."""

from __future__ import annotations

import json
import math
import re

import numpy as np

# Whisper tends to invent these on silence or noise.
_HALLUCINATIONS = re.compile(
    r'(cảm ơn các bạn|đăng ký kênh|hẹn gặp lại các bạn|subscribe|'
    r'ghiền mì gõ|like và share|thanks for watching)', re.IGNORECASE)


def is_hallucination(text):
    return bool(_HALLUCINATIONS.search(text))


class VoskBackend:
    """Offline streaming recogniser; fast on a Raspberry Pi."""

    def __init__(self, model_path, sample_rate=16000):
        try:
            import vosk
        except ImportError as exc:
            raise RuntimeError('Cài vosk: pip install vosk') from exc
        vosk.SetLogLevel(-1)
        self._vosk = vosk
        self._model = vosk.Model(model_path)
        self._rate = sample_rate

    def transcribe(self, audio):
        rec = self._vosk.KaldiRecognizer(self._model, self._rate)
        rec.SetWords(True)
        rec.AcceptWaveform(audio.astype(np.int16).tobytes())
        result = json.loads(rec.FinalResult())
        text = result.get('text', '').strip()
        if not text:
            return None
        confs = [w.get('conf', 1.0) for w in result.get('result', [])]
        return text, (sum(confs) / len(confs) if confs else 0.5)


class WhisperBackend:
    """faster-whisper; more accurate on free speech, slower on small CPUs."""

    def __init__(self, model_size='small', language='vi', device='cpu',
                 compute_type='int8'):
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise RuntimeError('Cài faster-whisper: pip install faster-whisper') from exc
        self._model = WhisperModel(model_size, device=device, compute_type=compute_type)
        self._language = language

    def transcribe(self, audio):
        samples = audio.astype(np.float32) / 32768.0
        segments, _ = self._model.transcribe(
            samples, language=self._language, beam_size=1,
            condition_on_previous_text=False, vad_filter=False)
        parts, confs = [], []
        for seg in segments:
            if seg.no_speech_prob > 0.6:
                continue
            parts.append(seg.text.strip())
            confs.append(math.exp(min(0.0, seg.avg_logprob)))
        text = ' '.join(p for p in parts if p).strip()
        if not text or is_hallucination(text):
            return None
        return text, sum(confs) / len(confs)


def make_backend(name, model_path='', whisper_model='small', language='vi',
                 sample_rate=16000):
    if name == 'vosk':
        if not model_path:
            raise RuntimeError('Backend vosk cần tham số model_path')
        return VoskBackend(model_path, sample_rate)
    if name == 'whisper':
        return WhisperBackend(whisper_model, language)
    raise RuntimeError(f'Backend không hợp lệ: {name}')

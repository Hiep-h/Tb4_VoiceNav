"""Speech-to-text backends. All take one finished utterance (int16, 16 kHz).

transcribe() returns (text, confidence), or None when nothing was understood,
and raises when the engine itself fails (network, model), so FallbackBackend
can switch to the backup engine.
"""

from __future__ import annotations

import json
import math
import re

import numpy as np

from voice_person_perception.intent import normalize
from voice_person_perception.vocab import UNK

# Whisper tends to invent these on silence or noise.
_HALLUCINATIONS = re.compile(
    r'(cảm ơn các bạn|đăng ký kênh|hẹn gặp lại các bạn|subscribe|'
    r'ghiền mì gõ|like và share|thanks for watching)', re.IGNORECASE)


# With an initial_prompt, Whisper sometimes repeats the prompt on noise.
_PROMPT_ECHO = re.compile(r'(các trạm:|các điểm đến|lệnh cho robot giao (đồ|hàng))',
                          re.IGNORECASE)


def is_hallucination(text):
    return bool(_HALLUCINATIONS.search(text) or _PROMPT_ECHO.search(text))


class VoskBackend:
    """Offline streaming recogniser; fast on a Raspberry Pi."""

    def __init__(self, model_path, sample_rate=16000, grammar=None):
        try:
            import vosk
        except ImportError as exc:
            raise RuntimeError('Cài vosk: pip install vosk') from exc
        vosk.SetLogLevel(-1)
        self._vosk = vosk
        self._model = vosk.Model(model_path)
        self._rate = sample_rate
        # grammar: list of allowed phrases (see vocab.vosk_grammar) or None.
        self._grammar = json.dumps(grammar, ensure_ascii=False) if grammar else None

    def transcribe(self, audio):
        if self._grammar:
            rec = self._vosk.KaldiRecognizer(self._model, self._rate, self._grammar)
        else:
            rec = self._vosk.KaldiRecognizer(self._model, self._rate)
        rec.SetWords(True)
        rec.AcceptWaveform(audio.astype(np.int16).tobytes())
        result = json.loads(rec.FinalResult())
        text = result.get('text', '').replace(UNK, ' ').strip()
        text = ' '.join(text.split())
        if not text:
            return None
        confs = [w.get('conf', 1.0) for w in result.get('result', [])]
        return text, (sum(confs) / len(confs) if confs else 0.5)


class WhisperBackend:
    """faster-whisper; more accurate on free speech, slower on small CPUs."""

    def __init__(self, model_size='small', language='vi', device='cpu',
                 compute_type='int8', prompt=None):
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise RuntimeError('Cài faster-whisper: pip install faster-whisper') from exc
        self._model = WhisperModel(model_size, device=device, compute_type=compute_type)
        self._language = language
        self._prompt = prompt or None

    def transcribe(self, audio):
        samples = audio.astype(np.float32) / 32768.0
        segments, _ = self._model.transcribe(
            samples, language=self._language, beam_size=1,
            condition_on_previous_text=False, vad_filter=False,
            initial_prompt=self._prompt)
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


GOOGLE_LANG = {'vi': 'vi-VN', 'en': 'en-US'}
GOOGLE_DEFAULT_CONF = 0.8  # Google gives a confidence only for its top guess


def pick_alternative(alternatives, hints=()):
    """Choose among Google's guesses: the first one that names a known
    destination (hints, e.g. names and aliases), else Google's top guess.

    Returns (text, confidence) or None.
    """
    texts = [(a.get('transcript', '').strip(), a.get('confidence')) for a in alternatives]
    texts = [(t, c) for t, c in texts if t]
    if not texts:
        return None
    top_conf = texts[0][1] if texts[0][1] is not None else GOOGLE_DEFAULT_CONF
    norm_hints = [h for h in (normalize(x) for x in hints) if h]
    for i, (text, conf) in enumerate(texts):
        padded = f' {normalize(text)} '
        if any(f' {h} ' in padded for h in norm_hints):
            if conf is None:
                conf = min(top_conf, GOOGLE_DEFAULT_CONF) if i else top_conf
            return text, float(conf)
    return texts[0][0], float(top_conf)


class GoogleBackend:
    """Google Web Speech API via the SpeechRecognition package (needs Internet)."""

    def __init__(self, language='vi', sample_rate=16000, hints=(), timeout_s=5.0,
                 recognize=None):
        self._rate = sample_rate
        self._language = GOOGLE_LANG.get(language, language)
        self._hints = tuple(hints)
        if recognize is None:
            try:
                import speech_recognition as sr
            except ImportError as exc:
                raise RuntimeError('Cài SpeechRecognition: pip install SpeechRecognition') from exc
            recognizer = sr.Recognizer()
            recognizer.operation_timeout = timeout_s  # fail fast so the backup takes over

            def recognize(raw, rate, lang):
                audio = sr.AudioData(raw, rate, 2)
                return recognizer.recognize_google(audio, language=lang, show_all=True)
        self._recognize = recognize

    def transcribe(self, audio):
        result = self._recognize(audio.astype(np.int16).tobytes(), self._rate, self._language)
        alternatives = result.get('alternative', []) if isinstance(result, dict) else []
        return pick_alternative(alternatives, self._hints)


class BackupNotReady(RuntimeError):
    """The primary engine failed and the backup is still loading or failed to load."""


class FallbackBackend:
    """Use the primary engine; if it raises, transcribe with the backup instead.

    `backup` is an engine, or a callable that builds one. A callable is run in a
    background thread (Whisper downloads ~500 MB on first use), so the primary
    engine works at once; until the backup is ready a primary failure raises
    BackupNotReady. `last_engine` tells which one produced the last result.
    """

    def __init__(self, primary, backup, primary_name='primary', backup_name='backup',
                 on_fallback=None, on_backup_ready=None):
        self._primary = primary
        self._names = (primary_name, backup_name)
        self._on_fallback = on_fallback
        self._on_backup_ready = on_backup_ready
        self.last_engine = primary_name
        self._backup = None
        self._backup_error = None
        self._loader = None
        if callable(backup) and not hasattr(backup, 'transcribe'):
            import threading
            self._loader = threading.Thread(target=self._load, args=(backup,), daemon=True)
            self._loader.start()
        else:
            self._backup = backup

    def _load(self, factory):
        try:
            self._backup = factory()
        except Exception as exc:  # noqa: BLE001 - reported when the backup is needed
            self._backup_error = exc
        if self._on_backup_ready:
            self._on_backup_ready(self._backup_error)

    @property
    def backup_ready(self):
        return self._backup is not None

    def wait_backup(self, timeout=None):
        if self._loader:
            self._loader.join(timeout)
        return self.backup_ready

    def transcribe(self, audio):
        try:
            result = self._primary.transcribe(audio)
            self.last_engine = self._names[0]
            return result
        except Exception as exc:
            if self._on_fallback:
                self._on_fallback(exc)
            if self._backup is None:
                why = (f'nạp lỗi: {self._backup_error}' if self._backup_error
                       else 'đang tải/nạp')
                raise BackupNotReady(
                    f'{self._names[0]} lỗi ({exc}); {self._names[1]} chưa sẵn sàng ({why})'
                ) from exc
            self.last_engine = self._names[1]
            return self._backup.transcribe(audio)


def make_backend(name, model_path='', whisper_model='small', language='vi',
                 sample_rate=16000, grammar=None, prompt=None, hints=(),
                 fallback='', lazy_fallback=False, on_fallback=None,
                 on_backup_ready=None):
    """name: vosk | whisper | google. fallback: '' / 'none' or another backend name,
    used only when `name` raises (for example Google without network).
    lazy_fallback: load the fallback in a background thread."""
    if name == 'vosk':
        if not model_path:
            raise RuntimeError('Backend vosk cần tham số model_path')
        backend = VoskBackend(model_path, sample_rate, grammar)
    elif name == 'whisper':
        backend = WhisperBackend(whisper_model, language, prompt=prompt)
    elif name == 'google':
        backend = GoogleBackend(language, sample_rate, hints)
    else:
        raise RuntimeError(f'Backend không hợp lệ: {name}')
    if not fallback or fallback in ('none', name):
        return backend

    def build_backup():
        return make_backend(fallback, model_path, whisper_model, language, sample_rate,
                            grammar, prompt, hints)

    backup = build_backup if lazy_fallback else build_backup()
    return FallbackBackend(backend, backup, name, fallback, on_fallback=on_fallback,
                           on_backup_ready=on_backup_ready)

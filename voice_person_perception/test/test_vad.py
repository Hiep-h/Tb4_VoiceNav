import numpy as np

from voice_person_perception.asr_backends import is_hallucination
from voice_person_perception.vad import EnergyVad, resample_to

RATE = 16000
RNG = np.random.default_rng(0)


def noise(seconds, level=40):
    return (RNG.standard_normal(int(RATE * seconds)) * level).astype(np.int16)


def tone(seconds, amp=4000):
    t = np.arange(int(RATE * seconds)) / RATE
    return (amp * np.sin(2 * np.pi * 220 * t)).astype(np.int16)


def run(vad, signal, chunk=1600):
    out = []
    for i in range(0, len(signal), chunk):
        out += vad.feed(signal[i:i + chunk])
    return out


def test_noise_only_gives_no_utterance():
    assert run(EnergyVad(), noise(5)) == []


def test_one_utterance_with_preroll_and_length():
    signal = np.concatenate([noise(1), tone(1.0), noise(1.5)])
    utts = run(EnergyVad(), signal)
    assert len(utts) == 1
    seconds = len(utts[0]) / RATE
    assert 1.0 <= seconds <= 1.8


def test_two_utterances_separated_by_silence():
    signal = np.concatenate([noise(1), tone(0.8), noise(1.2), tone(0.8), noise(1.5)])
    assert len(run(EnergyVad(), signal)) == 2


def test_short_click_is_ignored():
    signal = np.concatenate([noise(1), tone(0.1), noise(1.5)])
    assert run(EnergyVad(), signal) == []


def test_long_speech_is_split():
    utts = run(EnergyVad(max_utterance_s=2.0), np.concatenate([noise(1), tone(5), noise(1.5)]))
    assert len(utts) >= 2


def test_threshold_follows_noise_floor():
    vad = EnergyVad()
    run(vad, noise(2, level=400))
    assert vad.threshold > 1000


def test_resample_length():
    audio = tone(1.0)
    assert abs(len(resample_to(audio, 48000, 16000)) - len(audio) // 3) <= 2
    assert resample_to(audio, 16000, 16000) is audio


def test_hallucination_filter():
    assert is_hallucination('Hãy đăng ký kênh để ủng hộ')
    assert not is_hallucination('mang đến phòng khách')


def test_clear_keeps_noise_floor_and_observe_noise_calibrates():
    import numpy as np
    from voice_person_perception.vad import EnergyVad
    rng = np.random.default_rng(0)
    vad = EnergyVad(16000)
    noise = rng.normal(0, 100, 16000).astype(np.int16)
    vad.observe_noise(noise)
    assert not vad.calibrating
    floor = vad.threshold
    assert floor > vad.min_rms  # 3 x ~100 rms is above min_rms 250
    t = np.arange(4800) / 16000
    vad.feed((5000 * np.sin(2 * np.pi * 300 * t)).astype(np.int16))
    assert vad.in_speech
    vad.clear()
    assert not vad.in_speech and vad.threshold == floor


def _tone(seconds, amp, rate=16000):
    import numpy as np
    t = np.arange(int(seconds * rate)) / rate
    return (amp * np.sin(2 * np.pi * 300 * t)).astype(np.int16)


def _quiet(seconds, rate=16000, seed=1):
    import numpy as np
    return np.random.default_rng(seed).normal(0, 60, int(seconds * rate)).astype(np.int16)


def test_soft_syllables_and_pauses_do_not_split_a_sentence():
    import numpy as np
    from voice_person_perception.vad import EnergyVad
    # loud word, soft word (between release and start threshold), 1 s pause, loud word
    audio = np.concatenate([_quiet(1.0), _tone(0.6, 4000), _tone(0.6, 350), _quiet(1.0),
                            _tone(0.6, 4000), _quiet(2.0)])
    old = EnergyVad(16000, end_silence_ms=700)
    new = EnergyVad(16000, end_silence_ms=1500, release_ratio=0.6)
    assert len(old.feed(audio)) == 2  # the old setting cut the sentence in two
    parts = new.feed(audio)
    assert len(parts) == 1 and len(parts[0]) / 16000 > 2.5


def test_flush_ends_sentence_now():
    import numpy as np
    from voice_person_perception.vad import EnergyVad
    vad = EnergyVad(16000, end_silence_ms=1500)
    assert vad.feed(np.concatenate([_quiet(1.0), _tone(1.0, 4000)])) == []
    assert vad.in_speech
    audio = vad.flush()
    assert audio is not None and len(audio) / 16000 >= 0.9
    assert not vad.in_speech and vad.flush() is None


def test_normalize_peak():
    import numpy as np
    from voice_person_perception.vad import normalize_peak
    quiet = _tone(0.5, 4000)
    loud = normalize_peak(quiet)
    assert abs(int(np.max(np.abs(loud))) - int(0.7 * 32767)) < 100
    assert normalize_peak(_tone(0.5, 30000)) is not None
    assert np.array_equal(normalize_peak(_tone(0.5, 30000)), _tone(0.5, 30000))
    tiny = normalize_peak(_tone(0.5, 100))  # gain capped at 8x: noise is not blown up
    assert int(np.max(np.abs(tiny))) <= 801
    assert len(normalize_peak(np.zeros(0, dtype=np.int16))) == 0


def test_soft_last_word_is_not_trimmed():
    import numpy as np
    from voice_person_perception.vad import EnergyVad
    # "đi tới trạm" loud, then a soft "sạc" below the release threshold, then silence
    audio = np.concatenate([_quiet(1.0), _tone(1.0, 4000), _tone(0.4, 200), _quiet(2.0)])
    old = EnergyVad(16000, end_silence_ms=1500, release_ratio=0.6)
    new = EnergyVad(16000, end_silence_ms=1500, release_ratio=0.6, tail_ms=600)
    (cut,) = old.feed(audio)
    (kept,) = new.feed(audio)
    assert len(cut) / 16000 < 1.4      # old: soft word trimmed with the silence
    assert len(kept) / 16000 >= 1.6   # new: loud part + soft word kept


def _voice(seconds, rate=16000, amp=6000):
    import numpy as np
    t = np.arange(int(seconds * rate)) / rate
    phase = 2 * np.pi * np.cumsum(130 * (1 + 0.05 * np.sin(2 * np.pi * 3 * t))) / rate
    s = sum(np.sin(k * phase) / k for k in range(1, 25))
    env = 0.55 + 0.45 * np.sin(2 * np.pi * 4 * t) ** 2
    return amp * env * s / np.max(np.abs(s))


def test_webrtc_vad_cuts_a_voice_like_sentence():
    import numpy as np
    import pytest
    pytest.importorskip('webrtcvad')
    from voice_person_perception.vad import WebRtcVad, make_vad
    audio = np.concatenate([_quiet(1.0), _voice(1.2), _quiet(1.5)]).astype(np.int16)
    for vad in (WebRtcVad(16000, aggressiveness=2), make_vad('webrtc', 16000)):
        (utt,) = vad.feed(audio)
        assert 1.1 <= len(utt) / 16000 <= 2.0


def test_webrtc_vad_ignores_steady_hiss_after_calibration():
    import numpy as np
    import pytest
    pytest.importorskip('webrtcvad')
    from voice_person_perception.vad import WebRtcVad
    rng = np.random.default_rng(3)
    hiss = rng.normal(0, 700, 16000 * 4).astype(np.int16)
    assert WebRtcVad(16000, aggressiveness=3).feed(hiss) == []


def test_make_vad_rejects_unknown_kind():
    import pytest
    from voice_person_perception.vad import EnergyVad, make_vad
    assert isinstance(make_vad('energy', 16000), EnergyVad)
    with pytest.raises(ValueError):
        make_vad('magic', 16000)


def test_spectral_denoise_reduces_steady_noise():
    import numpy as np
    from voice_person_perception.denoise import NoiseProfile, spectral_denoise
    rng = np.random.default_rng(4)
    clean = _voice(1.5)
    noisy = (clean + rng.normal(0, 1500, len(clean))).astype(np.int16)
    profile = NoiseProfile(16000, seconds=1.0)
    for _ in range(20):
        profile.add(rng.normal(0, 1500, 1600).astype(np.int16))
    assert profile.seconds() == 1.0   # keeps only the last second
    out = spectral_denoise(noisy, profile.get())
    assert out.dtype == np.int16 and len(out) == len(noisy)

    def snr(x):
        return 10 * np.log10(np.sum(clean ** 2) / np.sum((x.astype(float) - clean) ** 2))
    assert snr(out) > snr(noisy) + 2.0


def test_spectral_denoise_needs_enough_noise():
    import numpy as np
    from voice_person_perception.denoise import spectral_denoise
    audio = _tone(0.5, 3000)
    assert np.array_equal(spectral_denoise(audio, np.zeros(100, np.int16)), audio)
    assert len(spectral_denoise(np.zeros(0, np.int16), _quiet(1.0))) == 0


def test_spectral_denoise_does_not_spike_at_the_edges():
    import numpy as np
    from voice_person_perception.denoise import spectral_denoise
    rng = np.random.default_rng(5)
    clean = _voice(1.0)
    noisy = (clean + rng.normal(0, 400, len(clean))).astype(np.int16)
    out = spectral_denoise(noisy, rng.normal(0, 400, 16000).astype(np.int16))
    assert np.max(np.abs(out.astype(int))) <= np.max(np.abs(noisy.astype(int))) * 1.2
    assert np.max(np.abs(out[:64].astype(int))) < 3000
    assert np.max(np.abs(out[-64:].astype(int))) < 3000

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

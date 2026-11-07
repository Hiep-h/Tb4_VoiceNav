"""Measure speech recognition + command understanding on a real microphone.

Same code path as the robot: EnergyVad cuts the utterance, the ASR backend
transcribes it, intent.parse_utterance resolves it. No ROS needed.

Record once, then compare backends on the SAME audio:

    # 1) record (and evaluate with Vosk)
    ros2 run voice_person_perception eval_voice --backend vosk \\
        --model-path models/vosk-model-small-vn-0.4 --reps 3 --record-dir eval_audio/hiep
    # 2) replay the saved audio with other settings
    ros2 run voice_person_perception eval_voice --backend vosk \\
        --model-path models/vosk-model-small-vn-0.4 --vosk-grammar --from-dir eval_audio/hiep
    ros2 run voice_person_perception eval_voice --backend whisper --from-dir eval_audio/hiep

Each run prints a summary and writes results.csv next to the audio, so wrong
transcripts can be added as aliases in destinations.yaml.
"""

from __future__ import annotations

import argparse
import csv
import os
import statistics
import sys
import time
import wave
from dataclasses import dataclass

import numpy as np
import yaml

from voice_person_perception import vocab
from voice_person_perception.intent import load_destinations, parse_utterance
from voice_person_perception.vad import EnergyVad

RATE = 16000
LEAD_IN_S = 1.0  # silence before "NÓI", used by the VAD to measure room noise

# Outcome classes, from best to worst.
CORRECT_AUTO = 'correct_auto'        # right, robot acts at once
CORRECT_CONFIRM = 'correct_confirm'  # right, robot asks before acting
WRONG_CONFIRM = 'wrong_confirm'      # wrong, but robot asks first (safe)
MISSED = 'missed'                    # no text recognised
WRONG_AUTO = 'wrong_auto'            # wrong and acted on: the dangerous case
OUTCOMES = (CORRECT_AUTO, CORRECT_CONFIRM, WRONG_CONFIRM, MISSED, WRONG_AUTO)


@dataclass
class Case:
    id: str
    say: str
    expect_intent: str
    expect_destination: str | None


def load_cases(data):
    cases = []
    for i, item in enumerate(data['cases'], 1):
        cases.append(Case(item.get('id', f'c{i:02d}'), item['say'],
                          item['expect_intent'], item.get('expect_destination')))
    return cases


def classify(case, text, result):
    """Outcome class of one attempt. result is a ParseResult or None."""
    if not text or result is None:
        return MISSED
    right = (result.intent == case.expect_intent
             and (case.expect_intent != 'GO_TO'
                  or result.destination == case.expect_destination))
    asks = result.intent == 'GO_TO' and result.needs_confirm
    if right:
        return CORRECT_CONFIRM if asks else CORRECT_AUTO
    if result.intent == 'UNKNOWN' or asks:
        return WRONG_CONFIRM  # robot does nothing or asks back
    return WRONG_AUTO


def summarize(rows):
    """rows: dicts with 'outcome' and 'asr_s'. Returns counts and latency stats."""
    n = len(rows)
    counts = {o: sum(1 for r in rows if r['outcome'] == o) for o in OUTCOMES}
    lat = sorted(r['asr_s'] for r in rows if r['asr_s'] is not None)
    return {
        'n': n,
        'counts': counts,
        'accuracy': (counts[CORRECT_AUTO] + counts[CORRECT_CONFIRM]) / n if n else 0.0,
        'latency_mean_s': statistics.mean(lat) if lat else None,
        'latency_p90_s': lat[min(len(lat) - 1, int(0.9 * len(lat)))] if lat else None,
    }


def cut_utterance(audio, rate=RATE):
    """Longest VAD utterance in a recording; the whole speech part if VAD finds none."""
    vad = EnergyVad(rate)
    pad = np.zeros(rate, dtype=np.int16)  # trailing silence closes the utterance
    found = vad.feed(np.concatenate([audio, pad]))
    found = [u for u in found if u is not None]
    if found:
        return max(found, key=len)
    return audio[int(LEAD_IN_S * rate):]


def save_wav(path, audio, rate=RATE):
    with wave.open(path, 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(audio.astype(np.int16).tobytes())


def load_wav(path):
    with wave.open(path, 'rb') as w:
        if w.getnchannels() != 1 or w.getsampwidth() != 2 or w.getframerate() != RATE:
            raise ValueError(f'{path}: cần WAV mono 16-bit {RATE} Hz')
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)


def record(seconds, device=None):
    import sounddevice as sd
    total = LEAD_IN_S + seconds
    buf = sd.rec(int(total * RATE), samplerate=RATE, channels=1, dtype='int16',
                 device=device)
    time.sleep(LEAD_IN_S)
    print('   >>> NÓI <<<', flush=True)
    sd.wait()
    return buf[:, 0].copy()


def _package_config(name):
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = []
    try:
        from ament_index_python.packages import get_package_share_directory
        candidates.append(os.path.join(
            get_package_share_directory('voice_person_perception'), 'config', name))
    except Exception:
        pass
    candidates.append(os.path.join(here, '..', 'config', name))
    for path in candidates:
        if os.path.isfile(path):
            return path
    return candidates[-1]


def _read_yaml(path):
    with open(path, encoding='utf-8') as f:
        return yaml.safe_load(f)


def _attempts(args, cases):
    """Yield (case, rep, wav_path, audio) from the mic or from a folder."""
    by_id = {c.id: c for c in cases}
    if args.from_dir:
        with open(os.path.join(args.from_dir, 'manifest.csv'), encoding='utf-8') as f:
            for row in csv.DictReader(f):
                case = by_id.get(row['case'])
                if case is None:
                    print(f"Bỏ qua {row['wav']}: không có câu '{row['case']}'")
                    continue
                path = os.path.join(args.from_dir, row['wav'])
                yield case, int(row['rep']), path, load_wav(path)
        return

    out_dir = args.record_dir
    manifest = None
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        manifest = open(os.path.join(out_dir, 'manifest.csv'), 'w', newline='',
                        encoding='utf-8')
        writer = csv.writer(manifest)
        writer.writerow(['case', 'rep', 'wav', 'say'])
    device = None if args.device_index < 0 else args.device_index
    try:
        for rep in range(1, args.reps + 1):
            for case in cases:
                print(f'\n[{rep}/{args.reps}] {case.id}: "{case.say}"')
                input('   Enter để bắt đầu (im lặng 1 s rồi nói)...')
                audio = record(args.seconds, device)
                path = None
                if out_dir:
                    name = f'{case.id}_r{rep}.wav'
                    path = os.path.join(out_dir, name)
                    save_wav(path, audio)
                    writer.writerow([case.id, rep, name, case.say])
                    manifest.flush()
                yield case, rep, path, audio
    finally:
        if manifest:
            manifest.close()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--backend', choices=['vosk', 'whisper'], default='vosk')
    ap.add_argument('--model-path', default='', help='thư mục model Vosk')
    ap.add_argument('--whisper-model', default='small')
    ap.add_argument('--vosk-grammar', action='store_true',
                    help='Vosk chỉ nhận câu mẫu sinh từ destinations.yaml')
    ap.add_argument('--whisper-prompt', action='store_true',
                    help='gợi ý tên điểm đến cho Whisper')
    ap.add_argument('--destinations', default='', help='mặc định config/destinations.yaml')
    ap.add_argument('--phrases', default='', help='mặc định config/eval_phrases.yaml')
    ap.add_argument('--reps', type=int, default=3, help='số lần nói mỗi câu')
    ap.add_argument('--seconds', type=float, default=4.0, help='thời gian ghi mỗi câu')
    ap.add_argument('--device-index', type=int, default=-1)
    src = ap.add_mutually_exclusive_group()
    src.add_argument('--record-dir', default='', help='lưu WAV để chạy lại sau')
    src.add_argument('--from-dir', default='', help='chạy lại trên WAV đã lưu')
    ap.add_argument('--out', default='', help='file CSV kết quả')
    args = ap.parse_args(argv)

    dest_data = _read_yaml(args.destinations or _package_config('destinations.yaml'))
    destinations = load_destinations(dest_data)
    cases = load_cases(_read_yaml(args.phrases or _package_config('eval_phrases.yaml')))

    from voice_person_perception.asr_backends import make_backend
    grammar = vocab.vosk_grammar(dest_data) if args.vosk_grammar else None
    prompt = vocab.whisper_prompt(dest_data) if args.whisper_prompt else None
    backend = make_backend(args.backend, args.model_path, args.whisper_model, 'vi',
                           RATE, grammar=grammar, prompt=prompt)
    label = args.backend + ('+grammar' if grammar else '') + ('+prompt' if prompt else '')

    rows = []
    for case, rep, path, audio in _attempts(args, cases):
        utt = cut_utterance(audio)
        t0 = time.monotonic()
        out = backend.transcribe(utt)
        asr_s = time.monotonic() - t0
        text, conf = out if out else ('', 0.0)
        result = parse_utterance(text, destinations, asr_conf=conf) if text else None
        outcome = classify(case, text, result)
        rows.append({
            'config': label, 'case': case.id, 'rep': rep, 'say': case.say,
            'heard': text, 'asr_conf': round(conf, 2), 'asr_s': round(asr_s, 3),
            'intent': result.intent if result else '',
            'destination': (result.destination or '') if result else '',
            'needs_confirm': result.needs_confirm if result else '',
            'expect_intent': case.expect_intent,
            'expect_destination': case.expect_destination or '',
            'outcome': outcome, 'wav': os.path.basename(path) if path else '',
        })
        mark = 'OK ' if outcome in (CORRECT_AUTO, CORRECT_CONFIRM) else 'SAI'
        print(f'   {mark} nghe "{text}" -> {rows[-1]["intent"]} '
              f'{rows[-1]["destination"]} ({outcome}, {asr_s:.2f}s)')

    if not rows:
        print('Không có mẫu nào.')
        return 1

    out_path = args.out or os.path.join(
        args.from_dir or args.record_dir or '.', f'results_{label}.csv')
    with open(out_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    s = summarize(rows)
    print(f'\n=== {label}: {s["n"]} mẫu ===')
    print(f'Đúng (kể cả hỏi lại): {s["accuracy"]:.0%}')
    for o in OUTCOMES:
        print(f'  {o:16s} {s["counts"][o]}')
    if s['latency_mean_s'] is not None:
        print(f'Thời gian nhận dạng: TB {s["latency_mean_s"]:.2f}s, '
              f'p90 {s["latency_p90_s"]:.2f}s (chỉ khâu ASR, sau khi nói xong)')
    print(f'Chi tiết: {out_path}')
    return 0


if __name__ == '__main__':
    sys.exit(main())

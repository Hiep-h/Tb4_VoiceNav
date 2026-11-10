"""Command vocabulary built from destinations.yaml, used to bias speech recognition.

- Vosk: a grammar (list of allowed phrases). Recognition only returns these
  phrases or "[unk]", which raises accuracy a lot on a small command set but
  cuts free speech that is not in the list. So it is optional (`vosk_grammar`).
- Whisper: a short `initial_prompt` naming the destinations, so rare names are
  spelled the way destinations.yaml spells them.

Pure Python (no ROS) so it can be unit-tested.
"""

from __future__ import annotations

UNK = '[unk]'

# Ways people ask for a delivery. "{}" is the station.
GO_TEMPLATES = (
    '{}',
    'đi đến {}', 'đi tới {}', 'đến {}', 'tới {}', 'ra {}', 'về {}',
    'mang đến {}', 'mang tới {}', 'mang hàng đến {}', 'mang đồ đến {}',
    'giao đến {}', 'giao hàng đến {}', 'giao tới {}', 'chở đến {}', 'đem đến {}',
)
CHANGE_TEMPLATES = ('đổi sang {}', 'đổi đích sang {}', 'chuyển sang {}', 'đổi đến {}')
ROUTE_TEMPLATES = ('từ {} đến {}', 'mang hàng từ {} đến {}', 'lấy hàng ở {} giao đến {}')

# Must stay in line with the keyword patterns in intent.py.
PAUSE_PHRASES = ('dừng', 'dừng lại', 'tạm dừng', 'ngừng', 'ngừng lại', 'đứng lại',
                 'chờ đã', 'khẩn cấp', 'robot dừng lại')
RESUME_PHRASES = ('tiếp tục', 'đi tiếp', 'chạy tiếp', 'tiếp tục giao')
CANCEL_PHRASES = ('hủy', 'hủy đơn', 'hủy lệnh', 'bỏ qua', 'không cần', 'không cần nữa', 'thôi')
STATUS_PHRASES = ('trạng thái', 'đơn hàng đến đâu rồi', 'đến đâu rồi', 'robot đang ở đâu',
                  'giao xong chưa', 'bao giờ đến')


def destination_phrases(data):
    """Every name and alias in destinations.yaml, in file order, no duplicates."""
    phrases = []
    for item in data['destinations']:
        phrases.append(item.get('name', item['id']))
        phrases.extend(item.get('aliases', []))
    return list(dict.fromkeys(p.strip().lower() for p in phrases if p and p.strip()))


def vosk_grammar(data, templates=GO_TEMPLATES):
    """All allowed phrases for a Vosk KaldiRecognizer grammar, plus "[unk]"."""
    phrases = []
    for dest in destination_phrases(data):
        # Vosk models spell numbers as words ("một không một"); a phrase with
        # digits would lose them, so rely on the spelled-out aliases instead.
        if any(c.isdigit() for c in dest):
            continue
        phrases.extend(t.format(dest) for t in templates)
        phrases.extend(t.format(dest) for t in CHANGE_TEMPLATES)
    names = [n for n in (str(i.get('name', i['id'])).lower() for i in data['destinations'])
             if not any(c.isdigit() for c in n)]
    for src in names:  # source -> destination, main names only to keep the list short
        for dst in names:
            if src != dst:
                phrases.extend(t.format(src, dst) for t in ROUTE_TEMPLATES)
    for group in (PAUSE_PHRASES, RESUME_PHRASES, CANCEL_PHRASES, STATUS_PHRASES):
        phrases.extend(group)
    phrases = list(dict.fromkeys(phrases))
    phrases.append(UNK)
    return phrases


def whisper_prompt(data):
    """Short prompt naming the destination names (not every alias)."""
    names = [item.get('name', item['id']) for item in data['destinations']]
    return 'Lệnh cho robot giao hàng. Các trạm: ' + ', '.join(names) + '.'

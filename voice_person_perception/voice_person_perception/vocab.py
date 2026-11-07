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

# Ways people start a delivery command. "{}" is the destination.
GO_TEMPLATES = (
    '{}',
    'đi đến {}', 'đi tới {}', 'đến {}', 'tới {}', 'ra {}', 'vào {}', 'về {}',
    'mang đến {}', 'mang tới {}', 'mang đồ đến {}', 'mang đồ tới {}',
    'mang cái này đến {}', 'giao đến {}', 'giao đồ đến {}', 'giao hàng đến {}',
    'di chuyển đến {}', 'chở đến {}', 'đem đến {}', 'đem đồ đến {}',
)

# Must stay in line with the STOP/CANCEL patterns in intent.py.
STOP_PHRASES = ('dừng', 'dừng lại', 'ngừng', 'ngừng lại', 'đứng lại', 'khẩn cấp',
                'robot dừng lại')
CANCEL_PHRASES = ('hủy', 'hủy lệnh', 'bỏ qua', 'không cần', 'không cần nữa', 'thôi')


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
    phrases.extend(STOP_PHRASES)
    phrases.extend(CANCEL_PHRASES)
    phrases = list(dict.fromkeys(phrases))
    phrases.append(UNK)
    return phrases


def whisper_prompt(data):
    """Short prompt naming the destination names (not every alias)."""
    names = [item.get('name', item['id']) for item in data['destinations']]
    return 'Lệnh cho robot giao đồ. Các điểm đến: ' + ', '.join(names) + '.'

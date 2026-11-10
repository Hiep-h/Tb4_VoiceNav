"""Turn a Vietnamese transcript into one of the team's voice intents
(docs/interfaces.md section 2) with source and destination stations.

Pure Python (no ROS) so it can be unit-tested.

Order of checks (first match wins):
  PAUSE               "dừng lại", "tạm dừng", "đứng lại", "chờ đã"
  CHANGE_DESTINATION  "đổi/chuyển/thay ... (sang) trạm C"   (needs a station)
  CANCEL              "hủy", "không cần nữa", "thôi"
  RESUME              "tiếp tục", "đi tiếp"                 (no station named)
  GET_STATUS          "đến đâu rồi", "trạng thái", "xong chưa"
  CREATE_DELIVERY     a station is named: "mang từ trạm A đến trạm B", "giao đến B"
  UNKNOWN             nothing above (e.g. a place that is not a station)

Keywords are matched on the accented text, because after accent removal
"dừng"/"đúng"/"dùng" and "từ"/"tủ" collapse to the same word.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from rapidfuzz import fuzz

from voice_person_perception.contract import (
    INTENT_CANCEL,
    INTENT_CHANGE_DESTINATION,
    INTENT_CREATE_DELIVERY,
    INTENT_GET_STATUS,
    INTENT_PAUSE,
    INTENT_RESUME,
    INTENT_UNKNOWN,
)


def _words(*phrases):
    return re.compile(r'(?<!\w)(' + '|'.join(phrases) + r')(?!\w)')


_PAUSE_RE = _words('dừng lại', 'tạm dừng', 'dừng', 'ngừng', 'đứng lại', 'đứng yên',
                   'khẩn cấp', 'chờ đã', 'đợi đã', 'khoan đã', 'stop')
_PAUSE_PLAIN_RE = _words('dung lai', 'tam dung', 'ngung', 'dung yen', 'stop')
_CHANGE_RE = _words('đổi', 'chuyển', 'thay')
_CHANGE_PLAIN_RE = _words('doi dich', 'doi sang', 'chuyen', 'thay doi')
_CANCEL_RE = _words('hủy', 'huỷ', 'bỏ qua', 'không cần', 'thôi')
_CANCEL_PLAIN_RE = _words('huy', 'bo qua', 'khong can')
_RESUME_RE = _words('tiếp tục', 'đi tiếp', 'chạy tiếp', 'tiếp đi', 'giao tiếp')
_RESUME_PLAIN_RE = _words('tiep tuc', 'di tiep', 'chay tiep')
_STATUS_RE = _words('trạng thái', 'đến đâu', 'tới đâu', 'ở đâu', 'bao giờ', 'khi nào',
                    'bao lâu', 'xong chưa', 'đến chưa', 'tới chưa', 'giao chưa', 'thế nào rồi')
_STATUS_PLAIN_RE = _words('trang thai', 'den dau', 'toi dau', 'bao gio', 'khi nao',
                          'bao lau', 'xong chua')

# Word right before a station that says what the station is for.
SOURCE_MARKERS = {'từ', 'ở', 'tại'}
DEST_MARKERS = {'đến', 'tới', 'sang', 'về', 'ra', 'vào', 'qua'}
SOURCE_MARKERS_PLAIN = {'tu', 'tai'}
DEST_MARKERS_PLAIN = {'den', 'toi', 'sang', 've', 'vao', 'qua'}

# How a single-letter station id may be heard when said without "trạm":
# "đến B" may come back as "đến b", "đến bê" or "đến bờ".
SPOKEN_LETTERS = {
    'a': ('a',),
    'b': ('b', 'be', 'bo'),
    'c': ('c', 'xe', 'ce', 'xi'),
    'd': ('d', 'de', 'do'),
}
LETTER_SCORE = 1.0          # "đến b": the letter itself after a marker
SPOKEN_LETTER_SCORE = 0.9   # "đến bê": a reading of it (asks to confirm)


def _nfc_lower(text):
    return unicodedata.normalize('NFC', text).lower()


def normalize(text):
    """Lowercase, drop accents (including đ) and punctuation."""
    text = _nfc_lower(text).replace('đ', 'd')
    text = unicodedata.normalize('NFD', text)
    text = ''.join(c for c in text if unicodedata.category(c) != 'Mn')
    text = re.sub(r'[^a-z0-9\s]', ' ', text)
    return ' '.join(text.split())


def _tokens(text):
    """Accented and unaccented tokens with the same indices."""
    accented = re.sub(r'[^\w\s]', ' ', _nfc_lower(text)).split()
    plain = [normalize(t) for t in accented]
    keep = [i for i, p in enumerate(plain) if p]
    return [accented[i] for i in keep], [plain[i] for i in keep]


@dataclass(frozen=True)
class Destination:
    id: str
    name: str
    aliases: tuple


def load_destinations(data):
    destinations = []
    for item in data['destinations']:
        name = item.get('name', item['id'])
        phrases = [name] + list(item.get('aliases', []))
        aliases = tuple(dict.fromkeys(normalize(p) for p in phrases if normalize(p)))
        destinations.append(Destination(str(item['id']), name, aliases))
    return destinations


def _is_strict(token):
    """Letters and numbers: "trạm a" vs "trạm b", "phòng 101" vs "phòng 102"."""
    return token.isdigit() or len(token) == 1


def _must_match(token):
    """Alias words that must be heard exactly: letters, numbers and short
    readings like "bê", "đê", "xê" ("diem de" must not match "di den")."""
    return _is_strict(token) or len(token) <= 2


def best_alias_match(alias, utterance_tokens):
    """(score 0-100, start index) of an alias against windows of the utterance.

    Digits and single letters must match exactly, otherwise "tram a" and
    "tram b" would score 83 against each other.
    """
    alias_tokens = alias.split()
    n = len(alias_tokens)
    best, start = 0.0, None
    for size in sorted({max(1, n - 1), n, n + 1}):
        for i in range(len(utterance_tokens) - size + 1):
            window = utterance_tokens[i:i + size]
            if not all(t in window for t in alias_tokens if _must_match(t)):
                continue
            # "trạm e" must not match "trạm bê": a letter or number the alias
            # does not have rules the window out.
            if any(_is_strict(t) and t not in alias_tokens for t in window):
                continue
            score = fuzz.ratio(alias, ' '.join(window))
            if score > best:
                best, start = score, i
    return best, start


def score_alias(alias, utterance_tokens):
    return best_alias_match(alias, utterance_tokens)[0]


@dataclass
class StationMatch:
    id: str
    score: float      # 0-1
    start: int        # token index where the match begins
    role: str | None  # 'source', 'dest' or None (no marker before it)


def _role(i, accented, plain, has_accents):
    if i is None or i == 0:
        return None
    before = accented[i - 1] if has_accents else plain[i - 1]
    if before in (SOURCE_MARKERS if has_accents else SOURCE_MARKERS_PLAIN):
        return 'source'
    if before in (DEST_MARKERS if has_accents else DEST_MARKERS_PLAIN):
        return 'dest'
    return None


def match_stations(text, destinations):
    """Best match of every destination in the text, best score first."""
    accented, plain = _tokens(text)
    has_accents = accented != plain
    markers = (SOURCE_MARKERS | DEST_MARKERS) if has_accents else (
        SOURCE_MARKERS_PLAIN | DEST_MARKERS_PLAIN)
    words = accented if has_accents else plain
    out = []
    for dest in destinations:
        score, start = 0.0, None
        for alias in dest.aliases:
            s, i = best_alias_match(alias, plain)
            if s / 100.0 > score:
                score, start = s / 100.0, i
        letter = dest.id.lower()
        for reading in SPOKEN_LETTERS.get(letter, ()):  # bare letter after a marker
            value = LETTER_SCORE if reading == letter else SPOKEN_LETTER_SCORE
            for i in range(1, len(plain)):
                if plain[i] == reading and words[i - 1] in markers and value > score:
                    score, start = value, i
        # role: the word right before the match ("từ | trạm A", "đến | b")
        out.append(StationMatch(dest.id, score, start,
                                _role(start, accented, plain, has_accents)))
    out.sort(key=lambda m: m.score, reverse=True)
    return out


@dataclass
class ParseResult:
    intent: str
    destination: str | None
    confidence: float
    needs_confirm: bool
    candidates: list = field(default_factory=list)
    source: str | None = None


def _search(accented_re, plain_re, text):
    folded = _nfc_lower(text)
    if accented_re.search(folded):
        return True
    return folded == normalize(text) and plain_re.search(normalize(text)) is not None


def parse_utterance(text, destinations, asr_conf=1.0, accept=0.75,
                    confident=0.97, margin=0.10, min_asr_conf=0.6):
    asr_conf = min(max(asr_conf, 0.0), 1.0)

    def keyword(intent):
        return ParseResult(intent, None, asr_conf, False, [])

    if _search(_PAUSE_RE, _PAUSE_PLAIN_RE, text):
        return keyword(INTENT_PAUSE)

    matches = match_stations(text, destinations)
    found = [m for m in matches if m.score >= accept and m.start is not None]
    candidates = [{'station': m.id, 'score': round(m.score, 2)}
                  for m in matches[:3] if m.score > 0]

    if found and _search(_CHANGE_RE, _CHANGE_PLAIN_RE, text):
        dest = _pick_destination(found, change=True)
        return _station_result(INTENT_CHANGE_DESTINATION, None, dest, found, matches,
                               candidates, asr_conf, confident, margin, min_asr_conf)
    if _search(_CANCEL_RE, _CANCEL_PLAIN_RE, text):
        return keyword(INTENT_CANCEL)
    if not found and _search(_RESUME_RE, _RESUME_PLAIN_RE, text):
        return keyword(INTENT_RESUME)
    if _search(_STATUS_RE, _STATUS_PLAIN_RE, text):
        return keyword(INTENT_GET_STATUS)
    if not found:
        return ParseResult(INTENT_UNKNOWN, None, 0.0, False, candidates)

    dest = _pick_destination(found)
    source = _pick_source(found, dest)
    return _station_result(INTENT_CREATE_DELIVERY, source, dest, found, matches, candidates,
                           asr_conf, confident, margin, min_asr_conf)


def _pick_destination(found, change=False):
    marked = [m for m in found if m.role == 'dest']
    if marked:
        return max(marked, key=lambda m: m.score)
    unmarked = [m for m in found if m.role is None]
    if change:
        pool = unmarked or found
        return max(pool, key=lambda m: m.start)  # "đổi từ B sang C": the later one
    if len(found) >= 2 and unmarked:
        # "trạm A trạm B": first is the source, last the destination
        return max(found, key=lambda m: m.start)
    if unmarked:
        return max(unmarked, key=lambda m: m.score)
    return None  # only "từ trạm A": no destination given


def _pick_source(found, dest):
    others = [m for m in found if dest is None or m.id != dest.id]
    marked = [m for m in others if m.role == 'source']
    if marked:
        return max(marked, key=lambda m: m.score)
    if dest is not None and dest.role is None:
        earlier = [m for m in others if m.role is None and m.start < dest.start]
        if earlier:
            return min(earlier, key=lambda m: m.start)
    return None


def _station_result(intent, source, dest, found, matches, candidates, asr_conf,
                    confident, margin, min_asr_conf):
    used = {m.id for m in (source, dest) if m is not None}
    # a station said as "từ B" in "đổi từ B sang C" is not competing with C
    used |= {m.id for m in found if m.role == 'source'}
    rivals = [m.score for m in matches if m.id not in used]
    main = dest or source
    second = rivals[0] if rivals else 0.0
    needs_confirm = (
        dest is None                       # nobody said where to deliver
        or main.score < confident
        or (source is not None and source.score < confident)
        or main.score - second < margin
        or asr_conf < min_asr_conf)
    return ParseResult(intent, dest.id if dest else None, main.score * asr_conf,
                       needs_confirm, candidates, source.id if source else None)

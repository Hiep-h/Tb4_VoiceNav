"""Turn a Vietnamese transcript into an intent and a known destination.

Pure Python (no ROS) so it can be unit-tested. STOP/CANCEL are matched on the
accented text because after accent removal "dừng", "đúng" and "dùng" all
collapse to "dung".
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from rapidfuzz import fuzz

from voice_person_perception.contract import (
    INTENT_CANCEL,
    INTENT_GO_TO,
    INTENT_STOP,
    INTENT_UNKNOWN,
)

_STOP_RE = re.compile(
    r'(?<!\w)(dừng lại|dừng|ngừng|đứng lại|khẩn cấp|stop)(?!\w)')
_CANCEL_RE = re.compile(r'(?<!\w)(hủy|huỷ|bỏ qua|không cần|thôi)(?!\w)')
_UNACCENTED_STOP_RE = re.compile(r'(?<!\w)(dung lai|ngung|stop)(?!\w)')


def _nfc_lower(text):
    return unicodedata.normalize('NFC', text).lower()


def normalize(text):
    """Lowercase, drop accents (including đ) and punctuation."""
    text = _nfc_lower(text).replace('đ', 'd')
    text = unicodedata.normalize('NFD', text)
    text = ''.join(c for c in text if unicodedata.category(c) != 'Mn')
    text = re.sub(r'[^a-z0-9\s]', ' ', text)
    return ' '.join(text.split())


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
        aliases = tuple(dict.fromkeys(normalize(p) for p in phrases))
        destinations.append(Destination(item['id'], name, aliases))
    return destinations


def _is_strict(token):
    return token.isdigit() or len(token) == 1


def _strict_tokens_present(alias_tokens, window):
    return all(t in window for t in alias_tokens if _is_strict(t))


def score_alias(alias, utterance_tokens):
    """Best fuzzy score (0-100) of an alias against windows of the utterance.

    Digits and single letters must match exactly, otherwise "phong a" and
    "phong b" would score 86 against each other.
    """
    alias_tokens = alias.split()
    n = len(alias_tokens)
    best = 0.0
    for size in {max(1, n - 1), n, n + 1}:
        for i in range(len(utterance_tokens) - size + 1):
            window = utterance_tokens[i:i + size]
            if not _strict_tokens_present(alias_tokens, window):
                continue
            best = max(best, fuzz.ratio(alias, ' '.join(window)))
    return best


def rank_destinations(text, destinations):
    tokens = normalize(text).split()
    ranked = []
    for dest in destinations:
        score = max((score_alias(a, tokens) for a in dest.aliases), default=0.0)
        ranked.append((dest.id, score / 100.0))
    ranked.sort(key=lambda item: item[1], reverse=True)
    return ranked


@dataclass
class ParseResult:
    intent: str
    destination: str | None
    confidence: float
    needs_confirm: bool
    candidates: list


def _has_accents(text):
    return _nfc_lower(text) != normalize(text)


def parse_utterance(text, destinations, asr_conf=1.0, accept=0.75,
                    confident=0.97, margin=0.10, min_asr_conf=0.6):
    folded = _nfc_lower(text)
    if _STOP_RE.search(folded) or (
            not _has_accents(text) and _UNACCENTED_STOP_RE.search(folded)):
        return ParseResult(INTENT_STOP, None, 1.0, False, [])
    if _CANCEL_RE.search(folded):
        return ParseResult(INTENT_CANCEL, None, 1.0, False, [])

    ranked = rank_destinations(text, destinations)
    candidates = [{'destination': d, 'score': round(s, 2)}
                  for d, s in ranked[:3] if s > 0]
    if not ranked or ranked[0][1] < accept:
        return ParseResult(INTENT_UNKNOWN, None, 0.0, False, candidates)

    best_id, best = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else 0.0
    asr_conf = min(max(asr_conf, 0.0), 1.0)
    needs_confirm = (best < confident or best - second < margin
                     or asr_conf < min_asr_conf)
    return ParseResult(INTENT_GO_TO, best_id, best * asr_conf, needs_confirm,
                       candidates)

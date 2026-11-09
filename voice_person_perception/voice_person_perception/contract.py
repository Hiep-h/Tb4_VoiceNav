"""Wire format shared with the executor; the written spec is INTERFACE.md."""

import json

SCHEMA_VERSION = 1

SPEECH_TEXT_TOPIC = '/speech_text'
VOICE_COMMAND_TOPIC = '/voice_command'
PERSON_TOPIC = '/person_detections'
ASR_MUTE_TOPIC = '/asr_mute'
ASR_STATUS_TOPIC = '/asr_status'
ASR_LISTEN_TOPIC = '/asr_listen'  # push-to-talk: True = listen for one sentence, False = cancel

# asr_node states shown by voice_gui
ASR_MUTED = 'muted'              # muted by the executor (/asr_mute), e.g. while robot speaks
ASR_IDLE = 'idle'                # push-to-talk: waiting for the button
ASR_CALIBRATING = 'calibrating'  # measuring room noise, keep quiet
ASR_LISTENING = 'listening'      # waiting for speech
ASR_SPEECH = 'speech'            # someone is talking
ASR_RECOGNIZING = 'recognizing'  # utterance sent to the recogniser

INTENT_GO_TO = 'GO_TO'
INTENT_STOP = 'STOP'
INTENT_CANCEL = 'CANCEL'
INTENT_UNKNOWN = 'UNKNOWN'


def dumps(payload):
    return json.dumps(payload, ensure_ascii=False, separators=(',', ':'))


def make_speech_text(stamp, text, asr_conf, latency_s, engine=None, audio_s=None):
    out = {
        'v': SCHEMA_VERSION,
        'stamp': round(stamp, 3),
        'text': text,
        'asr_conf': round(asr_conf, 3),
        'latency_s': round(latency_s, 3),
    }
    if engine:
        out['engine'] = engine        # which recogniser produced the text
    if audio_s is not None:
        out['audio_s'] = round(audio_s, 2)  # length of the sentence sent to it
    return out


def make_voice_command(seq, stamp, text, intent, destination, confidence,
                       needs_confirm, candidates):
    return {
        'v': SCHEMA_VERSION,
        'seq': seq,
        'stamp': round(stamp, 3),
        'text': text,
        'intent': intent,
        'destination': destination,
        'confidence': round(confidence, 3),
        'needs_confirm': needs_confirm,
        'candidates': candidates,
    }


def make_person(track_id, distance_m, bearing_deg, confidence, approaching):
    return {
        'id': track_id,
        'distance_m': None if distance_m is None else round(distance_m, 2),
        'bearing_deg': round(bearing_deg, 1) + 0.0,
        'confidence': round(confidence, 2),
        'approaching': approaching,
    }


def make_person_message(stamp, persons, healthy, frame_age_s):
    return {
        'v': SCHEMA_VERSION,
        'stamp': round(stamp, 3),
        'healthy': healthy,
        'frame_age_s': None if frame_age_s is None else round(frame_age_s, 2),
        'persons': persons,
    }


def make_asr_status(stamp, state, level, threshold, backend, fallback, backup_ready,
                    push_to_talk):
    return {
        'v': SCHEMA_VERSION,
        'stamp': round(stamp, 3),
        'state': state,
        'level': round(float(level), 1),
        'threshold': round(float(threshold), 1),
        'backend': backend,
        'fallback': fallback,
        'backup_ready': backup_ready,
        'push_to_talk': push_to_talk,
    }

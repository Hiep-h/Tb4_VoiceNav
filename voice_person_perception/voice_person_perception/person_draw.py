"""Draw person boxes on a camera frame for the debug image (no ROS).

Labels are ASCII because cv2.putText cannot draw Vietnamese accents:
"#3 1.2m L15 <-" = track 3, 1.2 m away, 15 degrees to the left, coming closer.
"""

import cv2

GREEN, ORANGE, RED, WHITE = (60, 180, 60), (0, 140, 255), (40, 40, 220), (255, 255, 255)


def person_label(person):
    parts = [f"#{person['id']}" if person.get('id') is not None else '#?']
    dist = person.get('distance_m')
    parts.append('?m' if dist is None else f'{dist:.1f}m')
    if person.get('source') in ('height', 'width'):
        parts[-1] += '~'  # rough estimate without depth
    b = person.get('bearing_deg', 0.0)
    parts.append('C' if abs(b) < 3 else f"{'L' if b > 0 else 'R'}{abs(b):.0f}")
    if person.get('approaching'):
        parts.append('<-')
    return ' '.join(parts)


def person_colour(person):
    if person.get('approaching'):
        return RED
    dist = person.get('distance_m')
    if dist is not None and dist < 1.0:
        return RED
    if dist is not None and dist < 2.0:
        return ORANGE
    return GREEN


def draw_persons(frame, boxes, persons):
    img = frame.copy()
    h, w = img.shape[:2]
    cv2.line(img, (w // 2, 0), (w // 2, h), (200, 200, 200), 1)  # bearing 0
    for box, person in zip(boxes, persons):
        x1, y1, x2, y2 = (int(v) for v in box)
        colour = person_colour(person)
        cv2.rectangle(img, (x1, y1), (x2, y2), colour, 2)
        label = person_label(person)
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 2)
        ty = max(th + 6, y1)
        cv2.rectangle(img, (x1, ty - th - 6), (x1 + tw + 6, ty), colour, -1)
        cv2.putText(img, label, (x1 + 3, ty - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.55, WHITE, 2,
                    cv2.LINE_AA)
    cv2.putText(img, f'{len(persons)} person(s)', (8, h - 10), cv2.FONT_HERSHEY_SIMPLEX,
                0.6, WHITE, 2, cv2.LINE_AA)
    return img

#!/usr/bin/env bash
# Tải model Vosk tiếng Việt nhỏ về models/ (https://alphacephei.com/vosk/models).
# vosk-model-small-vn-0.4 đã chạy được offline trong bài Tb4_VoiceNav_Map.
set -euo pipefail

MODEL="${1:-vosk-model-small-vn-0.4}"
DEST="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/models"
mkdir -p "$DEST"

if [ -d "$DEST/$MODEL" ]; then
  echo "Đã có $DEST/$MODEL"
  exit 0
fi

echo "Đang tải $MODEL ..."
curl -L --fail -o "$DEST/$MODEL.zip" "https://alphacephei.com/vosk/models/$MODEL.zip"
unzip -q "$DEST/$MODEL.zip" -d "$DEST"
rm "$DEST/$MODEL.zip"
echo "Xong: $DEST/$MODEL"

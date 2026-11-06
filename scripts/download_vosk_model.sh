#!/usr/bin/env bash
# Tải model Vosk tiếng Việt nhỏ về models/. Tên model theo trang https://alphacephei.com/vosk/models
# (chưa kiểm tra được trong lúc viết; nếu lỗi, vào trang đó lấy tên model Vietnamese mới nhất).
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

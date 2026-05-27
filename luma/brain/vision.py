from __future__ import annotations

import base64
from typing import Any


class VisionProvider:
    def __init__(self) -> None:
        try:
            import cv2  # type: ignore

            self._cv2 = cv2
            self._face_cascade = cv2.CascadeClassifier(
                cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
            )
        except Exception:
            self._cv2 = None
            self._face_cascade = None

    @property
    def available(self) -> bool:
        return self._cv2 is not None and self._face_cascade is not None

    def analyze_snapshot(self, image_b64: str, mime: str = "image/jpeg") -> dict[str, Any]:
        image_bytes = base64.b64decode(image_b64, validate=False)
        result: dict[str, Any] = {
            "mime": mime,
            "bytes": len(image_bytes),
            "person_detected": False,
            "target": None,
            "description": "Frame received. No local vision backend is installed.",
        }
        if not self.available:
            return result

        import numpy as np  # type: ignore

        cv2 = self._cv2
        arr = np.frombuffer(image_bytes, dtype=np.uint8)
        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if frame is None:
            result["description"] = "Frame received but could not be decoded."
            return result

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = self._face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(32, 32))
        if len(faces) == 0:
            result["description"] = "I do not see a person in front of me."
            return result

        x, y, w, h = max(faces, key=lambda item: item[2] * item[3])
        height, width = frame.shape[:2]
        result.update(
            {
                "person_detected": True,
                "target": {
                    "x": (x + w / 2) / width,
                    "y": (y + h / 2) / height,
                    "w": w / width,
                    "h": h / height,
                },
                "description": "I see a person in front of me.",
            }
        )
        return result


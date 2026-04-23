from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time
from typing import Iterator

import cv2
from ultralytics import YOLO


@dataclass
class FloatingDetectionResult:
    model_name: str
    model_path: str
    boxes: list[dict[str, float]]
    confidence: float
    frames_analyzed: int
    annotated_video_path: str | None = None


class FloatingDetector:
    """Run floating-object detection on sampled video frames using YOLO."""

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self._model_cache: YOLO | None = None

    def resolve_model(self) -> Path:
        best_model = self.project_root / "best_floating.pt"
        last_model = self.project_root / "last_floating.pt"

        if best_model.exists():
            return best_model
        if last_model.exists():
            return last_model
        raise FileNotFoundError("best_floating.pt / last_floating.pt 파일을 찾을 수 없습니다.")

    def _get_model(self) -> YOLO:
        if self._model_cache is None:
            self._model_cache = YOLO(str(self.resolve_model()))
        return self._model_cache

    def resolve_video(self) -> Path:
        candidates = [
            self.project_root / "floating_matters.mp4",
            self.project_root / "floating_matter.mp4",
        ]
        for path in candidates:
            if path.exists():
                return path
        raise FileNotFoundError("floating_matters.mp4 또는 floating_matter.mp4 파일을 찾을 수 없습니다.")

    def _extract_normalized_boxes(self, result, frame_w: int, frame_h: int) -> tuple[list[dict[str, float]], float]:
        detected_boxes: list[dict[str, float]] = []
        frame_best_conf = 0.0

        if result.boxes is None or len(result.boxes) == 0:
            return detected_boxes, frame_best_conf

        xyxy = result.boxes.xyxy.tolist()
        confs = result.boxes.conf.tolist() if result.boxes.conf is not None else [0.0] * len(xyxy)
        for raw_box, conf in zip(xyxy, confs):
            x1, y1, x2, y2 = raw_box
            x1 = max(0.0, min(float(x1), float(frame_w)))
            y1 = max(0.0, min(float(y1), float(frame_h)))
            x2 = max(0.0, min(float(x2), float(frame_w)))
            y2 = max(0.0, min(float(y2), float(frame_h)))

            w = max(0.0, x2 - x1)
            h = max(0.0, y2 - y1)
            if w <= 1.0 or h <= 1.0:
                continue

            detected_boxes.append(
                {
                    "x": x1 / frame_w,
                    "y": y1 / frame_h,
                    "w": w / frame_w,
                    "h": h / frame_h,
                    "confidence": float(conf),
                }
            )
            frame_best_conf = max(frame_best_conf, float(conf))

        return detected_boxes, frame_best_conf

    def get_video_duration(self, video_path: Path) -> float:
        capture = cv2.VideoCapture(str(video_path))
        if not capture.isOpened():
            return 0.0
        try:
            fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
            frame_count = float(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0)
            if fps <= 0.0 or frame_count <= 0.0:
                return 0.0
            return frame_count / fps
        finally:
            capture.release()

    def stream_detected_frames(self, video_path: Path, conf_threshold: float = 0.2) -> Iterator[bytes]:
        if not video_path.exists():
            raise FileNotFoundError(f"샘플 영상이 없습니다: {video_path.name}")

        capture = cv2.VideoCapture(str(video_path))
        if not capture.isOpened():
            raise RuntimeError(f"비디오를 열 수 없습니다: {video_path.name}")

        model = self._get_model()
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
        frame_interval = 1.0 / fps if fps > 0 else 1.0 / 24.0

        try:
            while True:
                ok, frame = capture.read()
                if not ok:
                    break

                frame_h, frame_w = frame.shape[:2]
                results = model.predict(source=frame, verbose=False)

                if results:
                    result = results[0]
                    boxes, _ = self._extract_normalized_boxes(result, frame_w, frame_h)
                    for box in boxes:
                        conf = float(box.get("confidence", 0.0))
                        if conf < conf_threshold:
                            continue

                        x1 = int(box["x"] * frame_w)
                        y1 = int(box["y"] * frame_h)
                        x2 = int((box["x"] + box["w"]) * frame_w)
                        y2 = int((box["y"] + box["h"]) * frame_h)

                        x1 = max(0, min(x1, frame_w - 1))
                        y1 = max(0, min(y1, frame_h - 1))
                        x2 = max(0, min(x2, frame_w - 1))
                        y2 = max(0, min(y2, frame_h - 1))

                        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 0, 255), 3)
                        cv2.putText(
                            frame,
                            f"floating {conf:.2f}",
                            (x1, max(20, y1 - 8)),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.65,
                            (255, 255, 255),
                            2,
                            cv2.LINE_AA,
                        )

                ok, buffer = cv2.imencode(".jpg", frame)
                if not ok:
                    continue

                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n" + buffer.tobytes() + b"\r\n"
                )
                time.sleep(frame_interval)
        finally:
            capture.release()

    def detect(self, video_path: Path) -> FloatingDetectionResult:
        if not video_path.exists():
            raise FileNotFoundError(f"샘플 영상이 없습니다: {video_path.name}")

        model_path = self.resolve_model()

        capture = cv2.VideoCapture(str(video_path))
        if not capture.isOpened():
            raise RuntimeError(f"비디오를 열 수 없습니다: {video_path.name}")

        model = self._get_model()
        best_confidence = 0.0
        best_boxes: list[dict[str, float]] = []
        frames_analyzed = 0

        frame_step = 5
        max_frames = 60
        frame_index = 0

        try:
            while frames_analyzed < max_frames:
                ok, frame = capture.read()
                if not ok:
                    break

                frame_index += 1
                if frame_index % frame_step != 0:
                    continue

                frames_analyzed += 1
                frame_h, frame_w = frame.shape[:2]
                if frame_h <= 0 or frame_w <= 0:
                    continue

                results = model.predict(source=frame, verbose=False)
                if not results:
                    continue

                result = results[0]
                detected_boxes, frame_conf = self._extract_normalized_boxes(result, frame_w, frame_h)
                if not detected_boxes:
                    continue

                if frame_conf > best_confidence:
                    best_confidence = frame_conf
                    best_boxes = detected_boxes
        finally:
            capture.release()

        return FloatingDetectionResult(
            model_name=model_path.name,
            model_path=str(model_path),
            boxes=best_boxes,
            confidence=best_confidence,
            frames_analyzed=frames_analyzed,
        )

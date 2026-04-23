from __future__ import annotations

import os
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("YOLO_CONFIG_DIR", str(PROJECT_ROOT))

import cv2
import numpy as np
from ultralytics import YOLO

MODEL_NAME = "yolo11n.pt"
MODEL_PATH = PROJECT_ROOT / MODEL_NAME
VIDEO_PATH = PROJECT_ROOT / "wrongway.mp4"
OUTPUT_VIDEO_PATH = PROJECT_ROOT / "wrongway_result.mp4"

DEFAULT_CCTV_ID = 1
CONFIDENCE_THRESHOLD = 0.4
MAX_TRACKING_DISTANCE = 95.0
TRACK_TIMEOUT_FRAMES = 20
MAX_HISTORY_SIZE = 30
ROI_GRID_ROWS = 2
ROI_GRID_COLS = 2
MIN_BASELINE_DISTANCE = 20.0
MIN_BASELINE_SAMPLES = 8
RECENT_DIRECTION_WINDOW = 6
MIN_DECISION_DISTANCE = 18.0
WRONG_WAY_DOT_THRESHOLD = -0.15
MIN_OPPOSITE_CONSECUTIVE_FRAMES = 3
LEARNING_WARMUP_FRAMES = 12
MIN_EVENT_CONFIDENCE = 0.65
MIN_EVENT_BOX_AREA = 1800


@dataclass
class Detection:
    label: str
    confidence: float
    box: tuple[int, int, int, int]
    anchor: tuple[int, int]


@dataclass
class Track:
    track_id: int
    label: str
    confidence: float
    box: tuple[int, int, int, int]
    anchor: tuple[int, int]
    last_seen_frame: int
    anchor_history: list[tuple[int, int]] = field(default_factory=list)
    opposite_frame_count: int = 0
    has_wrong_way_event: bool = False
    last_dot_product: float | None = None
    roi_name: str | None = None


class BottomCenterTracker:
    def __init__(self, max_distance: float, timeout_frames: int, max_history_size: int):
        self.max_distance = max_distance
        self.timeout_frames = timeout_frames
        self.max_history_size = max_history_size
        self.tracks: dict[int, Track] = {}
        self.next_track_id = 1

    def update(self, detections: list[Detection], frame_index: int) -> dict[int, Track]:
        matched_track_ids: set[int] = set()

        for detection in detections:
            nearest_track_id: int | None = None
            nearest_distance = self.max_distance

            for track_id, track in self.tracks.items():
                if track_id in matched_track_ids:
                    continue

                distance = (
                    (detection.anchor[0] - track.anchor[0]) ** 2
                    + (detection.anchor[1] - track.anchor[1]) ** 2
                ) ** 0.5
                if distance < nearest_distance:
                    nearest_distance = distance
                    nearest_track_id = track_id

            if nearest_track_id is None:
                self.tracks[self.next_track_id] = Track(
                    track_id=self.next_track_id,
                    label=detection.label,
                    confidence=detection.confidence,
                    box=detection.box,
                    anchor=detection.anchor,
                    last_seen_frame=frame_index,
                    anchor_history=[detection.anchor],
                )
                matched_track_ids.add(self.next_track_id)
                self.next_track_id += 1
                continue

            track = self.tracks[nearest_track_id]
            track.label = detection.label
            track.confidence = detection.confidence
            track.box = detection.box
            track.anchor = detection.anchor
            track.last_seen_frame = frame_index
            track.anchor_history.append(detection.anchor)
            if len(track.anchor_history) > self.max_history_size:
                track.anchor_history.pop(0)
            matched_track_ids.add(nearest_track_id)

        self._remove_stale_tracks(frame_index)
        return self.tracks

    def _remove_stale_tracks(self, frame_index: int) -> None:
        stale_track_ids = [
            track_id
            for track_id, track in self.tracks.items()
            if frame_index - track.last_seen_frame > self.timeout_frames
        ]
        for track_id in stale_track_ids:
            del self.tracks[track_id]


class WrongWayService:
    def __init__(self):
        self.model_path = Path(MODEL_PATH)
        self.video_path = Path(VIDEO_PATH)
        self.output_video_path = Path(OUTPUT_VIDEO_PATH)
        self.default_cctv_id = DEFAULT_CCTV_ID
        self.confidence_threshold = CONFIDENCE_THRESHOLD
        self.min_baseline_distance = MIN_BASELINE_DISTANCE
        self.min_decision_distance = MIN_DECISION_DISTANCE
        self.wrong_way_dot_threshold = WRONG_WAY_DOT_THRESHOLD
        self.min_opposite_consecutive_frames = MIN_OPPOSITE_CONSECUTIVE_FRAMES
        self.learning_warmup_frames = LEARNING_WARMUP_FRAMES
        self.min_event_confidence = MIN_EVENT_CONFIDENCE
        self.min_event_box_area = MIN_EVENT_BOX_AREA
        self.vehicle_labels = {"car", "truck", "bus", "motorcycle"}

        self.tracker = BottomCenterTracker(
            max_distance=MAX_TRACKING_DISTANCE,
            timeout_frames=TRACK_TIMEOUT_FRAMES,
            max_history_size=MAX_HISTORY_SIZE,
        )
        self.yolo_model: YOLO | None = None

        self._load_model()

    def detect_wrong_way(self) -> dict[str, Any]:
        try:
            if not self.video_path.exists():
                return {
                    "ok": False,
                    "message": f"영상 파일을 찾을 수 없습니다: {self.video_path}",
                }
            if self.yolo_model is None:
                return {
                    "ok": False,
                    "message": f"YOLO 모델을 불러오지 못했습니다: {self.model_path}",
                }
            return self._analyze_video()
        except Exception as error:
            return {
                "ok": False,
                "message": "역주행 분석 중 오류가 발생했습니다.",
                "error": str(error),
            }

    def _load_model(self) -> None:
        try:
            if self.model_path.exists():
                self.yolo_model = YOLO(str(self.model_path))
                print(f"[INFO] 로컬 YOLO 모델 사용: {self.model_path}")
                return

            self.yolo_model = YOLO(MODEL_NAME)
            print(f"[INFO] 로컬 모델이 없어 {MODEL_NAME} 다운로드 후 사용을 시도합니다.")
        except Exception as error:
            print(f"[WARN] YOLO 모델 로드 실패: {error}")
            self.yolo_model = None

    def _analyze_video(self) -> dict[str, Any]:
        video_capture = cv2.VideoCapture(str(self.video_path))
        if not video_capture.isOpened():
            return {"ok": False, "message": "영상 파일을 열지 못했습니다."}

        frame_per_second = video_capture.get(cv2.CAP_PROP_FPS)
        if frame_per_second <= 0:
            frame_per_second = 30.0

        frame_width = int(video_capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        frame_height = int(video_capture.get(cv2.CAP_PROP_FRAME_HEIGHT))

        video_writer = self._create_video_writer(
            frame_width=frame_width,
            frame_height=frame_height,
            frame_per_second=frame_per_second,
        )
        if video_writer is None:
            video_capture.release()
            return {
                "ok": False,
                "message": f"결과 영상을 저장할 수 없습니다: {self.output_video_path}",
            }

        frame_index = 0
        roi_definitions = self._build_roi_definitions(frame_width=frame_width, frame_height=frame_height)
        roi_vector_samples: dict[str, list[tuple[float, float]]] = defaultdict(list)
        roi_direction_map: dict[str, Any] = {}
        created_events: list[dict[str, Any]] = []

        try:
            while True:
                success, frame = video_capture.read()
                if not success:
                    break

                frame_index += 1
                frame_height, frame_width = frame.shape[:2]
                roi_definitions = self._build_roi_definitions(frame_width=frame_width, frame_height=frame_height)

                detections = self._detect_vehicles(frame)
                tracks = self.tracker.update(detections=detections, frame_index=frame_index)

                self._update_track_rois(tracks=tracks, roi_definitions=roi_definitions)
                self._accumulate_roi_vectors(tracks=tracks, roi_vector_samples=roi_vector_samples)
                roi_direction_map = self._build_roi_direction_map(
                    roi_vector_samples=roi_vector_samples,
                    roi_definitions=roi_definitions,
                )

                if frame_index > self.learning_warmup_frames:
                    for track in tracks.values():
                        self._evaluate_wrong_way(
                            track=track,
                            roi_direction_map=roi_direction_map,
                            created_events=created_events,
                        )

                annotated_frame = self._draw_result_frame(
                    frame=frame,
                    tracks=tracks,
                    roi_definitions=roi_definitions,
                    roi_direction_map=roi_direction_map,
                )
                video_writer.write(annotated_frame)
        finally:
            video_capture.release()
            video_writer.release()

        return {
            "ok": True,
            "message": "역주행 영상 분석이 완료되었습니다.",
            "video_path": str(self.video_path),
            "output_video_path": str(self.output_video_path),
            "roi_direction_map": self._format_roi_direction_map(roi_direction_map),
            "event_count": len(created_events),
            "events": created_events,
        }

    def _detect_vehicles(self, frame: np.ndarray) -> list[Detection]:
        detected_vehicles: list[Detection] = []

        try:
            results = self.yolo_model.predict(
                source=frame,
                conf=self.confidence_threshold,
                verbose=False,
            )
        except Exception as error:
            print(f"[WARN] YOLO 추론 실패: {error}")
            return detected_vehicles

        if not results:
            return detected_vehicles

        first_result = results[0]
        name_map = getattr(first_result, "names", {})
        boxes = getattr(first_result, "boxes", None)
        if boxes is None:
            return detected_vehicles

        for box in boxes:
            class_id = int(box.cls[0].item())
            class_name = str(name_map.get(class_id, class_id)).lower()
            if class_name not in self.vehicle_labels:
                continue

            x1, y1, x2, y2 = [int(value) for value in box.xyxy[0].tolist()]
            detected_vehicles.append(
                Detection(
                    label=class_name,
                    confidence=float(box.conf[0].item()),
                    box=(x1, y1, x2, y2),
                    anchor=(int((x1 + x2) / 2), y2),
                )
            )

        return detected_vehicles

    def _build_roi_definitions(self, frame_width: int, frame_height: int) -> dict[str, dict[str, Any]]:
        roi_definitions: dict[str, dict[str, Any]] = {}
        roi_width = frame_width / ROI_GRID_COLS
        roi_height = frame_height / ROI_GRID_ROWS

        for row_index in range(ROI_GRID_ROWS):
            for col_index in range(ROI_GRID_COLS):
                x1 = int(round(col_index * roi_width))
                y1 = int(round(row_index * roi_height))
                x2 = int(round((col_index + 1) * roi_width))
                y2 = int(round((row_index + 1) * roi_height))
                roi_name = self._get_roi_name(row_index=row_index, col_index=col_index)
                roi_definitions[roi_name] = {"name": roi_name, "box": (x1, y1, x2, y2)}

        return roi_definitions

    def _get_roi_name(self, row_index: int, col_index: int) -> str:
        vertical = "upper" if row_index == 0 else "lower"
        horizontal = "left" if col_index == 0 else "right"
        return f"{vertical}_{horizontal}"

    def _get_roi_name_for_point(
        self,
        point: tuple[int, int],
        roi_definitions: dict[str, dict[str, Any]],
    ) -> str:
        point_x, point_y = point
        for roi_name, roi_definition in roi_definitions.items():
            x1, y1, x2, y2 = roi_definition["box"]
            if x1 <= point_x < x2 and y1 <= point_y < y2:
                return roi_name
        return list(roi_definitions.keys())[-1]

    def _update_track_rois(
        self,
        tracks: dict[int, Track],
        roi_definitions: dict[str, dict[str, Any]],
    ) -> None:
        for track in tracks.values():
            track.roi_name = self._get_roi_name_for_point(track.anchor, roi_definitions)

    def _accumulate_roi_vectors(
        self,
        tracks: dict[int, Track],
        roi_vector_samples: dict[str, list[tuple[float, float]]],
    ) -> None:
        for track in tracks.values():
            if track.roi_name is None or len(track.anchor_history) < 2:
                continue

            baseline_movement = self._get_track_direction(track, window=None)
            if baseline_movement is None or baseline_movement["distance"] < self.min_baseline_distance:
                continue

            sample_list = roi_vector_samples[track.roi_name]
            sample_list.append(baseline_movement["direction"])
            if len(sample_list) > 200:
                sample_list.pop(0)

    def _build_roi_direction_map(
        self,
        roi_vector_samples: dict[str, list[tuple[float, float]]],
        roi_definitions: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        roi_direction_map: dict[str, Any] = {}

        for roi_name in roi_definitions.keys():
            direction_info = self._summarize_vectors(roi_vector_samples.get(roi_name, []))
            if direction_info is None:
                continue
            if direction_info["vector_count"] < MIN_BASELINE_SAMPLES:
                continue
            roi_direction_map[roi_name] = direction_info

        global_direction = self._summarize_vectors(
            [vector for sample_list in roi_vector_samples.values() for vector in sample_list]
        )
        if global_direction is None:
            return roi_direction_map

        for roi_name in roi_definitions.keys():
            if roi_name in roi_direction_map:
                continue
            roi_direction_map[roi_name] = {
                "direction": global_direction["direction"],
                "confidence": round(global_direction["confidence"] * 0.7, 4),
                "vector_count": 0,
            }

        return roi_direction_map

    def _get_track_direction(self, track: Track, window: int | None) -> dict[str, Any] | None:
        history = track.anchor_history
        if len(history) < 2:
            return None

        if window is not None and len(history) > window:
            history = history[-window:]

        start_anchor = history[0]
        end_anchor = history[-1]
        move_x = float(end_anchor[0] - start_anchor[0])
        move_y = float(end_anchor[1] - start_anchor[1])
        distance = (move_x ** 2 + move_y ** 2) ** 0.5
        if distance == 0:
            return None

        return {
            "vector": (move_x, move_y),
            "direction": (move_x / distance, move_y / distance),
            "distance": distance,
        }

    def _summarize_vectors(self, vectors: list[tuple[float, float]]) -> dict[str, Any] | None:
        normalized_vectors: list[tuple[float, float]] = []
        for vector_x, vector_y in vectors:
            length = (vector_x ** 2 + vector_y ** 2) ** 0.5
            if length == 0:
                continue
            normalized_vectors.append((vector_x / length, vector_y / length))

        if not normalized_vectors:
            return None

        average_x = float(np.mean([vector[0] for vector in normalized_vectors]))
        average_y = float(np.mean([vector[1] for vector in normalized_vectors]))
        direction_length = (average_x ** 2 + average_y ** 2) ** 0.5
        if direction_length == 0:
            return None

        return {
            "direction": (average_x / direction_length, average_y / direction_length),
            "confidence": round(direction_length, 4),
            "vector_count": len(normalized_vectors),
        }

    def _evaluate_wrong_way(
        self,
        track: Track,
        roi_direction_map: dict[str, Any],
        created_events: list[dict[str, Any]],
    ) -> None:
        if track.has_wrong_way_event or track.roi_name is None:
            return

        roi_info = roi_direction_map.get(track.roi_name)
        if roi_info is None:
            return

        recent_movement = self._get_track_direction(track, window=RECENT_DIRECTION_WINDOW)
        if recent_movement is None:
            return
        if recent_movement["distance"] < self.min_decision_distance:
            return
        if not self._is_event_quality_sufficient(track):
            return

        allowed_direction = roi_info["direction"]
        vehicle_direction = recent_movement["direction"]
        dot_product = (
            vehicle_direction[0] * allowed_direction[0]
            + vehicle_direction[1] * allowed_direction[1]
        )
        track.last_dot_product = dot_product

        if dot_product <= self.wrong_way_dot_threshold:
            track.opposite_frame_count += 1
        else:
            track.opposite_frame_count = 0

        if track.opposite_frame_count < self.min_opposite_consecutive_frames:
            return

        track.has_wrong_way_event = True
        created_events.append(
            self._create_wrong_way_event(
                track=track,
                movement=recent_movement,
                roi_info=roi_info,
                dot_product=dot_product,
            )
        )

    def _create_wrong_way_event(
        self,
        track: Track,
        movement: dict[str, Any],
        roi_info: dict[str, Any],
        dot_product: float,
    ) -> dict[str, Any]:
        x1, y1, x2, y2 = track.box
        return {
            "ok": True,
            "event_id": None,
            "cctv_id": self.default_cctv_id,
            "event_type": "wrong_way",
            "description": f"track_id {track.track_id} 차량이 역주행으로 감지되었습니다.",
            "track_id": track.track_id,
            "roi_name": track.roi_name,
            "dot_product": round(float(dot_product), 4),
            "opposite_frame_count": track.opposite_frame_count,
            "movement_distance": round(float(movement["distance"]), 2),
            "box_confidence": round(float(track.confidence), 4),
            "allowed_direction": {
                "x": round(float(roi_info["direction"][0]), 4),
                "y": round(float(roi_info["direction"][1]), 4),
            },
            "vehicle_direction": {
                "x": round(float(movement["direction"][0]), 4),
                "y": round(float(movement["direction"][1]), 4),
            },
            "anchor": {"x": track.anchor[0], "y": track.anchor[1]},
            "box": {"x1": x1, "y1": y1, "x2": x2, "y2": y2},
        }

    def _is_event_quality_sufficient(self, track: Track) -> bool:
        x1, y1, x2, y2 = track.box
        box_area = max(0, x2 - x1) * max(0, y2 - y1)
        return (
            track.confidence >= self.min_event_confidence
            and box_area >= self.min_event_box_area
        )

    def _format_roi_direction_map(self, roi_direction_map: dict[str, Any]) -> dict[str, Any]:
        formatted_map: dict[str, Any] = {}
        for roi_name, roi_info in roi_direction_map.items():
            formatted_map[roi_name] = {
                "direction": {
                    "x": round(float(roi_info["direction"][0]), 4),
                    "y": round(float(roi_info["direction"][1]), 4),
                },
                "confidence": round(float(roi_info["confidence"]), 4),
                "vector_count": roi_info["vector_count"],
            }
        return formatted_map

    def _create_video_writer(
        self,
        frame_width: int,
        frame_height: int,
        frame_per_second: float,
    ) -> cv2.VideoWriter | None:
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        video_writer = cv2.VideoWriter(
            str(self.output_video_path),
            fourcc,
            frame_per_second,
            (frame_width, frame_height),
        )
        if not video_writer.isOpened():
            return None
        return video_writer

    def _draw_result_frame(
        self,
        frame: np.ndarray,
        tracks: dict[int, Track],
        roi_definitions: dict[str, dict[str, Any]],
        roi_direction_map: dict[str, Any],
    ) -> np.ndarray:
        result_frame = frame.copy()

        for track in tracks.values():
            x1, y1, x2, y2 = track.box
            color = (0, 0, 255) if track.has_wrong_way_event else (0, 255, 0)
            status = f"ID {track.track_id}"
            if track.has_wrong_way_event:
                status += " Wrong Way"
            elif track.last_dot_product is not None:
                status += f" {track.last_dot_product:.2f}"

            cv2.rectangle(result_frame, (x1, y1), (x2, y2), color, 2)
            cv2.circle(result_frame, track.anchor, 4, color, -1)

            cv2.putText(
                result_frame,
                status,
                (x1, max(25, y1 - 8)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                color,
                2,
                cv2.LINE_AA,
            )

        summary_text = f"Wrong-way events: {sum(1 for track in tracks.values() if track.has_wrong_way_event)}"
        cv2.putText(
            result_frame,
            summary_text,
            (20, 35),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.9,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )

        return result_frame

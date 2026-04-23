from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from ultralytics import YOLO

from database.config import SessionLocal
from models import CCTV, Event

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODEL_PATH = PROJECT_ROOT / "best.pt"
VIDEO_PATH = PROJECT_ROOT / "fire.mp4"

# 설정
DEFAULT_CCTV_ID = 1
# YOLO 최소 신뢰도
YOLO_CONFIDENCE = 0.35
# 보조 판별에서 최종 양성으로 볼 최소 점수
SUPPORT_POSITIVE_THRESHOLD = 0.55
MIN_MOTION_SECONDS = 5.0
# 한 번의 API 호출에서 몇 초 동안만 분석할지
MAX_ANALYZE_SECONDS = 15.0
# 얼마나 많이 움직여야 움직임이 있다고 볼지
MOTION_RATIO_THRESHOLD = 0.02
# 트래킹 시 박스 중심점이 이 거리 안이면 같은 객체로 봄
MAX_TRACKING_DISTANCE = 90
# 이벤트 순간 캡처 이미지를 저장할 폴더
SNAPSHOT_DIR = PROJECT_ROOT / "fire" / "output"

@dataclass
class FireTrack:
    # 화재 또는 연기 후보 1개를 계속 추적하기 위한 데이터 묶음
    trackId: int
    labelName: str
    currentBox: tuple[int, int, int, int]
    currentCenter: tuple[int, int]
    firstSeenAt: datetime
    lastSeenAt: datetime
    motionStartedAt: datetime | None = None
    lastMotionAt: datetime | None = None
    eventCreated: bool = False
    bestYoloConfidence: float = 0.0
    bestSupportScore: float = 0.0
    latestColorScore: float = 0.0
    latestMotionScore: float = 0.0
    lastMetadata: dict[str, Any] = field(default_factory=dict)


class FireDetectionService:
    # YOLO는 화재와 연기를 찾고 색상과 움직임 보조 판별은 오탐을 줄이는 역할
    def __init__(self):
        self.db = SessionLocal()
        self.modelPath = Path(MODEL_PATH)
        self.videoPath = Path(VIDEO_PATH)
        self.defaultCctvId = DEFAULT_CCTV_ID
        self.yoloConfidence = YOLO_CONFIDENCE
        self.supportPositiveThreshold = SUPPORT_POSITIVE_THRESHOLD
        self.minMotionSeconds = MIN_MOTION_SECONDS
        self.maxAnalyzeSeconds = MAX_ANALYZE_SECONDS
        self.motionRatioThreshold = MOTION_RATIO_THRESHOLD
        self.maxTrackingDistance = MAX_TRACKING_DISTANCE

        self.targetLabelNames = {"fire", "smoke"}

        self.yoloModel: YOLO | None = None
        # 모델과 추적용 딕셔너리
        self.fireTracks: dict[int, FireTrack] = {}
        self.nextTrackId = 1

        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        self._loadYoloModel()

    # 메인 실행 메소드
    def detect_fire(self) -> dict[str, Any]:
        try:
            self.db = self._openDbSession()

            cctvInfo = self._getTargetCctv()
            if cctvInfo is None:
                return {
                    "ok": False,
                    "message": "분석할 CCTV 정보를 찾지 못했습니다.",
                }
            if self.yoloModel is None:
                return {
                    "ok": False,
                    "message": f"YOLO 모델 파일을 찾지 못했습니다: {self.modelPath}",
                }
            if not cctvInfo.stream_url:
                return {
                    "ok": False,
                    "message": "CCTV stream_url 값이 비어 있습니다.",
                    "cctv_id": cctvInfo.id,
                }
            return self._analyzeVideoSource(
                videoSource=str(cctvInfo.stream_url),
                cctvId=cctvInfo.id,
                locationName=cctvInfo.location,
                sourceLabel=str(cctvInfo.stream_url),
                saveToDb=True,
            )
        except Exception as error:
            return {
                "ok": False,
                "message": "화재 감지 처리 중 오류가 발생했습니다.",
                "error": str(error),
            }
        finally:
            if self.db is not None:
                self.db.close()

    # 동영상 테스트 메소드
    # wrong_way 서비스처럼 DB 없이 로컬 동영상만 분석할 수 있게 만든 버전
    def detect_fire_video_test(self) -> dict[str, Any]:
        self.db = None

        try:
            if not self.videoPath.exists():
                return {
                    "ok": False,
                    "message": f"테스트 영상 파일을 찾을 수 없습니다: {self.videoPath}",
                }
            if self.yoloModel is None:
                return {
                    "ok": False,
                    "message": f"YOLO 모델 파일을 찾지 못했습니다: {self.modelPath}",
                }

            return self._analyzeVideoSource(
                videoSource=str(self.videoPath),
                cctvId=self.defaultCctvId,
                locationName="동영상 테스트",
                sourceLabel=str(self.videoPath),
                saveToDb=False,
            )
        except Exception as error:
            return {
                "ok": False,
                "message": "화재 동영상 테스트 중 오류가 발생했습니다.",
                "error": str(error),
            }
        finally:
            if self.db is not None:
                self.db.close()

    # DB 세션 열기
    # 테스트에서는 DB 연결이 없어도 분석 자체는 가능하게 만들기 위해 분리함
    def _openDbSession(self):
        try:
            return SessionLocal()
        except Exception as error:
            print(f"[WARN] DB 연결 없이 분석을 진행합니다: {error}")
            return None

    def _loadYoloModel(self) -> None:
        try:
            if not self.modelPath.exists():
                self.yoloModel = None
                return

            self.yoloModel = YOLO(str(self.modelPath))
        except Exception as error:
            print(f"[WARN] YOLO 모델 로드 실패: {error}")
            self.yoloModel = None

    # DB에서 사용할 CCTV
    def _getTargetCctv(self) -> CCTV | None:
        if self.db is None:
            return None

        selectedCctv = self.db.query(CCTV).filter(CCTV.id == self.defaultCctvId).first()
        if selectedCctv is not None:
            return selectedCctv

        return self.db.query(CCTV).order_by(CCTV.id.asc()).first()

    # 실제 CCTV 스트림 또는 테스트 동영상을 분석
    def _analyzeVideoSource(
        self,
        videoSource: str,
        cctvId: int,
        locationName: str,
        sourceLabel: str,
        saveToDb: bool,
    ) -> dict[str, Any]:
        videoCapture = cv2.VideoCapture(videoSource)

        if not videoCapture.isOpened():
            return {
                "ok": False,
                "message": "영상 소스를 열지 못했습니다.",
                "cctv_id": cctvId,
                "stream_url": videoSource,
            }
        # FPS 확인
        framePerSecond = videoCapture.get(cv2.CAP_PROP_FPS)
        if framePerSecond <= 0:
            framePerSecond = 30.0

        maxFrameCount = max(1, int(framePerSecond * self.maxAnalyzeSeconds))

        previousGrayFrame: np.ndarray | None = None
        createdEvents: list[dict[str, Any]] = []
        frameIndex = 0

        try:
            while frameIndex < maxFrameCount:
                success, currentFrame = videoCapture.read()
                if not success:
                    break

                frameIndex += 1
                currentTime = datetime.now()
                # 각 프레임에서 YOLO감지
                yoloDetectionResults = self._runYoloDetection(currentFrame)
                activeTrackIds = set()

                for detectedObject in yoloDetectionResults:
                    # YOLO가 찾은 박스를 기준으로 자름
                    fireBox = detectedObject["box"]
                    fireCenter = detectedObject["center"]
                    fireRoi = self._cropBox(currentFrame, fireBox)
                    if fireRoi.size == 0:
                        continue

                    # 색상 특징과 움직임 특징을 함께 계산
                    colorFeature = self._extractColorFeature(fireRoi)
                    motionFeature = self._extractMotionFeature(currentFrame, previousGrayFrame, fireBox)

                    # 보조 판별 점수를 계산
                    supportResult = self._classifyWithSupportLogic(
                        colorScore=colorFeature["colorScore"],
                        motionScore=motionFeature["motionScore"],
                        labelName=detectedObject["labelName"],
                    )

                    # YOLO와 보조 판별을 모두 통과한 후보만 추적 정보 갱신
                    if not supportResult["isPositive"]:
                        continue

                    trackId = self._upsertTrack(
                        labelName=detectedObject["labelName"],
                        currentBox=fireBox,
                        currentCenter=fireCenter,
                        currentTime=currentTime,
                        yoloConfidence=detectedObject["confidence"],
                        supportScore=supportResult["positiveScore"],
                        colorScore=colorFeature["colorScore"],
                        motionScore=motionFeature["motionScore"],
                        metadata={
                            "support_mode": supportResult["mode"],
                            "support_positive_score": round(supportResult["positiveScore"], 4),
                            "color_score": round(colorFeature["colorScore"], 4),
                            "motion_score": round(motionFeature["motionScore"], 4),
                            "smoke_gray_ratio": round(colorFeature["smokeGrayRatio"], 4),
                            "fire_color_ratio": round(colorFeature["fireColorRatio"], 4),
                        },
                    )
                    activeTrackIds.add(trackId)

                    # 5초 이상 연속 움직임이 있으면 event를 생성
                    eventResult = self._createEventIfNeeded(
                        cctvId=cctvId,
                        locationName=locationName,
                        saveToDb=saveToDb,
                        trackId=trackId,
                        frame=currentFrame,
                    )
                    if eventResult is not None:
                        createdEvents.append(eventResult)
                # 이번 프레임에 오래 보이지 않은 추적 객체는 지움
                self._cleanupOldTracks(nowTime=currentTime, activeTrackIds=activeTrackIds)
                # 다음 프레임 움직임 계산을 위해 현재 회색 영상을 저장
                previousGrayFrame = cv2.cvtColor(currentFrame, cv2.COLOR_BGR2GRAY)
        finally:
            videoCapture.release()

        return {
            "ok": True,
            "message": "화재/연기 분석을 완료했습니다.",
            "cctv_id": cctvId,
            "location": locationName,
            "stream_url": sourceLabel,
            "used_model_path": str(self.modelPath),
            "video_path": str(videoSource),
            "db_saved": bool(saveToDb and self.db is not None),
            "support_logic": "color_and_motion",
            "checked_frame_count": frameIndex,
            "created_event_count": len(createdEvents),
            "events": createdEvents,
        }

    def getResponseEventName(self) -> str:
        return "fire_detected"

    # YOLO 실행
    def _runYoloDetection(self, frame: np.ndarray) -> list[dict[str, Any]]:
        detectedItems: list[dict[str, Any]] = []

        try:
            predictionResults = self.yoloModel.predict(
                source=frame,
                conf=self.yoloConfidence,
                verbose=False,
            )
        except Exception as error:
            print(f"[WARN] YOLO 예측 실패: {error}")
            return detectedItems

        if not predictionResults:
            return detectedItems

        firstResult = predictionResults[0]
        nameMap = getattr(firstResult, "names", {})
        boxes = getattr(firstResult, "boxes", None)

        if boxes is None:
            return detectedItems

        for detectedBox in boxes:
            classId = int(detectedBox.cls[0].item())
            labelName = str(nameMap.get(classId, classId)).lower()
            if labelName not in self.targetLabelNames:
                continue

            x1, y1, x2, y2 = [int(value) for value in detectedBox.xyxy[0].tolist()]
            x1 = max(0, x1)
            y1 = max(0, y1)
            x2 = max(x1 + 1, x2)
            y2 = max(y1 + 1, y2)

            centerX = int((x1 + x2) / 2)
            centerY = int((y1 + y2) / 2)

            detectedItems.append(
                {
                    "labelName": labelName,
                    "confidence": float(detectedBox.conf[0].item()),
                    "box": (x1, y1, x2, y2),
                    "center": (centerX, centerY),
                }
            )

        return detectedItems

    # 박스 영역만 잘라내기
    def _cropBox(self, frame: np.ndarray, box: tuple[int, int, int, int]) -> np.ndarray:
        x1, y1, x2, y2 = box
        frameHeight, frameWidth = frame.shape[:2]

        safeX1 = min(max(0, x1), frameWidth - 1)
        safeY1 = min(max(0, y1), frameHeight - 1)
        safeX2 = min(max(safeX1 + 1, x2), frameWidth)
        safeY2 = min(max(safeY1 + 1, y2), frameHeight)

        return frame[safeY1:safeY2, safeX1:safeX2]

    # 색상 특징을 계산 (화재는 빨주노, 연기는 회색)
    def _extractColorFeature(self, fireRoi: np.ndarray) -> dict[str, Any]:
        resizedRoi = cv2.resize(fireRoi, (64, 64))
        hsvFrame = cv2.cvtColor(resizedRoi, cv2.COLOR_BGR2HSV)

        fireMask1 = cv2.inRange(hsvFrame, (0, 80, 120), (25, 255, 255))
        fireMask2 = cv2.inRange(hsvFrame, (160, 80, 120), (179, 255, 255))
        fireColorMask = cv2.bitwise_or(fireMask1, fireMask2)

        grayFrame = cv2.cvtColor(resizedRoi, cv2.COLOR_BGR2GRAY)
        grayDiffB = cv2.absdiff(grayFrame, resizedRoi[:, :, 0])
        grayDiffG = cv2.absdiff(grayFrame, resizedRoi[:, :, 1])
        grayDiffR = cv2.absdiff(grayFrame, resizedRoi[:, :, 2])
        smokeGrayMask = np.where(
            (grayDiffB < 18) & (grayDiffG < 18) & (grayDiffR < 18) & (grayFrame > 70),
            255,
            0,
        ).astype(np.uint8)

        fireColorRatio = float(np.count_nonzero(fireColorMask)) / float(fireColorMask.size)
        smokeGrayRatio = float(np.count_nonzero(smokeGrayMask)) / float(smokeGrayMask.size)

        # fire와 smoke 둘 다 고려해야 하므로 둘 중 큰 값을 대표 점수로 사용
        colorScore = max(fireColorRatio, smokeGrayRatio)
        colorMask = cv2.max(fireColorMask, smokeGrayMask)

        return {
            "colorScore": colorScore,
            "fireColorRatio": fireColorRatio,
            "smokeGrayRatio": smokeGrayRatio,
            "colorMask": colorMask,
        }

    # 움직임 특징을 계산
    def _extractMotionFeature(
        self,
        currentFrame: np.ndarray,
        previousGrayFrame: np.ndarray | None,
        box: tuple[int, int, int, int],
    ) -> dict[str, Any]:
        currentRoi = self._cropBox(currentFrame, box)
        resizedCurrentRoi = cv2.resize(currentRoi, (64, 64))
        currentGrayRoi = cv2.cvtColor(resizedCurrentRoi, cv2.COLOR_BGR2GRAY)

        if previousGrayFrame is None:
            emptyMask = np.zeros((64, 64), dtype=np.uint8)
            return {
                "motionScore": 0.0,
                "motionMask": emptyMask,
            }

        previousRoi = self._cropBox(cv2.cvtColor(previousGrayFrame, cv2.COLOR_GRAY2BGR), box)
        if previousRoi.size == 0:
            emptyMask = np.zeros((64, 64), dtype=np.uint8)
            return {
                "motionScore": 0.0,
                "motionMask": emptyMask,
            }

        resizedPreviousRoi = cv2.resize(previousRoi, (64, 64))
        previousGrayRoi = cv2.cvtColor(resizedPreviousRoi, cv2.COLOR_BGR2GRAY)
        frameDiff = cv2.absdiff(currentGrayRoi, previousGrayRoi)
        _, motionMask = cv2.threshold(frameDiff, 25, 255, cv2.THRESH_BINARY)
        motionMask = cv2.GaussianBlur(motionMask, (5, 5), 0)
        _, motionMask = cv2.threshold(motionMask, 25, 255, cv2.THRESH_BINARY)

        motionScore = float(np.count_nonzero(motionMask)) / float(motionMask.size)

        return {
            "motionScore": motionScore,
            "motionMask": motionMask,
        }

    # 보조 판별 점수를 계산
    def _classifyWithSupportLogic(
        self,
        colorScore: float,
        motionScore: float,
        labelName: str,
    ) -> dict[str, Any]:
        positiveScore = self._calculateHeuristicScore(
            colorScore=colorScore,
            motionScore=motionScore,
            labelName=labelName,
        )

        return {
            "mode": "color_and_motion_support_logic",
            "positiveScore": positiveScore,
            "isPositive": positiveScore >= self.supportPositiveThreshold,
        }

    # 휴리스틱 점수를 계산 (= 색상과 움직임을 사람이 정한 비율로 섞어서 만든 보조 판단 점수 → 불은 색상↑, 연기는 움직임↑)
    def _calculateHeuristicScore(self, colorScore: float, motionScore: float, labelName: str) -> float:
        if labelName == "fire":
            rawScore = (colorScore * 0.7) + (motionScore * 0.3)
        else:
            rawScore = (colorScore * 0.5) + (motionScore * 0.5)

        return max(0.0, min(1.0, rawScore))

    # 같은 객체인지 판단해 추적 정보를 갱신
    def _upsertTrack(
        self,
        labelName: str,
        currentBox: tuple[int, int, int, int],
        currentCenter: tuple[int, int],
        currentTime: datetime,
        yoloConfidence: float,
        supportScore: float,
        colorScore: float,
        motionScore: float,
        metadata: dict[str, Any],
    ) -> int:
        nearestTrackId: int | None = None
        nearestDistance = float(self.maxTrackingDistance)

        for trackId, fireTrack in self.fireTracks.items():
            if fireTrack.labelName != labelName:
                continue

            distance = (
                (currentCenter[0] - fireTrack.currentCenter[0]) ** 2
                + (currentCenter[1] - fireTrack.currentCenter[1]) ** 2
            ) ** 0.5

            if distance < nearestDistance:
                nearestDistance = distance
                nearestTrackId = trackId

        if nearestTrackId is None:
            createdTrack = FireTrack(
                trackId=self.nextTrackId,
                labelName=labelName,
                currentBox=currentBox,
                currentCenter=currentCenter,
                firstSeenAt=currentTime,
                lastSeenAt=currentTime,
            )
            self.fireTracks[self.nextTrackId] = createdTrack
            nearestTrackId = self.nextTrackId
            self.nextTrackId += 1

        selectedTrack = self.fireTracks[nearestTrackId]
        selectedTrack.currentBox = currentBox
        selectedTrack.currentCenter = currentCenter
        selectedTrack.lastSeenAt = currentTime
        selectedTrack.bestYoloConfidence = max(selectedTrack.bestYoloConfidence, yoloConfidence)
        selectedTrack.bestSupportScore = max(selectedTrack.bestSupportScore, supportScore)
        selectedTrack.latestColorScore = colorScore
        selectedTrack.latestMotionScore = motionScore
        selectedTrack.lastMetadata = metadata

        if motionScore >= self.motionRatioThreshold:
            if selectedTrack.motionStartedAt is None:
                selectedTrack.motionStartedAt = currentTime
            selectedTrack.lastMotionAt = currentTime
        else:
            selectedTrack.motionStartedAt = None
            selectedTrack.lastMotionAt = None

        return nearestTrackId

    # 오래 안 보인 추적 객체를 지우기
    def _cleanupOldTracks(self, nowTime: datetime, activeTrackIds: set[int]) -> None:
        deleteTrackIds: list[int] = []

        for trackId, fireTrack in self.fireTracks.items():
            timeGap = (nowTime - fireTrack.lastSeenAt).total_seconds()
            if trackId not in activeTrackIds and timeGap > 2.0:
                deleteTrackIds.append(trackId)

        for trackId in deleteTrackIds:
            del self.fireTracks[trackId]

    # 5초 이상 연속 움직임이 이어지면 event 생성
    def _createEventIfNeeded(
        self,
        cctvId: int,
        locationName: str,
        saveToDb: bool,
        trackId: int,
        frame: np.ndarray,
    ) -> dict[str, Any] | None:
        fireTrack = self.fireTracks.get(trackId)
        if fireTrack is None:
            return None

        if fireTrack.eventCreated:
            return None

        if fireTrack.motionStartedAt is None:
            return None

        motionDuration = (fireTrack.lastSeenAt - fireTrack.motionStartedAt).total_seconds()
        if motionDuration < self.minMotionSeconds:
            return None

        # 이벤트가 발생한 순간의 캡처 이미지를 저장하고 그 경로를 image_url로 사용
        snapshotPath = self._saveEventSnapshot(frame=frame, box=fireTrack.currentBox, trackId=trackId)
        imageUrl = str(snapshotPath) if snapshotPath is not None else None

        eventMetadata = {
            "track_id": trackId,
            "label_name": fireTrack.labelName,
            "motion_duration_seconds": round(motionDuration, 2),
            "best_yolo_confidence": round(fireTrack.bestYoloConfidence, 4),
            "best_support_score": round(fireTrack.bestSupportScore, 4),
            "latest_color_score": round(fireTrack.latestColorScore, 4),
            "latest_motion_score": round(fireTrack.latestMotionScore, 4),
            "box": {
                "x1": fireTrack.currentBox[0],
                "y1": fireTrack.currentBox[1],
                "x2": fireTrack.currentBox[2],
                "y2": fireTrack.currentBox[3],
            },
            "location": locationName,
            "extra": fireTrack.lastMetadata,
        }

        if saveToDb and self.db is not None:
            createdEventId = self._insertEventRecord(
                cctvId=cctvId,
                eventType=f"{fireTrack.labelName}_detected",
                description=(
                    f"{locationName}에서 {fireTrack.labelName}가 "
                    f"{round(motionDuration, 2)}초 이상 움직여 이벤트를 생성했습니다."
                ),
                imageUrl=imageUrl,
                metadata=eventMetadata,
            )
        else:
            createdEventId = None

        fireTrack.eventCreated = True

        return {
            "event_id": createdEventId,
            "track_id": trackId,
            "label_name": fireTrack.labelName,
            "motion_duration_seconds": round(motionDuration, 2),
            "notification": self._buildNotificationMessage(
                cctvId=cctvId,
                locationName=locationName,
                fireTrack=fireTrack,
            ),
            "image_url": imageUrl,
            "db_saved": bool(saveToDb and self.db is not None),
        }

    # event 테이블에 이벤트를 저장
    def _insertEventRecord(
        self,
        cctvId: int,
        eventType: str,
        description: str,
        imageUrl: str | None,
        metadata: dict[str, Any],
    ) -> int | None:
        try:
            eventData = {
                "source_type": "cctv",
                "cctv_id": cctvId,
                "device_id": None,
                "event_type": eventType,
                "event_time": datetime.now(),
                "lat": None,
                "lng": None,
                "ng": None,
                "description": description,
                "image_url": imageUrl,
                "metadata": metadata,
                "event_metadata": metadata,
            }

            createdEvent = Event()
            validColumns = set(Event.__table__.columns.keys())

            for columnName, columnValue in eventData.items():
                if columnName in validColumns:
                    setattr(createdEvent, columnName, columnValue)

            self.db.add(createdEvent)
            self.db.commit()
            self.db.refresh(createdEvent)

            return getattr(createdEvent, "id", None)
        except Exception:
            self.db.rollback()
            return None

    # 이벤트 알림 문구
    def _buildNotificationMessage(self, cctvId: int, locationName: str, fireTrack: FireTrack) -> str:
        return (
            f"[화재 알림] CCTV {cctvId}번({locationName})에서 "
            f"{fireTrack.labelName}가 감지되었고 5초 이상 움직임이 확인되었습니다."
        )

    # 이벤트 순간 화면을 이미지 파일로 저장
    def _saveEventSnapshot(
        self,
        frame: np.ndarray,
        box: tuple[int, int, int, int],
        trackId: int,
    ) -> Path | None:
        try:
            copiedFrame = frame.copy()
            x1, y1, x2, y2 = box

            # 이벤트가 발생한 위치를 사각형으로 표시
            cv2.rectangle(copiedFrame, (x1, y1), (x2, y2), (0, 0, 255), 2)
            cv2.putText(
                copiedFrame,
                f"track:{trackId}",
                (x1, max(20, y1 - 10)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 0, 255),
                2,
            )

            fileName = f"fire_event_{trackId}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
            snapshotPath = SNAPSHOT_DIR / fileName
            cv2.imwrite(str(snapshotPath), copiedFrame)
            return snapshotPath
        except Exception:
            return None


if __name__ == "__main__":
    fireService = FireDetectionService()
    testResult = fireService.detect_fire_video_test()
    print(testResult)

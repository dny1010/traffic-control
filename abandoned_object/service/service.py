from datetime import datetime
from math import sqrt
from typing import Any


class AbandonedObjectService:
    """
    낙하물 기능의 핵심 서비스입니다.

    이 클래스는 "모델이 이미 box를 탐지했다"는 전제를 두고,
    그 box가 실제로 도로 위 낙하물처럼 보이는지 한 번 더 규칙으로 판단합니다.

    쉬운 비유:
    - 모델 = 눈
    - 이 서비스 = 눈이 본 것을 해석하는 판단 담당자
    """

    # 현재 데이터셋 기준에서 box 클래스는 2번입니다.
    # 모델이 숫자(class id)로 주든, 문자열(class name)로 주든 둘 다 받을 수 있게 준비합니다.
    BOX_CLASS_ID = 2
    BOX_CLASS_NAME = "box"

    # 차량 위 적재 박스를 낙하물로 잘못 보지 않기 위해 차량 계열 클래스도 같이 기억합니다.
    VEHICLE_CLASS_IDS = {4, 5, 6, 7, 8}
    VEHICLE_CLASS_NAMES = {"truck", "car", "motorcycle", "bicycle", "bus"}

    def __init__(self):
        """
        지금 단계에서는 DB를 실제로 연결하지 않습니다.

        이유:
        - 현재 목표는 "탐지 결과가 들어왔을 때 낙하물 판단이 정확히 되는가" 검증
        - DB 적재는 다음 단계에서 붙여도 늦지 않음

        그래서 실제 저장 대신, "나중에 어떤 값을 저장할지"만 설계 메모처럼 들고 있습니다.
        """
        # [운영 전 변경 예정]
        # 실제 DB insert는 아직 하지 않지만,
        # 나중에 어떤 값을 저장하면 되는지 코드만 봐도 이해되도록 구조를 남깁니다.
        self.dbSavePlan = {
            "plannedTablePurpose": "낙하물 이벤트 이력 저장",
            "plannedFields": [
                "eventTime",
                "cameraId",
                "objectType",
                "alertMessage",
                "snapshotImagePathOrBlob",
            ],
            "notes": [
                "우선 저장 우선순위가 높은 값은 사고/이벤트 발생 시각(eventTime)입니다.",
                "이미지는 파일 경로 저장 또는 blob 저장 중 어떤 방식이 맞는지 다음 단계에서 결정합니다.",
                "API가 붙은 뒤에는 DB에 저장된 정보를 API 응답에서 다시 조회하는 구조를 염두에 둡니다.",
            ],
        }

    def detect_abandoned_object(self, payload: dict | None = None) -> dict[str, Any]:
        """
        낙하물 판단의 메인 입구입니다.

        처리 순서:
        1. 입력이 최소 조건을 만족하는지 검사
        2. 시간이 충분히 지났는지 계산
        3. 거의 움직이지 않았는지 계산
        4. 도로 위인지 / 차량 위 적재물인지 공간 규칙 검사
        5. 최종 낙하물 여부 결정
        6. 로그 알림 출력
        7. DB 저장은 아직 안 하고 "저장 계획 정보"만 반환
        """
        requestPayload = payload or {}

        # 학습용 로그:
        # 실제 모델과 연결할 때 payload 구조가 예상과 다르면 여기서 바로 확인할 수 있습니다.
        print("[AbandonedObjectService] detect_abandoned_object start")
        print(f"[AbandonedObjectService] payload keys: {list(requestPayload.keys())}")

        # 1. 입력 검증
        validationResult = self._validate_payload(requestPayload)
        if not validationResult.get("ok"):
            return validationResult

        # 2. 공통으로 재사용할 객체 기본 정보
        objectInfo = validationResult["objectInfo"]

        # 3. 시간이 충분히 흘렀는가
        timeAnalysis = self._analyze_stationary_time(requestPayload)

        # 4. 거의 움직이지 않았는가
        movementAnalysis = self._analyze_object_movement(
            requestPayload,
            validationResult["referencePoint"],
        )

        # 5. 도로 위인가 / 차량 위 적재물인가
        spatialAnalysis = self._analyze_spatial_context(
            requestPayload,
            validationResult["referencePoint"],
        )

        # 6. 위 결과를 종합해 최종 낙하물 여부 결정
        decision = self._decide_abandoned_state(
            requestPayload,
            objectInfo,
            timeAnalysis,
            movementAnalysis,
            spatialAnalysis,
        )

        # 7. 사람이 읽기 쉬운 알림 문구 생성
        alertMessage = self._create_alert_message(
            requestPayload,
            objectInfo,
            timeAnalysis,
            movementAnalysis,
            spatialAnalysis,
            decision,
        )

        # 8. 아직 앱 연동이 없으므로 콘솔 로그를 임시 알림 채널처럼 사용
        self._emit_alert_log(
            objectInfo,
            timeAnalysis,
            movementAnalysis,
            spatialAnalysis,
            decision,
            alertMessage,
        )

        # 9. DB는 아직 연결하지 않고 저장 계획만 반환
        dbSaveResult = self._save_detection_result(
            requestPayload,
            objectInfo,
            timeAnalysis,
            movementAnalysis,
            spatialAnalysis,
            decision,
            alertMessage,
        )

        print("[AbandonedObjectService] detect_abandoned_object completed")

        return {
            "ok": True,
            "message": "Abandoned object analyzed",
            "objectInfo": objectInfo,
            "timeAnalysis": timeAnalysis,
            "movementAnalysis": movementAnalysis,
            "spatialAnalysis": spatialAnalysis,
            "decision": decision,
            "alertMessage": alertMessage,
            "dbSaveResult": dbSaveResult,
        }

    def _validate_payload(self, requestPayload: dict[str, Any]) -> dict[str, Any]:
        """
        입력이 최소한의 낙하물 판단 조건을 만족하는지 검사합니다.

        여기서 확인하는 것:
        - payload가 dict인가
        - 대상이 box 클래스인가
        - 기준 위치를 계산할 최소 좌표 정보가 있는가
        """
        if not isinstance(requestPayload, dict):
            return {
                "ok": False,
                "message": "payload는 딕셔너리 형태여야 합니다.",
            }

        objectInfo = self._extract_object_info(requestPayload)
        if not objectInfo.get("isTargetClass"):
            return {
                "ok": False,
                "message": "낙하물 판단은 box 클래스(id=2) 감지 결과만 처리합니다.",
                "objectInfo": objectInfo,
            }

        referencePoint = self._extract_reference_point(requestPayload)
        if referencePoint is None:
            return {
                "ok": False,
                "message": (
                    "최소한 previousPoint/currentPoint/currentBBox/bbox 중 하나가 필요합니다."
                ),
                "requiredExample": {
                    "detectedClassId": 2,
                    "currentBBox": {"x1": 100, "y1": 120, "x2": 180, "y2": 220},
                    "observedDurationSeconds": 6,
                },
            }

        return {
            "ok": True,
            "objectInfo": objectInfo,
            "referencePoint": referencePoint,
        }

    def _extract_object_info(self, requestPayload: dict[str, Any]) -> dict[str, Any]:
        """
        모델마다 class 정보 키 이름이 조금씩 다를 수 있어서,
        여기서 한 번 공통 형식으로 정리합니다.
        """
        classId = self._to_int(
            requestPayload.get("detectedClassId")
            or requestPayload.get("classId")
            or requestPayload.get("objectClassId")
            or requestPayload.get("labelIndex")
        )

        className = str(
            requestPayload.get("detectedClassName")
            or requestPayload.get("className")
            or requestPayload.get("labelName")
            or requestPayload.get("objectType")
            or self.BOX_CLASS_NAME
        ).strip()

        normalizedClassName = className.lower()
        isTargetClass = (
            classId == self.BOX_CLASS_ID
            or normalizedClassName == self.BOX_CLASS_NAME
        )

        return {
            "objectId": requestPayload.get("objectId") or requestPayload.get("trackId"),
            "classId": classId,
            "className": className,
            "normalizedClassName": normalizedClassName,
            "isTargetClass": isTargetClass,
        }

    def _extract_reference_point(
        self,
        requestPayload: dict[str, Any],
    ) -> dict[str, float] | None:
        """
        기준 위치를 계산합니다.

        우선순위:
        1. currentPoint
        2. previousPoint
        3. currentBBox 중심점
        4. previousBBox 중심점
        """
        currentPoint = self._extract_point(requestPayload.get("currentPoint"))
        if currentPoint is not None:
            return currentPoint

        previousPoint = self._extract_point(requestPayload.get("previousPoint"))
        if previousPoint is not None:
            return previousPoint

        currentBBoxCenter = self._extract_bbox_center(
            requestPayload.get("currentBBox") or requestPayload.get("bbox")
        )
        if currentBBoxCenter is not None:
            return currentBBoxCenter

        previousBBoxCenter = self._extract_bbox_center(requestPayload.get("previousBBox"))
        if previousBBoxCenter is not None:
            return previousBBoxCenter

        return None

    def _analyze_stationary_time(self, requestPayload: dict[str, Any]) -> dict[str, Any]:
        """
        객체가 얼마나 오래 같은 위치에 있었는지 계산합니다.

        시간 계산 우선순위:
        1. observedDurationSeconds 직접 제공
        2. firstDetectedAt ~ lastDetectedAt 차이
        3. observedFrameCount / fps
        """
        stationaryThresholdSeconds = (
            self._to_float(requestPayload.get("stationaryThresholdSeconds")) or 5.0
        )

        observedDurationSeconds = self._to_float(
            requestPayload.get("observedDurationSeconds")
            or requestPayload.get("stationarySeconds")
            or requestPayload.get("durationSeconds")
        )
        if observedDurationSeconds is not None:
            return {
                "observedDurationSeconds": round(observedDurationSeconds, 4),
                "stationaryThresholdSeconds": stationaryThresholdSeconds,
                "durationSource": "provided_duration",
                "isStationaryLongEnough": observedDurationSeconds >= stationaryThresholdSeconds,
            }

        firstDetectedAt = self._parse_datetime(
            requestPayload.get("firstDetectedAt")
            or requestPayload.get("firstSeenAt")
            or requestPayload.get("startTime")
        )
        lastDetectedAt = self._parse_datetime(
            requestPayload.get("lastDetectedAt")
            or requestPayload.get("lastSeenAt")
            or requestPayload.get("currentTime")
            or requestPayload.get("capturedAt")
        )
        if firstDetectedAt is not None and lastDetectedAt is not None:
            observedDurationSeconds = max(
                (lastDetectedAt - firstDetectedAt).total_seconds(),
                0.0,
            )
            return {
                "observedDurationSeconds": round(observedDurationSeconds, 4),
                "stationaryThresholdSeconds": stationaryThresholdSeconds,
                "durationSource": "timestamp_diff",
                "isStationaryLongEnough": observedDurationSeconds >= stationaryThresholdSeconds,
            }

        observedFrameCount = self._to_int(
            requestPayload.get("observedFrameCount")
            or requestPayload.get("stationaryFrameCount")
        )
        framesPerSecond = self._to_float(
            requestPayload.get("fps") or requestPayload.get("framesPerSecond")
        )
        if observedFrameCount is not None and framesPerSecond and framesPerSecond > 0:
            observedDurationSeconds = observedFrameCount / framesPerSecond
            return {
                "observedDurationSeconds": round(observedDurationSeconds, 4),
                "stationaryThresholdSeconds": stationaryThresholdSeconds,
                "durationSource": "frame_count_and_fps",
                "isStationaryLongEnough": observedDurationSeconds >= stationaryThresholdSeconds,
            }

        return {
            "observedDurationSeconds": None,
            "stationaryThresholdSeconds": stationaryThresholdSeconds,
            "durationSource": "unavailable",
            "isStationaryLongEnough": False,
        }

    def _analyze_object_movement(
        self,
        requestPayload: dict[str, Any],
        referencePoint: dict[str, float],
    ) -> dict[str, Any]:
        """
        객체가 거의 안 움직였는지 계산합니다.

        낙하물은 "오래 있음"만으로는 부족하고,
        "그 자리에 거의 그대로 있음"이 같이 만족돼야 의미가 있습니다.
        """
        movementTolerancePixels = (
            self._to_float(requestPayload.get("movementTolerancePixels")) or 15.0
        )

        previousPoint = self._extract_point(requestPayload.get("previousPoint"))
        currentPoint = self._extract_point(requestPayload.get("currentPoint"))

        if previousPoint is None:
            previousPoint = self._extract_bbox_center(requestPayload.get("previousBBox"))
        if currentPoint is None:
            currentPoint = self._extract_bbox_center(
                requestPayload.get("currentBBox") or requestPayload.get("bbox")
            )

        # 이전/현재 둘 중 하나라도 없으면 정확한 이동량은 계산할 수 없습니다.
        # 이 경우는 "움직임 계산 정보 부족" 상태를 명시적으로 반환합니다.
        if previousPoint is None or currentPoint is None:
            return {
                "previousPoint": previousPoint,
                "currentPoint": currentPoint or referencePoint,
                "movementDistancePixels": None,
                "movementTolerancePixels": movementTolerancePixels,
                "movementSource": "insufficient_points",
                "isMostlyStationary": True,
            }

        deltaX = currentPoint["x"] - previousPoint["x"]
        deltaY = currentPoint["y"] - previousPoint["y"]
        movementDistancePixels = round(sqrt((deltaX ** 2) + (deltaY ** 2)), 4)

        return {
            "previousPoint": previousPoint,
            "currentPoint": currentPoint,
            "deltaX": round(deltaX, 4),
            "deltaY": round(deltaY, 4),
            "movementDistancePixels": movementDistancePixels,
            "movementTolerancePixels": movementTolerancePixels,
            "movementSource": "point_distance",
            "isMostlyStationary": movementDistancePixels <= movementTolerancePixels,
        }

    def _analyze_spatial_context(
        self,
        requestPayload: dict[str, Any],
        referencePoint: dict[str, float],
    ) -> dict[str, Any]:
        """
        공간 규칙을 확인합니다.

        핵심 목적:
        - 도로 위 box만 낙하물 후보로 본다
        - 차량 위 적재 박스는 낙하물 후보에서 제외한다
        """
        currentBBox = (
            requestPayload.get("currentBBox")
            or requestPayload.get("bbox")
            or requestPayload.get("currentBox")
        )
        parsedCurrentBBox = self._extract_bbox(currentBBox)

        currentPoint = self._extract_point(requestPayload.get("currentPoint")) or referencePoint
        roadBounds = requestPayload.get("roadBounds")
        isInsideRoadBounds = self._is_point_inside_road_bounds(currentPoint, roadBounds)

        overlapThreshold = self._to_float(requestPayload.get("vehicleOverlapThreshold")) or 0.2
        frameDetections = (
            requestPayload.get("currentFrameDetections")
            or requestPayload.get("surroundingObjects")
            or []
        )

        overlappingVehicles = []
        isOnVehicle = False

        if parsedCurrentBBox is not None and isinstance(frameDetections, list):
            for detectedObject in frameDetections:
                if not isinstance(detectedObject, dict):
                    continue

                vehicleClassId = self._to_int(
                    detectedObject.get("detectedClassId")
                    or detectedObject.get("classId")
                    or detectedObject.get("objectClassId")
                    or detectedObject.get("labelIndex")
                )
                vehicleClassName = str(
                    detectedObject.get("detectedClassName")
                    or detectedObject.get("className")
                    or detectedObject.get("labelName")
                    or detectedObject.get("objectType")
                    or ""
                ).strip().lower()

                if (
                    vehicleClassId not in self.VEHICLE_CLASS_IDS
                    and vehicleClassName not in self.VEHICLE_CLASS_NAMES
                ):
                    continue

                vehicleBBox = self._extract_bbox(
                    detectedObject.get("currentBBox")
                    or detectedObject.get("bbox")
                    or detectedObject.get("box")
                )
                if vehicleBBox is None:
                    continue

                overlapRatio = self._calculate_bbox_overlap_ratio(parsedCurrentBBox, vehicleBBox)
                centerInsideVehicle = self._is_point_inside_bbox(currentPoint, vehicleBBox)
                if overlapRatio >= overlapThreshold or centerInsideVehicle:
                    isOnVehicle = True
                    overlappingVehicles.append(
                        {
                            "objectId": detectedObject.get("objectId") or detectedObject.get("trackId"),
                            "classId": vehicleClassId,
                            "className": vehicleClassName,
                            "overlapRatio": overlapRatio,
                            "centerInsideVehicle": centerInsideVehicle,
                        }
                    )

        return {
            "currentPoint": currentPoint,
            "currentBBox": parsedCurrentBBox,
            "roadBounds": roadBounds,
            "isInsideRoadBounds": isInsideRoadBounds,
            "isOnVehicle": isOnVehicle,
            "vehicleOverlapThreshold": overlapThreshold,
            "overlappingVehicles": overlappingVehicles,
            "contextRule": "road_bounds_and_vehicle_overlap",
        }

    def _decide_abandoned_state(
        self,
        requestPayload: dict[str, Any],
        objectInfo: dict[str, Any],
        timeAnalysis: dict[str, Any],
        movementAnalysis: dict[str, Any],
        spatialAnalysis: dict[str, Any],
    ) -> dict[str, Any]:
        """
        최종 낙하물 여부를 결정합니다.

        현재 규칙:
        - box 클래스인가
        - 충분히 오래 있었는가
        - 거의 움직이지 않았는가
        - 차량 위 적재물이 아닌가
        - 도로 영역 안인가
        """
        isTargetClass = bool(objectInfo.get("isTargetClass"))
        isStationaryLongEnough = bool(timeAnalysis.get("isStationaryLongEnough"))
        isMostlyStationary = bool(movementAnalysis.get("isMostlyStationary"))
        isInsideRoadBounds = spatialAnalysis.get("isInsideRoadBounds")
        isOnVehicle = bool(spatialAnalysis.get("isOnVehicle"))
        shouldSaveEvent = bool(requestPayload.get("saveEvent", False))

        isAbandonedObject = (
            isTargetClass
            and isStationaryLongEnough
            and isMostlyStationary
            and not isOnVehicle
            and isInsideRoadBounds is not False
        )

        if isOnVehicle:
            reason = "box가 차량 bbox와 겹쳐 적재물로 판단되어 낙하물에서 제외되었습니다."
        elif isInsideRoadBounds is False:
            reason = "box 중심점이 도로 영역 밖에 있어 낙하물에서 제외되었습니다."
        elif isAbandonedObject:
            reason = "box가 기준 시간 이상 거의 움직이지 않았고 도로 위에 있어 낙하물로 판단되었습니다."
        else:
            reason = "정지 시간 또는 이동량 조건이 아직 충분하지 않아 낙하물로 확정하지 않았습니다."

        return {
            "isTargetClass": isTargetClass,
            "isAbandonedObject": isAbandonedObject,
            "isInsideRoadBounds": isInsideRoadBounds,
            "isOnVehicle": isOnVehicle,
            "shouldTriggerAlert": isAbandonedObject,
            "shouldSaveEvent": shouldSaveEvent and isAbandonedObject,
            "ruleType": "box_stationary_time_based",
            "reason": reason,
        }

    def _create_alert_message(
        self,
        requestPayload: dict[str, Any],
        objectInfo: dict[str, Any],
        timeAnalysis: dict[str, Any],
        movementAnalysis: dict[str, Any],
        spatialAnalysis: dict[str, Any],
        decision: dict[str, Any],
    ) -> str:
        """
        계산 결과를 사람이 읽기 쉬운 문장으로 바꿉니다.
        """
        locationLabel = requestPayload.get("location") or requestPayload.get("roadName")
        objectLabel = requestPayload.get("objectLabel") or objectInfo.get("className") or "box"
        observedDurationSeconds = timeAnalysis.get("observedDurationSeconds")
        movementDistancePixels = movementAnalysis.get("movementDistancePixels")
        isInsideRoadBounds = spatialAnalysis.get("isInsideRoadBounds")
        isOnVehicle = bool(spatialAnalysis.get("isOnVehicle"))

        durationLabel = (
            f"{observedDurationSeconds}초"
            if observedDurationSeconds is not None
            else "시간 정보 없음"
        )
        movementLabel = (
            f"{movementDistancePixels}px"
            if movementDistancePixels is not None
            else "이동량 정보 부족"
        )

        if decision.get("isAbandonedObject"):
            if locationLabel:
                return (
                    f"{locationLabel} 구간에서 {objectLabel} 낙하물 후보가 감지되었습니다. "
                    f"정지 시간 {durationLabel}, 이동량 {movementLabel} 입니다."
                )
            return (
                f"{objectLabel} 낙하물 후보가 감지되었습니다. "
                f"정지 시간 {durationLabel}, 이동량 {movementLabel} 입니다."
            )

        if isOnVehicle:
            return (
                f"{objectLabel} 가 감지되었지만 차량 위 적재물로 판단되어 낙하물 알림은 보내지 않습니다. "
                f"(정지 시간 {durationLabel}, 이동량 {movementLabel})"
            )

        if isInsideRoadBounds is False:
            return (
                f"{objectLabel} 가 감지되었지만 도로 영역 밖으로 판단되어 낙하물 알림은 보내지 않습니다. "
                f"(정지 시간 {durationLabel}, 이동량 {movementLabel})"
            )

        return (
            f"{objectLabel} 가 감지되었지만 아직 낙하물 조건은 충족하지 못했습니다. "
            f"(정지 시간 {durationLabel}, 이동량 {movementLabel})"
        )

    def _emit_alert_log(
        self,
        objectInfo: dict[str, Any],
        timeAnalysis: dict[str, Any],
        movementAnalysis: dict[str, Any],
        spatialAnalysis: dict[str, Any],
        decision: dict[str, Any],
        alertMessage: str,
    ) -> None:
        """
        앱 연동 전까지는 콘솔 로그를 임시 알림 채널로 사용합니다.
        """
        if not decision.get("shouldTriggerAlert"):
            return

        objectId = objectInfo.get("objectId") or "unknown-object"
        observedDurationSeconds = timeAnalysis.get("observedDurationSeconds")
        movementDistancePixels = movementAnalysis.get("movementDistancePixels")
        isOnVehicle = spatialAnalysis.get("isOnVehicle")
        isInsideRoadBounds = spatialAnalysis.get("isInsideRoadBounds")

        print("[ALERT][ABANDONED_OBJECT] 낙하물/방치물 후보 감지")
        print(f"[ALERT][ABANDONED_OBJECT] objectId={objectId}")
        print(
            "[ALERT][ABANDONED_OBJECT] "
            f"observedDurationSeconds={observedDurationSeconds}, "
            f"movementDistancePixels={movementDistancePixels}, "
            f"isOnVehicle={isOnVehicle}, "
            f"isInsideRoadBounds={isInsideRoadBounds}"
        )
        print(f"[ALERT][ABANDONED_OBJECT] message={alertMessage}")

    def _save_detection_result(
        self,
        requestPayload: dict[str, Any],
        objectInfo: dict[str, Any],
        timeAnalysis: dict[str, Any],
        movementAnalysis: dict[str, Any],
        spatialAnalysis: dict[str, Any],
        decision: dict[str, Any],
        alertMessage: str,
    ) -> dict[str, Any]:
        """
        [운영 전 미구현 영역]
        실제 DB 저장은 다음 단계에서 붙일 예정이라, 지금은 저장 계획만 반환합니다.
        """
        shouldSaveEvent = bool(decision.get("shouldSaveEvent"))
        eventTime = (
            requestPayload.get("eventTime")
            or requestPayload.get("capturedAt")
            or requestPayload.get("currentTime")
            or datetime.now().isoformat()
        )
        snapshotImage = (
            requestPayload.get("snapshotImagePath")
            or requestPayload.get("snapshotImageUrl")
            or requestPayload.get("snapshotImageBase64")
        )

        if shouldSaveEvent:
            print(
                "[AbandonedObjectService] DB save skipped intentionally. "
                "Storage plan is ready, but DB connection will be added later."
            )

        return {
            "saved": False,
            "shouldSaveLater": shouldSaveEvent,
            "reason": "DB 연결은 아직 하지 않았고 저장 설계만 유지 중입니다.",
            "plannedRecordPreview": {
                "eventTime": eventTime,
                "cameraId": requestPayload.get("cctvId"),
                "objectType": "abandoned_object",
                "alertMessage": alertMessage,
                "snapshotImage": snapshotImage,
            },
            "dbPlan": self.dbSavePlan,
            "relatedAnalyses": {
                "objectInfo": objectInfo,
                "timeAnalysis": timeAnalysis,
                "movementAnalysis": movementAnalysis,
                "spatialAnalysis": spatialAnalysis,
                "decision": decision,
            },
        }

    def _extract_point(self, pointPayload: Any) -> dict[str, float] | None:
        """
        점 좌표를 공통 형식으로 정리합니다.
        """
        if not isinstance(pointPayload, dict):
            return None

        xValue = self._to_float(pointPayload.get("x", pointPayload.get("X")))
        yValue = self._to_float(pointPayload.get("y", pointPayload.get("Y")))
        if xValue is None or yValue is None:
            return None

        return {"x": xValue, "y": yValue}

    def _extract_bbox_center(self, bboxPayload: Any) -> dict[str, float] | None:
        """
        bbox가 있으면 중심점으로 바꿉니다.
        """
        parsedBBox = self._extract_bbox(bboxPayload)
        if parsedBBox is None:
            return None

        return {
            "x": round((parsedBBox["x1"] + parsedBBox["x2"]) / 2, 4),
            "y": round((parsedBBox["y1"] + parsedBBox["y2"]) / 2, 4),
        }

    def _extract_bbox(self, bboxPayload: Any) -> dict[str, float] | None:
        """
        bbox를 {x1, y1, x2, y2} 형식으로 통일합니다.
        """
        if not isinstance(bboxPayload, dict):
            return None

        x1 = self._to_float(bboxPayload.get("x1"))
        y1 = self._to_float(bboxPayload.get("y1"))
        x2 = self._to_float(bboxPayload.get("x2"))
        y2 = self._to_float(bboxPayload.get("y2"))

        if x1 is None or y1 is None or x2 is None or y2 is None:
            return None

        # 좌상단/우하단 순서가 뒤바뀌어 들어오더라도 안전하게 정렬합니다.
        minX = min(x1, x2)
        maxX = max(x1, x2)
        minY = min(y1, y2)
        maxY = max(y1, y2)

        return {"x1": minX, "y1": minY, "x2": maxX, "y2": maxY}

    def _calculate_bbox_overlap_ratio(
        self,
        firstBBox: dict[str, float] | None,
        secondBBox: dict[str, float] | None,
    ) -> float:
        """
        첫 번째 bbox 면적 중 두 번째 bbox와 겹친 비율을 구합니다.

        낙하물 box가 차량 bbox와 많이 겹치면 적재물일 가능성이 높다고 보는 규칙입니다.
        """
        if firstBBox is None or secondBBox is None:
            return 0.0

        overlapLeft = max(firstBBox["x1"], secondBBox["x1"])
        overlapTop = max(firstBBox["y1"], secondBBox["y1"])
        overlapRight = min(firstBBox["x2"], secondBBox["x2"])
        overlapBottom = min(firstBBox["y2"], secondBBox["y2"])

        overlapWidth = max(0.0, overlapRight - overlapLeft)
        overlapHeight = max(0.0, overlapBottom - overlapTop)
        overlapArea = overlapWidth * overlapHeight

        firstArea = self._calculate_bbox_area(firstBBox)
        if firstArea <= 0:
            return 0.0

        return round(overlapArea / firstArea, 4)

    def _calculate_bbox_area(self, bbox: dict[str, float] | None) -> float:
        """
        bbox 면적 계산용 헬퍼입니다.
        """
        if bbox is None:
            return 0.0
        return max(0.0, bbox["x2"] - bbox["x1"]) * max(0.0, bbox["y2"] - bbox["y1"])

    def _is_point_inside_bbox(
        self,
        point: dict[str, float] | None,
        bbox: dict[str, float] | None,
    ) -> bool:
        """
        점이 bbox 안에 있는지 검사합니다.
        """
        if point is None or bbox is None:
            return False

        return (
            bbox["x1"] <= point["x"] <= bbox["x2"]
            and bbox["y1"] <= point["y"] <= bbox["y2"]
        )

    def _is_point_inside_road_bounds(
        self,
        point: dict[str, float] | None,
        roadBoundsPayload: Any,
    ) -> bool | None:
        """
        점이 roadBounds 안에 있는지 검사합니다.

        반환 규칙:
        - True: 도로 안
        - False: 도로 밖
        - None: roadBounds 자체가 없어 판단 불가
        """
        if point is None or not isinstance(roadBoundsPayload, dict):
            return None

        minX = self._to_float(roadBoundsPayload.get("minX"))
        maxX = self._to_float(roadBoundsPayload.get("maxX"))
        minY = self._to_float(roadBoundsPayload.get("minY"))
        maxY = self._to_float(roadBoundsPayload.get("maxY"))

        # x 축 범위만 주는 카메라 세팅도 있을 수 있어 부분 입력도 허용합니다.
        isInsideXAxis = True
        isInsideYAxis = True

        if minX is not None and point["x"] < minX:
            isInsideXAxis = False
        if maxX is not None and point["x"] > maxX:
            isInsideXAxis = False
        if minY is not None and point["y"] < minY:
            isInsideYAxis = False
        if maxY is not None and point["y"] > maxY:
            isInsideYAxis = False

        return isInsideXAxis and isInsideYAxis

    def _parse_datetime(self, value: Any) -> datetime | None:
        """
        문자열 또는 datetime 값을 안전하게 datetime 객체로 바꿉니다.
        """
        if isinstance(value, datetime):
            return value
        if not value:
            return None
        if not isinstance(value, str):
            return None

        normalizedValue = value.strip()
        if not normalizedValue:
            return None

        # ISO 형식과 "Z" 표기도 최대한 유연하게 받아들입니다.
        try:
            return datetime.fromisoformat(normalizedValue.replace("Z", "+00:00"))
        except ValueError:
            return None

    def _to_float(self, value: Any) -> float | None:
        """
        숫자형으로 변환 가능한 값을 float로 바꿉니다.
        """
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _to_int(self, value: Any) -> int | None:
        """
        숫자형으로 변환 가능한 값을 int로 바꿉니다.
        """
        if value is None or value == "":
            return None
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None

from datetime import datetime
from math import sqrt
from typing import Any


class EmergencyVehicleService:
    """
    긴급출동 차량 후속 판단 서비스입니다.

    이 서비스는 "모델이 이미 긴급출동 차량 후보를 지정했다"는 전제에서,
    그 차량의 이동 방향, 차선 위치, 같은 방향 차량 목록을 계산해
    실제 관제에 쓸 수 있는 정보로 바꿔 줍니다.

    쉬운 비유:
    - 모델 = 화면에서 중요한 차량을 찾아주는 눈
    - 이 서비스 = 그 차량이 어디로 가는지 해석하는 판단 담당자
    """

    def __init__(self):
        """
        현재 단계에서는 DB를 실제로 연결하지 않습니다.

        이유:
        - 지금 먼저 완성해야 하는 것은 "탐지 후 해석 로직"
        - 이벤트 저장은 다음 단계에서 붙여도 늦지 않음

        그래서 실제 DB insert 대신,
        나중에 저장할 필드 계획만 코드 안에 남겨 둡니다.
        """
        self.dbSavePlan = {
            "plannedTablePurpose": "긴급출동 차량 이벤트 이력 저장",
            "plannedFields": [
                "eventTime",
                "cameraId",
                "vehicleType",
                "laneNumber",
                "laneSource",
                "alertMessage",
                "snapshotImagePathOrBlob",
            ],
            "notes": [
                "우선 저장 우선순위가 높은 값은 이벤트 발생 시각(eventTime)입니다.",
                "차선은 숫자만 저장하지 않고 출처(laneSource)도 같이 저장하는 방향을 권장합니다.",
                "이미지는 파일 경로 저장 또는 blob 저장 중 어떤 방식이 맞는지 다음 단계에서 결정합니다.",
            ],
        }

    def detect_emergency_vehicle(self, payload: dict | None = None) -> dict[str, Any]:
        """
        긴급출동 차량 분석 메인 입구입니다.

        처리 순서:
        1. 입력 검증
        2. 이동 벡터 계산
        3. 차선 분석
        4. 같은 방향 차량 찾기
        5. 알림 문구 생성
        6. 로그 출력
        7. DB는 아직 저장하지 않고 계획 정보만 반환
        """
        requestPayload = payload or {}

        print("[EmergencyVehicleService] detect_emergency_vehicle start")
        print(f"[EmergencyVehicleService] payload keys: {list(requestPayload.keys())}")

        validationResult = self._validate_payload(requestPayload)
        if not validationResult.get("ok"):
            return validationResult

        previousPoint = validationResult["previousPoint"]
        currentPoint = validationResult["currentPoint"]
        vehicleType = str(requestPayload.get("vehicleType") or "긴급차량")

        movementVector = self._calculate_movement_vector(previousPoint, currentPoint)
        laneAnalysis = self._analyze_lane(requestPayload, currentPoint)
        highwayContext = self._load_highway_context(requestPayload)
        sameDirectionVehicles = self._find_same_direction_vehicles(
            requestPayload,
            movementVector,
        )
        alertMessage = self._create_alert_message(
            vehicleType,
            laneAnalysis,
            highwayContext,
            sameDirectionVehicles,
            movementVector,
        )

        self._emit_alert_log(
            vehicleType,
            laneAnalysis,
            movementVector,
            sameDirectionVehicles,
            highwayContext,
            alertMessage,
        )

        dbSaveResult = self._save_detection_result(
            requestPayload,
            vehicleType,
            laneAnalysis,
            movementVector,
            sameDirectionVehicles,
            alertMessage,
            highwayContext,
        )

        print("[EmergencyVehicleService] detect_emergency_vehicle completed")

        return {
            "ok": True,
            "message": "Emergency vehicle detected and event analyzed",
            "vehicleType": vehicleType,
            "movementVector": movementVector,
            "laneAnalysis": laneAnalysis,
            "laneNumber": laneAnalysis["laneNumber"],
            "laneSource": laneAnalysis["laneSource"],
            "isLaneEstimated": laneAnalysis["isLaneEstimated"],
            "sameDirectionVehicles": sameDirectionVehicles,
            "sameDirectionVehicleCount": len(sameDirectionVehicles),
            "highwayContext": highwayContext,
            "alertMessage": alertMessage,
            "dbSaveResult": dbSaveResult,
        }

    def _validate_payload(self, requestPayload: dict[str, Any]) -> dict[str, Any]:
        """
        긴급출동 차량 해석에 필요한 최소 입력을 검사합니다.

        현재 이 기능에서 가장 중요한 최소 입력은
        `previousPoint` 와 `currentPoint` 입니다.
        이 두 점이 있어야 "어디로 움직였는가"를 계산할 수 있습니다.
        """
        if not isinstance(requestPayload, dict):
            return {
                "ok": False,
                "message": "payload는 딕셔너리 형태여야 합니다.",
            }

        previousPoint = self._extract_point(requestPayload.get("previousPoint"))
        currentPoint = self._extract_point(requestPayload.get("currentPoint"))

        if previousPoint is None or currentPoint is None:
            return {
                "ok": False,
                "message": "previousPoint 와 currentPoint 좌표가 모두 필요합니다.",
                "requiredExample": {
                    "previousPoint": {"x": 100, "y": 220},
                    "currentPoint": {"x": 145, "y": 225},
                },
            }

        return {
            "ok": True,
            "previousPoint": previousPoint,
            "currentPoint": currentPoint,
        }

    def _extract_point(self, pointPayload: Any) -> dict[str, float] | None:
        """
        점 좌표를 공통 형식으로 정리합니다.

        `x/y`, `X/Y` 둘 다 허용하는 이유는
        상위 모듈마다 키 이름이 조금씩 달라도 유연하게 받기 위해서입니다.
        """
        if not isinstance(pointPayload, dict):
            return None

        xValue = self._to_float(pointPayload.get("x", pointPayload.get("X")))
        yValue = self._to_float(pointPayload.get("y", pointPayload.get("Y")))

        if xValue is None or yValue is None:
            return None

        return {"x": xValue, "y": yValue}

    def _calculate_movement_vector(
        self,
        previousPoint: dict[str, float],
        currentPoint: dict[str, float],
    ) -> dict[str, Any]:
        """
        두 점을 기준으로 이동 벡터를 계산합니다.

        반환 값 의미:
        - deltaX / deltaY: x축, y축 방향 이동량
        - magnitude: 전체 이동 거리
        - normalizedX / normalizedY: 방향만 비교하기 쉽게 1로 정규화한 값
        - directionLabel: 사람이 읽기 쉬운 방향 설명
        """
        deltaX = currentPoint["x"] - previousPoint["x"]
        deltaY = currentPoint["y"] - previousPoint["y"]
        magnitude = round(sqrt((deltaX ** 2) + (deltaY ** 2)), 4)

        if magnitude == 0:
            return {
                "deltaX": 0.0,
                "deltaY": 0.0,
                "magnitude": 0.0,
                "normalizedX": 0.0,
                "normalizedY": 0.0,
                "directionLabel": "정지",
            }

        normalizedX = round(deltaX / magnitude, 4)
        normalizedY = round(deltaY / magnitude, 4)

        if abs(deltaX) > abs(deltaY):
            directionLabel = "오른쪽" if deltaX > 0 else "왼쪽"
        elif abs(deltaY) > abs(deltaX):
            directionLabel = "아래쪽" if deltaY > 0 else "위쪽"
        else:
            if deltaX > 0 and deltaY > 0:
                directionLabel = "오른쪽 아래 대각선"
            elif deltaX > 0 and deltaY < 0:
                directionLabel = "오른쪽 위 대각선"
            elif deltaX < 0 and deltaY > 0:
                directionLabel = "왼쪽 아래 대각선"
            else:
                directionLabel = "왼쪽 위 대각선"

        return {
            "deltaX": round(deltaX, 4),
            "deltaY": round(deltaY, 4),
            "magnitude": magnitude,
            "normalizedX": normalizedX,
            "normalizedY": normalizedY,
            "directionLabel": directionLabel,
        }

    def _analyze_lane(
        self,
        requestPayload: dict[str, Any],
        currentPoint: dict[str, float],
    ) -> dict[str, Any]:
        """
        차선 정보를 해석합니다.

        우선순위:
        1. laneNumber 직접 제공
        2. laneBoundaries 경계 정보로 판단
        3. laneCount + roadBounds 로 추정
        4. 없으면 판단 불가
        """
        laneNumber = self._to_int(requestPayload.get("laneNumber"))
        if laneNumber is not None and laneNumber > 0:
            return {
                "laneNumber": laneNumber,
                "laneSource": "provided_by_api",
                "isLaneEstimated": False,
            }

        laneBoundaries = requestPayload.get("laneBoundaries")
        if isinstance(laneBoundaries, list):
            laneNumber = self._find_lane_by_boundaries(laneBoundaries, currentPoint)
            if laneNumber is not None:
                return {
                    "laneNumber": laneNumber,
                    "laneSource": "provided_by_lane_boundaries",
                    "isLaneEstimated": False,
                }

        roadBounds = requestPayload.get("roadBounds")
        laneCount = self._to_int(requestPayload.get("laneCount"))
        if isinstance(roadBounds, dict) and laneCount is not None and laneCount > 0:
            laneNumber = self._find_lane_by_lane_count(roadBounds, laneCount, currentPoint)
            if laneNumber is not None:
                return {
                    "laneNumber": laneNumber,
                    "laneSource": "estimated_from_lane_count",
                    "isLaneEstimated": True,
                }

        return {
            "laneNumber": None,
            "laneSource": "unavailable",
            "isLaneEstimated": False,
        }

    def _find_lane_by_boundaries(
        self,
        laneBoundaries: list[Any],
        currentPoint: dict[str, float],
    ) -> int | None:
        """
        laneBoundaries 를 기준으로 현재 x 좌표가 어느 차선 구간에 있는지 찾습니다.

        기대 형식 예시:
        [650, 820, 980, 1160]
        그러면 구간은 650~820, 820~980, 980~1160 으로 해석합니다.
        """
        numericBoundaries = [
            self._to_float(boundary)
            for boundary in laneBoundaries
            if self._to_float(boundary) is not None
        ]
        if len(numericBoundaries) < 2:
            return None

        sortedBoundaries = sorted(numericBoundaries)
        pointX = currentPoint["x"]

        for index in range(len(sortedBoundaries) - 1):
            leftBoundary = sortedBoundaries[index]
            rightBoundary = sortedBoundaries[index + 1]
            if leftBoundary <= pointX <= rightBoundary:
                return index + 1

        return None

    def _find_lane_by_lane_count(
        self,
        roadBounds: dict[str, Any],
        laneCount: int,
        currentPoint: dict[str, float],
    ) -> int | None:
        """
        전체 도로 폭을 차선 수로 균등 분할해서 차선을 추정합니다.

        정확한 경계 정보가 없을 때 쓰는 fallback 규칙입니다.
        """
        minX = self._to_float(roadBounds.get("minX"))
        maxX = self._to_float(roadBounds.get("maxX"))
        if minX is None or maxX is None or laneCount <= 0 or maxX <= minX:
            return None

        pointX = currentPoint["x"]
        if pointX < minX or pointX > maxX:
            return None

        laneWidth = (maxX - minX) / laneCount
        if laneWidth <= 0:
            return None

        laneIndex = int((pointX - minX) / laneWidth) + 1
        return max(1, min(laneIndex, laneCount))

    def _find_same_direction_vehicles(
        self,
        requestPayload: dict[str, Any],
        movementVector: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """
        주변 차량 목록 중 같은 방향으로 움직이는 차량을 찾습니다.

        현재 기준:
        - surroundingVehicles 목록 사용
        - 각 차량의 이전/현재 점으로 이동 벡터 계산
        - cosine similarity 가 threshold 이상이면 같은 방향으로 판단
        """
        surroundingVehicles = requestPayload.get("surroundingVehicles") or []
        if not isinstance(surroundingVehicles, list):
            return []

        similarityThreshold = (
            self._to_float(requestPayload.get("sameDirectionThreshold")) or 0.85
        )
        result: list[dict[str, Any]] = []

        for vehiclePayload in surroundingVehicles:
            if not isinstance(vehiclePayload, dict):
                continue

            previousPoint = self._extract_point(vehiclePayload.get("previousPoint"))
            currentPoint = self._extract_point(vehiclePayload.get("currentPoint"))
            if previousPoint is None or currentPoint is None:
                continue

            targetVector = self._calculate_movement_vector(previousPoint, currentPoint)
            cosineSimilarity = self._calculate_cosine_similarity(movementVector, targetVector)
            if cosineSimilarity is None or cosineSimilarity < similarityThreshold:
                continue

            vehicleLaneAnalysis = self._analyze_lane(vehiclePayload, currentPoint)

            result.append(
                {
                    "vehicleId": vehiclePayload.get("vehicleId") or vehiclePayload.get("trackId"),
                    "vehicleType": vehiclePayload.get("vehicleType")
                    or vehiclePayload.get("className")
                    or "surrounding_vehicle",
                    "movementVector": targetVector,
                    "cosineSimilarity": cosineSimilarity,
                    "laneAnalysis": vehicleLaneAnalysis,
                }
            )

        return result

    def _calculate_cosine_similarity(
        self,
        firstVector: dict[str, Any],
        secondVector: dict[str, Any],
    ) -> float | None:
        """
        두 벡터의 방향 유사도를 계산합니다.

        1.0 에 가까울수록 같은 방향,
        -1.0 에 가까울수록 반대 방향입니다.
        """
        firstMagnitude = self._to_float(firstVector.get("magnitude"))
        secondMagnitude = self._to_float(secondVector.get("magnitude"))
        if (
            firstMagnitude is None
            or secondMagnitude is None
            or firstMagnitude == 0
            or secondMagnitude == 0
        ):
            return None

        firstX = self._to_float(firstVector.get("normalizedX"))
        firstY = self._to_float(firstVector.get("normalizedY"))
        secondX = self._to_float(secondVector.get("normalizedX"))
        secondY = self._to_float(secondVector.get("normalizedY"))
        if None in {firstX, firstY, secondX, secondY}:
            return None

        return round((firstX * secondX) + (firstY * secondY), 4)

    def _load_highway_context(self, requestPayload: dict[str, Any]) -> dict[str, Any]:
        """
        현재 요청에 들어온 도로/카메라 문맥 정보를 정리합니다.

        이전 버전처럼 외부 서비스 조회는 하지 않고,
        지금은 요청에 포함된 값만 정리해서 반환합니다.
        """
        return {
            "cctvId": self._to_int(requestPayload.get("cctvId")),
            "roadName": requestPayload.get("roadName"),
            "location": requestPayload.get("location"),
            "routeNo": requestPayload.get("routeNo"),
        }

    def _create_alert_message(
        self,
        vehicleType: str,
        laneAnalysis: dict[str, Any],
        highwayContext: dict[str, Any],
        sameDirectionVehicles: list[dict[str, Any]],
        movementVector: dict[str, Any],
    ) -> str:
        """
        관제나 로그에서 바로 읽을 수 있는 문장으로 바꿉니다.
        """
        locationLabel = highwayContext.get("location") or highwayContext.get("roadName")
        directionLabel = movementVector.get("directionLabel") or "미상 방향"
        laneNumber = laneAnalysis.get("laneNumber")
        isLaneEstimated = bool(laneAnalysis.get("isLaneEstimated"))
        sameDirectionVehicleCount = len(sameDirectionVehicles)

        if laneNumber is None:
            laneLabel = "차선 정보 없음"
        elif isLaneEstimated:
            laneLabel = f"약 {laneNumber}차선으로 추정되는 위치"
        else:
            laneLabel = f"{laneNumber}차선"

        if locationLabel:
            return (
                f"{locationLabel} 구간에서 {vehicleType}이(가) {directionLabel} 방향으로 이동 중입니다. "
                f"현재 위치는 {laneLabel}이며, 같은 방향 차량 {sameDirectionVehicleCount}대가 확인되었습니다."
            )

        return (
            f"{vehicleType}이(가) {directionLabel} 방향으로 이동 중입니다. "
            f"현재 위치는 {laneLabel}이며, 같은 방향 차량 {sameDirectionVehicleCount}대가 확인되었습니다."
        )

    def _emit_alert_log(
        self,
        vehicleType: str,
        laneAnalysis: dict[str, Any],
        movementVector: dict[str, Any],
        sameDirectionVehicles: list[dict[str, Any]],
        highwayContext: dict[str, Any],
        alertMessage: str,
    ) -> None:
        """
        앱 연동 전까지는 콘솔 로그를 임시 알림 채널로 사용합니다.
        """
        print("[ALERT][EMERGENCY_VEHICLE] 긴급출동 차량 후보 감지")
        print(
            "[ALERT][EMERGENCY_VEHICLE] "
            f"vehicleType={vehicleType}, "
            f"laneNumber={laneAnalysis.get('laneNumber')}, "
            f"laneSource={laneAnalysis.get('laneSource')}, "
            f"direction={movementVector.get('directionLabel')}, "
            f"sameDirectionVehicleCount={len(sameDirectionVehicles)}, "
            f"location={highwayContext.get('location') or highwayContext.get('roadName')}"
        )
        print(f"[ALERT][EMERGENCY_VEHICLE] message={alertMessage}")

    def _save_detection_result(
        self,
        requestPayload: dict[str, Any],
        vehicleType: str,
        laneAnalysis: dict[str, Any],
        movementVector: dict[str, Any],
        sameDirectionVehicles: list[dict[str, Any]],
        alertMessage: str,
        highwayContext: dict[str, Any],
    ) -> dict[str, Any]:
        """
        [운영 전 미구현 영역]
        실제 DB 저장은 아직 하지 않고,
        나중에 어떤 값을 저장할지 계획 정보만 반환합니다.
        """
        shouldSaveEvent = bool(requestPayload.get("saveEvent", False))
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
                "[EmergencyVehicleService] DB save skipped intentionally. "
                "Storage plan is ready, but DB connection will be added later."
            )

        return {
            "saved": False,
            "shouldSaveLater": shouldSaveEvent,
            "reason": "DB 연결은 아직 하지 않았고 저장 설계만 유지 중입니다.",
            "plannedRecordPreview": {
                "eventTime": eventTime,
                "cameraId": highwayContext.get("cctvId"),
                "vehicleType": vehicleType,
                "laneNumber": laneAnalysis.get("laneNumber"),
                "laneSource": laneAnalysis.get("laneSource"),
                "sameDirectionVehicleCount": len(sameDirectionVehicles),
                "alertMessage": alertMessage,
                "snapshotImage": snapshotImage,
            },
            "dbPlan": self.dbSavePlan,
            "relatedAnalyses": {
                "laneAnalysis": laneAnalysis,
                "movementVector": movementVector,
                "sameDirectionVehicles": sameDirectionVehicles,
                "highwayContext": highwayContext,
            },
        }

    def _to_float(self, value: Any) -> float | None:
        """
        숫자형으로 바꿀 수 있는 값을 float 로 변환합니다.
        """
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _to_int(self, value: Any) -> int | None:
        """
        숫자형으로 바꿀 수 있는 값을 int 로 변환합니다.
        """
        if value is None or value == "":
            return None
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None

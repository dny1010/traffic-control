import os
import requests
from database.config import SessionLocal
from database.event_repository import create_event_with_detection

class TrafficJamService:
    def __init__(self):
        self.api_key = os.getenv("TAGO_API_KEY")
        self.base_url = os.getenv("TAGO_BASE_URL", "http://www.tago.go.kr")
        self.traffic_info_endpoint = os.getenv("TAGO_TRAFFIC_INFO_ENDPOINT", "/api/TrafficInfo")
        self.db = SessionLocal()

    def detect_traffic_jam(self, road_id=None):
        """
        교통체증 감지 및 이벤트 생성
        """
        try:
            traffic_data = self.fetch_traffic_info(road_id)

            if not traffic_data:
                return {"message": "No traffic data available"}

            events = self.analyze_and_create_events(traffic_data)

            return {
                "message": "Traffic jam detection completed",
                "detected_events": len(events),
                "events": events
            }
        except Exception as e:
            return {"error": str(e)}

    def fetch_traffic_info(self, road_id=None):
        """
        TAGO API에서 실시간 교통 정보 조회
        """
        try:
            params = {
                "apiKey": self.api_key,
                "type": "json"
            }

            if road_id:
                params["roadId"] = road_id

            url = f"{self.base_url.rstrip('/')}{self.traffic_info_endpoint}"
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()

            data = response.json()
            return data
        except requests.exceptions.RequestException as e:
            print(f"API 호출 실패: {e}")
            return None

    def analyze_and_create_events(self, traffic_data):
        """
        교통 데이터를 분석하여 이벤트 생성
        """
        events = []

        try:
            if "response" in traffic_data:
                items = traffic_data["response"].get("items", [])

                for item in items:
                    congestion_level = item.get("congestionLevel", "normal")
                    speed = item.get("speed", 0)
                    cctv_id = item.get("cctvId", 1)
                    road_name = item.get("roadName", "Unknown")

                    if congestion_level in ["heavy", "severe"] or (speed and speed < 20):
                        detection, event = create_event_with_detection(
                            db=self.db,
                            cctv_id=int(cctv_id),
                            event_type="traffic_jam",
                            description=f"교통체증 감지: {road_name}",
                            metadata={
                                "congestion_level": congestion_level,
                                "speed": speed,
                                "road_name": road_name,
                            },
                            object_type="traffic_jam",
                        )
                        events.append(
                            {
                                "event_id": event.id,
                                "detection_id": detection.id,
                                "road": road_name,
                                "level": congestion_level,
                            }
                        )

                self.db.commit()
        except Exception as e:
            self.db.rollback()
            print(f"이벤트 생성 실패: {e}")

        return events

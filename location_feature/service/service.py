class LocationFeatureService:
    def current_location(self):
        return {"message": "현재 위치 조회 구조 준비 완료"}

    def nearby_events(self, distance_km: float = 3.0):
        return {
            "message": "거리 기반 이벤트 필터 구조 준비 완료",
            "distance_km": distance_km,
        }
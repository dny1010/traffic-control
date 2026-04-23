class MapFeatureService:
    def base_map(self):
        return {"message": "기본 지도 표시 구조 준비 완료"}

    def event_markers(self):
        return {"message": "이벤트 마커 표시 구조 준비 완료"}

    def event_detail(self, event_id: int):
        return {"message": "마커 클릭 상세 조회 구조 준비 완료", "event_id": event_id}
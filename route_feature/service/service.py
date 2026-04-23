class RouteFeatureService:
    def search_route(self, origin: str, destination: str):
        return {
            "message": "길찾기 경로 검색 구조 준비 완료",
            "origin": origin,
            "destination": destination,
        }

    def map_guidance(self, route_id: str):
        return {"message": "지도 연동 경로 안내 구조 준비 완료", "route_id": route_id}
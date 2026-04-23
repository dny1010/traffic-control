class NotificationFeatureService:
    def realtime_receive(self):
        return {"message": "실시간 이벤트 수신 구조 준비 완료"}

    def push_notify(self):
        return {"message": "푸시 알림 구조 준비 완료"}

    def list_notifications(self):
        return {"message": "알림 리스트 조회 구조 준비 완료"}
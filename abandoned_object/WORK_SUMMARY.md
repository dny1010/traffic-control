# Abandoned Object 작업 정리

## 1. 이 기능이 하는 일

`abandoned_object`는 **모델이 이미 `box` 객체를 탐지했다는 전제**에서,
그 객체가 실제로 **도로 위 낙하물처럼 보이는지 후속 규칙으로 판단하는 기능**입니다.

즉 역할을 나누면 이렇게 보면 됩니다.

- 모델/추론 코드: 영상에서 `box`, `truck`, `car` 등을 탐지
- `abandoned_object/service/service.py`: 탐지 결과를 받아 낙하물 여부 판단
- `abandoned_object/view/router.py`: API 요청을 받아 서비스 결과 반환

쉬운 비유:

- 모델 = 눈
- `service.py` = 판단 담당자
- `router.py` = 출입문


## 2. 현재 남아 있는 파일 구조

현재 `abandoned_object` 폴더는 기능에 필요한 핵심 파일만 남겨 둔 상태입니다.

```text
abandoned_object/
  model/
    .gitkeep
  service/
    service.py
  video/
    .gitkeep
  view/
    router.py
  WORK_SUMMARY.md
```

설명:

- `service/service.py`
  - 낙하물 판단 핵심 로직
- `view/router.py`
  - `/detect` API 라우트
- `model/.gitkeep`, `video/.gitkeep`
  - 나중에 테스트 파일을 다시 넣을 수 있도록 폴더만 유지
- `WORK_SUMMARY.md`
  - 현재 작업 정리 문서


## 3. 이번에 구현된 핵심 기능

현재 `abandoned_object`에 들어간 기능은 아래와 같습니다.

### 3-1. `box` 클래스만 낙하물 판단 대상으로 처리

- 데이터셋 기준 `box` 클래스 인덱스는 `2`
- 문자열 `box`로 들어와도 처리 가능

즉 아래 둘 다 허용합니다.

```json
{ "detectedClassId": 2 }
```

```json
{ "detectedClassName": "box" }
```

### 3-2. 정지 시간 계산

아래 순서로 시간을 계산합니다.

1. `observedDurationSeconds`
2. `firstDetectedAt` ~ `lastDetectedAt`
3. `observedFrameCount / fps`

기본 정지 시간 기준은 `5초`입니다.

### 3-3. 이동량 계산

- `previousPoint` / `currentPoint`
- 또는 `previousBBox` / `currentBBox`

를 사용해서 얼마나 움직였는지 계산합니다.

기본 이동 허용치는 `15px`입니다.

즉:

- 오래 있었더라도 많이 움직이면 낙하물 아님
- 오래 있었고 거의 안 움직이면 낙하물 후보

### 3-4. 도로 영역 필터링

`roadBounds`가 들어오면,
객체 중심점이 도로 안에 있는지 확인합니다.

이 규칙이 필요한 이유:

- 도로 밖 물체까지 낙하물로 처리하면 오탐이 많아짐

### 3-5. 차량 적재물 제외 규칙

같은 프레임의 차량 bbox(`truck`, `car`, `bus`, `motorcycle`, `bicycle`)와
현재 `box`가 많이 겹치면 **낙하물이 아니라 차량 적재물**로 보고 제외합니다.

이 규칙이 필요한 이유:

- 트럭 위 박스를 도로 위 낙하물로 잘못 판단하는 문제 방지

### 3-6. 로그 알림

앱 연동이 아직 없기 때문에,
낙하물 조건이 맞으면 콘솔에 아래 형식으로 로그를 찍습니다.

```text
[ALERT][ABANDONED_OBJECT] 낙하물/방치물 후보 감지
```

### 3-7. DB는 아직 연결하지 않고 계획만 유지

실제 DB 저장은 아직 하지 않습니다.

대신 `dbSaveResult` 안에 아래 정보를 남기도록 했습니다.

- 지금 이 결과가 저장 후보인지
- 나중에 어떤 필드를 저장하면 되는지
- 예시 저장값 미리보기

현재 저장 계획 필드:

- `eventTime`
- `cameraId`
- `objectType`
- `alertMessage`
- `snapshotImagePathOrBlob`


## 4. 현재 API 흐름

현재 흐름은 아래와 같습니다.

1. 상위 탐지 모듈이 `box` 탐지 결과를 만듦
2. `/detect` API로 payload 전달
3. `router.py`가 `service.py` 호출
4. `service.py`가 시간/이동/공간 규칙 계산
5. 최종 낙하물 여부 반환
6. 조건이 맞으면 로그 알림 출력

즉 현재는 **탐지 자체를 하는 기능이 아니라, 탐지 결과를 해석하는 기능**입니다.


## 5. 현재 입력으로 받는 주요 값

최소 입력 예시는 이런 형태입니다.

```json
{
  "detectedClassId": 2,
  "currentBBox": { "x1": 100, "y1": 120, "x2": 180, "y2": 220 },
  "observedDurationSeconds": 6
}
```

정확도를 높이려면 아래 값들이 추가되는 것이 좋습니다.

```json
{
  "detectedClassId": 2,
  "objectId": "track-1",
  "previousBBox": { "x1": 102, "y1": 121, "x2": 182, "y2": 221 },
  "currentBBox": { "x1": 100, "y1": 120, "x2": 180, "y2": 220 },
  "observedDurationSeconds": 6,
  "roadBounds": { "minX": 100, "maxX": 760, "minY": 80, "maxY": 470 },
  "currentFrameDetections": [
    {
      "detectedClassId": 4,
      "bbox": { "x1": 80, "y1": 70, "x2": 300, "y2": 260 }
    }
  ],
  "saveEvent": true
}
```


## 6. 최종 판단 기준

현재 `isAbandonedObject=True`가 되려면 아래 조건을 만족해야 합니다.

1. `box` 클래스이다
2. 기준 시간 이상 정지했다
3. 거의 움직이지 않았다
4. 차량 위 적재물이 아니다
5. 도로 영역 밖으로 판정되지 않았다

즉 현재 규칙은:

**`box` + 오래 정지 + 거의 안 움직임 + 차량 위 아님 + 도로 위**


## 7. 이번에 제거한 테스트용 요소

기능과 직접 관계없는 테스트용 보조 파일은 삭제했습니다.

삭제한 파일:

- `abandoned_object/extend_video.py`
- `abandoned_object/path_config.py`

삭제한 테스트 자산:

- `abandoned_object/model/best.pt`
- `abandoned_object/video/KakaoTalk_20260421_121313178.mp4`

남겨 둔 것:

- `model/`, `video/` 폴더 자체
- `.gitkeep`

이유:

- 나중에 다시 테스트 파일을 넣기 쉽게 폴더 구조만 유지하기 위해서


## 8. 현재 남은 핵심 파일 설명

### `service/service.py`

이 파일은 현재 `abandoned_object` 기능의 본체입니다.

주요 메서드:

- `detect_abandoned_object`
  - 전체 처리 흐름 시작점
- `_validate_payload`
  - 입력 검증
- `_analyze_stationary_time`
  - 정지 시간 계산
- `_analyze_object_movement`
  - 이동량 계산
- `_analyze_spatial_context`
  - 도로/차량 중첩 판단
- `_decide_abandoned_state`
  - 최종 낙하물 여부 결정
- `_create_alert_message`
  - 사람이 읽을 알림 문구 생성
- `_emit_alert_log`
  - 콘솔 알림 출력
- `_save_detection_result`
  - 실제 DB 저장 대신 저장 계획 반환

### `view/router.py`

이 파일은 API 입구입니다.

현재 역할:

- `/detect` POST 요청 받기
- payload를 서비스로 넘기기
- 서비스 결과 반환하기


## 9. 현재 DB 계획

현재는 DB 연결을 안 했고, 계획만 남겨 둔 상태입니다.

구상 방향:

- 우선 저장하고 싶은 값
  - `eventTime`
  - `cameraId`
  - `objectType`
  - `alertMessage`
  - `snapshotImage`

- 향후 구조
  - 낙하물 판단 성공 시 DB에 이벤트 저장
  - 이미지도 같이 저장하거나 이미지 경로 저장
  - API가 붙으면 DB 정보는 API가 DB에서 조회해서 반환

즉 지금은:

- 판단 기능 = 완료
- 로그 알림 = 완료
- DB 저장 = 계획만 존재


## 10. 검증 상태

현재 코드에 대해 수행한 검증:

- `py -3 -m py_compile abandoned_object\\service\\service.py abandoned_object\\view\\router.py`
  - 통과

즉 현재 남아 있는 파일 기준으로는 **문법 오류 없이 동작 가능한 상태**입니다.


## 11. 다음 단계에서 하면 좋은 일

다음 단계 후보는 아래 정도입니다.

1. 실제 모델 추론 코드와 `abandoned_object` API 연결
2. `roadBounds`를 카메라별로 어떻게 줄지 결정
3. `currentFrameDetections`에 차량 bbox도 같이 넘기도록 상위 모듈 정리
4. DB 스키마 설계
5. 이미지 저장 방식 결정


## 12. 한 줄 요약

현재 `abandoned_object`는
**"box 탐지 결과를 받아서 시간/이동/도로/차량 규칙으로 낙하물 여부를 판단하고, 조건이 맞으면 로그 알림을 띄우는 기능"** 으로 정리된 상태입니다.

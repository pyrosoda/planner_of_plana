# 블루아카이브 화면 분석기

블루아카이브 스팀 클라이언트 화면을 자동 캡처하고,
Claude Vision API로 학생 정보와 재화 현황을 읽어내는 GUI 앱이야.

## 설치

```bash
pip install -r requirements.txt
```

## 실행

```bash
python main.py
```

## 사용법

1. Anthropic API 키를 입력해 (https://console.anthropic.com에서 발급)
2. 블루아카이브 스팀 클라이언트를 실행해
3. 읽고 싶은 화면으로 이동 (학생 목록, 재화 현황 등)
4. **"블루아카이브 화면 캡처 & 분석"** 버튼 클릭
5. Claude가 화면을 분석해서 대시보드에 표시해줄 거야

## 지원 화면

| 화면 | 읽는 데이터 |
|------|------------|
| 학생 목록 | 이름, 별 등급, 레벨, 호감도 |
| 로비 | 상단 재화 (파이로사이트, 크레딧, 활동력) |
| 상점/인벤토리 | 아이템 종류와 수량 |

## 파일 구조

```
ba_analyzer/
├── main.py          # 메인 앱
├── requirements.txt # 의존성
└── captures/        # 자동 저장되는 캡처 이미지
```

## 윈도우 타이틀 인식

다음 키워드가 포함된 윈도우를 자동으로 찾아:
- `Blue Archive`
- `블루 아카이브`
- `ブルーアーカイブ`

## 주의사항

- Windows 환경에서 동작 (pygetwindow 의존)
- Anthropic API 키 필요 (유료)
- 캡처 이미지는 `captures/` 폴더에 자동 저장됨

"""
item_names.py — 블루아카이브 아이템/장비 이름 DB (OCR 교정용)

학생 이름과 다른 점:
  - 중복 이름 허용 (같은 이름 다른 아이템)
  - 교정은 이름만 (코스튬/괄호 처리 없음)
  - index는 스캔 순서로 부여 (caller 측에서 관리)
"""

# ── 아이템 이름 목록 ───────────────────────────────────────
ITEM_NAMES = [
    # 강화석
    "일반 강화석", "고급 강화석", "특수 강화석",
    # 추천/모집 관련
    "추천 상자", "모집권", "모집 티켓",
    "일반 모집권", "고급 모집권", "픽업 모집권",
    "EX 선택 모집권", "선택 모집권",
    # 청휘석/재화
    "청휘석", "학원 교환권", "활동 보고서",
    # 상자류
    "선물 상자", "선물 선택 상자", "랜덤 상자",
    "오파츠 추천 상자", "오파츠 추천 상자2", "오파츠 추천 상자3",
    # 제조
    "제조 가속권", "제조 가속 티켓",
    "크래프트 챔버 부스터 티켓",
    # 경험치
    "학생 경험치 보고서", "일반 경험치 보고서",
    "고급 경험치 보고서", "특수 경험치 보고서",
    # 스킬
    "일반 스킬 북", "고급 스킬 북", "특수 스킬 북",
    "EX 스킬 노트", "스킬 노트",
    # 장비 강화
    "크레딧", "장비 강화 재료",
    # 기타 소모품
    "체력 포션", "AP 회복제",
    "작전 보고서", "전술 교재",
    "엘레프 기억 조각", "엘레프 기억 조각+",
    "모집 포인트",
    # 이벤트
    "이벤트 코인", "이벤트 교환권",
    "시험 계획서", "업무 보고서",
    # 기타
    "프레나파테스의 어른의 카드",
    "와일드카드 코인",
]

# ── 장비(설계도면) 이름 목록 ──────────────────────────────
EQUIPMENT_NAMES = [
    # 설계도면 (티어별로 같은 이름 존재)
    "설계도면",
    # 장비 종류별
    "안경", "목걸이", "반지", "귀걸이", "팔찌",
    "가방", "신발", "모자", "시계", "장갑",
    "헤어핀", "배지", "브로치",
    # 설계도면 + 장비 이름 조합
    "안경 설계도면", "목걸이 설계도면", "반지 설계도면",
    "귀걸이 설계도면", "팔찌 설계도면", "가방 설계도면",
    "신발 설계도면", "모자 설계도면", "시계 설계도면",
    "장갑 설계도면", "헤어핀 설계도면", "배지 설계도면",
    "브로치 설계도면",
    # 소재
    "강화 소재", "합성 소재", "특수 소재",
]


def _levenshtein(a: str, b: str) -> int:
    if len(a) < len(b):
        return _levenshtein(b, a)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for ca in a:
        curr = [prev[0] + 1]
        for j, cb in enumerate(b):
            curr.append(min(prev[j+1]+1, curr[j]+1, prev[j]+(ca!=cb)))
        prev = curr
    return prev[-1]


def correct_item_name(raw: str, is_equipment: bool = False) -> str:
    """
    OCR 결과를 아이템/장비 이름 DB와 비교해 교정.
    중복 이름 처리는 호출자(scanner)에서 index로 관리.

    반환: 교정된 이름 (str)
    """
    if not raw:
        return raw

    cleaned = raw.strip()
    db = EQUIPMENT_NAMES if is_equipment else ITEM_NAMES

    # 완전 일치
    if cleaned in db:
        return cleaned

    # 편집거리 교정
    best_name = cleaned
    best_dist = 999
    cleaned_len = len(cleaned)

    for name in db:
        if abs(len(name) - cleaned_len) > 3:
            continue
        d = _levenshtein(cleaned, name)
        if d < best_dist:
            best_dist = d
            best_name = name

    if best_dist <= 2:
        if best_name != cleaned:
            kind = "장비" if is_equipment else "아이템"
            print(f"[Names] {kind} 교정: '{cleaned}' → '{best_name}' (거리={best_dist})")
        return best_name

    print(f"[Names] 교정 실패: '{cleaned}' (최소거리={best_dist})")
    return cleaned

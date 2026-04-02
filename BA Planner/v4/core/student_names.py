"""
student_names.py — 블루아카이브 학생 이름 DB

설계 원칙:
  - 기본 이름과 코스튬 태그를 분리 관리
  - OCR 결과에서 이름/코스튬을 분리 파싱
  - 이름은 기본 이름 목록에서만 교정
  - 코스튬은 태그 목록에서만 교정
  - 특수 고유명(예: 시로코*테러)은 별도 예외 처리
  - 너무 애매한 경우에는 무리하게 교정하지 않고 원문 유지
"""

from __future__ import annotations
import re


# ── 기본 이름 목록 ─────────────────────────────────────────
_BASE_NAMES = [
    "호시노", "시로코", "세리카", "노노미", "아야네", "시로코*테러",
    "마코토", "이로하", "이부키", "사츠키", "치아키",
    "히나", "아코", "이오리", "치나츠",
    "아루", "무츠키", "카요코", "하루카",
    "하루나", "아카리", "이즈미", "준코",
    "후우카", "주리",
    "세나", "카스미", "메구", "키라라",
    "리오", "노아", "유우카", "코유키",
    "유즈", "모모이", "미도리", "아리스",
    "네루", "아스나", "카린", "아카네", "토키",
    "히마리", "치히로", "코타마", "하레", "마키",
    "우타하", "히비키", "코토리",
    "스미레", "레이",
    "에이미", "케이",
    "나기사", "미카", "세이아",
    "히후미", "하나코", "아즈사", "코하루",
    "스즈미", "레이사",
    "우이", "시미코",
    "아이리", "카즈사", "요시미", "나츠",
    "미네", "세리나", "하나에",
    "츠루기", "하스미", "이치카", "마시로",
    "사쿠라코", "히나타", "마리",
    "라브",
    "니야", "카호", "치세",
    "시즈코", "피나", "우미카",
    "츠바키", "미모리", "카에데",
    "미치루", "츠쿠요", "이즈나",
    "나구사", "렌게", "키쿄", "유카리",
    "와카모",
    "키사키", "미나",
    "사야",
    "슌", "코코나",
    "루미", "레이죠",
    "체리노", "토모에", "마리나",
    "노도카", "시구레",
    "메루", "모미지",
    "미노리",
    "야쿠모", "타카네",
    "칸나", "코노카",
    "키리노", "후부키",
    "미야코", "사키", "모에", "미유",
    "사오리", "미사키", "히요리", "아츠코",
    "스바루",
    "히카리", "노조미", "아오바",
    "에리", "츠무기", "카노에", "레나",
    "미요", "후유", "리츠",
    "하츠네 미쿠", "미사카 미코토", "쇼쿠호 미사키", "사텐 루이코",
]

# ── 코스튬/변형 태그 목록 ─────────────────────────────────
_COSTUME_TAGS = [
    "수영복", "무장", "아르바이트", "임전", "온천", "바니걸", "드레스",
    "새해", "캠핑", "응원", "교복", "아이돌", "밴드", "매지컬",
    "크리스마스", "파자마", "어린이", "치파오", "가이드", "사복",
]

# ── 특수 고유명 예외 처리 ─────────────────────────────────
# 코스튬 태그처럼 분리하면 안 되는 고유 표기들
_SPECIAL_FULL_NAMES = {
    "시로코*테러": ["시로코*테러", "시로코 테러", "시로코테러"],
}

# ── 외부 사용 목록 ────────────────────────────────────────
BASE_NAMES = list(dict.fromkeys(_BASE_NAMES))
COSTUME_TAGS = list(dict.fromkeys(_COSTUME_TAGS))

# 전체 표시용 (필요 시)
STUDENT_NAMES = BASE_NAMES + [f"{n}({t})" for n in BASE_NAMES for t in COSTUME_TAGS]


def _levenshtein(a: str, b: str) -> int:
    if len(a) < len(b):
        return _levenshtein(b, a)
    if not b:
        return len(a)

    prev = list(range(len(b) + 1))
    for ca in a:
        curr = [prev[0] + 1]
        for j, cb in enumerate(b):
            curr.append(min(
                prev[j + 1] + 1,        # deletion
                curr[j] + 1,            # insertion
                prev[j] + (ca != cb)    # substitution
            ))
        prev = curr
    return prev[-1]


def _normalize_text(s: str) -> str:
    if not s:
        return ""

    s = s.strip()
    s = s.replace("（", "(").replace("）", ")")
    s = s.replace("[", "(").replace("]", ")")
    s = s.replace("【", "(").replace("】", ")")
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def _normalize_special_names(raw: str) -> str:
    """
    시로코*테러 같은 특수명 정규화.
    OCR이 '*', 공백을 다르게 읽어도 동일 이름으로 통일.
    """
    raw = _normalize_text(raw)
    for canonical, variants in _SPECIAL_FULL_NAMES.items():
        if raw in variants:
            return canonical
    return raw


def parse_name(raw: str) -> tuple[str, str | None]:
    """
    OCR 결과에서 이름과 코스튬을 분리.

    예:
      "미카(수영복)"   -> ("미카", "수영복")
      "미카 (수영복)"  -> ("미카", "수영복")
      "시즈코 수영복" -> ("시즈코", "수영복")
      "시즈코수영복"  -> ("시즈코", "수영복")
      "시로코*테러"   -> ("시로코*테러", None)
      "미카"          -> ("미카", None)
    """
    raw = _normalize_text(raw)
    if not raw:
        return "", None

    # 1) 괄호 태그 우선
    m = re.search(r"\((.+?)\)", raw)
    if m:
        costume = m.group(1).strip()
        name = re.sub(r"\s*\(.+?\)", "", raw).strip()
        return name, costume

    # 2) 공백 분리형: "시즈코 수영복"
    for tag in sorted(COSTUME_TAGS, key=len, reverse=True):
        suffix = " " + tag
        if raw.endswith(suffix):
            name = raw[:-len(suffix)].strip()
            if name:
                return name, tag

    # 3) 붙어서 나온 경우: "시즈코수영복"
    for tag in sorted(COSTUME_TAGS, key=len, reverse=True):
        if raw.endswith(tag) and len(raw) > len(tag):
            name = raw[:-len(tag)].strip()
            if len(name) >= 2:
                return name, tag

    return raw, None


def _closest_name(name: str, candidates: list[str], max_dist: int = 2) -> tuple[str, int]:
    """
    가장 가까운 후보를 찾되, 너무 멀면 원문 유지.
    """
    if not name:
        return name, 999

    best = name
    best_dist = 999
    name_len = len(name)

    for candidate in candidates:
        if abs(len(candidate) - name_len) > 2:
            continue
        d = _levenshtein(name, candidate)
        if d < best_dist:
            best_dist = d
            best = candidate

    if best_dist <= max_dist:
        return best, best_dist
    return name, best_dist


def correct_name(raw: str) -> tuple[str, str | None]:
    """
    OCR 결과를 교정.
    반환: (교정된_이름, 교정된_코스튬 or None)

    흐름:
      1. 정규화
      2. 특수 고유명(시로코*테러 등) 즉시 확정
      3. parse_name()으로 이름/코스튬 분리
      4. 이름은 BASE_NAMES에서만 교정
      5. 코스튬은 COSTUME_TAGS에서만 교정
      6. 너무 애매하면 원문 유지
    """
    raw = _normalize_text(raw)
    raw = _normalize_special_names(raw)

    if not raw:
        return raw, None

    # 특수 고유명은 그대로 확정
    if raw in _SPECIAL_FULL_NAMES:
        return raw, None

    name, costume = parse_name(raw)
    if not name:
        return raw, None

    # ── 이름 교정 ────────────────────────────────────────
    if name in BASE_NAMES:
        fixed_name = name
        name_dist = 0
    else:
        fixed_name, name_dist = _closest_name(name, BASE_NAMES, max_dist=2)

        if fixed_name != name:
            print(f"[Names] 이름 교정: '{name}' -> '{fixed_name}' (거리={name_dist})")
        else:
            print(f"[Names] 이름 유지: '{name}' (최소거리={name_dist})")

    # ── 코스튬 교정 ──────────────────────────────────────
    fixed_costume = costume
    if costume:
        costume = costume.strip()

        if costume in COSTUME_TAGS:
            fixed_costume = costume
        else:
            fixed_costume, tag_dist = _closest_name(costume, COSTUME_TAGS, max_dist=2)

            if fixed_costume != costume:
                print(f"[Names] 코스튬 교정: '{costume}' -> '{fixed_costume}' (거리={tag_dist})")
            elif tag_dist <= 2:
                print(f"[Names] 코스튬 유지: '{costume}' (최소거리={tag_dist})")
            else:
                print(f"[Names] 코스튬 제거: '{costume}' (최소거리={tag_dist})")
                fixed_costume = None

    return fixed_name, fixed_costume


def format_name(name: str, costume: str | None) -> str:
    """
    최종 표시용 문자열 생성.
    """
    if costume:
        return f"{name}({costume})"
    return name
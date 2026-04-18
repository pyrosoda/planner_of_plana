from __future__ import annotations

from dataclasses import dataclass


_SCHOOL_ORDER = (
    "백귀야행",
    "붉은겨울",
    "트리니티",
    "게헨나",
    "아비도스",
    "밀레니엄",
    "아리우스",
    "산해경",
    "발키리",
    "하이랜더",
    "와일드헌트",
)

_SCHOOL_LABELS = {
    "Abydos": "아비도스",
    "Arius": "아리우스",
    "Gehenna": "게헨나",
    "Highlander": "하이랜더",
    "Hyakkiyako": "백귀야행",
    "Millennium": "밀레니엄",
    "RedWinter": "붉은겨울",
    "Shanhaijing": "산해경",
    "Trinity": "트리니티",
    "Valkyrie": "발키리",
    "Wildhunt": "와일드헌트",
}

_TIER_LABELS = {
    "0": "기초",
    "1": "일반",
    "2": "상급",
    "3": "최상급",
}

def _object_opart_variants(base: str, *, first_suffix: str = "조각") -> tuple[str, str, str, str]:
    return (
        f"{base} {first_suffix}",
        f"파손된 {base}",
        f"마모된 {base}",
        f"온전한 {base}",
    )


_OOPART_GROUPS = (
    _object_opart_variants("네브라 디스크"),
    _object_opart_variants("파에스트스 원반"),
    _object_opart_variants("볼프세크 강철"),
    _object_opart_variants("님루드 렌즈"),
    _object_opart_variants("만드라고라 농축액"),
    _object_opart_variants("로혼치 사본"),
    ("에테르 가루", "에테르 조각", "에테르 결정", "에테르 정수"),
    _object_opart_variants("안티키테라 장치"),
    _object_opart_variants("보이니치 사본"),
    _object_opart_variants("수정 하니와", first_suffix="파편"),
    _object_opart_variants("토템폴"),
    _object_opart_variants("고대 전지"),
    _object_opart_variants("황금 양모"),
    _object_opart_variants("머리가 자라는 인형"),
    _object_opart_variants("디스코 콜간테"),
    _object_opart_variants("아틀란티스 메달"),
    _object_opart_variants("로마 12면체"),
    _object_opart_variants("킴바야 유물"),
    _object_opart_variants("이스탄불 로켓"),
    _object_opart_variants("위니페소키 스톤"),
)

_OOPART_WB_NAMES = ("교양 체육 WB", "교양 사격 WB", "교양 위생 WB")


def _build_opart_aliases() -> dict[str, str]:
    aliases: dict[str, str] = {}
    short_forms = (
        ("로혼치", "로혼치 사본", "조각"),
        ("안티키테라", "안티키테라 장치", "조각"),
        ("보이니치", "보이니치 사본", "조각"),
        ("하니와", "수정 하니와", "파편"),
        ("전지", "고대 전지", "조각"),
        ("양털", "황금 양모", "조각"),
        ("인형", "머리가 자라는 인형", "조각"),
        ("콜간테", "디스코 콜간테", "조각"),
        ("로마", "로마 12면체", "조각"),
        ("킴바야", "킴바야 유물", "조각"),
        ("이스탄불", "이스탄불 로켓", "조각"),
    )
    for short_name, full_name, first_suffix in short_forms:
        short_variants = _object_opart_variants(short_name, first_suffix=first_suffix)
        full_variants = _object_opart_variants(full_name, first_suffix=first_suffix)
        aliases.update(dict(zip(short_variants, full_variants)))
    return aliases


_ALIASES = {
    "붉은겨올": "붉은겨울",
    "붉으겨올": "붉은겨울",
    "북은겨올": "붉은겨울",
    "밀레니업": "밀레니엄",
    "밀레니움": "밀레니엄",
    "아리으스": "아리우스",
    "아리므스": "아리우스",
    "게회나": "게헨나",
    "하이랜터": "하이랜더",
    "하이린더": "하이랜더",
    "와일드현트": "와일드헌트",
    "기초기술노트": "기초 기술 노트",
    "일반기술노트": "일반 기술 노트",
    "상급기술노트": "상급 기술 노트",
    "최상급기술노트": "최상급 기술 노트",
    "기초전술교육bd": "기초 전술 교육 bd",
    "일반전술교육bd": "일반 전술 교육 bd",
    "상급전술교육bd": "상급 전술 교육 bd",
    "최상급전술교육bd": "최상급 전술 교육 bd",
    "교약위생wb": "교양 위생 wb",
} | _build_opart_aliases()


def _tech_note_names() -> list[str]:
    ordered: list[str] = []
    for school in _SCHOOL_ORDER:
        ordered.extend(
            [
                f"기초 기술 노트 ({school})",
                f"일반 기술 노트 ({school})",
                f"상급 기술 노트 ({school})",
                f"최상급 기술 노트 ({school})",
            ]
        )
    ordered.append("비의서")
    return ordered


def _tactical_bd_names() -> list[str]:
    ordered: list[str] = []
    for school in _SCHOOL_ORDER:
        ordered.extend(
            [
                f"기초 전술 교육 BD ({school})",
                f"일반 전술 교육 BD ({school})",
                f"상급 전술 교육 BD ({school})",
                f"최상급 전술 교육 BD ({school})",
            ]
        )
    return ordered

def _ooparts_ordered_names() -> list[str]:
    ordered = [name for group in _OOPART_GROUPS for name in group]
    ordered.extend(_OOPART_WB_NAMES)
    return ordered

_COIN_NAMES = [
    "총력전 코인",
    "전술대회 코인",
    "상급 총력전 코인",
    "엘리그마",
    "종합전술시험 코인",
    "현상수배 코인",
    "대결전 코인",
    "상급 대결전 코인",
]

_REPORT_NAMES = [
    "초급 활동 보고서",
    "일반 활동 보고서",
    "상급 활동 보고서",
    "최상급 활동 보고서",
]


@dataclass(frozen=True, slots=True)
class InventoryScanProfile:
    profile_id: str
    source: str
    ordered_names: tuple[str, ...]
    terminal_names: frozenset[str]
    expected_item_ids: frozenset[str] = frozenset()
    terminal_item_ids: frozenset[str] = frozenset()


_PROFILES = {
    "tech_notes": InventoryScanProfile(
        profile_id="tech_notes",
        source="item",
        ordered_names=tuple(_tech_note_names()),
        terminal_names=frozenset({"비의서"}),
        expected_item_ids=frozenset(
            {
                f"Item_Icon_SkillBook_{template_school}_{tier}"
                for template_school in _SCHOOL_LABELS
                for tier in _TIER_LABELS
            }
            | {"Item_Icon_SkillBook_Ultimate_Piece"}
        ),
        terminal_item_ids=frozenset({"Item_Icon_SkillBook_Ultimate_Piece"}),
    ),
    "tactical_bd": InventoryScanProfile(
        profile_id="tactical_bd",
        source="item",
        ordered_names=tuple(_tactical_bd_names()),
        terminal_names=frozenset({"최상급 전술 교육 BD (와일드헌트)"}),
        expected_item_ids=frozenset(
            {
                f"Item_Icon_Material_ExSkill_{template_school}_{tier}"
                for template_school in _SCHOOL_LABELS
                for tier in _TIER_LABELS
            }
        ),
        terminal_item_ids=frozenset({"Item_Icon_Material_ExSkill_Wildhunt_3"}),
    ),
    "ooparts": InventoryScanProfile(
        profile_id="ooparts",
        source="item",
        ordered_names=tuple(_ooparts_ordered_names()),
        terminal_names=frozenset({"교양 위생 WB"}),
    ),
    "coins": InventoryScanProfile(
        profile_id="coins",
        source="item",
        ordered_names=tuple(_COIN_NAMES),
        terminal_names=frozenset({"상급 대결전 코인"}),
    ),
    "activity_reports": InventoryScanProfile(
        profile_id="activity_reports",
        source="item",
        ordered_names=tuple(_REPORT_NAMES),
        terminal_names=frozenset({"최상급 활동 보고서"}),
    ),
}

_PROFILE_LABELS = {
    "all": "전체",
    "tech_notes": "기술 노트",
    "tactical_bd": "전술 교육 BD",
    "ooparts": "오파츠",
    "coins": "코인",
    "activity_reports": "활동 보고서",
}


def _compact(text: str | None) -> str:
    if not text:
        return ""
    out = str(text).strip().lower()
    out = out.replace("(", "").replace(")", "")
    out = out.replace("[", "").replace("]", "")
    out = out.replace(" ", "")
    out = out.replace("bd", "bd")
    out = out.replace("wb", "wb")
    for wrong, right in _ALIASES.items():
        out = out.replace(wrong.lower().replace(" ", ""), right.lower().replace(" ", ""))
    return out


def _levenshtein(a: str, b: str) -> int:
    if len(a) < len(b):
        return _levenshtein(b, a)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for ca in a:
        curr = [prev[0] + 1]
        for j, cb in enumerate(b):
            curr.append(min(prev[j + 1] + 1, curr[j] + 1, prev[j] + (ca != cb)))
        prev = curr
    return prev[-1]


def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        return 0.92
    dist = _levenshtein(a, b)
    return max(0.0, 1.0 - (dist / max(len(a), len(b), 1)))


def inventory_item_display_name(item_id: str | None) -> str | None:
    if not item_id:
        return None

    if item_id.startswith("Item_Icon_SkillBook_"):
        suffix = item_id.removeprefix("Item_Icon_SkillBook_")
        if suffix == "Ultimate_Piece":
            return "비의서"
        if suffix == "Ultimate":
            return "최상급 기술 노트"
        if suffix.startswith("Selection_"):
            tier = _TIER_LABELS.get(suffix.rsplit("_", 1)[-1])
            return f"{tier} 기술 노트 선택권" if tier else None
        if suffix.startswith("Random_"):
            tier = _TIER_LABELS.get(suffix.rsplit("_", 1)[-1])
            return f"{tier} 기술 노트 랜덤 상자" if tier else None
        school, _, tier_key = suffix.rpartition("_")
        school_label = _SCHOOL_LABELS.get(school)
        tier_label = _TIER_LABELS.get(tier_key)
        if school_label and tier_label:
            return f"{tier_label} 기술 노트 ({school_label})"

    if item_id.startswith("Item_Icon_Material_ExSkill_"):
        suffix = item_id.removeprefix("Item_Icon_Material_ExSkill_")
        school, _, tier_key = suffix.rpartition("_")
        school_label = _SCHOOL_LABELS.get(school)
        tier_label = _TIER_LABELS.get(tier_key)
        if school_label and tier_label:
            return f"{tier_label} 전술 교육 BD ({school_label})"

    return None


def inventory_profile_ordered_item_ids(profile: InventoryScanProfile) -> tuple[str | None, ...]:
    if profile.profile_id == "tech_notes":
        ordered: list[str | None] = []
        for school_label in _SCHOOL_ORDER:
            school_key = next(
                (key for key, label in _SCHOOL_LABELS.items() if label == school_label),
                None,
            )
            if school_key is None:
                ordered.extend([None, None, None, None])
                continue
            for tier in ("0", "1", "2", "3"):
                ordered.append(f"Item_Icon_SkillBook_{school_key}_{tier}")
        ordered.append("Item_Icon_SkillBook_Ultimate_Piece")
        return tuple(ordered)

    if profile.profile_id == "tactical_bd":
        ordered = []
        for school_label in _SCHOOL_ORDER:
            school_key = next(
                (key for key, label in _SCHOOL_LABELS.items() if label == school_label),
                None,
            )
            if school_key is None:
                ordered.extend([None, None, None, None])
                continue
            for tier in ("0", "1", "2", "3"):
                ordered.append(f"Item_Icon_Material_ExSkill_{school_key}_{tier}")
        return tuple(ordered)

    return tuple(None for _ in profile.ordered_names)


def get_inventory_profile(profile_id: str | None) -> InventoryScanProfile | None:
    if not profile_id:
        return None
    return _PROFILES.get(profile_id)


def inventory_profile_label(profile_id: str | None) -> str:
    if not profile_id:
        return _PROFILE_LABELS["all"]
    return _PROFILE_LABELS.get(profile_id, profile_id)


def infer_inventory_scan_profile(
    source: str,
    item_ids: list[str],
    raw_names: list[str] | None = None,
) -> InventoryScanProfile | None:
    if source != "item":
        return None

    if item_ids:
        skill_book_hits = [item_id for item_id in item_ids if item_id.startswith("Item_Icon_SkillBook_")]
        if len(skill_book_hits) >= 4 and len(skill_book_hits) >= max(4, int(len(item_ids) * 0.7)):
            return _PROFILES["tech_notes"]

        skill_bd_hits = [item_id for item_id in item_ids if item_id.startswith("Item_Icon_Material_ExSkill_")]
        if len(skill_bd_hits) >= 4 and len(skill_bd_hits) >= max(4, int(len(item_ids) * 0.7)):
            return _PROFILES["tactical_bd"]

    sample = [_compact(name) for name in (raw_names or []) if name]
    if not sample:
        return None

    best_profile: InventoryScanProfile | None = None
    best_score = 0.0
    for profile in _PROFILES.values():
        order = [_compact(name) for name in profile.ordered_names]
        score = 0.0
        last_idx = -1
        for token in sample[: min(6, len(sample))]:
            best_local = 0.0
            best_pos = -1
            for pos, expected in enumerate(order):
                sim = _similarity(token, expected)
                if sim > best_local:
                    best_local = sim
                    best_pos = pos
            if best_local >= 0.72:
                score += best_local
                if best_pos >= last_idx:
                    score += 0.05
                last_idx = max(last_idx, best_pos)
        if score > best_score:
            best_score = score
            best_profile = profile

    return best_profile if best_score >= 1.5 else None


def resolve_inventory_profile_name(
    profile: InventoryScanProfile,
    raw_name: str | None,
    seen_names: set[str],
) -> str | None:
    if not raw_name:
        return None

    compact_raw = _compact(raw_name)
    if not compact_raw:
        return None

    ordered = list(profile.ordered_names)
    index_by_name = {name: idx for idx, name in enumerate(ordered)}
    anchor = 0
    seen_indices = [index_by_name[name] for name in seen_names if name in index_by_name]
    if seen_indices:
        anchor = max(seen_indices) + 1

    best_name: str | None = None
    best_score = 0.0
    for idx, candidate in enumerate(ordered):
        if candidate in seen_names:
            continue
        score = _similarity(compact_raw, _compact(candidate))
        if idx >= anchor:
            score += max(0.0, 0.08 - (idx - anchor) * 0.01)
        else:
            score -= 0.10
        if score > best_score:
            best_score = score
            best_name = candidate

    return best_name if best_score >= 0.72 else None


def next_inventory_profile_name(
    profile: InventoryScanProfile,
    seen_names: set[str],
) -> str | None:
    for candidate in profile.ordered_names:
        if candidate not in seen_names:
            return candidate
    return None


def find_inventory_profile_duplicate(
    profile: InventoryScanProfile,
    raw_name: str | None,
    seen_names: set[str],
) -> str | None:
    if not raw_name or not seen_names:
        return None

    compact_raw = _compact(raw_name)
    if not compact_raw:
        return None

    best_name: str | None = None
    best_score = 0.0
    for candidate in profile.ordered_names:
        if candidate not in seen_names:
            continue
        score = _similarity(compact_raw, _compact(candidate))
        if score > best_score:
            best_score = score
            best_name = candidate

    return best_name if best_score >= 0.78 else None


def is_inventory_profile_complete(
    profile: InventoryScanProfile,
    found_item_ids: set[str],
    found_names: set[str],
) -> bool:
    if profile.terminal_item_ids and profile.terminal_item_ids & found_item_ids:
        return True
    if profile.terminal_names and profile.terminal_names & found_names:
        return True
    if profile.expected_item_ids:
        return profile.expected_item_ids.issubset(found_item_ids)
    return set(profile.ordered_names).issubset(found_names)

"""
Student scanning pipeline for BA Analyzer v6.

This module coordinates student navigation, recognition, and data collection.
Broken legacy comments and UI strings were cleaned up for readability.
"""

import ctypes
import os
import sys
import time
import json
import hashlib
import numpy as np
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional
from PIL import Image


from core.logger import get_logger, log_section, LOG_SCANNER
from core.log_context import (
    ScanCtx, log_exc, EXC_WARNING, EXC_ERROR, EXC_FATAL,
    dump_roi,
)

# Module logger
_log = get_logger(LOG_SCANNER)


from core.capture import (
    capture_window_background,
    crop_region,
    get_window_rect,
    find_target_hwnd,
)
from core.input import (
    click_center,
    safe_click,
    drag_scroll,
    press_esc,
    click_point,
    send_escape,
    ratio_to_client,
)


from core.matcher import (
    WeaponState,
    CheckFlag,
    EquipSlotFlag,
    match_score_resized,
    match_score_resized_raw,
    match_score_textonly,
    match_student_texture,
    is_lobby,
    is_student_menu,
    is_student_additional_menu_on,
    is_level_tab_on,
    is_basic_info_tab_on,
    is_star_tab_on,
    detect_weapon_state,
    read_skill_check,
    read_equip_check,
    read_equip_check_inside,
    read_equip_slot_flag,
    read_stat_value,
    read_student_star_v5,
    read_weapon_star_v5,
    read_skill,
    read_equip_tier,
    read_equip_level,
    read_weapon_level,
    read_student_level_v5,
)

import core.ocr as ocr
import core.student_meta as student_meta
from core.config import BASE_DIR, TEMPLATE_DIR
from core.inventory_profiles import (
    find_inventory_profile_duplicate,
    get_inventory_profile,
    infer_inventory_scan_profile,
    inventory_item_display_name,
    inventory_profile_ordered_item_ids,
    is_inventory_profile_complete,
    is_inventory_profile_terminal_seen,
    next_inventory_profile_name,
    normalize_inventory_profile_ids,
    resolve_inventory_profile_name,
)
from core.inventory_count_matcher import (
    read_equipment_count_from_detail,
    read_item_count_from_detail,
)



# Constants


MAX_SCROLLS          = 60
SAME_THRESH          = 0.97
STUDENT_MENU_WAIT    = 3.0
MAX_CONSECUTIVE_DUP  = 3
MAX_STUDENT_LEVEL    = 90
STAT_UNLOCK_LEVEL    = 90
STAT_UNLOCK_STAR     = 5
DETAIL_READY_SCORE   = 0.80
DETAIL_READY_WAIT    = 6.0
DETAIL_READY_STABLE_POLLS = 2
LOBBY_EXIT_WAIT      = 5.5
MENU_CLICK_SETTLE_WAIT = 1.2
STUDENT_MENU_READY_STABLE_POLLS = 2
STUDENT_MENU_READY_SETTLE_WAIT = 0.45
FIRST_STUDENT_PRECLICK_WAIT = 0.45
DETAIL_CLICK_SETTLE_WAIT = 1.0
PANEL_CLOSE_SETTLE_WAIT = 0.55
BASIC_TAB_SETTLE_WAIT = 0.45
LEVEL_CAPTURE_RETRY_WAIT = 0.40
WEAPON_CAPTURE_RETRY_WAIT = 0.40
MENU_CLOSE_DETAIL_WAIT = 0.35
EQUIP_CHECK_RETRY_WAIT = 0.25
UI_FLAG_POLL = 0.12
ADDITIONAL_PANEL_READY_WAIT = 1.8
TAB_ON_READY_WAIT = 1.5
UI_FLAG_MATCH_DELAY = 0.10
STAT_PANEL_MATCH_DELAY = 0.22
CAPTURED_CLICK_POINTS_FILE = BASE_DIR / "debug" / "captured_click_points.json"
REGION_CAPTURE_DIR = BASE_DIR / "debug" / "region_captures"
INVENTORY_SORT_RULE_MATCH_THRESHOLD = 0.78
ITEM_SORT_RULE_MATCH_THRESHOLD = 0.68
INVENTORY_SORT_RULE_MAX_ATTEMPTS = 3
INVENTORY_FILTER_MENU_SETTLE_WAIT = 0.65
INVENTORY_FILTER_TAB_SETTLE_WAIT = 0.45
INVENTORY_SORT_RULE_CHECK_WAIT = 0.75
INVENTORY_SORT_RULE_RETRY_WAIT = 0.45
INVENTORY_FILTER_CONFIRM_WAIT = 0.65
INVENTORY_PROFILE_MAX_UNIQUE_ITEMS = {
    "activity_reports": 4,
    "tech_notes": 45,
    "tactical_bd": 44,
    "ooparts": 83,
    "equipment": 110,
}
INVENTORY_PROFILE_MAX_DETAIL_CANDIDATES = {
    "activity_reports": 4,
}
PROFILE_DIRECT_MATCH_THRESHOLD = 0.82
STRICT_DETAIL_FAMILY_THRESHOLDS: dict[str, tuple[float, float, float]] = {
    "Equipment_Icon_WeaponExpGrowth": (0.92, 0.025, 0.03),
}


def _inventory_detail_strict_family(item_id: str | None) -> str | None:
    if not item_id:
        return None
    for prefix in STRICT_DETAIL_FAMILY_THRESHOLDS:
        if item_id.startswith(prefix):
            return prefix
    return None


def _inventory_detail_strict_family_position(
    item_id: str | None,
) -> tuple[str, int, int] | None:
    family_key = _inventory_detail_strict_family(item_id)
    if family_key != "Equipment_Icon_WeaponExpGrowth" or not item_id:
        return None
    suffix = item_id.removeprefix("Equipment_Icon_WeaponExpGrowth")
    parts = suffix.split("_")
    if len(parts) != 2:
        return None
    group_token = parts[0]
    try:
        tier_token = int(parts[1])
    except ValueError:
        return None
    group_rank = {"Z": 0, "C": 1, "B": 2, "A": 3}.get(group_token)
    tier_rank = {3: 0, 2: 1, 1: 2, 0: 3}.get(tier_token)
    if group_rank is None or tier_rank is None:
        return None
    return family_key, group_rank, tier_rank
PROFILE_SEARCH_MATCH_THRESHOLD = 0.88
VK_SPACE = 0x20
_USER32 = ctypes.windll.user32 if sys.platform == "win32" else None

# Retry policy
RETRY_IDENTIFY   = 2      # max student identify retries
RETRY_CAPTURE    = 2      # capture retry count
DELAY_AFTER_CLICK = 0.22  # generic click settle
DELAY_TAB_SWITCH  = 0.55  # tab switch settle
DELAY_NEXT        = 1.20  # next student settle
DELAY_ESC         = 0.35  # escape settle


@dataclass(frozen=True)
class InventoryDragConfig:
    start_screen_x: int
    start_screen_y: int
    delta_px: int
    duration: float


ITEM_INVENTORY_DRAG = InventoryDragConfig(
    start_screen_x=1900,
    start_screen_y=1135,
    delta_px=-900,
    duration=0.50,
)

EQUIPMENT_INVENTORY_DRAG = InventoryDragConfig(
    start_screen_x=1900,
    start_screen_y=1315,
    delta_px=-1108,
    duration=0.50,
)




@dataclass
class ItemEntry:
    name:     Optional[str]
    quantity: Optional[str]
    item_id:  Optional[str] = None
    source:   str = "item"
    index:    int = 0
    scan_meta: dict = field(default_factory=dict)
    detail_crop: Optional[Image.Image] = field(default=None, repr=False, compare=False)
    detail_name_crop: Optional[Image.Image] = field(default=None, repr=False, compare=False)

    def key(self) -> str:
        stable = (self.item_id or self.name or "").strip().lower()
        return f"{self.source}:{stable}"






class FieldStatus:
    """Status marker for each tracked student field."""









    OK              = "ok"
    INFERRED        = "inferred"
    UNCERTAIN       = "uncertain"
    FAILED          = "failed"
    SKIPPED         = "skipped"
    REGION_MISSING  = "region_missing"


class FieldSource:
    """Source marker for each tracked student field."""








    TEMPLATE = "template"
    OCR      = "ocr"
    INFERRED = "inferred"
    CACHED   = "cached"
    DEFAULT  = "default"


@dataclass
class FieldMeta:
    """Metadata captured for each scanned field."""









    status: str            = FieldStatus.OK
    source: str            = FieldSource.TEMPLATE
    score:  Optional[float] = None
    note:   str            = ""

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "source": self.source,
            "score":  round(self.score, 3) if self.score is not None else None,
            "note":   self.note,
        }

    @classmethod
    def ok(cls, source: str, score: Optional[float] = None) -> "FieldMeta":
        return cls(status=FieldStatus.OK, source=source, score=score)

    @classmethod
    def inferred(cls, note: str = "") -> "FieldMeta":
        return cls(status=FieldStatus.INFERRED,
                   source=FieldSource.INFERRED, note=note)

    @classmethod
    def uncertain(cls, source: str, score: Optional[float] = None,
                  note: str = "") -> "FieldMeta":
        return cls(status=FieldStatus.UNCERTAIN,
                   source=source, score=score, note=note)

    @classmethod
    def failed(cls, source: str, note: str = "") -> "FieldMeta":
        return cls(status=FieldStatus.FAILED, source=source, note=note)

    @classmethod
    def skipped(cls, note: str = "") -> "FieldMeta":
        return cls(status=FieldStatus.SKIPPED,
                   source=FieldSource.DEFAULT, note=note)

    @classmethod
    def region_missing(cls, note: str = "") -> "FieldMeta":
        return cls(status=FieldStatus.REGION_MISSING,
                   source=FieldSource.DEFAULT, note=note)




class ScanState:
    """Lifecycle state for a student entry while scanning."""






    TEMP      = "temp"
    PARTIAL   = "partial"
    COMMITTED = "committed"
    SKIPPED   = "skipped"
    FAILED    = "failed"


@dataclass
class StudentEntry:
    student_id:   Optional[str] = None
    display_name: Optional[str] = None
    level:        Optional[int] = None
    student_star: Optional[int] = None
    # Weapon
    weapon_state: Optional[WeaponState] = None
    weapon_star:  Optional[int]         = None
    weapon_level: Optional[int]         = None
    # Skills
    ex_skill: Optional[int] = None
    skill1:   Optional[int] = None
    skill2:   Optional[int] = None
    skill3:   Optional[int] = None
    # Equipment tiers
    equip1:   Optional[str] = None
    equip2:   Optional[str] = None
    equip3:   Optional[str] = None
    equip4:   Optional[str] = None
    # Equipment levels
    equip1_level: Optional[int] = None
    equip2_level: Optional[int] = None
    equip3_level: Optional[int] = None

    stat_hp:   Optional[int] = None
    stat_atk:  Optional[int] = None
    stat_heal: Optional[int] = None
    # Scan bookkeeping
    skipped:    bool = False
    scan_state: str  = ScanState.TEMP



    #   level / student_star / weapon_state / weapon_star / weapon_level
    #   ex_skill / skill1~3 / equip1~4 / equip1~3_level
    #   stat_hp / stat_atk / stat_heal
    _meta: dict = field(default_factory=dict)

    def label(self) -> str:
        return self.display_name or self.student_id or "?"

    def is_committed(self) -> bool:
        return self.scan_state == ScanState.COMMITTED

    def is_partial(self) -> bool:
        return self.scan_state == ScanState.PARTIAL

    def set_meta(self, field_name: str, meta: FieldMeta) -> None:
        """Store metadata for a specific field."""
        self._meta[field_name] = meta

    def get_meta(self, field_name: str) -> Optional[FieldMeta]:
        """Return field metadata or None if it does not exist."""
        return self._meta.get(field_name)

    def meta_summary(self) -> dict[str, dict]:
        """Return every field metadata entry as a serializable dict."""
        return {k: v.to_dict() for k, v in self._meta.items()}

    def uncertain_fields(self) -> list[str]:
        """List fields currently marked as uncertain."""
        return [k for k, v in self._meta.items()
                if v.status == FieldStatus.UNCERTAIN]

    def failed_fields(self) -> list[str]:
        """List fields currently marked as failed."""
        return [k for k, v in self._meta.items()
                if v.status == FieldStatus.FAILED]

    def missing_fields(self) -> list[str]:
        """List required fields that are still missing."""
        required = [
            "level", "student_star", "weapon_state",
            "ex_skill", "skill1", "skill2", "skill3",
            "equip1", "equip2", "equip3",
            "equip1_level", "equip2_level", "equip3_level",
        ]
        return [f for f in required if getattr(self, f) is None]

    def confidence(self) -> float:
        """Return the fraction of required fields that are filled."""
        required_all = [
            "level", "student_star", "weapon_state",
            "ex_skill", "skill1", "skill2", "skill3",
            "equip1", "equip2", "equip3",
            "equip1_level", "equip2_level", "equip3_level",
        ]
        filled = sum(1 for f in required_all if getattr(self, f) is not None)
        return round(filled / len(required_all), 3)

    def to_dict(self) -> dict:
        """Serialize the student entry and tracked metadata to a dict."""

























        ws = self.weapon_state
        d: dict = {
            "student_id":   self.student_id,
            "display_name": self.display_name,
            "level":        self.level,
            "student_star": self.student_star,
            "weapon_state": ws.value if ws else None,
            "weapon_star":  self.weapon_star,
            "weapon_level": self.weapon_level,
            "ex_skill":     self.ex_skill,
            "skill1":       self.skill1,
            "skill2":       self.skill2,
            "skill3":       self.skill3,
            "equip1":       self.equip1,
            "equip2":       self.equip2,
            "equip3":       self.equip3,
            "equip4":       self.equip4,
            "equip1_level": self.equip1_level,
            "equip2_level": self.equip2_level,
            "equip3_level": self.equip3_level,
            "stat_hp":      self.stat_hp,
            "stat_atk":     self.stat_atk,
            "stat_heal":    self.stat_heal,
            "skipped":      self.skipped,
            "scan_state":   self.scan_state,
            "confidence":   self.confidence(),
        }

        # Expand tracked field metadata for downstream consumers.
        _TRACKED = [
            "level", "student_star",
            "weapon_state", "weapon_star", "weapon_level",
            "ex_skill", "skill1", "skill2", "skill3",
            "equip1", "equip2", "equip3", "equip4",
            "equip1_level", "equip2_level", "equip3_level",
            "stat_hp", "stat_atk", "stat_heal",
        ]
        for fname in _TRACKED:
            meta = self._meta.get(fname)
            if meta:
                d[f"{fname}_status"] = meta.status
                d[f"{fname}_source"] = meta.source
                if meta.score is not None:
                    d[f"{fname}_score"] = round(meta.score, 3)
                if meta.note:
                    d[f"{fname}_note"] = meta.note
            else:

                val = getattr(self, fname, None)
                d[f"{fname}_status"] = (
                    FieldStatus.OK if val is not None else FieldStatus.FAILED
                )

        # Keep the raw metadata backup for later restore/debugging.
        if self._meta:
            d["_field_meta"] = self.meta_summary()

        return d

    @classmethod
    def from_dict(cls, d: dict) -> "StudentEntry":
        """Restore a StudentEntry from serialized data."""



        ws_raw = d.get("weapon_state")
        try:
            ws = WeaponState(ws_raw) if ws_raw else None
        except ValueError:
            ws = None

        entry = cls(
            student_id=d.get("student_id"),
            display_name=d.get("display_name"),
            level=d.get("level"),
            student_star=d.get("student_star"),
            weapon_state=ws,
            weapon_star=d.get("weapon_star"),
            weapon_level=d.get("weapon_level"),
            ex_skill=d.get("ex_skill"),
            skill1=d.get("skill1"),
            skill2=d.get("skill2"),
            skill3=d.get("skill3"),
            equip1=d.get("equip1"),
            equip2=d.get("equip2"),
            equip3=d.get("equip3"),
            equip4=d.get("equip4"),
            equip1_level=d.get("equip1_level"),
            equip2_level=d.get("equip2_level"),
            equip3_level=d.get("equip3_level"),
            stat_hp=d.get("stat_hp"),
            stat_atk=d.get("stat_atk"),
            stat_heal=d.get("stat_heal"),
            skipped=d.get("skipped", False),
            scan_state=d.get("scan_state", ScanState.COMMITTED),
        )

        # Restore per-field metadata when present.
        raw_meta = d.get("_field_meta", {})
        for fname, md in raw_meta.items():
            entry.set_meta(fname, FieldMeta(
                status=md.get("status", FieldStatus.OK),
                source=md.get("source", FieldSource.TEMPLATE),
                score=md.get("score"),
                note=md.get("note", ""),
            ))

        return entry


@dataclass
class EntryCommitResult:
    """Result of validating one student entry before commit."""










    entry:      StudentEntry
    committed:  bool
    missing:    list[str]
    confidence: float
    reason:     str = ""


@dataclass
class ScanResult:
    items:     list[ItemEntry]    = field(default_factory=list)
    equipment: list[ItemEntry]    = field(default_factory=list)
    students:  list[StudentEntry] = field(default_factory=list)
    resources: dict               = field(default_factory=dict)
    errors:    list[str]          = field(default_factory=list)


@dataclass
class InventorySlotSnapshot:
    slot_index: int
    icon_hash: str


@dataclass
class InventoryPageSnapshot:
    page_index: int
    grid_hash: str
    last_row_hashes: list[str]
    slots: list[InventorySlotSnapshot]


@dataclass
class InventoryVerification:
    name: Optional[str]
    count: str
    item_id: Optional[str] = None
    match_score: float = 0.0
    detail_crop: Optional[Image.Image] = None
    detail_name_crop: Optional[Image.Image] = None


@dataclass
class InventoryDetailCandidate:
    sequence: int
    slot_index: int
    count: str
    detail_crop: Image.Image
    detail_name_crop: Optional[Image.Image] = None
    detected_item_id: Optional[str] = None
    detected_score: float = 0.0



# Utility helpers


def _space_key_down() -> bool:
    if _USER32 is None:
        return False
    try:
        return bool(_USER32.GetAsyncKeyState(VK_SPACE) & 0x8000)
    except Exception:
        return False


def _img_hash(img: Image.Image) -> str:
    small = img.convert("L").resize((16, 16))
    return hashlib.md5(small.tobytes()).hexdigest()


def _images_similar(a: Image.Image, b: Image.Image, thresh: float = SAME_THRESH) -> bool:
    try:
        a2 = np.array(a.convert("L").resize((64, 64))).flatten().astype(float)
        b2 = np.array(b.convert("L").resize((64, 64))).flatten().astype(float)
        return float(np.corrcoef(a2, b2)[0, 1]) >= thresh
    except Exception:
        return False


def _grid_region(slots: list[dict]) -> dict:
    return {
        "x1": min(s["x1"] for s in slots),
        "y1": min(s["y1"] for s in slots),
        "x2": max(s["x2"] for s in slots),
        "y2": max(s["y2"] for s in slots),
    }


def _expand_region(
    region: dict,
    *,
    left: float = 0.0,
    top: float = 0.0,
    right: float = 0.0,
    bottom: float = 0.0,
) -> dict:
    return {
        "x1": max(0.0, region["x1"] - left),
        "y1": max(0.0, region["y1"] - top),
        "x2": min(1.0, region["x2"] + right),
        "y2": min(1.0, region["y2"] + bottom),
    }


def _slot_icon_region(slot: dict) -> dict:
    width = slot["x2"] - slot["x1"]
    height = slot["y2"] - slot["y1"]
    return {
        "x1": slot["x1"] + width * 0.10,
        "y1": slot["y1"] + height * 0.07,
        "x2": slot["x2"] - width * 0.10,
        "y2": slot["y2"] - height * 0.24,
    }


def _count_row_overlap(
    before_hashes: list[str],
    after_hashes: list[str],
    grid_cols: int,
) -> int:
    if grid_cols <= 0:
        return 0
    before_rows = [
        tuple(before_hashes[i:i + grid_cols])
        for i in range(0, len(before_hashes), grid_cols)
        if len(before_hashes[i:i + grid_cols]) == grid_cols
    ]
    after_rows = [
        tuple(after_hashes[i:i + grid_cols])
        for i in range(0, len(after_hashes), grid_cols)
        if len(after_hashes[i:i + grid_cols]) == grid_cols
    ]
    max_rows = min(len(before_rows), len(after_rows))
    for overlap in range(max_rows, 0, -1):
        if before_rows[-overlap:] == after_rows[:overlap]:
            return overlap
    return 0


_INVENTORY_TEMPLATE_DIRS: dict[str, tuple[str, ...]] = {
    "item": ("skill_book", "ooparts", "skill_db"),
    "equipment": ("equipment",),
}
_INVENTORY_TEMPLATE_CATALOG: dict[str, list[tuple[str, str]]] = {}
_INVENTORY_DETAIL_TEMPLATE_CATALOG: dict[str, list[tuple[str, str]]] = {}
_INVENTORY_DETAIL_TEMPLATE_REGION: dict[str, dict] = {}
_INVENTORY_DETAIL_NAME_TEMPLATE_CATALOG: dict[str, list[tuple[str, str]]] = {}
_INVENTORY_DETAIL_NAME_TEMPLATE_REGION: dict[str, dict] = {}
_REGION_CAPTURE_PAYLOADS: dict[str, dict] = {}
_REGION_CAPTURE_REGIONS: dict[str, dict] = {}
_REGION_CAPTURE_REFERENCE_PATHS: dict[str, str | None] = {}


def _inventory_template_catalog(source: str) -> list[tuple[str, str]]:
    cached = _INVENTORY_TEMPLATE_CATALOG.get(source)
    if cached is not None:
        return cached

    dirs = _INVENTORY_TEMPLATE_DIRS.get(source, ())
    catalog: list[tuple[str, str]] = []
    for dir_name in dirs:
        base = TEMPLATE_DIR / "icons" / dir_name
        if not base.exists():
            continue
        for png in sorted(base.rglob("*.png")):
            catalog.append((png.stem, str(png)))

    _INVENTORY_TEMPLATE_CATALOG[source] = catalog
    return catalog


def _inventory_detail_template_catalog(profile_id: str | None) -> list[tuple[str, str]]:
    if not profile_id:
        return []
    cached = _INVENTORY_DETAIL_TEMPLATE_CATALOG.get(profile_id)
    if cached is not None:
        return cached

    base = TEMPLATE_DIR / "inventory_detail" / profile_id
    catalog: list[tuple[str, str]] = []
    if base.exists():
        for png in sorted(base.glob("*.png")):
            catalog.append((png.stem, str(png)))

    _INVENTORY_DETAIL_TEMPLATE_CATALOG[profile_id] = catalog
    return catalog


def _inventory_detail_template_region(profile_id: str | None) -> dict | None:
    if not profile_id:
        return None
    cached = _INVENTORY_DETAIL_TEMPLATE_REGION.get(profile_id)
    if cached is not None:
        return cached

    base = TEMPLATE_DIR / "inventory_detail" / profile_id
    if not base.exists():
        return None

    for json_path in sorted(base.glob("*.json")):
        try:
            payload = json.loads(json_path.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        points = payload.get("points_ratio") or []
        if len(points) < 4:
            continue
        xs = [float(point.get("x", 0.0)) for point in points]
        ys = [float(point.get("y", 0.0)) for point in points]
        region = {
            "x1": max(0.0, min(xs)),
            "y1": max(0.0, min(ys)),
            "x2": min(1.0, max(xs)),
            "y2": min(1.0, max(ys)),
        }
        _INVENTORY_DETAIL_TEMPLATE_REGION[profile_id] = region
        return region

    return None


def _inventory_detail_name_template_catalog(profile_id: str | None) -> list[tuple[str, str]]:
    if not profile_id:
        return []
    cached = _INVENTORY_DETAIL_NAME_TEMPLATE_CATALOG.get(profile_id)
    if cached is not None:
        return cached

    base = TEMPLATE_DIR / "inventory_detail_names" / profile_id
    catalog: list[tuple[str, str]] = []
    if base.exists():
        for png in sorted(base.glob("*.png")):
            catalog.append((png.stem, str(png)))

    _INVENTORY_DETAIL_NAME_TEMPLATE_CATALOG[profile_id] = catalog
    return catalog


def _region_from_payload(payload: dict) -> dict | None:
    points = payload.get("points_ratio") or []
    if len(points) < 4:
        return None
    try:
        xs = [float(point.get("x", 0.0)) for point in points]
        ys = [float(point.get("y", 0.0)) for point in points]
    except Exception:
        return None
    return {
        "x1": max(0.0, min(xs)),
        "y1": max(0.0, min(ys)),
        "x2": min(1.0, max(xs)),
        "y2": min(1.0, max(ys)),
    }


def _inventory_detail_name_template_region(source: str) -> dict | None:
    key = "equipment" if source == "equipment" else "item"
    cached = _INVENTORY_DETAIL_NAME_TEMPLATE_REGION.get(key)
    if cached is not None:
        return cached

    stems = (
        ("equip_name_image_region", "equip_name_image_regino")
        if key == "equipment"
        else ("item_name_image_region", "item_name_image_regino")
    )
    search_dirs = (
        TEMPLATE_DIR / "inventory_detail_names",
        BASE_DIR / "debug" / "region_captures",
    )
    for base in search_dirs:
        for stem in stems:
            json_path = base / f"{stem}.region.json"
            if not json_path.exists():
                continue
            try:
                payload = json.loads(json_path.read_text(encoding="utf-8-sig"))
            except Exception:
                continue
            region = _region_from_payload(payload)
            if region is None:
                continue
            _INVENTORY_DETAIL_NAME_TEMPLATE_REGION[key] = region
            return region
    return None


def _load_region_capture_payload(name: str, *, reference: bool = False) -> dict | None:
    suffix = "_001.json" if reference else ".region.json"
    cache_key = f"{name}{suffix}"
    cached = _REGION_CAPTURE_PAYLOADS.get(cache_key)
    if cached is not None:
        return cached

    path = REGION_CAPTURE_DIR / f"{name}{suffix}"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    _REGION_CAPTURE_PAYLOADS[cache_key] = payload
    return payload


def _region_from_payload(payload: dict) -> dict | None:
    points = payload.get("points_ratio") or []
    if len(points) < 4:
        return None
    try:
        xs = [float(point.get("x", 0.0)) for point in points]
        ys = [float(point.get("y", 0.0)) for point in points]
    except Exception:
        return None
    return {
        "x1": max(0.0, min(xs)),
        "y1": max(0.0, min(ys)),
        "x2": min(1.0, max(xs)),
        "y2": min(1.0, max(ys)),
    }


def _region_capture_region(name: str) -> dict | None:
    cached = _REGION_CAPTURE_REGIONS.get(name)
    if cached is not None:
        return cached
    payload = _load_region_capture_payload(name)
    if payload is None:
        return None
    region = _region_from_payload(payload)
    if region is None:
        return None
    _REGION_CAPTURE_REGIONS[name] = region
    return region


def _region_capture_reference_path(name: str) -> str | None:
    if name in _REGION_CAPTURE_REFERENCE_PATHS:
        return _REGION_CAPTURE_REFERENCE_PATHS[name]
    payload = _load_region_capture_payload(name, reference=True)
    if payload is None:
        return None
    image_path = str(payload.get("image_path") or "").strip()
    resolved = image_path if image_path and Path(image_path).exists() else None
    _REGION_CAPTURE_REFERENCE_PATHS[name] = resolved
    return resolved


def _dict_to_student_entry(d: dict) -> StudentEntry:
    ws_raw = d.get("weapon_state")
    try:
        ws = WeaponState(ws_raw) if ws_raw else None
    except ValueError:
        ws = None
    return StudentEntry(
        student_id=d.get("student_id"),
        display_name=d.get("display_name"),
        level=d.get("level"),
        student_star=d.get("student_star"),
        weapon_state=ws,
        weapon_star=d.get("weapon_star"),
        weapon_level=d.get("weapon_level"),
        ex_skill=d.get("ex_skill"),
        skill1=d.get("skill1"),
        skill2=d.get("skill2"),
        skill3=d.get("skill3"),
        equip1=d.get("equip1"),
        equip2=d.get("equip2"),
        equip3=d.get("equip3"),
        equip4=d.get("equip4"),
        equip1_level=d.get("equip1_level"),
        equip2_level=d.get("equip2_level"),
        equip3_level=d.get("equip3_level"),
        stat_hp=d.get("stat_hp"),
        stat_atk=d.get("stat_atk"),
        stat_heal=d.get("stat_heal"),
        skipped=True,
    )



# Scanner


class Scanner:

    def __init__(
        self,
        regions: dict,
        on_progress: Optional[Callable[[str], None]] = None,
        on_progress_state: Optional[Callable[[dict], None]] = None,
        maxed_ids:   Optional[set[str]]  = None,
        maxed_saved_data: Optional[dict[str, dict]] = None,
        student_saved_data: Optional[dict[str, dict]] = None,
        student_total_hint: Optional[int] = None,
        autosave_manager = None,   # AutoSaveManager | None
        inventory_profile_id: str | list[str] | tuple[str, ...] | None = None,
        fast_student_ids: Optional[list[str]] = None,
        inventory_detail_override_dir: str | os.PathLike | None = None,
    ):
        self.r             = regions
        self._on_progress  = on_progress
        self._on_progress_state = on_progress_state
        self._stop         = False
        self._space_stop_latched = False
        self._maxed_ids    = frozenset(maxed_ids or [])
        self._maxed_saved_data: dict[str, dict] = maxed_saved_data or {}
        self._student_saved_data: dict[str, dict] = student_saved_data or {}
        self._student_total_hint = student_total_hint if student_total_hint and student_total_hint > 0 else None
        self._asv          = autosave_manager   # AutoSaveManager or None
        self._fast_student_ids = list(fast_student_ids or [])
        self._student_basic_img: Optional[Image.Image] = None
        self._captured_click_points = self._load_captured_click_points()
        self._active_student_panel: str | None = None
        self._inventory_icon_cache: dict[str, dict[str, tuple[str | None, str, str | None]]] = {
            "item": {},
            "equipment": {},
        }
        self._inventory_failed_hashes: dict[str, set[str]] = {
            "item": set(),
            "equipment": set(),
        }
        self._default_inventory_profile_ids = normalize_inventory_profile_ids(inventory_profile_id)
        self._inventory_detail_override_dir = (
            Path(inventory_detail_override_dir)
            if inventory_detail_override_dir
            else None
        )
        self._forced_inventory_profile_id: str | None = (
            None
            if not self._default_inventory_profile_ids or self._default_inventory_profile_ids == ("all",)
            else self._default_inventory_profile_ids[0]
        )

        if self._maxed_ids:
            self._info(f"만렙 스킵용 저장데이터 로드: {len(self._maxed_ids)}명")

    def stop(self) -> None:
        self._stop = True
        _log.info("스캔 중지 요청")

    def clear_stop(self) -> None:
        self._stop = False
        self._space_stop_latched = False

    def _stop_requested(self) -> bool:
        if not self._stop and _space_key_down():
            self._stop = True
            if not self._space_stop_latched:
                self._space_stop_latched = True
                self._info("[stop] Spacebar emergency stop requested")
                _log.info("spacebar emergency stop requested")
        return self._stop

    def _wait(self, seconds: float, step: float = 0.05) -> bool:
        end = time.monotonic() + max(0.0, seconds)
        while time.monotonic() < end:
            if self._stop_requested():
                return False
            time.sleep(min(step, end - time.monotonic()))
        return not self._stop_requested()

    def _load_captured_click_points(self) -> dict[str, dict]:
        path = Path(CAPTURED_CLICK_POINTS_FILE)
        try:
            if path.exists():
                raw = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    _log.info("[coord_capture] loaded %d points from %s", len(raw), path)
                    return raw
        except Exception as exc:
            _log.warning("[coord_capture] failed to load %s: %s", path, exc)
        return {}

    def _click_ratio_point(self, rx: float, ry: float, label: str = "", delay: float = 0.0) -> bool:
        rect = self._rect()
        if rect is None:
            _log.warning(f"[click] rect missing: {label}")
            return False
        hwnd = self._hwnd()
        if not hwnd:
            _log.warning(f"[click] hwnd missing: {label}")
            return False
        cx, cy = ratio_to_client(rect, rx, ry)
        ok = click_point(hwnd, cx, cy, label=label, delay=delay)
        _log.debug(
            f"[click] {label} ratio=({rx:.6f},{ry:.6f}) client=({cx},{cy}) ok={ok}"
        )
        return ok

    def _click_captured_point(self, name: str, *, label: str = "", delay: float = 0.0) -> bool:
        point = self._captured_click_points.get(name)
        if not isinstance(point, dict):
            return False
        ratio = point.get("ratio")
        if not isinstance(ratio, dict):
            return False
        try:
            rx = float(ratio["x"])
            ry = float(ratio["y"])
        except Exception:
            return False
        return self._click_ratio_point(rx, ry, label=label or name, delay=delay)

    def _click_region_capture(self, name: str, *, label: str = "", delay: float = 0.0) -> bool:
        region = _region_capture_region(name)
        if region is None:
            self.log(f"warning: missing region capture {name}")
            return False
        clicked = self._click_r(region, label or name)
        if clicked and delay > 0:
            return self._wait(delay)
        return clicked

    def _region_capture_match_score(self, name: str) -> float | None:
        region = _region_capture_region(name)
        template_path = _region_capture_reference_path(name)
        if region is None or not template_path:
            return None
        img = self._capture()
        if img is None:
            return None
        crop = crop_region(img, region)
        return match_score_resized(crop, template_path, focus_center=True)

    def _ensure_region_matches_reference(
        self,
        name: str,
        *,
        threshold: float = INVENTORY_SORT_RULE_MATCH_THRESHOLD,
        click_delay: float = DELAY_AFTER_CLICK,
        check_wait: float = INVENTORY_SORT_RULE_CHECK_WAIT,
        retry_wait: float = INVENTORY_SORT_RULE_RETRY_WAIT,
        max_attempts: int = INVENTORY_SORT_RULE_MAX_ATTEMPTS,
    ) -> bool:
        for attempt in range(1, max_attempts + 1):
            if check_wait > 0 and not self._wait(check_wait):
                return False
            score = self._region_capture_match_score(name)
            if score is None:
                self.log(f"  {name} reference unavailable -> skip check")
                return False
            self.log(f"  {name} match score={score:.3f} (attempt {attempt}/{max_attempts})")
            if score >= threshold:
                return True
            if attempt >= max_attempts:
                break
            self.log(f"  {name} mismatch -> clicking")
            if not self._click_region_capture(name, label=name, delay=click_delay):
                return False
            if retry_wait > 0 and not self._wait(retry_wait):
                return False
        self.log(f"  {name} did not reach threshold {threshold:.2f}")
        return False

    def _item_scan_profiles(
        self,
        inventory_profile_id: str | list[str] | tuple[str, ...] | None,
    ) -> tuple[str | None, ...]:
        requested = inventory_profile_id
        if requested is None:
            requested = self._default_inventory_profile_ids
        normalized = normalize_inventory_profile_ids(requested)
        if not normalized or normalized == ("all",):
            return (None,)
        return tuple(normalized)

    def _prepare_item_inventory(self, profile_id: str | None, *, ensure_sort_rule: bool) -> bool:
        self.log("  item filter menu open")
        if not self._click_region_capture(
            "filtermenu_button",
            label="filtermenu_button",
            delay=INVENTORY_FILTER_MENU_SETTLE_WAIT,
        ):
            return False
        if ensure_sort_rule:
            if not self._click_region_capture(
                "sort_tab",
                label="sort_tab",
                delay=INVENTORY_FILTER_TAB_SETTLE_WAIT,
            ):
                return False
            if not self._ensure_region_matches_reference(
                "sort_rule_check",
                threshold=ITEM_SORT_RULE_MATCH_THRESHOLD,
            ):
                return False
        if not self._click_region_capture(
            "filter_tab",
            label="filter_tab",
            delay=INVENTORY_FILTER_TAB_SETTLE_WAIT,
        ):
            return False
        if not self._click_region_capture(
            "filter_reset_button",
            label="filter_reset_button",
            delay=INVENTORY_FILTER_TAB_SETTLE_WAIT,
        ):
            return False

        filter_button_by_profile = {
            "tech_notes": "note_filter",
            "tactical_bd": "bd_filter",
            "ooparts": "ooparts_filter",
            "coins": "coin_filter",
            "activity_reports": "reports_filter",
        }
        filter_button = filter_button_by_profile.get(profile_id or "")
        if filter_button:
            if not self._click_region_capture(
                filter_button,
                label=filter_button,
                delay=INVENTORY_FILTER_TAB_SETTLE_WAIT,
            ):
                return False

        if not self._click_region_capture(
            "filter_confirm_button",
            label="filter_confirm_button",
            delay=INVENTORY_FILTER_CONFIRM_WAIT,
        ):
            return False
        return self._wait(INVENTORY_FILTER_CONFIRM_WAIT)

    def _prepare_equipment_inventory(self) -> bool:
        self.log("  equipment filter menu open")
        if not self._click_region_capture(
            "eq_filtermenu_button",
            label="eq_filtermenu_button",
            delay=INVENTORY_FILTER_MENU_SETTLE_WAIT,
        ):
            return False
        if not self._ensure_region_matches_reference("eq_sort_rule_check"):
            return False
        if not self._click_region_capture(
            "eq_filter_confirm_button",
            label="eq_filter_confirm_button",
            delay=INVENTORY_FILTER_CONFIRM_WAIT,
        ):
            return False
        return self._wait(INVENTORY_FILTER_CONFIRM_WAIT)

    def _reset_inventory_scan_state(self, source: str) -> None:
        self._inventory_icon_cache[source] = {}
        self._inventory_failed_hashes[source] = set()

    def _close_inventory_menu(self) -> bool:
        menu_back = self.r.get("menu", {}).get("backbutton")
        if not menu_back:
            self.log("warning: missing menu backbutton")
            return False
        if not self._click_r(menu_back, "menu_backbutton"):
            return False
        return self._wait(0.2)

    def _go_home_from_inventory(self) -> bool:
        return self._click_region_capture("home", label="home", delay=0.35)

    def _exit_inventory_to_menu(self) -> bool:
        if not self._close_inventory_menu():
            return False
        if not self._go_home_from_inventory():
            return False
        if not self._open_menu():
            return False
        return self._wait(1.0)

    def _return_inventory_to_lobby(self) -> None:
        self.log("로비 복귀...")
        if not self._close_inventory_menu():
            return
        self._go_home_from_inventory()

    def _close_student_panel(
        self,
        *,
        capture_name: str | None = None,
        region_key: str | None = None,
        settle_reason: str,
        wait: float = PANEL_CLOSE_SETTLE_WAIT,
    ) -> None:
        sr = self.r["student"]
        self._active_student_panel = None
        clicked = False
        if capture_name:
            clicked = self._click_captured_point(capture_name, label=capture_name, delay=wait)
        if (not clicked) and region_key and region_key in sr:
            clicked = self._click_r(sr[region_key], region_key)
            if clicked and wait > 0:
                self._wait(wait)
        if not clicked:
            self._esc(delay=wait)
        self._settle_student_detail(settle_reason)

    def _panel_close_spec(self, panel_name: str) -> tuple[str | None, str | None, str]:
        if panel_name == "skill":
            return "skill_close_button", "skillmenu_quit_button", "close_skill_menu"
        if panel_name == "weapon":
            return "weapon_close_button", "weapon_menu_quit_button", "close_weapon_menu"
        if panel_name == "equipment":
            return "equipment_close_button", "equipmentmenu_quit_button", "close_equipment_menu"
        if panel_name == "stat":
            return "stat_close_button", "statmenu_quit_button", "close_stat_menu"
        return None, None, "close_panel"

    def _close_active_student_panel(self, *, wait: float = PANEL_CLOSE_SETTLE_WAIT) -> bool:
        panel_name = self._active_student_panel
        if not panel_name:
            return False
        capture_name, region_key, settle_reason = self._panel_close_spec(panel_name)
        self._active_student_panel = None
        sr = self.r["student"]
        clicked = False
        if capture_name:
            clicked = self._click_captured_point(capture_name, label=capture_name, delay=wait)
        if (not clicked) and region_key and region_key in sr:
            clicked = self._click_r(sr[region_key], region_key)
            if clicked and wait > 0:
                self._wait(wait)
        if clicked:
            self._settle_student_detail(settle_reason)
        return clicked


    # Forward logs to both the file logger and the UI progress callback.

    def _debug(self, msg: str) -> None:
        _log.debug(msg)

    def _info(self, msg: str) -> None:
        _log.info(msg)
        if self._on_progress:
            self._on_progress(msg)

    def _emit_progress_state(
        self,
        *,
        current: int | None = None,
        total: int | None = None,
        note: str = "",
    ) -> None:
        if self._on_progress_state:
            self._on_progress_state(
                {
                    "current": current,
                    "total": total,
                    "note": note,
                }
            )

    def _warn(self, msg: str) -> None:
        _log.warning(msg)
        if self._on_progress:
            self._on_progress(f"주의 {msg}")

    def _error(self, msg: str) -> None:
        _log.error(msg)
        if self._on_progress:
            self._on_progress(f"오류 {msg}")

    # Backward-compatible alias so old code can keep using self.log(msg).
    @property
    def log(self):
        return self._info


    # Student entry lifecycle helpers


    def begin_student_scan(self, student_id: str) -> StudentEntry:
        """Create a temporary student entry at the start of a scan."""
        entry = StudentEntry(
            student_id=student_id,
            display_name=student_meta.display_name(student_id),
            scan_state=ScanState.TEMP,
        )
        _log.debug(f"[TEMP] start: {entry.label()}")
        return entry

    def _saved_student(self, student_id: str | None) -> dict:
        if not student_id:
            return {}
        saved = self._student_saved_data.get(student_id)
        return saved if isinstance(saved, dict) else {}

    def _saved_int(self, saved: dict, field_name: str) -> int | None:
        try:
            value = saved.get(field_name)
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    def _apply_saved_fields(
        self,
        entry: StudentEntry,
        saved: dict,
        field_names: tuple[str, ...],
        note: str,
    ) -> None:
        for field_name in field_names:
            value = saved.get(field_name)
            if field_name == "weapon_state" and value is not None:
                try:
                    value = WeaponState(value)
                except ValueError:
                    value = None
            setattr(entry, field_name, value)
            entry.set_meta(field_name, FieldMeta.skipped(note))

    def _skills_maxed_from_saved_data(self, saved: dict) -> bool:
        return (
            self._saved_int(saved, "ex_skill") == 5
            and self._saved_int(saved, "skill1") == 10
            and self._saved_int(saved, "skill2") == 10
            and self._saved_int(saved, "skill3") == 10
        )

    def _weapon_maxed_from_saved_data(self, saved: dict) -> bool:
        return (
            saved.get("weapon_state") == WeaponState.WEAPON_EQUIPPED.value
            and self._saved_int(saved, "weapon_star") == 4
            and self._saved_int(saved, "weapon_level") == 60
        )

    def _equipment_maxed_from_saved_data(self, saved: dict) -> bool:
        return all(
            saved.get(f"equip{slot}") == "T10"
            and self._saved_int(saved, f"equip{slot}_level") == 70
            for slot in (1, 2, 3)
        )

    def _favorite_item_maxed_from_saved_data(self, student_id: str | None, saved: dict) -> bool:
        return bool(student_id) and student_meta.favorite_item_enabled(student_id) and saved.get("equip4") == "T2"

    def _stats_maxed_from_saved_data(self, saved: dict) -> bool:
        return all(self._saved_int(saved, field_name) == 25 for field_name in ("stat_hp", "stat_atk", "stat_heal"))





    def finalize_student_entry(
        self,
        entry:   StudentEntry,
        ctx:     "ScanCtx",
        *,
        partial_ok: bool = True,
    ) -> EntryCommitResult:
        """Validate a temporary student entry before it is committed."""


















        if not entry.student_id:
            entry.scan_state = ScanState.FAILED
            return EntryCommitResult(
                entry=entry, committed=False,
                missing=[], confidence=0.0,
                reason="student_id missing",
            )

        missing    = entry.missing_fields()
        confidence = entry.confidence()

        if not missing:
            # All required fields were filled, so the entry can be committed.
            entry.scan_state = ScanState.COMMITTED

            # Still log if any field succeeded with low confidence.
            uncertain = entry.uncertain_fields()
            if uncertain:
                _log.warning(
                    f"{ctx} warning: committed with uncertain fields: {uncertain}"
                )
            else:
                _log.info(
                    f"{ctx} COMMITTED "
                    f"(confidence={confidence:.2f})"
                )
            return EntryCommitResult(
                entry=entry, committed=True,
                missing=[], confidence=confidence,
            )

        # Missing fields are allowed in partial mode.
        if partial_ok:
            entry.scan_state = ScanState.PARTIAL
            _log.warning(
                f"{ctx} warning: PARTIAL "
                f"(confidence={confidence:.2f} missing={missing})"
            )
            return EntryCommitResult(
                entry=entry, committed=True,
                missing=missing, confidence=confidence,
                reason=f"missing={missing}",
            )

        # In strict mode, missing required fields make the entry fail.
        entry.scan_state = ScanState.FAILED
        _log.warning(
            f"{ctx} FAILED (strict) "
            f"(confidence={confidence:.2f} missing={missing})"
        )
        return EntryCommitResult(
            entry=entry, committed=False,
            missing=missing, confidence=confidence,
            reason=f"strict_fail missing={missing}",
        )

    def commit_student_entry(
        self,
        result:  EntryCommitResult,
        results: list[StudentEntry],
        idx:     int,
    ) -> bool:
        """Append a validated entry to the results list when allowed."""
        entry = result.entry
        if not result.committed:
            _log.warning(
                f"[{idx+1:>3}] skipped entry: {entry.label()} -> {result.reason}"
            )
            return False

        results.append(entry)

        state_tag = "COMMITTED" if entry.is_committed() else "PARTIAL"
        _log.info(
            f"[{idx+1:>3}] {state_tag}: {entry.label()} "
            f"(confidence={result.confidence:.2f})"
        )
        if result.missing:
            self._warn(
                f"  [{idx+1:>3}] {entry.label()} missing fields: {result.missing}"
            )
        return True



    def _capture(self, retry: int = RETRY_CAPTURE) -> Optional[Image.Image]:
        """Capture the game window, retrying briefly on failure."""
        for i in range(retry + 1):
            if self._stop_requested():
                return None
            img = capture_window_background()
            if img is not None:
                return img
            if i < retry:
                _log.debug(f"capture retry ({i+1}/{retry})")
                if not self._wait(0.1):
                    return None
        self._error("capture failed")
        return None

    def _invalidate_student_basic_capture(self) -> None:
        self._student_basic_img = None

    def _get_student_basic_capture(
        self,
        *,
        refresh: bool = False,
    ) -> Optional[Image.Image]:
        if refresh or self._student_basic_img is None:
            img = self._capture()
            if img is None:
                return None
            self._student_basic_img = img
        return self._student_basic_img

    def _adjust_region(
        self,
        region: dict,
        *,
        left: float = 0.0,
        top: float = 0.0,
        right: float = 0.0,
        bottom: float = 0.0,
    ) -> dict:
        return {
            "x1": max(0.0, min(1.0, region["x1"] + left)),
            "y1": max(0.0, min(1.0, region["y1"] + top)),
            "x2": max(0.0, min(1.0, region["x2"] + right)),
            "y2": max(0.0, min(1.0, region["y2"] + bottom)),
        }

    def _is_lobby_capture(self, img: Optional[Image.Image]) -> bool:
        detect_r = self.r.get("lobby", {}).get("detect_flag")
        if img is None or not detect_r:
            return False
        roi = crop_region(img, detect_r)
        return is_lobby(roi, {"x1": 0.0, "y1": 0.0, "x2": 1.0, "y2": 1.0})

    def _is_student_menu_capture(self, img: Optional[Image.Image]) -> bool:
        detect_r = self.r.get("student_menu", {}).get("menu_detect_flag")
        if img is None or not detect_r:
            return False
        roi = crop_region(img, detect_r)
        return is_student_menu(roi, {"x1": 0.0, "y1": 0.0, "x2": 1.0, "y2": 1.0})

    def _student_additional_menu_region(self) -> Optional[dict]:
        # Reuse the student-menu detect ROI by default because the additional
        # menu applies the same dimmed effect to that area.
        return (
            self.r.get("student", {}).get("student_additional_menu_on_flag")
            or self.r.get("student_menu", {}).get("menu_detect_flag")
        )

    def _is_student_additional_menu_capture(self, img: Optional[Image.Image]) -> bool:
        detect_r = self._student_additional_menu_region()
        if img is None or not detect_r:
            return False
        roi = crop_region(img, detect_r)
        return is_student_additional_menu_on(
            roi,
            {"x1": 0.0, "y1": 0.0, "x2": 1.0, "y2": 1.0},
        )

    def _is_level_tab_on_capture(self, img: Optional[Image.Image]) -> bool:
        detect_r = self.r.get("student", {}).get("levelcheck_button")
        if img is None or not detect_r:
            return False
        roi = crop_region(img, detect_r)
        return is_level_tab_on(roi, {"x1": 0.0, "y1": 0.0, "x2": 1.0, "y2": 1.0})

    def _is_basic_info_tab_on_capture(self, img: Optional[Image.Image]) -> bool:
        detect_r = self.r.get("student", {}).get("basic_info_button")
        if img is None or not detect_r:
            return False
        roi = crop_region(img, detect_r)
        return is_basic_info_tab_on(
            roi,
            {"x1": 0.0, "y1": 0.0, "x2": 1.0, "y2": 1.0},
        )

    def _is_star_tab_on_capture(self, img: Optional[Image.Image]) -> bool:
        detect_r = self.r.get("student", {}).get("star_menu_button")
        if img is None or not detect_r:
            return False
        roi = crop_region(img, detect_r)
        return is_star_tab_on(
            roi,
            {"x1": 0.0, "y1": 0.0, "x2": 1.0, "y2": 1.0},
        )

    def _student_detail_score(self, img: Optional[Image.Image]) -> float:
        texture_r = self.r.get("student", {}).get("student_texture_region")
        if img is None or not texture_r:
            return 0.0
        crop = crop_region(img, texture_r)
        _, score = match_student_texture(crop)
        return score

    def _wait_for_student_menu_state(
        self,
        expected_in_student_menu: bool,
        *,
        timeout: float,
        initial_wait: float = 0.0,
        poll: float = 0.25,
    ) -> bool:
        if initial_wait > 0 and not self._wait(initial_wait):
            return False
        deadline = time.monotonic() + timeout
        ready_streak = 0
        while time.monotonic() < deadline:
            if self._stop_requested():
                return False
            img = self._capture()
            matches = img is not None and self._is_student_menu_capture(img) == expected_in_student_menu
            if matches:
                ready_streak += 1
                if ready_streak < STUDENT_MENU_READY_STABLE_POLLS:
                    if not self._wait(poll):
                        return False
                    continue
                self._invalidate_student_basic_capture()
                return True
            ready_streak = 0
            if not self._wait(poll):
                return False
        return False

    def _wait_for_student_detail(
        self,
        *,
        timeout: float = DETAIL_READY_WAIT,
        initial_wait: float = 0.0,
        poll: float = 0.25,
    ) -> bool:
        if initial_wait > 0 and not self._wait(initial_wait):
            return False
        deadline = time.monotonic() + timeout
        ready_streak = 0
        while time.monotonic() < deadline:
            if self._stop_requested():
                return False
            img = self._capture()
            score = self._student_detail_score(img)
            _log.debug(
                f"[detail_wait] texture_score={score:.3f} "
                f"ready_streak={ready_streak}"
            )
            if score >= DETAIL_READY_SCORE:
                ready_streak += 1
                if ready_streak < DETAIL_READY_STABLE_POLLS:
                    if not self._wait(poll):
                        return False
                    continue
                self._student_basic_img = img
                return True
            else:
                ready_streak = 0
            if not self._wait(poll):
                return False
        return False

    def _wait_for_student_detail_fast(
        self,
        *,
        timeout: float = DETAIL_READY_WAIT,
        initial_wait: float = 0.0,
        poll: float = 0.20,
    ) -> bool:
        if initial_wait > 0 and not self._wait(initial_wait):
            return False
        deadline = time.monotonic() + timeout
        last_img: Optional[Image.Image] = None
        while time.monotonic() < deadline:
            if self._stop_requested():
                return False
            img = self._capture()
            last_img = img
            if img is not None and self._is_basic_info_tab_on_capture(img):
                self._student_basic_img = img
                return True
            if not self._wait(poll):
                return False
        if last_img is not None:
            self._student_basic_img = last_img
            return True
        return False

    def _student_texture_digest(self, img: Optional[Image.Image]) -> Optional[str]:
        texture_r = self.r.get("student", {}).get("student_texture_region")
        if img is None or not texture_r:
            return None
        try:
            crop = crop_region(img, texture_r)
        except Exception:
            return None
        return hashlib.sha1(crop.tobytes()).hexdigest()

    def _current_student_digest(self, *, refresh: bool) -> Optional[str]:
        img = self._get_student_basic_capture(refresh=refresh)
        return self._student_texture_digest(img)

    def _wait_for_student_change(
        self,
        previous_digest: str,
        *,
        timeout: float = 3.0,
        initial_wait: float = DELAY_NEXT,
        poll: float = 0.12,
    ) -> Optional[str]:
        if initial_wait > 0 and not self._wait(initial_wait):
            return None
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._stop_requested():
                return None
            img = self._get_student_basic_capture(refresh=True)
            digest = self._student_texture_digest(img)
            if digest and digest != previous_digest:
                return digest
            if not self._wait(poll):
                return None
        return None

    def _wait_for_capture_match(
        self,
        predicate: Callable[[Optional[Image.Image]], bool],
        *,
        timeout: float,
        initial_wait: float = 0.0,
        poll: float = UI_FLAG_POLL,
        stable_polls: int = 1,
        label: str = "",
    ) -> Optional[Image.Image]:
        if initial_wait > 0 and not self._wait(initial_wait):
            return None
        deadline = time.monotonic() + timeout
        ready_streak = 0
        last_img: Optional[Image.Image] = None
        while time.monotonic() < deadline:
            if self._stop_requested():
                return None
            img = self._capture()
            last_img = img
            matched = img is not None and predicate(img)
            _log.debug(
                f"[wait_match] label={label} matched={matched} "
                f"ready_streak={ready_streak}"
            )
            if matched:
                ready_streak += 1
                if ready_streak >= stable_polls:
                    return img
            else:
                ready_streak = 0
            if not self._wait(poll):
                return last_img if matched else None
        return None

    def _click_student_region_and_wait(
        self,
        region_key: str,
        label: str,
        predicate: Callable[[Optional[Image.Image]], bool],
        *,
        timeout: float,
        initial_wait: float = DELAY_AFTER_CLICK,
        poll: float = UI_FLAG_POLL,
        stable_polls: int = 1,
        fallback_delay: float = DELAY_TAB_SWITCH,
        match_delay: float = UI_FLAG_MATCH_DELAY,
    ) -> Optional[Image.Image]:
        region = self.r.get("student", {}).get(region_key)
        if not region:
            self.log(f"  missing {region_key}")
            return None
        if not self._click_r(region, label):
            return None
        img = self._wait_for_capture_match(
            predicate,
            timeout=timeout,
            initial_wait=initial_wait + max(0.0, match_delay),
            poll=poll,
            stable_polls=stable_polls,
            label=label,
        )
        if img is not None:
            return img
        if fallback_delay > 0 and not self._wait(fallback_delay):
            return None
        return self._capture()

    def _recover_first_student_entry(self) -> bool:
        _log.warning("첫 학생 진입 복구 루틴 시작")
        img = self._capture()
        if img is not None:
            if self._is_lobby_capture(img):
                _log.warning("recover detect: still in lobby")
                if not self.enter_student_menu():
                    return False
            elif self._is_student_menu_capture(img):
                _log.warning("recover detect: still in student menu")
        self._invalidate_student_basic_capture()
        return self.enter_first_student()

    def _rect(self) -> Optional[tuple[int, int, int, int]]:
        return get_window_rect()

    def _hwnd(self) -> Optional[int]:
        return find_target_hwnd()

    def _retry(
        self,
        fn: Callable,
        max_attempts: int = 2,
        delay: float = 0.3,
        label: str = "",
    ):
        """Retry fn() until it returns a non-None result or attempts run out."""




        for i in range(max_attempts):
            if self._stop_requested():
                return None
            result = fn()
            if result is not None:
                return result
            if i < max_attempts - 1:
                self.log(f"  재시도 {label} ({i+2}/{max_attempts})")
                if not self._wait(delay):
                    return None
        return None



    def _click_r(self, region: dict, label: str = "") -> bool:
        """Click the center point of a ratio region."""
        rect = self._rect()
        if rect is None:
            _log.warning(f"[click] window rect missing: {label}")
            return False
        hwnd = self._hwnd()
        rx = (region["x1"] + region["x2"]) / 2
        ry = (region["y1"] + region["y2"]) / 2
        if hwnd:
            cx, cy = ratio_to_client(rect, rx, ry)
            ok = click_point(hwnd, cx, cy, label=label)
            _log.debug(
                f"[click] {label} hwnd={hwnd} ratio=({rx:.4f},{ry:.4f}) "
                f"client=({cx},{cy}) ok={ok}"
            )
            return ok
        ok = click_center(rect, region, label)
        _log.debug(f"[click] {label} ratio=({rx:.4f},{ry:.4f}) fallback ok={ok}")
        return ok

    def _tab(self, region_key: str, delay: float = DELAY_TAB_SWITCH) -> bool:
        """Click a student tab/button region and wait for it to settle."""
        sr = self.r["student"]
        region = sr.get(region_key)
        if not region:
            self.log(f"  warning: {region_key} missing -> 이동 생략")
            return False
        ok = self._click_r(region, region_key)
        if delay > 0:
            if not self._wait(delay):
                return False
        return ok

    def _esc(self, n: int = 1, delay: float = PANEL_CLOSE_SETTLE_WAIT) -> None:
        """Close the current panel, usually via ESC fallback logic."""
        hwnd = self._hwnd()
        for _ in range(n):
            if self._stop_requested():
                return
            if n == 1 and self._close_active_student_panel(wait=delay):
                return
            if hwnd:
                send_escape(hwnd, delay=delay)
            else:
                press_esc()

    def _restore_basic_tab(self) -> bool:
        """Return to the basic info tab."""
        sr = self.r["student"]
        current = self._get_student_basic_capture(refresh=True)
        if current is not None and self._is_basic_info_tab_on_capture(current):
            self._student_basic_img = current
            return True
        if "basic_info_button" in sr:
            img = self._click_student_region_and_wait(
                "basic_info_button",
                "basic_info_tab",
                self._is_basic_info_tab_on_capture,
                timeout=TAB_ON_READY_WAIT,
                initial_wait=DELAY_AFTER_CLICK,
                poll=UI_FLAG_POLL,
                stable_polls=1,
                fallback_delay=BASIC_TAB_SETTLE_WAIT,
            )
            if img is not None:
                self._student_basic_img = img
                return True
        else:
            self._esc()
        return self._settle_student_detail("basic_info_tab", initial_wait=0.0)

    def _settle_student_detail(
        self,
        reason: str,
        *,
        initial_wait: float = MENU_CLOSE_DETAIL_WAIT,
        timeout: float = 2.5,
        poll: float = 0.20,
    ) -> bool:
        self._invalidate_student_basic_capture()
        ok = self._wait_for_student_detail(
            timeout=timeout,
            initial_wait=initial_wait,
            poll=poll,
        )
        _log.debug(f"[detail_settle] reason={reason} ok={ok}")
        return ok





    def scan_resources(self) -> dict:
        self.log("자원 스캔 중...")
        img = self._capture()
        if img is None:
            return {}

        lobby_r = self.r["lobby"]
        result: dict = {}

        ocr.load()
        try:
            for key, rk in [("credit", "credit_region"),
                             ("pyroxene", "pyroxene_region")]: 
                try:
                    crop = crop_region(img, lobby_r[rk])
                    result[key] = ocr.read_item_count(crop)
                except Exception as e:
                    result[key] = None
                    _log.warning(f"자원 OCR 실패 ({key}): {type(e).__name__}: {e}")
        finally:
            ocr.unload()

        self.log(f"Lobby OCR: pyroxene={result.get('pyroxene', '-')} credit={result.get('credit', '-')}")
        return result





    def _open_menu(self) -> bool:
        rect = self._rect()
        if not rect:
            return False
        self.log("메뉴 열기...")
        self._click_r(self.r["lobby"]["menu_button"], "menu_button")
        return self._wait(0.7)

    def _go_to(self, btn_key: str, label: str) -> bool:
        btn = self.r["menu"].get(btn_key)
        if not btn:
            self.log(f"warning: {label} 버튼 설정 없음")
            return False
        self.log(f"  {label} 진입...")
        self._click_r(btn, label)
        return self._wait(1.0)

    def _return_lobby(self) -> None:
        self.log("로비 복귀...")
        self._esc()

    def _capture_inventory_page(
        self,
        img: Image.Image,
        slots: list[dict],
        *,
        grid_hash: str,
        page_index: int,
        grid_cols: int,
    ) -> InventoryPageSnapshot:
        slot_snaps: list[InventorySlotSnapshot] = []
        for idx, slot in enumerate(slots):
            icon_crop = crop_region(img, _slot_icon_region(slot))
            slot_snaps.append(
                InventorySlotSnapshot(
                    slot_index=idx,
                    icon_hash=_img_hash(icon_crop),
                )
            )
        last_row_hashes = [s.icon_hash for s in slot_snaps[-grid_cols:]] if grid_cols > 0 else []
        return InventoryPageSnapshot(
            page_index=page_index,
            grid_hash=grid_hash,
            last_row_hashes=last_row_hashes,
            slots=slot_snaps,
        )

    def _verify_inventory_slot(
        self,
        rect: tuple[int, int, int, int],
        slot: dict,
        name_r: dict,
        count_r: dict,
        source: str,
        profile_id: str | None = None,
    ) -> InventoryVerification | None:
        click_ry = slot["y1"] + (slot["y2"] - slot["y1"]) * 0.4
        safe_click(rect, slot["cx"], click_ry, f"{source}_slot")
        if not self._wait(DELAY_AFTER_CLICK):
            return None

        img2 = self._capture()
        if img2 is None:
            return None

        count = ""
        if source == "item" or profile_id:
            count_match = None
            if source == "equipment" or profile_id == "equipment":
                count_match = read_equipment_count_from_detail(img2)
                if (
                    count_match.value is None
                    and count_match.reason in ("no_x_templates", "missing_digit_templates")
                ):
                    self.log(
                        "    equipment count fallback -> item templates "
                        f"(reason={count_match.reason})"
                    )
                    count_match = read_item_count_from_detail(img2)
            else:
                count_match = read_item_count_from_detail(img2)
            if count_match.value is not None:
                count = count_match.value
                self.log(
                    f"    count template matched: {count} "
                    f"(digits={count_match.digit_count}, conf={count_match.confidence:.2f})"
                )
            else:
                self.log(
                    f"    count template fallback: reason={count_match.reason} "
                    f"(digits={count_match.digit_count}, conf={count_match.confidence:.2f})"
                )
            if not count:
                return None
            matched_item_id = None
            matched_score = 0.0
            detail_crop = self._inventory_detail_crop(img2, profile_id) if profile_id else None
            detail_name_crop = self._inventory_detail_name_crop(img2, source) if profile_id else None
            if profile_id:
                matched_item_id, matched_score = self._match_inventory_detail_crop(
                    detail_crop,
                    profile_id,
                    detail_name_crop,
                )
                if matched_item_id:
                    self.log(
                        f"    detail template matched: {matched_item_id} "
                        f"(score={matched_score:.2f})"
                    )
            return InventoryVerification(
                name=None,
                count=count,
                item_id=matched_item_id,
                match_score=matched_score,
                detail_crop=detail_crop,
                detail_name_crop=detail_name_crop,
            )
        self.log("    detail template fallback disabled: profile/template match required")
        return None

    def _match_inventory_icon(
        self,
        icon_crop: Image.Image,
        source: str,
    ) -> tuple[str | None, float]:
        best_item_id: str | None = None
        best_score = 0.0
        for item_id, path in _inventory_template_catalog(source):
            score = match_score_resized_raw(icon_crop, path)
            if score > best_score:
                best_score = score
                best_item_id = item_id
        threshold = 0.84 if source == "equipment" else 0.80
        if best_score < threshold:
            return None, best_score
        return best_item_id, best_score

    def _inventory_detail_crop(
        self,
        image: Image.Image,
        profile_id: str | None,
    ) -> Image.Image | None:
        region = _inventory_detail_template_region(profile_id)
        if region is None:
            return None
        return crop_region(image, region)

    def _inventory_detail_name_crop(
        self,
        image: Image.Image,
        source: str,
    ) -> Image.Image | None:
        region = _inventory_detail_name_template_region(source)
        if region is None:
            return None
        return crop_region(image, region)

    def _inventory_detail_template_catalog_for_scan(
        self,
        profile_id: str | None,
    ) -> list[tuple[str, str]]:
        base_catalog = _inventory_detail_template_catalog(profile_id)
        if not profile_id or self._inventory_detail_override_dir is None:
            return base_catalog

        override_base = self._inventory_detail_override_dir / profile_id
        if not override_base.exists():
            return base_catalog

        override_by_id: dict[str, str] = {}
        for png in sorted(override_base.glob("*.png")):
            override_by_id[png.stem] = str(png)
        if not override_by_id:
            return base_catalog

        catalog: list[tuple[str, str]] = []
        used: set[str] = set()
        for item_id, path in base_catalog:
            if item_id.startswith("Equipment_Icon_WeaponExpGrowth"):
                catalog.append((item_id, path))
                used.add(item_id)
                continue
            override_path = override_by_id.get(item_id)
            if override_path:
                catalog.append((item_id, override_path))
                used.add(item_id)
            else:
                catalog.append((item_id, path))
        for item_id, path in override_by_id.items():
            if item_id.startswith("Equipment_Icon_WeaponExpGrowth"):
                continue
            if item_id not in used:
                catalog.append((item_id, path))
        return catalog

    def _inventory_detail_name_template_catalog_for_scan(
        self,
        profile_id: str | None,
    ) -> list[tuple[str, str]]:
        base_catalog = _inventory_detail_name_template_catalog(profile_id)
        if not profile_id or self._inventory_detail_override_dir is None:
            return base_catalog

        override_base = self._inventory_detail_override_dir.parent / "inventory_detail_names" / profile_id
        if not override_base.exists():
            return base_catalog

        override_by_id = {png.stem: str(png) for png in sorted(override_base.glob("*.png"))}
        if not override_by_id:
            return base_catalog

        catalog: list[tuple[str, str]] = []
        used: set[str] = set()
        for item_id, path in base_catalog:
            override_path = override_by_id.get(item_id)
            catalog.append((item_id, override_path or path))
            used.add(item_id)
        for item_id, path in override_by_id.items():
            if item_id not in used:
                catalog.append((item_id, path))
        return catalog

    def _match_inventory_detail_name_crop(
        self,
        crop: Image.Image | None,
        profile_id: str | None,
    ) -> tuple[str | None, float]:
        if crop is None:
            return None, 0.0
        catalog = self._inventory_detail_name_template_catalog_for_scan(profile_id)
        if not catalog:
            return None, 0.0

        best_item_id: str | None = None
        best_score = 0.0
        second_best = 0.0
        for item_id, path in catalog:
            score = match_score_textonly(crop, path)
            if score > best_score:
                second_best = best_score
                best_score = score
                best_item_id = item_id
            elif score > second_best:
                second_best = score

        if best_score < 0.72 or (best_score - second_best) < 0.02:
            return None, best_score
        return best_item_id, best_score

    def _match_inventory_detail_crop(
        self,
        crop: Image.Image | None,
        profile_id: str | None,
        name_crop: Image.Image | None = None,
    ) -> tuple[str | None, float]:
        if crop is None:
            return None, 0.0
        catalog = self._inventory_detail_template_catalog_for_scan(profile_id)
        if not catalog:
            return None, 0.0
        name_catalog = dict(self._inventory_detail_name_template_catalog_for_scan(profile_id))

        best_item_id: str | None = None
        best_score = 0.0
        second_best = 0.0
        family_top_scores: dict[str, list[tuple[str, float]]] = {}
        for item_id, path in catalog:
            icon_score = match_score_resized_raw(crop, path)
            name_path = name_catalog.get(item_id)
            name_score = match_score_textonly(name_crop, name_path) if name_crop is not None and name_path else 0.0
            if name_score > 0.0:
                score = 0.72 * icon_score + 0.28 * name_score
            else:
                score = icon_score
            if score > best_score:
                second_best = best_score
                best_score = score
                best_item_id = item_id
            elif score > second_best:
                second_best = score

            family_key = _inventory_detail_strict_family(item_id)
            if family_key is not None:
                top_scores = family_top_scores.setdefault(family_key, [])
                top_scores.append((item_id, score))
                top_scores.sort(key=lambda row: row[1], reverse=True)
                if len(top_scores) > 4:
                    del top_scores[4:]

        if best_score < 0.88 or (best_score - second_best) < 0.015:
            return None, best_score

        strict_family = _inventory_detail_strict_family(best_item_id)
        if strict_family is not None:
            family_threshold, overall_margin_threshold, family_margin_threshold = (
                STRICT_DETAIL_FAMILY_THRESHOLDS[strict_family]
            )
            family_second_best = 0.0
            for item_id, score in family_top_scores.get(strict_family, []):
                if item_id != best_item_id:
                    family_second_best = score
                    break
            overall_margin = best_score - second_best
            family_margin = best_score - family_second_best
            if (
                best_score < family_threshold
                or overall_margin < overall_margin_threshold
                or family_margin < family_margin_threshold
            ):
                self.log(
                    f"    detail template ambiguous reject: {best_item_id} "
                    f"(score={best_score:.2f}, overall_margin={overall_margin:.3f}, "
                    f"family_margin={family_margin:.3f})"
                )
                return None, best_score
        return best_item_id, best_score

    def _match_inventory_detail_template(
        self,
        image: Image.Image,
        profile_id: str | None,
    ) -> tuple[str | None, float]:
        return self._match_inventory_detail_crop(
            self._inventory_detail_crop(image, profile_id),
            profile_id,
            self._inventory_detail_name_crop(image, profile_id or "item"),
        )

    def _fill_missing_profile_entries(
        self,
        items: list[ItemEntry],
        profile,
        source: str,
    ) -> list[ItemEntry]:
        ordered_names = list(profile.ordered_names)
        ordered_item_ids = list(inventory_profile_ordered_item_ids(profile))
        if not ordered_names:
            return items

        def _entry_rank(entry: ItemEntry) -> tuple[int, int, int]:
            quantity = str(entry.quantity or "").strip()
            has_nonzero_quantity = int(quantity not in ("", "0"))
            has_item_id = int(bool(entry.item_id))
            quantity_len = len(quantity)
            return (has_nonzero_quantity, has_item_id, quantity_len)

        by_item_id: dict[str, ItemEntry] = {}
        by_name: dict[str, ItemEntry] = {}
        unmatched: list[ItemEntry] = []
        for entry in items:
            if entry.item_id:
                prev = by_item_id.get(entry.item_id)
                if prev is None or _entry_rank(entry) > _entry_rank(prev):
                    if prev is not None:
                        unmatched.append(prev)
                    by_item_id[entry.item_id] = entry
                else:
                    unmatched.append(entry)
                continue
            if entry.name:
                prev = by_name.get(entry.name)
                if prev is None or _entry_rank(entry) > _entry_rank(prev):
                    if prev is not None:
                        unmatched.append(prev)
                    by_name[entry.name] = entry
                else:
                    unmatched.append(entry)
                continue
            unmatched.append(entry)

        rebuilt: list[ItemEntry] = []
        for idx, expected_name in enumerate(ordered_names):
            expected_item_id = ordered_item_ids[idx] if idx < len(ordered_item_ids) else None
            matched = None
            if expected_item_id:
                matched = by_item_id.pop(expected_item_id, None)
            if matched is None and expected_name:
                matched = by_name.pop(expected_name, None)
            if matched is None:
                continue
            matched.name = expected_name or matched.name
            matched.item_id = expected_item_id or matched.item_id
            matched.index = idx
            rebuilt.append(matched)

        tail = [entry for entry in items if entry not in rebuilt]
        for idx, entry in enumerate(tail, start=len(rebuilt)):
            entry.index = idx
        return rebuilt + tail

    def _recover_profile_gaps_from_candidates(
        self,
        items: list[ItemEntry],
        candidates: list[InventoryDetailCandidate],
        profile,
        source: str,
    ) -> list[ItemEntry]:
        ordered_names = list(profile.ordered_names)
        ordered_item_ids = list(inventory_profile_ordered_item_ids(profile))
        if not ordered_names or not candidates:
            return items

        template_catalog = dict(self._inventory_detail_template_catalog_for_scan(profile.profile_id))
        if not template_catalog:
            return items
        family_profile_indices: dict[str, list[int]] = {}
        for idx, item_id in enumerate(ordered_item_ids):
            family_key = _inventory_detail_strict_family(item_id)
            if family_key is not None:
                family_profile_indices.setdefault(family_key, []).append(idx)

        def _template_path_for(idx: int) -> str | None:
            if idx >= len(ordered_names):
                return None
            expected_id = ordered_item_ids[idx] if idx < len(ordered_item_ids) else None
            expected_name = ordered_names[idx]
            if expected_id and expected_id in template_catalog:
                return template_catalog[expected_id]
            if expected_name and expected_name in template_catalog:
                return template_catalog[expected_name]
            return None

        name_template_catalog = dict(
            self._inventory_detail_name_template_catalog_for_scan(profile.profile_id)
        )

        def _entry_index(entry: ItemEntry) -> int | None:
            if entry.item_id:
                for idx, expected_id in enumerate(ordered_item_ids):
                    if expected_id == entry.item_id:
                        return idx
            if entry.name:
                for idx, expected_name in enumerate(ordered_names):
                    if expected_name == entry.name:
                        return idx
            return None

        def _candidate_detected_index(candidate: InventoryDetailCandidate) -> int | None:
            if not candidate.detected_item_id:
                return None
            for idx, expected_id in enumerate(ordered_item_ids):
                if expected_id == candidate.detected_item_id:
                    return idx
            for idx, expected_name in enumerate(ordered_names):
                if expected_name == candidate.detected_item_id:
                    return idx
            return None

        def _entry_key_for(idx: int) -> str:
            expected_id = ordered_item_ids[idx] if idx < len(ordered_item_ids) else None
            return expected_id or ordered_names[idx]

        def _score(candidate: InventoryDetailCandidate, idx: int) -> float:
            template_path = _template_path_for(idx)
            if not template_path:
                return 0.0
            icon_score = match_score_resized_raw(candidate.detail_crop, template_path)
            expected_id = ordered_item_ids[idx] if idx < len(ordered_item_ids) else None
            name_path = name_template_catalog.get(expected_id or "") if expected_id else None
            if candidate.detail_name_crop is None or not name_path:
                return icon_score
            name_score = match_score_textonly(candidate.detail_name_crop, name_path)
            return 0.72 * icon_score + 0.28 * name_score

        candidate_count = len(candidates)
        profile_count = len(ordered_names)
        score_cache: dict[tuple[int, int], float] = {}
        family_margin_cache: dict[tuple[int, int], float] = {}
        neg_inf = -10.0**9

        def _normalized_distance(candidate_idx: int, profile_idx: int) -> float:
            cand_ratio = (
                candidate_idx / max(1, candidate_count - 1)
                if candidate_count > 1
                else 0.0
            )
            prof_ratio = (
                profile_idx / max(1, profile_count - 1)
                if profile_count > 1
                else 0.0
            )
            return abs(cand_ratio - prof_ratio)

        def _match_score(candidate_idx: int, profile_idx: int) -> float:
            key = (candidate_idx, profile_idx)
            cached = score_cache.get(key)
            if cached is not None:
                return cached

            candidate = candidates[candidate_idx]
            template_score = _score(candidate, profile_idx)
            if template_score <= 0.0:
                score_cache[key] = neg_inf
                return neg_inf

            detected_idx = _candidate_detected_index(candidate)
            expected_item_id = ordered_item_ids[profile_idx] if profile_idx < len(ordered_item_ids) else None
            family_key = _inventory_detail_strict_family(expected_item_id)
            family_margin: float | None = None
            detected_item_id = None
            if detected_idx is not None and detected_idx < len(ordered_item_ids):
                detected_item_id = ordered_item_ids[detected_idx]

            if family_key is not None:
                alt_best = 0.0
                for alt_profile_idx in family_profile_indices.get(family_key, []):
                    if alt_profile_idx == profile_idx:
                        continue
                    alt_score = _score(candidate, alt_profile_idx)
                    if alt_score > alt_best:
                        alt_best = alt_score
                family_margin = template_score - alt_best
                family_margin_cache[key] = family_margin
                if template_score < 0.90 and family_margin < 0.015:
                    score_cache[key] = neg_inf
                    return neg_inf

            score = (template_score - PROFILE_DIRECT_MATCH_THRESHOLD) * 4.0
            if detected_idx == profile_idx:
                if family_key is not None:
                    strict_bonus = 0.45 + max(0.0, candidate.detected_score - 0.95) * 0.9
                    if family_margin is not None:
                        if family_margin >= 0.05:
                            strict_bonus += 0.25
                        elif family_margin < 0.03:
                            strict_bonus -= 0.35
                    score += strict_bonus
                else:
                    score += 1.6 + max(0.0, candidate.detected_score - PROFILE_DIRECT_MATCH_THRESHOLD) * 1.5
            elif detected_idx is not None:
                if family_key is not None:
                    mismatch_distance = abs(detected_idx - profile_idx)
                    score -= 1.35 + min(mismatch_distance * 0.32, 2.0)
                    detected_position = _inventory_detail_strict_family_position(detected_item_id)
                    expected_position = _inventory_detail_strict_family_position(expected_item_id)
                    if detected_position is not None and expected_position is not None:
                        _family, detected_group, detected_tier = detected_position
                        _family, expected_group, expected_tier = expected_position
                        score -= abs(detected_group - expected_group) * 0.55
                        score -= abs(detected_tier - expected_tier) * 0.18
                else:
                    score -= 1.2 + min(abs(detected_idx - profile_idx) * 0.15, 0.9)

            if family_key is not None and family_margin is not None:
                if family_margin < 0.02:
                    score -= 1.2
                elif family_margin < 0.03:
                    score -= 0.6

            score -= _normalized_distance(candidate_idx, profile_idx) * 0.75
            score_cache[key] = score
            return score

        def _skip_profile_penalty(profile_idx: int) -> float:
            if profile_count <= 1:
                return -0.45
            edge_distance = min(profile_idx, profile_count - 1 - profile_idx)
            return -0.35 if edge_distance == 0 else -0.55

        def _skip_candidate_penalty(candidate_idx: int) -> float:
            candidate = candidates[candidate_idx]
            detected_idx = _candidate_detected_index(candidate)
            if detected_idx is not None and candidate.detected_score >= PROFILE_DIRECT_MATCH_THRESHOLD:
                return -1.25
            if candidate.detected_score >= 0.90:
                return -0.85
            return -0.35

        def _anchor_strength(candidate_idx: int, profile_idx: int) -> float:
            candidate = candidates[candidate_idx]
            if candidate.detected_score < 0.95:
                return neg_inf
            template_score = _score(candidate, profile_idx)
            if template_score < 0.93:
                return neg_inf

            expected_item_id = (
                ordered_item_ids[profile_idx]
                if profile_idx < len(ordered_item_ids)
                else None
            )
            family_key = _inventory_detail_strict_family(expected_item_id)
            family_margin = family_margin_cache.get((candidate_idx, profile_idx))
            if family_key is not None:
                if family_margin is None:
                    _match_score(candidate_idx, profile_idx)
                    family_margin = family_margin_cache.get((candidate_idx, profile_idx))
                if candidate.detected_score < 0.96 or template_score < 0.94:
                    return neg_inf
                if family_margin is None or family_margin < 0.035:
                    return neg_inf
            elif candidate.detected_score < 0.97:
                return neg_inf

            return candidate.detected_score + template_score

        def _run_segment_dp(
            candidate_start: int,
            candidate_end: int,
            profile_start: int,
            profile_end: int,
        ) -> tuple[dict[int, int], int, float]:
            segment_candidate_count = candidate_end - candidate_start
            segment_profile_count = profile_end - profile_start
            if segment_candidate_count <= 0 and segment_profile_count <= 0:
                return {}, 0, 0.0

            dp: list[list[float]] = [
                [neg_inf] * (segment_profile_count + 1)
                for _ in range(segment_candidate_count + 1)
            ]
            prev: list[list[tuple[int, int, str] | None]] = [
                [None] * (segment_profile_count + 1)
                for _ in range(segment_candidate_count + 1)
            ]
            dp[0][0] = 0.0

            for local_candidate_idx in range(segment_candidate_count + 1):
                for local_profile_idx in range(segment_profile_count + 1):
                    current = dp[local_candidate_idx][local_profile_idx]
                    if current <= neg_inf / 2:
                        continue

                    global_candidate_idx = candidate_start + local_candidate_idx
                    global_profile_idx = profile_start + local_profile_idx

                    if local_profile_idx < segment_profile_count:
                        score = current + _skip_profile_penalty(global_profile_idx)
                        if score > dp[local_candidate_idx][local_profile_idx + 1]:
                            dp[local_candidate_idx][local_profile_idx + 1] = score
                            prev[local_candidate_idx][local_profile_idx + 1] = (
                                local_candidate_idx,
                                local_profile_idx,
                                "skip_profile",
                            )

                    if local_candidate_idx < segment_candidate_count:
                        score = current + _skip_candidate_penalty(global_candidate_idx)
                        if score > dp[local_candidate_idx + 1][local_profile_idx]:
                            dp[local_candidate_idx + 1][local_profile_idx] = score
                            prev[local_candidate_idx + 1][local_profile_idx] = (
                                local_candidate_idx,
                                local_profile_idx,
                                "skip_candidate",
                            )

                    if (
                        local_candidate_idx < segment_candidate_count
                        and local_profile_idx < segment_profile_count
                    ):
                        match_score = _match_score(
                            global_candidate_idx,
                            global_profile_idx,
                        )
                        if match_score > neg_inf / 2:
                            score = current + match_score
                            if score > dp[local_candidate_idx + 1][local_profile_idx + 1]:
                                dp[local_candidate_idx + 1][local_profile_idx + 1] = score
                                prev[local_candidate_idx + 1][local_profile_idx + 1] = (
                                    local_candidate_idx,
                                    local_profile_idx,
                                    "match",
                                )

            segment_matches: dict[int, int] = {}
            segment_skipped_candidates = 0
            local_candidate_idx = segment_candidate_count
            local_profile_idx = segment_profile_count
            while local_candidate_idx > 0 or local_profile_idx > 0:
                step = prev[local_candidate_idx][local_profile_idx]
                if step is None:
                    break
                prev_local_candidate_idx, prev_local_profile_idx, action = step
                if action == "match":
                    segment_matches[profile_start + prev_local_profile_idx] = (
                        candidate_start + prev_local_candidate_idx
                    )
                elif action == "skip_candidate":
                    segment_skipped_candidates += 1
                local_candidate_idx, local_profile_idx = (
                    prev_local_candidate_idx,
                    prev_local_profile_idx,
                )

            return (
                segment_matches,
                segment_skipped_candidates,
                dp[segment_candidate_count][segment_profile_count],
            )

        raw_anchors: list[tuple[int, int, float]] = []
        for candidate_idx, candidate in enumerate(candidates):
            detected_idx = _candidate_detected_index(candidate)
            if detected_idx is None:
                continue
            strength = _anchor_strength(candidate_idx, detected_idx)
            if strength <= neg_inf / 2:
                continue
            raw_anchors.append((candidate_idx, detected_idx, strength))

        anchors: list[tuple[int, int, float]] = []
        for candidate_idx, profile_idx, strength in raw_anchors:
            if not anchors:
                anchors.append((candidate_idx, profile_idx, strength))
                continue
            last_candidate_idx, last_profile_idx, last_strength = anchors[-1]
            if candidate_idx <= last_candidate_idx:
                continue
            if profile_idx > last_profile_idx:
                anchors.append((candidate_idx, profile_idx, strength))
                continue
            if profile_idx == last_profile_idx and strength > last_strength:
                anchors[-1] = (candidate_idx, profile_idx, strength)

        matched_candidates: dict[int, int] = {}
        skipped_candidates = 0
        total_alignment_score = 0.0
        segment_count = 0
        anchor_points = [(-1, -1, 0.0), *anchors, (candidate_count, profile_count, 0.0)]
        for segment_idx in range(len(anchor_points) - 1):
            left_candidate_idx, left_profile_idx, _left_strength = anchor_points[segment_idx]
            right_candidate_idx, right_profile_idx, right_strength = anchor_points[segment_idx + 1]
            segment_matches, segment_skipped_candidates, segment_score = _run_segment_dp(
                left_candidate_idx + 1,
                right_candidate_idx,
                left_profile_idx + 1,
                right_profile_idx,
            )
            matched_candidates.update(segment_matches)
            skipped_candidates += segment_skipped_candidates
            total_alignment_score += segment_score
            segment_count += 1
            if right_candidate_idx < candidate_count and right_profile_idx < profile_count:
                matched_candidates[right_profile_idx] = right_candidate_idx
                total_alignment_score += _match_score(right_candidate_idx, right_profile_idx)

        self.log(
            f"  profile dp anchors: count={len(anchors)} segments={segment_count}"
        )

        matched_indices = sorted(matched_candidates)
        first_match_idx = matched_indices[0] if matched_indices else None
        last_match_idx = matched_indices[-1] if matched_indices else None

        aligned: list[ItemEntry] = []
        matched_count = 0
        zero_filled_count = 0
        for profile_idx, expected_name in enumerate(ordered_names):
            expected_item_id = ordered_item_ids[profile_idx] if profile_idx < len(ordered_item_ids) else None
            matched_candidate_idx = matched_candidates.get(profile_idx)
            if matched_candidate_idx is None:
                review_required = (
                    first_match_idx is not None
                    and last_match_idx is not None
                    and first_match_idx <= profile_idx <= last_match_idx
                )
                aligned.append(
                    ItemEntry(
                        name=expected_name,
                        quantity="0",
                        item_id=expected_item_id,
                        source=source,
                        index=profile_idx,
                        scan_meta={
                            "status": "zero_filled",
                            "reason": "dp_skip_profile",
                            "profile_id": profile.profile_id,
                            "profile_index": profile_idx,
                            "review_required": review_required,
                        },
                    )
                )
                zero_filled_count += 1
                continue

            candidate = candidates[matched_candidate_idx]
            template_score = _score(candidate, profile_idx)
            detected_idx = _candidate_detected_index(candidate)
            family_margin = family_margin_cache.get((matched_candidate_idx, profile_idx))
            family_key = _inventory_detail_strict_family(expected_item_id)
            detected_direct_match = (
                detected_idx == profile_idx
                and candidate.detected_score >= PROFILE_DIRECT_MATCH_THRESHOLD
            )
            strict_family_confident_direct = (
                detected_direct_match
                and family_key is not None
                and candidate.detected_score >= 0.965
                and template_score >= 0.94
                and (family_margin or 0.0) >= 0.04
            )
            direct_match = (
                strict_family_confident_direct
                if family_key is not None
                else detected_direct_match
            )
            status = "ok" if direct_match else "dp_aligned"
            if direct_match:
                reason = "direct_match"
            elif detected_direct_match and family_key is not None:
                reason = "strict_family_review"
            else:
                reason = "dp_sequence_alignment"
            aligned.append(
                ItemEntry(
                    name=expected_name,
                    quantity=candidate.count,
                    item_id=expected_item_id,
                    source=source,
                    index=profile_idx,
                    scan_meta={
                        "status": status,
                        "reason": reason,
                        "profile_id": profile.profile_id,
                        "profile_index": profile_idx,
                        "candidate_sequence": candidate.sequence,
                        "candidate_slot": candidate.slot_index,
                        "detected_item_id": candidate.detected_item_id,
                        "detected_score": round(candidate.detected_score, 4),
                        "match_score": round(template_score, 4),
                        "family_margin": round(family_margin, 4) if family_margin is not None else None,
                        "strict_family_review": bool(
                            detected_direct_match and family_key is not None and not direct_match
                        ),
                        "review_required": not direct_match,
                    },
                    detail_crop=candidate.detail_crop,
                    detail_name_crop=candidate.detail_name_crop,
                )
            )
            matched_count += 1

        self.log(
            f"  profile dp alignment: matched={matched_count} "
            f"zero_filled={zero_filled_count} "
            f"skipped_candidates={skipped_candidates} "
            f"score={total_alignment_score:.2f}"
        )
        return aligned

    def _append_profile_gap_entries(
        self,
        items: list[ItemEntry],
        seen_keys: set[str],
        profile_seen_names: set[str],
        profile,
        ordered_names: list[str],
        ordered_item_ids: list[str | None],
        source: str,
        start_idx: int,
        end_idx: int,
    ) -> None:
        if end_idx <= start_idx:
            return
        self.log(
            f"  profile gap skipped: start={start_idx} end={min(end_idx, len(ordered_names))}"
        )

    def _scroll_inventory_page(
        self,
        rect: tuple[int, int, int, int],
        slots: list[dict],
        grid_r: dict,
        drag_config: InventoryDragConfig,
        scroll_amount: int,
        grid_cols: int,
    ) -> tuple[bool, Optional[InventoryPageSnapshot], int, int]:
        before_img = self._capture()
        before = crop_region(before_img, grid_r) if before_img else None
        before_grid_hash = _img_hash(before) if before is not None else ""
        before_page = self._capture_inventory_page(
            before_img,
            slots,
            grid_hash=before_grid_hash,
            page_index=-1,
            grid_cols=grid_cols,
        ) if before_img is not None else None
        next_amount = scroll_amount
        left, top, width, height = rect
        width = max(width, 1)
        height = max(height, 1)
        start_rx = (drag_config.start_screen_x - left) / width
        start_ry = (drag_config.start_screen_y - top) / height
        attempts = [scroll_amount, int(scroll_amount * 1.05)]

        for idx, amount in enumerate(attempts, start=1):
            end_ry = start_ry + (amount / height)
            start_rx_clamped = max(0.02, min(0.98, start_rx))
            start_ry_clamped = max(0.02, min(0.98, start_ry))
            end_ry_clamped = max(0.02, min(0.98, end_ry))
            scroll_ok = drag_scroll(
                find_target_hwnd(),
                rect,
                start_rx_clamped,
                start_ry_clamped,
                end_ry_clamped,
                delay=0.35,
                duration=drag_config.duration,
            )
            self.log(
                f"  drag try {idx}: start=({start_rx_clamped:.6f},{start_ry_clamped:.6f}) "
                f"end=({start_rx_clamped:.6f},{end_ry_clamped:.6f}) "
                f"delta_px={amount} duration={drag_config.duration:.2f} ok={scroll_ok}"
            )
            if not self._wait(0.18):
                return False, None, next_amount, 0

            after_img = self._capture()
            if after_img is None:
                return scroll_ok, None, next_amount, 0
            after = crop_region(after_img, grid_r)
            after_grid_hash = _img_hash(after)
            after_page = self._capture_inventory_page(
                after_img,
                slots,
                grid_hash=after_grid_hash,
                page_index=-1,
                grid_cols=grid_cols,
            )
            before_hashes = [snap.icon_hash for snap in before_page.slots] if before_page is not None else []
            after_hashes = [snap.icon_hash for snap in after_page.slots]
            image_changed = before is None or not _images_similar(before, after)
            hash_changed = before_grid_hash != after_grid_hash
            slot_sequence_changed = before_hashes != after_hashes
            moved = image_changed or hash_changed or slot_sequence_changed
            self.log(
                f"  drag try {idx}: moved={moved} "
                f"(image_changed={image_changed}, hash_changed={hash_changed}, "
                f"slot_sequence_changed={slot_sequence_changed})"
            )
            if moved:
                overlap_rows = _count_row_overlap(before_hashes, after_hashes, grid_cols)
                self.log(f"  drag try {idx}: overlap_rows={overlap_rows}")
                next_amount = amount
                return True, after_page, next_amount, overlap_rows

        return False, None, scroll_amount, 0

    def _scan_grid(
        self,
        section: str,
        source: str,
        drag_config: InventoryDragConfig,
        scroll_amount: int,
    ) -> list[ItemEntry]:
        r_sec   = self.r[section]
        slots   = r_sec["grid_slots"]
        name_r  = r_sec["name_region"]
        count_r = r_sec["count_region"]
        grid_r  = _grid_region(slots)

        rect = self._rect()
        if not rect:
            self.log("window not found")
            return []

        items:       list[ItemEntry] = []
        seen_keys:   set[str]        = set()
        seen_hashes: list[str]       = []
        detail_candidates: list[InventoryDetailCandidate] = []
        detail_candidate_seq = 0
        icon_cache = self._inventory_icon_cache.setdefault(source, {})
        failed_hashes = self._inventory_failed_hashes.setdefault(source, set())
        active_profile = get_inventory_profile(self._forced_inventory_profile_id)
        if active_profile is not None and active_profile.source != source:
            active_profile = None
        profile_seen_names: set[str] = set()
        icon = "아이템" if source == "item" else "장비"
        grid_cols = int(r_sec.get("grid_cols", 0))
        current_scroll_amount = scroll_amount
        profile_ordered_names: list[str] = list(active_profile.ordered_names) if active_profile is not None else []
        profile_ordered_item_ids: list[str | None] = list(inventory_profile_ordered_item_ids(active_profile)) if active_profile is not None else []
        profile_index_by_name: dict[str, int] = {name: idx for idx, name in enumerate(profile_ordered_names)}
        profile_index_by_item_id: dict[str, int] = {
            item_id: idx for idx, item_id in enumerate(profile_ordered_item_ids) if item_id
        }
        profile_cursor = 0
        profile_max_unique_items = (
            INVENTORY_PROFILE_MAX_UNIQUE_ITEMS.get(active_profile.profile_id)
            if active_profile is not None
            else None
        )
        profile_max_detail_candidates = (
            INVENTORY_PROFILE_MAX_DETAIL_CANDIDATES.get(active_profile.profile_id)
            if active_profile is not None
            else None
        )
        def _unique_scanned_item_count() -> int:
            return len(
                {
                    entry.item_id or entry.name
                    for entry in items
                    if entry.item_id or entry.name
                }
            )

        self.log(f"{icon} 그리드 스캔 시작 (슬롯 {len(slots)}개)")
        if active_profile is not None:
            expected_count = len(active_profile.expected_item_ids) or len(active_profile.ordered_names)
            limit_suffix = (
                f", max_unique={profile_max_unique_items}"
                if profile_max_unique_items is not None
                else ""
            )
            self.log(
                f"  inventory profile forced: {active_profile.profile_id} "
                f"({expected_count} expected{limit_suffix})"
            )

        def _profile_found_count() -> int:
            if active_profile is None:
                return 0
            if active_profile.expected_item_ids:
                return len(
                    {
                        entry.item_id
                        for entry in items
                        if entry.item_id in active_profile.expected_item_ids
                    }
                )
            return len(
                {
                    entry.name
                    for entry in items
                    if entry.name in set(active_profile.ordered_names)
                }
            )

        for scroll_i in range(MAX_SCROLLS):
            if self._stop_requested():
                break


            img = self._capture()
            if img is None:
                break

            grid_crop = crop_region(img, grid_r)
            cur_hash  = _img_hash(grid_crop)
            page = self._capture_inventory_page(
                img,
                slots,
                grid_hash=cur_hash,
                page_index=scroll_i,
                grid_cols=grid_cols,
            )

            if cur_hash in seen_hashes:
                self.log(f"  동일 화면 반복 감지 -> 스캔 종료 ({len(items)}개)")
                break
            seen_hashes.append(cur_hash)
            if len(seen_hashes) > 10:
                seen_hashes.pop(0)

            new_this = 0
            candidates_before_page = len(detail_candidates)
            page_item_ids: list[str] = []
            page_raw_names: list[str] = []
            profile_limit_reached = False
            candidate_limit_reached = False
            for slot_idx, (slot, slot_snap) in enumerate(zip(slots, page.slots)):
                if self._stop_requested():
                    break

                icon_crop = crop_region(img, _slot_icon_region(slot))
                icon_template_item_id, icon_template_score = self._match_inventory_icon(icon_crop, source)
                icon_template_matched = icon_template_item_id is not None
                detail_template_item_id: str | None = None
                detail_template_score = 0.0
                assigned_profile_idx: int | None = None
                matched_profile_name: str | None = None

                verified = self._verify_inventory_slot(
                    rect,
                    slot,
                    name_r,
                    count_r,
                    source,
                    profile_id=active_profile.profile_id if active_profile is not None else None,
                )
                if not verified:
                    continue
                name = verified.name
                count = verified.count
                if verified.item_id:
                    detail_template_item_id = verified.item_id
                    detail_template_score = verified.match_score
                if active_profile is not None and verified.detail_crop is not None:
                    detail_candidate_seq += 1
                    detail_candidates.append(
                        InventoryDetailCandidate(
                            sequence=detail_candidate_seq,
                            slot_index=slot_idx,
                            count=count,
                            detail_crop=verified.detail_crop,
                            detail_name_crop=verified.detail_name_crop,
                            detected_item_id=detail_template_item_id,
                            detected_score=detail_template_score,
                        )
                    )
                    if (
                        profile_max_detail_candidates is not None
                        and len(detail_candidates) >= profile_max_detail_candidates
                    ):
                        candidate_limit_reached = True
                item_id = detail_template_item_id or icon_template_item_id
                if not item_id:
                    self.log(f"  template unresolved skip: slot={slot_idx}")
                    if candidate_limit_reached:
                        self.log(
                            f"  profile detail candidate limit reached: "
                            f"{active_profile.profile_id} "
                            f"({len(detail_candidates)}/{profile_max_detail_candidates})"
                        )
                        profile_limit_reached = True
                        break
                    continue

                if active_profile is not None:
                    matched_profile_name = inventory_item_display_name(item_id)
                    if not matched_profile_name and item_id in profile_index_by_name:
                        matched_profile_name = item_id
                    assigned_profile_idx = profile_index_by_item_id.get(item_id)
                    if assigned_profile_idx is None and matched_profile_name:
                        assigned_profile_idx = profile_index_by_name.get(matched_profile_name)

                    if assigned_profile_idx is None:
                        self.log(
                            f"  explicit template outside profile skip: "
                            f"slot={slot_idx} item_id={item_id}"
                        )
                        continue

                    if assigned_profile_idx > profile_cursor:
                        self.log(
                            f"  profile cursor jump: {profile_cursor} -> {assigned_profile_idx}"
                        )
                    if assigned_profile_idx < len(profile_ordered_names):
                        name = profile_ordered_names[assigned_profile_idx]
                    else:
                        name = matched_profile_name
                    if (
                        assigned_profile_idx < len(profile_ordered_item_ids)
                        and profile_ordered_item_ids[assigned_profile_idx]
                    ):
                        item_id = profile_ordered_item_ids[assigned_profile_idx]

                if not name and item_id:
                    name = inventory_item_display_name(item_id) or item_id
                if not name:
                    continue

                icon_cache[slot_snap.icon_hash] = (name, count, item_id)
                if detail_template_item_id is not None:
                    detect_source = f"detail_image_template+detail({detail_template_score:.2f})"
                elif icon_template_matched:
                    detect_source = f"icon_template+detail({icon_template_score:.2f})"
                else:
                    detect_source = "detail_template"

                canonical_name = inventory_item_display_name(item_id)
                if canonical_name:
                    name = canonical_name
                elif active_profile is not None:
                    profile_name = resolve_inventory_profile_name(active_profile, name, profile_seen_names)
                    if profile_name:
                        name = profile_name
                        detect_source = f"{detect_source}+profile"
                    else:
                        duplicate_name = find_inventory_profile_duplicate(active_profile, name, profile_seen_names)
                        if duplicate_name:
                            self.log(
                                f"  duplicate profile match skipped: raw={name} "
                                f"-> {duplicate_name}"
                            )
                            continue
                if item_id:
                    page_item_ids.append(item_id)
                if name:
                    page_raw_names.append(name)

                entry = ItemEntry(
                    name=name,
                    quantity=count,
                    item_id=item_id,
                    source=source,
                    index=len(items),
                    scan_meta={
                        "status": "ok",
                        "reason": "direct_match",
                        "profile_id": active_profile.profile_id if active_profile is not None else None,
                        "profile_index": assigned_profile_idx,
                        "match_score": round(max(detail_template_score, icon_template_score), 4),
                        "review_required": False,
                    },
                    detail_crop=verified.detail_crop,
                    detail_name_crop=verified.detail_name_crop,
                )
                k = entry.key()
                if k not in seen_keys:
                    seen_keys.add(k)
                    items.append(entry)
                    if entry.name:
                        profile_seen_names.add(entry.name)
                        if active_profile is not None:
                            mapped_idx = profile_index_by_name.get(entry.name)
                            if mapped_idx is not None:
                                profile_cursor = max(profile_cursor, mapped_idx + 1)
                    new_this += 1
                    self.log(f"  {icon} [{len(items):>3}] {name}  x{count} ({detect_source})")
                    if (
                        profile_max_unique_items is not None
                        and _unique_scanned_item_count() >= profile_max_unique_items
                    ):
                        self.log(
                            f"  profile max unique items reached: "
                            f"{active_profile.profile_id} "
                            f"({_unique_scanned_item_count()}/{profile_max_unique_items})"
                        )
                        profile_limit_reached = True
                        break
                if candidate_limit_reached:
                    self.log(
                        f"  profile detail candidate limit reached: "
                        f"{active_profile.profile_id} "
                        f"({len(detail_candidates)}/{profile_max_detail_candidates})"
                    )
                    profile_limit_reached = True
                    break

            if active_profile is None:
                active_profile = infer_inventory_scan_profile(source, page_item_ids, page_raw_names)
                if active_profile is not None:
                    expected_count = len(active_profile.expected_item_ids) or len(active_profile.ordered_names)
                    profile_max_unique_items = INVENTORY_PROFILE_MAX_UNIQUE_ITEMS.get(
                        active_profile.profile_id
                    )
                    profile_max_detail_candidates = INVENTORY_PROFILE_MAX_DETAIL_CANDIDATES.get(
                        active_profile.profile_id
                    )
                    profile_ordered_names = list(active_profile.ordered_names)
                    profile_ordered_item_ids = list(inventory_profile_ordered_item_ids(active_profile))
                    profile_index_by_name = {name: idx for idx, name in enumerate(profile_ordered_names)}
                    profile_index_by_item_id = {
                        item_id: idx for idx, item_id in enumerate(profile_ordered_item_ids) if item_id
                    }
                    profile_cursor = 0
                    for entry in items:
                        mapped_idx = None
                        if entry.item_id:
                            mapped_idx = profile_index_by_item_id.get(entry.item_id)
                        if mapped_idx is None and entry.name:
                            mapped_idx = profile_index_by_name.get(entry.name)
                        if mapped_idx is not None:
                            profile_cursor = max(profile_cursor, mapped_idx + 1)
                    rebuilt_seen_keys: set[str] = set()
                    rebuilt_profile_names: set[str] = set()
                    for entry in items:
                        if not entry.item_id:
                            normalized_name = resolve_inventory_profile_name(
                                active_profile,
                                entry.name,
                                rebuilt_profile_names,
                            )
                            if normalized_name:
                                entry.name = normalized_name
                        if entry.name:
                            rebuilt_profile_names.add(entry.name)
                        rebuilt_seen_keys.add(entry.key())
                    seen_keys = rebuilt_seen_keys
                    profile_seen_names = rebuilt_profile_names
                    limit_suffix = (
                        f", max_unique={profile_max_unique_items}"
                        if profile_max_unique_items is not None
                        else ""
                    )
                    self.log(
                        f"  inventory profile detected: {active_profile.profile_id} "
                        f"({expected_count} expected{limit_suffix})"
                    )
                    if (
                        profile_max_unique_items is not None
                        and _unique_scanned_item_count() >= profile_max_unique_items
                    ):
                        self.log(
                            f"  profile max unique items reached: "
                            f"{active_profile.profile_id} "
                            f"({_unique_scanned_item_count()}/{profile_max_unique_items})"
                        )
                        profile_limit_reached = True

            new_candidates_this = len(detail_candidates) - candidates_before_page
            candidate_suffix = (
                f", candidates +{new_candidates_this}/{len(detail_candidates)}"
                if active_profile is not None
                else ""
            )
            self.log(
                f"  scroll {scroll_i+1}: new {new_this} / total {len(items)}"
                f"{candidate_suffix}"
            )

            if profile_limit_reached:
                break

            if active_profile is not None:
                expected_count = len(active_profile.expected_item_ids) or len(active_profile.ordered_names)
                found_item_ids = {entry.item_id for entry in items if entry.item_id}
                found_names = {entry.name for entry in items if entry.name}
                if is_inventory_profile_complete(active_profile, found_item_ids, found_names):
                    self.log(
                        f"  profile complete: {active_profile.profile_id} "
                        f"({_profile_found_count()}/{expected_count} matched)"
                    )
                    break
                if is_inventory_profile_terminal_seen(active_profile, found_item_ids, found_names):
                    self.log(
                        f"  profile terminal reached: {active_profile.profile_id} "
                        f"({_profile_found_count()}/{expected_count} matched, "
                        f"candidates={len(detail_candidates)})"
                    )
                    break

            moved, after_page, current_scroll_amount, _overlap_rows = self._scroll_inventory_page(
                rect,
                slots,
                grid_r,
                drag_config,
                current_scroll_amount,
                grid_cols,
            )
            self.log(f"  next drag delta_px={current_scroll_amount}")
            if after_page is None:
                break
            repeated_last_row = (
                page.last_row_hashes
                and after_page.last_row_hashes
                and page.last_row_hashes == after_page.last_row_hashes
            )
            if not moved:
                self.log(f"  scroll finished: total {len(items)}")
                break
            if repeated_last_row:
                self.log(f"  repeated last row after scroll: total {len(items)}")
                break
        if active_profile is not None:
            expected_count = len(active_profile.expected_item_ids) or len(active_profile.ordered_names)
            if detail_candidates:
                self.log(
                    f"  profile dp alignment start: "
                    f"{active_profile.profile_id} "
                    f"({len(items)}/{expected_count}, candidates={len(detail_candidates)})"
                )
                items = self._recover_profile_gaps_from_candidates(
                    items,
                    detail_candidates,
                    active_profile,
                    source,
                )
            items = self._fill_missing_profile_entries(items, active_profile, source)
        return items

    def scan_items(
        self,
        inventory_profile_id: str | list[str] | tuple[str, ...] | None = None,
    ) -> list[ItemEntry]:
        self.log("[scan] item scan start")
        prev_forced_profile_id = self._forced_inventory_profile_id
        try:
            if not self._open_menu():
                return []
            item_profiles = self._item_scan_profiles(inventory_profile_id)
            all_items: list[ItemEntry] = []
            sort_rule_checked = False

            for index, profile_id in enumerate(item_profiles, start=1):
                profile_label = profile_id or "all"
                self.log(f"[scan] item pass {index}/{len(item_profiles)} profile={profile_label}")
                self._forced_inventory_profile_id = profile_id
                if not self._go_to("item_entry_button", "items"):
                    return all_items
                if not self._wait(0.5):
                    return all_items
                if not self._prepare_item_inventory(profile_id, ensure_sort_rule=not sort_rule_checked):
                    return all_items
                sort_rule_checked = True
                self._reset_inventory_scan_state("item")
                result = self._scan_grid("item", "item", ITEM_INVENTORY_DRAG, ITEM_INVENTORY_DRAG.delta_px)
                all_items.extend(result)
                self.log(f"[scan] item pass done: {len(result)} entries")
                if index < len(item_profiles):
                    if not self._exit_inventory_to_menu():
                        return all_items

            self.log(f"[scan] item scan done: {len(all_items)} entries")
            return all_items
        except Exception as e:
            self.log(f"item scan error: {e}")
            return []
        finally:
            self._forced_inventory_profile_id = prev_forced_profile_id
            self._return_inventory_to_lobby()

    def scan_equipment(self) -> list[ItemEntry]:
        self.log("[scan] equipment scan start")
        prev_forced_profile_id = self._forced_inventory_profile_id
        try:
            self._forced_inventory_profile_id = "equipment"
            if not self._open_menu():
                return []
            if not self._go_to("equipment_entry_button", "equipment"): 
                return []
            if not self._wait(0.5):
                return []
            if not self._prepare_equipment_inventory():
                return []
            self._reset_inventory_scan_state("equipment")
            result = self._scan_grid(
                "equipment",
                "equipment",
                EQUIPMENT_INVENTORY_DRAG,
                EQUIPMENT_INVENTORY_DRAG.delta_px,
            )
            self.log(f"[scan] equipment scan done: {len(result)} entries")
            return result
        except Exception as e:
            self.log(f"equipment scan error: {e}")
            return []
        finally:
            self._forced_inventory_profile_id = prev_forced_profile_id
            self._return_inventory_to_lobby()




    def scan_students(self) -> list[StudentEntry]:
        if self._fast_student_ids:
            return self.scan_students_fast()
        return self.scan_students_v5()

    def scan_current_student(self) -> list[StudentEntry]:
        self._info("[scan] current student scan start")
        self._emit_progress_state(current=0, total=1, note="현재 학생")
        results: list[StudentEntry] = []

        try:
            sid = self.identify_student(0)
            if sid is None:
                self._warn("[현재 학생] 식별 실패")
                return []

            if sid in self._maxed_ids:
                entry = self._make_skipped_entry(sid)
                results.append(entry)
                self._emit_progress_state(current=1, total=1, note="현재 학생")
                self._info(f"  스킵 {entry.label()} (저장데이터 기준 만렙)")
                return results

            ctx = ScanCtx(idx=1, student_id=sid)
            entry = self.begin_student_scan(sid)

            self.read_skills(entry)
            if self._stop_requested():
                return results
            self.read_weapon(entry)
            if self._stop_requested():
                return results
            self.read_equipment(entry)
            if self._stop_requested():
                return results
            self.read_level(entry)
            if self._stop_requested():
                return results
            self.read_student_star(entry)
            if self._stop_requested():
                return results
            self.read_stats(entry)
            if self._stop_requested():
                return results

            commit_result = self.finalize_student_entry(entry, ctx, partial_ok=True)
            added = self.commit_student_entry(commit_result, results, 0)
            if added:
                self._emit_progress_state(current=1, total=1, note="현재 학생")
                self._log_student(entry, 0)
                if self._asv:
                    self._asv.on_student_committed(entry)
        except Exception as e:
            _log.exception(f"현재 학생 스캔 중 예외 발생: {e}")
            self._error(f"현재 학생 스캔 오류: {e}")
            if self._asv:
                partial = ScanResult(students=list(results))
                self._asv.emergency_save(partial, {})
        finally:
            self._restore_basic_tab()
            if self._asv:
                self._asv.log_stats()

        summary = f"current student scan done: total {len(results)}"
        self._emit_progress_state(current=len(results), total=1, note="현재 학생")
        _log.info(summary)
        self._info(f"[scan] {summary}")
        return results

    def scan_students_v5(self) -> list[StudentEntry]:
        log_section(_log, "학생 스캔 시작 (V6)")
        self._info("[scan] student scan start (v6)")
        results:       list[StudentEntry] = []
        skipped_count  = 0
        scanned_count  = 0
        self._emit_progress_state(
            current=0,
            total=self._student_total_hint,
            note="학생 스캔",
        )

        try:
            if not self.enter_student_menu():
                return []
            if not self.enter_first_student():
                return []

            seen_ids:        set[str]       = set()
            consecutive_dup: int            = 0
            prev_id:         Optional[str]  = None

            for idx in range(500):
                if self._stop_requested():
                    _log.info("중지 요청 감지로 학생 스캔 루프 종료")
                    break


                _log.debug(f"[{idx+1}] 학생 식별 시작")
                sid = self.identify_student(idx)
                if sid is None:
                    self._warn(f"[{idx+1}] 식별 실패로 스캔 종료")
                    break


                if sid == prev_id:
                    consecutive_dup += 1
                    _log.info(
                        f"[{idx+1}] 동일 학생 연속 감지: {sid} "
                        f"({consecutive_dup}/{MAX_CONSECUTIVE_DUP})"
                    )
                    if consecutive_dup >= MAX_CONSECUTIVE_DUP:
                        _log.info("연속 동일 학생 감지, 마지막 학생으로 판단하고 종료")
                        self._info("  종료: 마지막 학생으로 판단")
                        break
                    self._restore_basic_tab()
                    self.go_next_student()
                    continue

                consecutive_dup = 0
                prev_id = sid

                if sid in seen_ids:
                    _log.info(f"[{idx+1}] 이미 스캔한 학생 {sid} -> 종료")
                    self._info(f"  종료: 이미 스캔한 학생 {sid}")
                    break
                seen_ids.add(sid)


                if sid in self._maxed_ids:
                    entry = self._make_skipped_entry(sid)
                    results.append(entry)
                    skipped_count += 1
                    self._emit_progress_state(
                        current=len(results),
                        total=self._student_total_hint,
                        note="학생 스캔",
                    )
                    _log.info(f"[{idx+1:>3}] {entry.label()} -> 저장데이터 기준 만렙 스킵")
                    self._info(f"  스킵 [{idx+1:>3}] {entry.label()} (저장데이터 기준 만렙)")
                    self._restore_basic_tab()
                    self.go_next_student()
                    continue


                _log.info(f"[{idx+1:>3}] 학생 스캔 시작: {sid}")
                ctx = ScanCtx(idx=idx+1, student_id=sid)

                # Create a temporary entry, then fill it step by step.
                entry = self.begin_student_scan(sid)

                # Keep going through the pipeline even if a step is missing.
                # Each step writes into the same TEMP entry.
                self.read_skills(entry)
                if self._stop_requested():
                    break
                self.read_weapon(entry)
                if self._stop_requested():
                    break
                self.read_equipment(entry)
                if self._stop_requested():
                    break
                self.read_level(entry)
                if self._stop_requested():
                    break
                self.read_student_star(entry)
                if self._stop_requested():
                    break
                self.read_stats(entry)
                if self._stop_requested():
                    break

                # Validate TEMP entry and decide COMMITTED/PARTIAL
                commit_result = self.finalize_student_entry(
                    entry, ctx, partial_ok=True
                )

                # Add the validated result unless it failed strict checks.
                added = self.commit_student_entry(commit_result, results, idx)
                if added:
                    scanned_count += 1
                    self._emit_progress_state(
                        current=len(results),
                        total=self._student_total_hint,
                        note="학생 스캔",
                    )
                    self._log_student(entry, len(results) - 1)

                    if self._asv:
                        self._asv.on_student_committed(entry)

                self._restore_basic_tab()
                self.go_next_student()

        except Exception as e:
            _log.exception(f"학생 스캔 중 예외 발생: {e}")
            self._error(f"학생 스캔 오류: {e}")

            if self._asv:
                partial = ScanResult(students=list(results))
                self._asv.emergency_save(partial, {})
        finally:
            self._return_lobby()

            if self._asv:
                self._asv.log_stats()

        summary = (
            f"학생 스캔 완료: 총 {len(results)}명"
            f"(스캔:{scanned_count} / 스킵:{skipped_count})"
        )
        self._emit_progress_state(
            current=len(results),
            total=max(self._student_total_hint or 0, len(results)) or None,
            note="학생 스캔",
        )
        _log.info(summary)
        self._info(f"[scan] {summary}")
        return results

    def scan_students_fast(self) -> list[StudentEntry]:
        ordered_ids = list(self._fast_student_ids)
        if not ordered_ids:
            return self.scan_students_v5()

        log_section(_log, "학생 패스트 스캔 시작")
        self._info("[scan] student fast scan start")
        self._info(f"  패스트 기준 목록 {len(ordered_ids)}명")
        results: list[StudentEntry] = []
        skipped_count = 0
        scanned_count = 0
        self._emit_progress_state(current=0, total=len(ordered_ids), note="학생 패스트 스캔")

        try:
            if not self.enter_student_menu():
                return []
            if not self.enter_first_student_fast():
                self._warn("첫 학생 상세 화면 진입 확인 실패로 패스트 스캔을 중단합니다.")
                return []

            current_digest = self._current_student_digest(refresh=False)
            if current_digest is None:
                self._warn("첫 학생 카드 해시를 만들 수 없어 패스트 스캔을 중단합니다.")
                return []

            for idx, sid in enumerate(ordered_ids):
                if self._stop_requested():
                    _log.info("중지 요청 감지로 학생 패스트 스캔 루프 종료")
                    break

                self._info(f"  패스트 [{idx+1}] {student_meta.display_name(sid)}")

                if sid in self._maxed_ids:
                    entry = self._make_skipped_entry(sid)
                    results.append(entry)
                    skipped_count += 1
                    self._emit_progress_state(current=len(results), total=len(ordered_ids), note="학생 패스트 스캔")
                    _log.info(f"[{idx+1:>3}] {entry.label()} -> 패스트 모드 저장데이터 기준 만렙 스킵")
                else:
                    _log.info(f"[{idx+1:>3}] 학생 패스트 스캔 시작: {sid}")
                    ctx = ScanCtx(idx=idx + 1, student_id=sid)
                    entry = self.begin_student_scan(sid)

                    self.read_skills(entry)
                    if self._stop_requested():
                        break
                    self.read_weapon(entry)
                    if self._stop_requested():
                        break
                    self.read_equipment(entry)
                    if self._stop_requested():
                        break
                    self.read_level(entry)
                    if self._stop_requested():
                        break
                    self.read_student_star(entry)
                    if self._stop_requested():
                        break
                    self.read_stats(entry)
                    if self._stop_requested():
                        break

                    commit_result = self.finalize_student_entry(entry, ctx, partial_ok=True)
                    added = self.commit_student_entry(commit_result, results, idx)
                    if added:
                        scanned_count += 1
                        self._emit_progress_state(current=len(results), total=len(ordered_ids), note="학생 패스트 스캔")
                        self._log_student(entry, len(results) - 1)
                        if self._asv:
                            self._asv.on_student_committed(entry)

                if idx >= len(ordered_ids) - 1:
                    continue

                self._restore_basic_tab()
                next_digest = self.go_next_student_fast(current_digest)
                if next_digest is None:
                    self._warn(
                        f"[{idx+1}] 다음 학생 이동 확인에 실패했습니다. "
                        "이름순 정렬이 어긋났을 수 있으니 롤백 후 일반 스캔을 권장합니다."
                    )
                    break
                current_digest = next_digest

        except Exception as e:
            _log.exception(f"학생 패스트 스캔 중 예외 발생: {e}")
            self._error(f"학생 패스트 스캔 오류: {e}")
            if self._asv:
                partial = ScanResult(students=list(results))
                self._asv.emergency_save(partial, {})
        finally:
            self._return_lobby()
            if self._asv:
                self._asv.log_stats()

        summary = (
            f"학생 패스트 스캔 완료: 총 {len(results)}명"
            f"(스캔:{scanned_count} / 스킵:{skipped_count})"
        )
        self._emit_progress_state(current=len(results), total=len(ordered_ids), note="학생 패스트 스캔")
        _log.info(summary)
        self._info(f"[scan] {summary}")
        return results



    def _make_skipped_entry(self, student_id: str) -> StudentEntry:
        if student_id in self._maxed_saved_data:
            entry = _dict_to_student_entry(self._maxed_saved_data[student_id])
        else:
            entry = StudentEntry(
                student_id=student_id,
                display_name=student_meta.display_name(student_id),
                skipped=True,
            )

        return entry


    # Student pipeline steps




    def enter_student_menu(self) -> bool:
        self.log("  학생 메뉴 진입...")
        btn = self.r["lobby"].get("student_menu_button")
        if not btn:
            self.log("  missing student_menu_button")
            return False

        attempts = [
            btn,

        ]
        for attempt, region in enumerate(attempts, start=1):
            clicked = self._click_r(region, f"student_menu_{attempt}")
            _log.info(f"[student_menu] attempt={attempt} clicked={clicked}")
            if not clicked:
                continue
            if self._wait_for_student_menu_state(
                True,
                timeout=LOBBY_EXIT_WAIT,
                initial_wait=MENU_CLICK_SETTLE_WAIT,
            ):
                return self._wait(STUDENT_MENU_READY_SETTLE_WAIT)
            if attempt < len(attempts):
                self.log(f"  학생 메뉴 재시도... ({attempt+1}/{len(attempts)})")
        return False

    def enter_first_student(self) -> bool:
        self.log("  첫 학생 선택...")
        btn = self.r["student_menu"].get("first_student_button")
        if not btn:
            self.log("  missing first_student_button")
            return False

        if not self._wait(FIRST_STUDENT_PRECLICK_WAIT):
            return False

        clicked = self._click_r(btn, "first_student")
        _log.info(f"[first_student] clicked={clicked}")
        if not clicked:
            return False
        return self._wait_for_student_detail(initial_wait=DETAIL_CLICK_SETTLE_WAIT)

    def enter_first_student_fast(self) -> bool:
        self.log("  첫 학생 선택(패스트)...")
        btn = self.r["student_menu"].get("first_student_button")
        if not btn:
            self.log("  missing first_student_button")
            return False
        if not self._wait(FIRST_STUDENT_PRECLICK_WAIT):
            return False
        clicked = self._click_r(btn, "first_student_fast")
        _log.info(f"[first_student_fast] clicked={clicked}")
        if not clicked:
            return False
        return self._wait_for_student_detail_fast(initial_wait=DETAIL_CLICK_SETTLE_WAIT)

    def go_next_student(self) -> bool:
        btn = self.r["student"].get("next_student_button")
        if not btn:
            self.log("  missing next_student_button")
            return False
        self._invalidate_student_basic_capture()
        self._click_r(btn, "next_student")
        return self._wait(DELAY_NEXT)

    def go_next_student_fast(self, previous_digest: str) -> Optional[str]:
        btn = self.r["student"].get("next_student_button")
        if not btn:
            self.log("  missing next_student_button")
            return None
        self._invalidate_student_basic_capture()
        if not self._click_r(btn, "next_student_fast"):
            return None
        return self._wait_for_student_change(previous_digest)



    def identify_student(self, idx: int = 0) -> Optional[str]:
        """Identify the current student from the portrait texture region."""
        sr = self.r["student"]
        texture_r = sr.get("student_texture_region")
        ctx = ScanCtx(idx=idx + 1, step="identify")

        if not texture_r:
            _log.warning(f"{ctx} student_texture_region missing -> cannot identify")
            return None

        def _try() -> Optional[str]:
            img = self._get_student_basic_capture(refresh=True)
            if img is None:
                return None
            crop = crop_region(img, texture_r)
            sid, score = match_student_texture(crop)
            if sid is not None:
                _log.info(
                    f"{ctx} 식별 성공: {student_meta.display_name(sid)} "
                    f"(score={score:.3f})"
                )
                self._info(
                    f"  인식 [{idx+1}] {student_meta.display_name(sid)} (score={score:.3f})"
                )
                return sid

            _log.debug(f"{ctx} 텍스처 식별 실패 (score={score:.3f})")
            dump_roi(crop, "identify_fail", score=score, reason="below_thresh")
            if self._asv:
                self._asv.on_step_error("identify")
            self._warn(f"[{idx+1}] 텍스처 식별 실패 (score={score:.3f})")
            return None

        sid = self._retry(_try, max_attempts=RETRY_IDENTIFY, delay=0.6, label="식별")
        if sid is not None or idx != 0:
            return sid

        _log.warning(f"{ctx} 첫 학생 식별 실패 -> 진입 복구 시도")
        self._warn(f"[{idx+1}] 첫 학생 진입 복구 시도")
        if not self._recover_first_student_entry():
            return None
        self._restore_basic_tab()
        self._invalidate_student_basic_capture()
        return self._retry(_try, max_attempts=RETRY_IDENTIFY, delay=0.6, label="식별 복구")



    def read_skills(self, entry: StudentEntry) -> None:
        """Read the skill panel from a single capture and fill skill fields."""
        ctx = ScanCtx(student_id=entry.student_id, step="read_skills")
        saved = self._saved_student(entry.student_id)
        if self._skills_maxed_from_saved_data(saved):
            self._apply_saved_fields(
                entry,
                saved,
                ("ex_skill", "skill1", "skill2", "skill3"),
                "saved_skill_max",
            )
            self.log("  저장데이터에서 스킬 5/10/10/10 확인 -> 스킬 스캔 생략")
            return

        self._active_student_panel = "skill"
        img = self._click_student_region_and_wait(
            "skill_menu_button",
            "skill_menu_button",
            self._is_student_additional_menu_capture,
            timeout=ADDITIONAL_PANEL_READY_WAIT,
        )
        if img is None:
            _log.warning(f"{ctx} 스킬 메뉴 진입 실패")
            self._esc()
            return

        sr      = self.r["student"]
        check_r = sr.get("skill_all_view_check_region")

        if check_r:
            if read_skill_check(crop_region(img, check_r)) == CheckFlag.FALSE:
                self.log("  스킬 일괄성장 체크 클릭")
                self._click_r(check_r, "skill_check")
                if not self._wait(0.3):
                    self._esc()
                    return
                img = self._capture()
                if img is None:
                    _log.warning(f"{ctx} 체크 재캡처 실패")
                    self._esc()
                    return

        for field_name, region_key, tmpl_key in [
            ("ex_skill", "EX_skill", "EX_Skill"),
            ("skill1",   "Skill_1",  "Skill1"),
            ("skill2",   "Skill_2",  "Skill2"),
            ("skill3",   "Skill_3",  "Skill3"),
        ]:
            region = sr.get(region_key)
            if region is None:
                _log.warning(f"{ctx.with_step(field_name)} region missing -> skip")
                entry.set_meta(field_name, FieldMeta.region_missing(region_key))
                continue
            crop = crop_region(img, region)
            raw  = read_skill(crop, tmpl_key)
            try:
                setattr(entry, field_name, int(raw))
                entry.set_meta(field_name, FieldMeta.ok(FieldSource.TEMPLATE))
            except (TypeError, ValueError):
                _log.debug(f"{ctx.with_step(field_name)} 값 변환 실패 (raw={raw!r})")
                dump_roi(crop, f"skill_{field_name}", reason="convert_fail")
                setattr(entry, field_name, None)
                entry.set_meta(field_name,
                               FieldMeta.failed(FieldSource.TEMPLATE,
                                                note=f"raw={raw!r}"))
                if self._asv:
                    self._asv.on_step_error("read_skills", entry.student_id or "")

        self.log(
            f"  스킬: EX={entry.ex_skill} "
            f"S1={entry.skill1} S2={entry.skill2} S3={entry.skill3}"
        )
        self._close_student_panel(
            capture_name="skill_close_button",
            region_key="skillmenu_quit_button",
            settle_reason="close_skill_menu",
        )



    def read_weapon(self, entry: StudentEntry) -> None:
        """Read weapon state and weapon panel information."""



        ctx      = ScanCtx(student_id=entry.student_id, step="read_weapon")
        saved   = self._saved_student(entry.student_id)
        if self._weapon_maxed_from_saved_data(saved):
            self._apply_saved_fields(
                entry,
                saved,
                ("weapon_state", "weapon_star", "weapon_level"),
                "saved_weapon_max",
            )
            self.log("  저장데이터에서 전용무기 4성 Lv.60 확인 -> 무기 스캔 생략")
            return

        sr       = self.r["student"]
        weapon_r = sr.get("weapon_detect_flag_region") or sr.get("weapon_unlocked_flag")
        if not weapon_r:

            entry.weapon_state = WeaponState.NO_WEAPON_SYSTEM
            entry.set_meta("weapon_state", FieldMeta.region_missing("weapon_detect_flag_region"))
            return

        img = self._get_student_basic_capture()
        if img is None:
            entry.weapon_state = WeaponState.NO_WEAPON_SYSTEM
            entry.set_meta("weapon_state", FieldMeta.failed(FieldSource.TEMPLATE, "capture_fail"))
            return

        state, score = detect_weapon_state(crop_region(img, weapon_r))
        entry.weapon_state = state

        if score < 0.60:
            entry.set_meta("weapon_state",
                           FieldMeta.uncertain(FieldSource.TEMPLATE, score=score,
                                               note=state.value))
            _log.warning(f"{ctx} 무기 상태 불확실 (score={score:.3f}, {state.name})")
        else:
            entry.set_meta("weapon_state",
                           FieldMeta.ok(FieldSource.TEMPLATE, score=score))
        self.log(f"  무기 상태: {state.name} (score={score:.3f})")

        if state == WeaponState.NO_WEAPON_SYSTEM:
            return

        if state == WeaponState.WEAPON_UNLOCKED_NOT_EQUIPPED:
            entry.weapon_star  = None
            entry.weapon_level = None
            entry.set_meta("weapon_star",  FieldMeta.skipped("not_equipped"))
            entry.set_meta("weapon_level", FieldMeta.skipped("not_equipped"))
            self.log("  무기 미장착 -> 레벨/성급 스킵")
            return


        self._active_student_panel = "weapon"
        img = self._click_student_region_and_wait(
            "weapon_info_menu_button",
            "weapon_info_menu",
            self._is_student_additional_menu_capture,
            timeout=ADDITIONAL_PANEL_READY_WAIT,
        )
        if img is None:
            self.log("  missing weapon_info_menu_button")
            self._esc()
            return

        star_r = sr.get("weapon_star_region")
        if star_r:
            from core.matcher import read_weapon_star_v5_result
            rs = read_weapon_star_v5_result(crop_region(img, star_r))
            entry.weapon_star = rs.value
            entry.set_meta("weapon_star",
                           FieldMeta.ok(FieldSource.TEMPLATE, score=rs.score)
                           if not rs.uncertain
                           else FieldMeta.uncertain(FieldSource.TEMPLATE,
                                                    score=rs.score))
        else:
            entry.set_meta("weapon_star", FieldMeta.region_missing("weapon_star_region"))

        d1 = sr.get("weapon_level_digit_1") or sr.get("weapon_level_digit1")
        d2 = sr.get("weapon_level_digit_2") or sr.get("weapon_level_digit2")
        if d1 and d2:
            entry.weapon_level = read_weapon_level(img, d1, d2)
            for _ in range(2):
                if entry.weapon_level is not None:
                    break
                if not self._wait(WEAPON_CAPTURE_RETRY_WAIT):
                    break
                retry_img = self._capture()
                if retry_img is None:
                    break
                retry_level = read_weapon_level(retry_img, d1, d2)
                if retry_level is not None:
                    img = retry_img
                    entry.weapon_level = retry_level
                    break
            entry.set_meta("weapon_level",
                           FieldMeta.ok(FieldSource.TEMPLATE)
                           if entry.weapon_level is not None
                           else FieldMeta.failed(FieldSource.TEMPLATE, "digit_read_fail"))
            self.log(f"  전용무기: {entry.weapon_star}성 Lv.{entry.weapon_level}")
        else:
            self.log("  missing weapon_level_digit")
            entry.set_meta("weapon_level", FieldMeta.region_missing("weapon_level_digit"))

        self._close_student_panel(
            capture_name="weapon_close_button",
            region_key="weapon_menu_quit_button",
            settle_reason="close_weapon_menu",
        )



    def read_equipment(self, entry: StudentEntry) -> None:
        """Read equipment state and slots from the equipment menu."""



        saved     = self._saved_student(entry.student_id)
        sid       = entry.student_id or ""
        equip_max = self._equipment_maxed_from_saved_data(saved)
        equip4_max = self._favorite_item_maxed_from_saved_data(sid, saved)

        if equip_max:
            self._apply_saved_fields(
                entry,
                saved,
                (
                    "equip1", "equip2", "equip3",
                    "equip1_level", "equip2_level", "equip3_level",
                ),
                "saved_equipment_max",
            )
            self.log("  저장데이터에서 장비 1~3 T10/Lv.70 확인 -> 장비 1~3 스캔 생략")

        if equip4_max:
            self._apply_saved_fields(entry, saved, ("equip4",), "saved_favorite_item_max")
            self.log("  저장데이터에서 애장품 T2 확인 -> 애장품 스캔 생략")

        if equip_max and (equip4_max or not student_meta.favorite_item_enabled(sid)):
            return

        sr        = self.r["student"]
        equip_btn = sr.get("equipment_button")
        if not equip_btn:
            self.log("  missing equipment_button")



        img = self._get_student_basic_capture()
        if img is None:
            return

        pre = read_equip_check(crop_region(img, equip_btn))
        if pre == CheckFlag.IMPOSSIBLE:
            self.log("  장비 버튼이 비활성 상태라 장비 스캔을 스킵합니다")
            # Mark every equipment field as skipped when the panel is unavailable.
            for slot in (1, 2, 3, 4):
                entry.set_meta(f"equip{slot}",
                               FieldMeta.skipped("equipment_impossible"))
                if slot <= 3:
                    entry.set_meta(f"equip{slot}_level",
                                   FieldMeta.skipped("equipment_impossible"))
            return

        self._active_student_panel = "equipment"
        img = self._click_student_region_and_wait(
            "equipment_button",
            "equipment_tab",
            self._is_student_additional_menu_capture,
            timeout=ADDITIONAL_PANEL_READY_WAIT,
        )
        if img is None:
            self._esc()
            return

        check_r = sr.get("equipment_all_view_check_region")
        if check_r:
            check_state = read_equip_check_inside(crop_region(img, check_r))
            if check_state == CheckFlag.FALSE and self._wait(EQUIP_CHECK_RETRY_WAIT):
                retry_img = self._capture()
                if retry_img is not None:
                    img = retry_img
                    check_state = read_equip_check_inside(crop_region(img, check_r))
            if check_state == CheckFlag.FALSE:
                _log.warning(
                    f"{entry.label()} 장비 전체보기 체크가 FALSE라 자동 클릭을 건너뜁니다"
                )
                if self._wait(0.35):
                    retry_img = self._capture()
                    if retry_img is not None:
                        img = retry_img

        # Slots 1-3 share the same equipment-menu capture.
        if not equip_max:
            for slot in (1, 2, 3):
                skip_flags = {EquipSlotFlag.EMPTY}
                if slot in (2, 3):
                    skip_flags.add(EquipSlotFlag.LEVEL_LOCKED)
                self._scan_equip_slot(entry, img, sr, slot,
                                      skip_flags=skip_flags, scan_level=True)

            if all(getattr(entry, f"equip{slot}") in (None, "unknown") for slot in (1, 2, 3)):
                _log.warning(f"{entry.label()} equipment capture unstable -> retry once")
                if self._wait(0.35):
                    retry_img = self._capture()
                    if retry_img is not None:
                        img = retry_img
                        for slot in (1, 2, 3):
                            skip_flags = {EquipSlotFlag.EMPTY}
                            if slot in (2, 3):
                                skip_flags.add(EquipSlotFlag.LEVEL_LOCKED)
                            self._scan_equip_slot(entry, img, sr, slot,
                                                  skip_flags=skip_flags, scan_level=True)

        # ?щ’ 4
        if student_meta.favorite_item_enabled(sid):
            if not equip4_max:
                self._scan_equip_slot(
                    entry, img, sr, 4,
                    skip_flags={EquipSlotFlag.EMPTY,
                                EquipSlotFlag.LOVE_LOCKED,
                                EquipSlotFlag.NULL},
                    scan_level=False,
                )
        else:
            self.log(f"  장비4: {sid}는 equip4 미지원 -> 스킵")

        self._close_student_panel(
            capture_name="equipment_close_button",
            region_key="equipmentmenu_quit_button",
            settle_reason="close_equipment_menu",
        )

    def _scan_equip_slot(
        self,
        entry: StudentEntry,
        img: Image.Image,
        sr: dict,
        slot: int,
        skip_flags: set[EquipSlotFlag],
        scan_level: bool,
    ) -> None:
        """Scan one equipment slot from a shared equipment-menu capture."""
        equip_key = f"equip{slot}"
        level_key = f"equip{slot}_level"

        flag_r = (sr.get(f"equip{slot}_flag")
                  or sr.get(f"equip{slot}_emptyflag")
                  or sr.get(f"equip{slot}_empty_flag"))
        if flag_r:
            slot_flag = read_equip_slot_flag(crop_region(img, flag_r), slot)
            if slot_flag in skip_flags:
                self.log(f"  장비{slot}: {slot_flag.value} -> 스킵")
                setattr(entry, equip_key, slot_flag.value)
                entry.set_meta(equip_key,
                               FieldMeta.skipped(f"slot_flag={slot_flag.value}"))
                if scan_level:
                    entry.set_meta(level_key,
                                   FieldMeta.skipped(f"slot_flag={slot_flag.value}"))
                return

        tier_r = sr.get(f"equipment_{slot}")
        if tier_r:
            tier = read_equip_tier(crop_region(img, tier_r), slot)
            setattr(entry, equip_key, tier)
            entry.set_meta(equip_key,
                           FieldMeta.ok(FieldSource.TEMPLATE)
                           if tier and tier != "unknown"
                           else FieldMeta.uncertain(FieldSource.TEMPLATE,
                                                    note=f"tier={tier}"))
            self.log(f"  장비{slot} 티어: {tier}")
        else:
            entry.set_meta(equip_key, FieldMeta.region_missing(f"equipment_{slot}"))

        if scan_level:
            d1 = sr.get(f"equipment_{slot}_level_digit_1")
            d2 = sr.get(f"equipment_{slot}_level_digit_2")
            if d1 and d2:
                lv = read_equip_level(img, slot, d1, d2)
                setattr(entry, level_key, lv)
                entry.set_meta(level_key,
                               FieldMeta.ok(FieldSource.TEMPLATE)
                               if lv is not None
                               else FieldMeta.failed(FieldSource.TEMPLATE,
                                                     "digit_read_fail"))
                self.log(f"  장비{slot} 레벨: {lv}")
            else:
                self.log(f"  missing equipment_{slot}_level_digit")
                entry.set_meta(level_key,
                               FieldMeta.region_missing(f"equipment_{slot}_level_digit"))



    def read_level(self, entry: StudentEntry) -> None:
        """Read the student level tab and parse the level digits."""
        ctx = ScanCtx(student_id=entry.student_id, step="read_level")
        saved = self._saved_student(entry.student_id)

        if self._saved_int(saved, "level") == MAX_STUDENT_LEVEL:
            entry.level = MAX_STUDENT_LEVEL

        if entry.level == MAX_STUDENT_LEVEL:
            self.log("  학생 레벨이 이미 90이라 레벨 스캔을 생략합니다")
            entry.set_meta("level", FieldMeta.skipped("already_max"))
            return



        img = self._click_student_region_and_wait(
            "levelcheck_button",
            "levelcheck_button",
            self._is_level_tab_on_capture,
            timeout=TAB_ON_READY_WAIT,
            fallback_delay=0.5,
        )
        if img is None:
            _log.warning(f"{ctx} 레벨 탭 진입 실패")
            entry.set_meta("level", FieldMeta.failed(FieldSource.TEMPLATE, "tab_fail"))
            return

        sr = self.r["student"]
        d1 = sr.get("level_digit_1")
        d2 = sr.get("level_digit_2")
        if not d1 or not d2:
            _log.warning(f"{ctx} missing level_digit region")
            self._restore_basic_tab()
            entry.set_meta("level", FieldMeta.region_missing("level_digit"))
            return

        lv = read_student_level_v5(img, d1, d2)
        for _ in range(2):
            if lv is not None:
                break
            if not self._wait(LEVEL_CAPTURE_RETRY_WAIT):
                break
            retry_img = self._capture()
            if retry_img is None:
                break
            retry_level = read_student_level_v5(retry_img, d1, d2)
            if retry_level is not None:
                img = retry_img
                lv = retry_level
                break
        entry.level = lv

        if lv is not None:
            entry.set_meta("level", FieldMeta.ok(FieldSource.TEMPLATE))
            self.log(f"  학생 레벨: {entry.label()} -> Lv.{lv}")
        else:
            entry.set_meta("level", FieldMeta.failed(FieldSource.TEMPLATE, "digit_read_fail"))
            _log.warning(f"{ctx} 레벨 인식 실패")
            if self._asv:
                self._asv.on_step_error("read_level", entry.student_id or "")

        self._restore_basic_tab()



    def read_student_star(self, entry: StudentEntry) -> None:
        """Read the student's star count, or infer it from weapon unlock state."""



        ctx = ScanCtx(student_id=entry.student_id, step="read_student_star")

        if entry.weapon_state != WeaponState.NO_WEAPON_SYSTEM:
            # Students with a weapon system unlocked are guaranteed to be 5-star.
            entry.student_star = 5
            entry.set_meta("student_star",
                           FieldMeta.inferred("weapon_state 기반 5성 확정"))
            self.log("  전용무기 보유 학생 -> 별 스캔 생략 (5성 확정)")
            return

        sr = self.r["student"]
        img = self._click_student_region_and_wait(
            "star_menu_button",
            "star_menu",
            self._is_star_tab_on_capture,
            timeout=TAB_ON_READY_WAIT,
            fallback_delay=0.3,
        )
        if img is None:
            entry.set_meta("student_star",
                           FieldMeta.failed(FieldSource.TEMPLATE, "capture_fail"))
            return

        region_key = (
            "student_star_region"
            if "student_star_region" in sr
            else "star_region"
        )
        star_r = sr.get(region_key)
        if not star_r:
            entry.set_meta("student_star",
                           FieldMeta.region_missing(region_key))
            return

        from core.matcher import read_student_star_v5_result
        r = read_student_star_v5_result(crop_region(img, star_r))

        entry.student_star = r.value
        if r.uncertain or r.value is None:
            entry.set_meta("student_star",
                           FieldMeta.uncertain(FieldSource.TEMPLATE,
                                               score=r.score,
                                               note=f"value={r.value}"))
            _log.warning(f"{ctx} 별 인식 불확실 (score={r.score:.3f} val={r.value})")
        else:
            entry.set_meta("student_star",
                           FieldMeta.ok(FieldSource.TEMPLATE, score=r.score))
            self.log(f"  학생 별: {entry.label()} -> {entry.student_star}성 (score={r.score:.3f})")



    def read_stats(self, entry: StudentEntry) -> None:
        """
        Lv.90 + 5성 조건을 만족할 때만 스탯을 읽습니다.
        상세 스탯 메뉴에 들어가서 HP / ATK / HEAL 값을 읽습니다.
        """
        level_ok = entry.level is not None and entry.level >= STAT_UNLOCK_LEVEL
        star_ok  = entry.student_star is not None and entry.student_star >= STAT_UNLOCK_STAR

        if not level_ok or not star_ok:
            self.log(
                f"  스탯 스캔 생략 "
                f"(Lv.{entry.level} / {entry.student_star}성)"
            )
            return

        saved = self._saved_student(entry.student_id)
        if self._stats_maxed_from_saved_data(saved):
            self._apply_saved_fields(
                entry,
                saved,
                ("stat_hp", "stat_atk", "stat_heal"),
                "saved_stat_max",
            )
            self.log("  저장데이터에서 능력 개방 25/25/25 확인 -> 스탯 스캔 생략")
            return

        self._active_student_panel = "stat"
        img = self._click_student_region_and_wait(
            "stat_menu_button",
            "stat_menu_button",
            self._is_student_additional_menu_capture,
            timeout=ADDITIONAL_PANEL_READY_WAIT,
            fallback_delay=0.4,
            match_delay=STAT_PANEL_MATCH_DELAY,
        )
        if img is None:
            self._esc()
            return

        ctx = ScanCtx(student_id=entry.student_id, step="read_stats")

        sr = self.r["student"]
        for stat_key, field_name, region_key in [
            ("hp",   "stat_hp",   "hp"),
            ("atk",  "stat_atk",  "atk"),
            ("heal", "stat_heal", "heal"),
        ]:
            region = sr.get(region_key)
            if not region:
                _log.warning(f"{ctx.with_step(field_name)} missing region")
                entry.set_meta(field_name, FieldMeta.region_missing(region_key))
                continue

            from core.matcher import read_stat_value_result
            r = read_stat_value_result(crop_region(img, region), stat_key)
            setattr(entry, field_name, r.value)

            if r.value is None or r.uncertain:
                entry.set_meta(field_name,
                               FieldMeta.uncertain(FieldSource.TEMPLATE,
                                                   score=r.score,
                                                   note=f"val={r.value}"))
                _log.warning(f"{ctx.with_step(field_name)} 스탯 인식 불확실"
                             f"(score={r.score:.3f} val={r.value})")
            else:
                entry.set_meta(field_name,
                               FieldMeta.ok(FieldSource.TEMPLATE, score=r.score))

        self.log(
            f"  스탯: HP={entry.stat_hp} "
            f"ATK={entry.stat_atk} HEAL={entry.stat_heal}"
        )
        self._close_student_panel(
            capture_name="stat_close_button",
            region_key="statmenu_quit_button",
            settle_reason="close_stat_menu",
        )



    def _log_student(self, entry: StudentEntry, idx: int) -> None:
        weapon_info = ""
        if entry.weapon_state == WeaponState.WEAPON_EQUIPPED:
            weapon_info = f" | 무기:{entry.weapon_star}성Lv.{entry.weapon_level}"
        elif entry.weapon_state == WeaponState.WEAPON_UNLOCKED_NOT_EQUIPPED:
            weapon_info = " | weapon:not-equipped"

        equip_info = (
            f"{entry.equip1}(Lv.{entry.equip1_level})/"

            f"{entry.equip3}(Lv.{entry.equip3_level})/"
            f"{entry.equip4}"
        )
        self.log(
            f"  [{idx+1:>3}] {entry.label()}  Lv.{entry.level}  "
            f"{entry.student_star}*{weapon_info}  "
            f"EX:{entry.ex_skill} S1:{entry.skill1} "
            f"S2:{entry.skill2} S3:{entry.skill3}  "
            f"equip:{equip_info}  "
            f"stats(HP:{entry.stat_hp}/ATK:{entry.stat_atk}/HEAL:{entry.stat_heal})"
        )


        # Emit a compact summary for uncertain / failed / inferred fields.
        uncertain = entry.uncertain_fields()
        failed    = entry.failed_fields()
        inferred  = [k for k, v in entry._meta.items()
                     if v.status == FieldStatus.INFERRED]

        if uncertain:
            _log.warning(
                f"  [{idx+1:>3}] {entry.label()} "
                f"-> uncertain: {uncertain}"
            )
        if failed:
            _log.warning(
                f"  [{idx+1:>3}] {entry.label()} "
                f"-> failed: {failed}"
            )
        if inferred:
            _log.info(
                f"  [{idx+1:>3}] {entry.label()} "
                f"-> inferred: {inferred}"
            )



    def run_full_scan(self) -> ScanResult:
        self.clear_stop()
        result = ScanResult()
        self.log("[scan] full scan start")
        result.resources = self.scan_resources()
        result.items     = self.scan_items()
        if not self._stop_requested():
            result.equipment = self.scan_equipment()
        if not self._stop_requested():
            result.students  = self.scan_students()
        self.log("[scan] full scan done")
        return result



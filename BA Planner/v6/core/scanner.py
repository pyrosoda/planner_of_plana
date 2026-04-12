"""
Student scanning pipeline for BA Analyzer v6.

This module coordinates student navigation, recognition, and data collection.
Broken legacy comments and UI strings were cleaned up for readability.
"""

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
    scroll_at,
    press_esc,
    click_point,
    send_escape,
    ratio_to_client,
)


from core.matcher import (
    WeaponState,
    CheckFlag,
    EquipSlotFlag,
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
from core.config import BASE_DIR
from core.item_names import correct_item_name



# Constants


MAX_SCROLLS          = 60
SCROLL_ITEM          = -3
SCROLL_EQUIP         = -2
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

# Retry policy
RETRY_IDENTIFY   = 2      # max student identify retries
RETRY_CAPTURE    = 2      # capture retry count
DELAY_AFTER_CLICK = 0.22  # generic click settle
DELAY_TAB_SWITCH  = 0.55  # tab switch settle
DELAY_NEXT        = 1.20  # next student settle
DELAY_ESC         = 0.35  # escape settle




@dataclass
class ItemEntry:
    name:     Optional[str]
    quantity: Optional[str]
    source:   str = "item"
    index:    int = 0

    def key(self) -> str:
        return f"{self.name}_{self.source}_{self.index}"






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



# Utility helpers


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
    ):
        self.r             = regions
        self._on_progress  = on_progress
        self._on_progress_state = on_progress_state
        self._stop         = False
        self._maxed_ids    = frozenset(maxed_ids or [])
        self._maxed_saved_data: dict[str, dict] = maxed_saved_data or {}
        self._student_saved_data: dict[str, dict] = student_saved_data or {}
        self._student_total_hint = student_total_hint if student_total_hint and student_total_hint > 0 else None
        self._asv          = autosave_manager   # AutoSaveManager or None
        self._student_basic_img: Optional[Image.Image] = None
        self._captured_click_points = self._load_captured_click_points()
        self._active_student_panel: str | None = None

        if self._maxed_ids:
            self._info(f"만렙 스킵용 저장데이터 로드: {len(self._maxed_ids)}명")

    def stop(self) -> None:
        self._stop = True
        _log.info("스캔 중지 요청")

    def clear_stop(self) -> None:
        self._stop = False

    def _stop_requested(self) -> bool:
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

    def _scan_grid(
        self,
        section: str,
        source: str,
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

        scroll_cx = (grid_r["x1"] + grid_r["x2"]) / 2
        scroll_cy = (grid_r["y1"] + grid_r["y2"]) / 2

        items:       list[ItemEntry] = []
        seen_keys:   set[str]        = set()
        seen_hashes: list[str]       = []
        icon = "아이템" if source == "item" else "장비"

        self.log(f"{icon} 그리드 스캔 시작 (슬롯 {len(slots)}개)")

        for scroll_i in range(MAX_SCROLLS):
            if self._stop_requested():
                break


            img = self._capture()
            if img is None:
                break

            grid_crop = crop_region(img, grid_r)
            cur_hash  = _img_hash(grid_crop)

            if cur_hash in seen_hashes:
                self.log(f"  동일 화면 반복 감지 -> 스캔 종료 ({len(items)}개)")
                break
            seen_hashes.append(cur_hash)
            if len(seen_hashes) > 10:
                seen_hashes.pop(0)

            new_this = 0
            for slot in slots:
                if self._stop_requested():
                    break

                click_ry = slot["y1"] + (slot["y2"] - slot["y1"]) * 0.4
                safe_click(rect, slot["cx"], click_ry, f"{source}_slot")
                if not self._wait(DELAY_AFTER_CLICK):
                    break

                # Capture once after clicking a grid slot.
                img2 = self._capture()
                if img2 is None:
                    continue

                # Crop the item name and count regions from the captured frame.
                count_crop = crop_region(img2, count_r)

                name  = ocr.read_item_name(name_crop)
                count = ocr.read_item_count(count_crop)
                if not name:
                    continue

                entry = ItemEntry(
                    name=name,
                    quantity=count,
                    source=source,
                    index=len(items),
                )
                k = entry.key()
                if k not in seen_keys:
                    seen_keys.add(k)
                    items.append(entry)
                    new_this += 1
                    self.log(f"  {icon} [{len(items):>3}] {name}  x{count}")

            self.log(f"  scroll {scroll_i+1}: new {new_this} / total {len(items)}")

            # Capture before and after scrolling to detect list movement.
            before_img = self._capture()
            before = crop_region(before_img, grid_r) if before_img else None

            scroll_at(rect, scroll_cx, scroll_cy, scroll_amount)
            if not self._wait(0.15):
                break

            after_img = self._capture()
            if after_img is None:
                break
            after = crop_region(after_img, grid_r)

            if before is not None and _images_similar(before, after):
                self.log(f"  scroll finished: total {len(items)}")
                break
            if new_this == 0 and scroll_i >= 2:
                self.log(f"  no new items: total {len(items)}")
                break

        return items



    def scan_items(self) -> list[ItemEntry]:
        self.log("[scan] item scan start")
        try:
            ocr.load()
            if not self._open_menu():
                return []
            if not self._go_to("item_entry_button", "items"): 
                return []
            if not self._wait(0.5):
                return []
            result = self._scan_grid("item", "item", SCROLL_ITEM)
            self.log(f"[scan] item scan done: {len(result)} entries")
            return result
        except Exception as e:
            self.log(f"item scan error: {e}")
            return []
        finally:
            self._return_lobby()
            ocr.unload()

    def scan_equipment(self) -> list[ItemEntry]:
        self.log("[scan] equipment scan start")
        try:
            ocr.load()
            if not self._open_menu():
                return []
            if not self._go_to("equipment_entry_button", "equipment"): 
                return []
            if not self._wait(0.5):
                return []
            result = self._scan_grid("equipment", "equipment", SCROLL_EQUIP)
            self.log(f"[scan] equipment scan done: {len(result)} entries")
            return result
        except Exception as e:
            self.log(f"equipment scan error: {e}")
            return []
        finally:
            self._return_lobby()
            ocr.unload()




    def scan_students(self) -> list[StudentEntry]:
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

    def go_next_student(self) -> bool:
        btn = self.r["student"].get("next_student_button")
        if not btn:
            self.log("  missing next_student_button")
            return False
        self._invalidate_student_basic_capture()
        self._click_r(btn, "next_student")
        return self._wait(DELAY_NEXT)



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
            result.students  = self.scan_students_v5()
        self.log("[scan] full scan done")
        return result



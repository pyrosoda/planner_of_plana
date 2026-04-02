"""
core/scanner.py — 스캔 자동화 엔진  V5

[수정]
  - _detect_weapon_state_for(): region 없을 때 기본값 NO_WEAPON_SYSTEM 으로 변경
  - _maybe_read_weapon_star_into(): weapon_info_menu_button 클릭으로 무기 메뉴 진입 추가
  - weapon_level 관련 코드 완전 제거 (무기 레벨은 스캔하지 않음)
"""

import time
import hashlib
import numpy as np
from dataclasses import dataclass, field
from typing import Callable
from PIL import Image

from core.capture import (
    capture_window, crop_ratio, get_window_rect,
    click_center, safe_click, scroll_at, press_esc
)
from core.matcher import (
    WeaponState,
    WeaponStatus,
    match_student_texture,
    detect_weapon_state,
    read_student_star_v5,
    read_weapon_star_v5,
    read_skill,
    read_equip_tier,
    read_student_level,
    read_student_level_v5,
)
import core.ocr as ocr
import core.student_names as student_names
from core.item_names import correct_item_name

# ── 상수 ──────────────────────────────────────────────────
MAX_SCROLLS         = 60
SCROLL_ITEM         = -3
SCROLL_EQUIP        = -2
SAME_THRESH         = 0.97
STUDENT_MENU_WAIT   = 3.0
STUDENT_NEXT_WAIT   = 0.4
MAX_CONSECUTIVE_DUP = 3
MAX_STUDENT_LEVEL   = 90


# ── 데이터 클래스 ──────────────────────────────────────────
@dataclass
class ItemEntry:
    name:     str | None
    quantity: str | None
    source:   str = "item"
    index:    int = 0

    def key(self):
        return f"{self.name}_{self.source}_{self.index}"


@dataclass
class StudentEntry:
    student_id:   str | None = None
    display_name: str | None = None
    level:        int | None = None
    student_star: int | None = None
    weapon_state: WeaponState | None = None
    weapon_star:  int | None         = None
    ex_skill: int | None = None
    skill1:   int | None = None
    skill2:   int | None = None
    skill3:   int | None = None
    equip1: str | None = None
    equip2: str | None = None
    equip3: str | None = None
    equip4: str | None = None

    def label(self) -> str:
        return self.display_name or self.student_id or "?"


@dataclass
class ScanResult:
    items:     list[ItemEntry]    = field(default_factory=list)
    equipment: list[ItemEntry]    = field(default_factory=list)
    students:  list[StudentEntry] = field(default_factory=list)
    resources: dict               = field(default_factory=dict)
    errors:    list[str]          = field(default_factory=list)


# ── 유틸 ──────────────────────────────────────────────────
def _img_hash(img: Image.Image) -> str:
    small = img.convert("L").resize((16, 16))
    return hashlib.md5(small.tobytes()).hexdigest()


def _images_similar(a: Image.Image, b: Image.Image) -> bool:
    try:
        a2 = np.array(a.convert("L").resize((64, 64))).flatten().astype(float)
        b2 = np.array(b.convert("L").resize((64, 64))).flatten().astype(float)
        return float(np.corrcoef(a2, b2)[0, 1]) >= SAME_THRESH
    except Exception:
        return False


def _grid_region(slots: list[dict]) -> dict:
    return {
        "x1": min(s["x1"] for s in slots),
        "y1": min(s["y1"] for s in slots),
        "x2": max(s["x2"] for s in slots),
        "y2": max(s["y2"] for s in slots),
    }


# ── 스캐너 ────────────────────────────────────────────────
class Scanner:
    def __init__(self, regions: dict,
                 on_progress: Callable[[str], None] | None = None):
        self.r     = regions
        self.log   = on_progress or print
        self._stop = False

    def stop(self):
        self._stop = True

    # ── 재화 ──────────────────────────────────────────────
    def scan_resources(self) -> dict:
        self.log("💰 재화 스캔 중...")
        img = capture_window()
        if img is None:
            self.log("❌ 캡처 실패")
            return {}

        lobby_r = self.r["lobby"]
        result  = {}

        ocr.load()
        try:
            for key, rk in [("크레딧",  "credit_region"),
                             ("청휘석", "pyroxene_region")]:
                try:
                    crop = crop_ratio(img, lobby_r[rk])
                    result[key] = ocr.read_item_count(crop)
                except Exception as e:
                    result[key] = None
                    print(f"[Scanner] 재화 OCR 실패 ({key}): {e}")
        finally:
            ocr.unload()

        self.log(
            f"💰 청휘석={result.get('청휘석','-')}  "
            f"크레딧={result.get('크레딧','-')}"
        )
        return result

    # ── 공통 그리드 스캔 ──────────────────────────────────
    def _scan_grid(self, section: str, source: str,
                   scroll_amount: int) -> list[ItemEntry]:
        r_sec   = self.r[section]
        slots   = r_sec["grid_slots"]
        name_r  = r_sec["name_region"]
        count_r = r_sec["count_region"]
        grid_r  = _grid_region(slots)

        rect = get_window_rect()
        if not rect:
            self.log("❌ 창 없음")
            return []

        scroll_cx = (grid_r["x1"] + grid_r["x2"]) / 2
        scroll_cy = (grid_r["y1"] + grid_r["y2"]) / 2

        items: list[ItemEntry] = []
        seen_keys:   set[str]  = set()
        seen_hashes: list[str] = []
        icon = "📦" if source == "item" else "🔧"

        self.log(f"{icon} 그리드 스캔 시작 (슬롯 {len(slots)}개)")

        for scroll_i in range(MAX_SCROLLS):
            if self._stop:
                break

            img = capture_window()
            if img is None:
                break

            grid_crop = crop_ratio(img, grid_r)
            cur_hash  = _img_hash(grid_crop)

            if cur_hash in seen_hashes:
                self.log(f"  🔁 화면 반복 감지 → 스캔 종료 ({len(items)}개)")
                break
            seen_hashes.append(cur_hash)
            if len(seen_hashes) > 10:
                seen_hashes.pop(0)

            new_this = 0

            for slot in slots:
                if self._stop:
                    break

                click_ry = slot["y1"] + (slot["y2"] - slot["y1"]) * 0.4
                safe_click(rect, slot["cx"], click_ry, f"{source}_slot")
                time.sleep(0.22)

                img2 = capture_window()
                if img2 is None:
                    continue

                name  = ocr.read_item_name(crop_ratio(img2, name_r))
                count = ocr.read_item_count(crop_ratio(img2, count_r))

                if not name:
                    continue

                entry = ItemEntry(name=name, quantity=count, source=source)
                k = entry.key()
                if k not in seen_keys:
                    seen_keys.add(k)
                    items.append(entry)
                    new_this += 1
                    self.log(f"  {icon} [{len(items):>3}] {name}  ×{count}")

            self.log(
                f"  스크롤 {scroll_i+1}회차: "
                f"신규 {new_this}개 / 누계 {len(items)}개"
            )

            before = crop_ratio(capture_window() or img, grid_r)
            scroll_at(rect, scroll_cx, scroll_cy, scroll_amount)
            time.sleep(0.15)

            after_img = capture_window()
            if after_img is None:
                break
            after = crop_ratio(after_img, grid_r)

            if _images_similar(before, after):
                self.log(f"  ✅ 스크롤 끝 — 총 {len(items)}개")
                break

            if new_this == 0 and scroll_i >= 2:
                self.log(f"  ✅ 신규 없음 — 총 {len(items)}개")
                break

        return items

    # ── 네비게이션 ────────────────────────────────────────
    def _open_menu(self) -> bool:
        rect = get_window_rect()
        if not rect:
            return False
        self.log("📂 메뉴 열기...")
        click_center(rect, self.r["lobby"]["menu_button"], "menu_button")
        time.sleep(0.7)
        return True

    def _go_to(self, btn_key: str, label: str) -> bool:
        rect = get_window_rect()
        if not rect:
            return False
        btn = self.r["menu"].get(btn_key)
        if not btn:
            self.log(f"❌ {label} 버튼 설정 없음")
            return False
        self.log(f"  → {label} 진입...")
        click_center(rect, btn, label)
        time.sleep(1.0)
        return True

    def _return_lobby(self):
        self.log("🏠 로비 복귀...")
        press_esc()
        time.sleep(0.5)

    # ── 아이템 스캔 ───────────────────────────────────────
    def scan_items(self) -> list[ItemEntry]:
        self._stop = False
        self.log("━━━ 📦 아이템 스캔 시작 ━━━")
        try:
            ocr.load()
            if not self._open_menu():
                return []
            if not self._go_to("item_entry_button", "아이템"):
                return []
            time.sleep(0.5)
            result = self._scan_grid("item", "item", SCROLL_ITEM)
            self.log(f"━━━ 📦 아이템 스캔 완료: {len(result)}개 ━━━")
            return result
        except Exception as e:
            self.log(f"❌ 아이템 스캔 오류: {e}")
            return []
        finally:
            self._return_lobby()
            ocr.unload()

    # ── 장비 스캔 ─────────────────────────────────────────
    def scan_equipment(self) -> list[ItemEntry]:
        self._stop = False
        self.log("━━━ 🔧 장비 스캔 시작 ━━━")
        try:
            ocr.load()
            if not self._open_menu():
                return []
            if not self._go_to("equipment_entry_button", "장비"):
                return []
            time.sleep(0.5)
            result = self._scan_grid("equipment", "equipment", SCROLL_EQUIP)
            self.log(f"━━━ 🔧 장비 스캔 완료: {len(result)}개 ━━━")
            return result
        except Exception as e:
            self.log(f"❌ 장비 스캔 오류: {e}")
            return []
        finally:
            self._return_lobby()
            ocr.unload()

    # ══════════════════════════════════════════════════════════
    # V5 학생 스캔
    # ══════════════════════════════════════════════════════════

    def scan_students_v5(self) -> list[StudentEntry]:
        self._stop = False
        self.log("━━━ 👩 학생 스캔 시작 (V5) ━━━")

        results: list[StudentEntry] = []

        try:
            ocr.load()

            if not self._open_student_menu():
                return []
            if not self._open_first_student():
                return []

            seen_student_ids:    set[str] = set()
            consecutive_duplicates: int  = 0

            for idx in range(500):
                if self._stop:
                    break

                entry = self.scan_one_student_v5(idx)

                if entry is None:
                    self.log(f"  ⚠️ [{idx+1}] 식별 실패 — 스캔 종료")
                    break

                dedup_key = entry.student_id or entry.display_name or ""

                if dedup_key and dedup_key in seen_student_ids:
                    consecutive_duplicates += 1
                    self.log(
                        f"  🔁 중복: {entry.label()} "
                        f"({consecutive_duplicates}/{MAX_CONSECUTIVE_DUP})"
                    )
                else:
                    consecutive_duplicates = 0
                    if dedup_key:
                        seen_student_ids.add(dedup_key)

                results.append(entry)
                self._log_student(entry, idx)

                if consecutive_duplicates >= MAX_CONSECUTIVE_DUP:
                    self.log("  ✅ 연속 중복 → 스캔 종료")
                    break

                self._restore_basic_info_tab()
                if not self._move_to_next_student():
                    self.log("  ✅ 마지막 학생 — 스캔 종료")
                    break

        except Exception as e:
            self.log(f"❌ 학생 스캔 오류: {e}")
            import traceback
            traceback.print_exc()
        finally:
            self._return_lobby()
            ocr.unload()

        self.log(f"━━━ 👩 학생 스캔 완료: {len(results)}명 ━━━")
        return results

    def scan_students(self) -> list[StudentEntry]:
        return self.scan_students_v5()

    # ── B. 학생 1명 스캔 ──────────────────────────────────
    def scan_one_student_v5(self, idx: int = 0) -> StudentEntry | None:
        sid = self._identify_student(idx)
        if sid is None:
            return None

        entry = StudentEntry(
            student_id   = sid,
            display_name = student_names.display_name(sid),
        )

        self._read_skills_into(entry)
        self._read_equipment_into(entry)
        entry.weapon_state = self._detect_weapon_state_for(entry)
        self._maybe_read_level_into(entry)
        self._maybe_read_student_star_into(entry)
        self._maybe_read_weapon_star_into(entry)

        return entry

    # ── C. 학생 texture 기반 식별 ────────────────────────
    def _identify_student(self, idx: int = 0) -> str | None:
        img = capture_window()
        if img is None:
            return None

        sr        = self.r["student"]
        texture_r = sr.get("student_texture_region")
        if not texture_r:
            self.log(f"  ⚠️ [{idx+1}] student_texture_region 미정의 — 식별 불가")
            return None

        texture_crop = crop_ratio(img, texture_r)
        sid, score   = match_student_texture(texture_crop)

        if sid is not None:
            self.log(f"  🔍 [{idx+1}] 식별: {student_names.display_name(sid)} (score={score:.3f})")
            return sid

        self.log(f"  ⚠️ [{idx+1}] 텍스처 식별 실패 (score={score:.3f})")
        return None

    # ── D. 스킬 읽기 ──────────────────────────────────────
    def _read_skills_into(self, entry: StudentEntry) -> None:
        img = capture_window()
        if img is None:
            return

        sr = self.r["student"]
        for field, region_key, tmpl_key in [
            ("ex_skill", "ex_skill_region", "EX_Skill"),
            ("skill1",   "skill1_region",   "Skill1"),
            ("skill2",   "skill2_region",   "Skill2"),
            ("skill3",   "skill3_region",   "Skill3"),
        ]:
            raw = read_skill(crop_ratio(img, sr[region_key]), tmpl_key)
            try:
                setattr(entry, field, int(raw))
            except (TypeError, ValueError):
                setattr(entry, field, None)

    # ── E. 장비 읽기 ──────────────────────────────────────
    def _read_equipment_into(self, entry: StudentEntry) -> None:
        img = capture_window()
        if img is None:
            return

        sr = self.r["student"]
        entry.equip1 = read_equip_tier(crop_ratio(img, sr["equipment1_region"]), 1)
        entry.equip2 = read_equip_tier(crop_ratio(img, sr["equipment2_region"]), 2)
        entry.equip3 = read_equip_tier(crop_ratio(img, sr["equipment3_region"]), 3)
        entry.equip4 = read_equip_tier(crop_ratio(img, sr["equipment4_region"]), 4)

    # ── F. 무기 상태 판별 ────────────────────────────────
    def _detect_weapon_state_for(self, entry: StudentEntry) -> WeaponState:
        """
        weapon_detect_flag_region crop → detect_weapon_state() 호출.
        region 없으면 NO_WEAPON_SYSTEM 반환 (성작 오기록 방지).
        """
        img = capture_window()
        if img is None:
            print("[Scanner] weapon_state 캡처 실패 → NO_WEAPON_SYSTEM 폴백")
            return WeaponState.NO_WEAPON_SYSTEM

        sr       = self.r["student"]
        weapon_r = sr.get("weapon_detect_flag_region") or sr.get("weapon_unlocked_flag")
        if not weapon_r:
            print("[Scanner] weapon_detect_flag_region 미정의 → NO_WEAPON_SYSTEM 폴백")
            return WeaponState.NO_WEAPON_SYSTEM

        state, _score = detect_weapon_state(crop_ratio(img, weapon_r))
        print(f"[Scanner] weapon_state={state.name} (score={_score:.3f})")
        return state

    # ── G. 레벨 읽기 ──────────────────────────────────────
    def _maybe_read_level_into(self, entry: StudentEntry) -> None:
        if self._should_skip_level_scan(entry.student_id):
            self.log(f"  ⏭ 레벨 스캔 생략: {entry.label()} (만렙 확정)")
            entry.level = MAX_STUDENT_LEVEL
            return

        self._open_level_menu()
        entry.level = self._read_student_level_from_menu()
        self._close_level_menu_or_restore_basic_tab()

    def _should_skip_level_scan(self, student_id: str | None) -> bool:
        return False

    def _open_level_menu(self) -> None:
        rect = get_window_rect()
        if not rect:
            return
        sr = self.r["student"]
        click_center(rect, sr["levelcheck_button"], "levelcheck_tab")
        time.sleep(0.4)

    def _read_student_level_from_menu(self) -> int | None:
        img = capture_window()
        if img is None:
            return None
        sr = self.r["student"]
        return read_student_level_v5(img, sr["level_digit_1"], sr["level_digit_2"])

    def _close_level_menu_or_restore_basic_tab(self) -> None:
        rect = get_window_rect()
        if not rect:
            return
        sr = self.r["student"]
        if "basic_info_button" in sr:
            click_center(rect, sr["basic_info_button"], "basic_info_tab")
            time.sleep(0.3)

    # ── H. 학생 성작 판독 ────────────────────────────────
    def _maybe_read_student_star_into(self, entry: StudentEntry) -> None:
        if entry.weapon_state != WeaponState.NO_WEAPON_SYSTEM:
            entry.student_star = 5
            self.log(f"  ⏭ 학생 성작 생략: {entry.label()} (무기 시스템 보유 → 5★ 확정)")
            return

        rect = get_window_rect()
        if not rect:
            return

        sr = self.r["student"]
        star_menu_btn = sr.get("star_menu_button")
        if star_menu_btn:
            click_center(rect, star_menu_btn, "star_menu")
            time.sleep(0.3)

        img = capture_window()
        if img is None:
            return

        region_key = "student_star_region" if "student_star_region" in sr else "star_region"
        entry.student_star = read_student_star_v5(crop_ratio(img, sr[region_key]))
        self.log(f"  ⭐ 학생 성작: {entry.label()} → {entry.student_star}★")

    # ── I. 무기 성작 판독 ────────────────────────────────
    def _maybe_read_weapon_star_into(self, entry: StudentEntry) -> None:
        """
        흐름:
          1. weapon_info_menu_button 클릭 → 무기 상세 화면 진입
          2. weapon_star_region 판독
          3. weapon_menu_quit_button 으로 복귀
        무기 레벨은 스캔하지 않음.
        """
        if entry.weapon_state == WeaponState.NO_WEAPON_SYSTEM:
            return

        rect = get_window_rect()
        if not rect:
            return

        sr = self.r["student"]

        # 1. 무기 메뉴 진입
        weapon_menu_btn = sr.get("weapon_info_menu_button")
        if weapon_menu_btn:
            click_center(rect, weapon_menu_btn, "weapon_info_menu")
            time.sleep(0.5)
        else:
            print("[Scanner] weapon_info_menu_button 미정의 — 무기 메뉴 진입 생략")

        img = capture_window()
        if img is None:
            return

        # 2. 무기 성작 판독
        weapon_star_r = sr.get("weapon_star_region")
        if weapon_star_r:
            entry.weapon_star = read_weapon_star_v5(crop_ratio(img, weapon_star_r))
        else:
            print("[Scanner] weapon_star_region 미정의 → weapon_star=None")

        self.log(f"  🗡 무기 성작: {entry.label()} → {entry.weapon_star}★")

        # 3. 무기 메뉴 복귀
        self._quit_weapon_menu()

    def _quit_weapon_menu(self) -> None:
        rect = get_window_rect()
        if not rect:
            return
        sr = self.r["student"]
        quit_btn = sr.get("weapon_menu_quit_button")
        if quit_btn:
            click_center(rect, quit_btn, "weapon_menu_quit")
            time.sleep(0.25)

    # ── J. 탭/화면 복귀 ──────────────────────────────────
    def _restore_basic_info_tab(self) -> None:
        rect = get_window_rect()
        if not rect:
            return

        sr = self.r["student"]
        if "basic_info_button" in sr:
            click_center(rect, sr["basic_info_button"], "basic_info_tab")
            time.sleep(0.3)
        else:
            press_esc()
            time.sleep(0.4)

    # ── K. 다음 학생 이동 ─────────────────────────────────
    def _move_to_next_student(self) -> bool:
        rect = get_window_rect()
        if not rect:
            return False

        sr       = self.r["student"]
        next_btn = sr.get("next_student_button")
        if not next_btn:
            return False

        before_img = capture_window()
        before_hash = _img_hash(before_img) if before_img else ""

        click_center(rect, next_btn, "next_student")
        time.sleep(STUDENT_NEXT_WAIT)

        for _ in range(3):
            after_img  = capture_window()
            after_hash = _img_hash(after_img) if after_img else ""
            if after_hash and after_hash != before_hash:
                return True
            time.sleep(0.15)

        self.log("  ⚠️ 화면 변화 없음 — 마지막 학생으로 판단")
        return False

    # ── L. 진입 헬퍼 ─────────────────────────────────────
    def _open_student_menu(self) -> bool:
        rect = get_window_rect()
        if not rect:
            return False
        lobby_r = self.r["lobby"]
        self.log("  학생 메뉴 진입...")
        click_center(rect, lobby_r["student_menu_button"], "student_menu")
        time.sleep(STUDENT_MENU_WAIT)
        return True

    def _open_first_student(self) -> bool:
        rect = get_window_rect()
        if not rect:
            return False
        self.log("  첫 학생 선택...")
        click_center(rect, self.r["student_menu"]["first_student_button"], "first_student")
        time.sleep(0.8)
        return True

    def _log_student(self, entry: StudentEntry, idx: int) -> None:
        weapon_info = ""
        if entry.weapon_state == WeaponState.WEAPON_EQUIPPED:
            weapon_info = f" | 무기:{entry.weapon_star}★"
        elif entry.weapon_state == WeaponState.WEAPON_UNLOCKED_NOT_EQUIPPED:
            weapon_info = " | 무기:미장착"

        self.log(
            f"  👩 [{idx+1:>3}] {entry.label()}  "
            f"Lv.{entry.level}  {entry.student_star}★{weapon_info}  "
            f"EX:{entry.ex_skill} S1:{entry.skill1} "
            f"S2:{entry.skill2} S3:{entry.skill3}  "
            f"장비:{entry.equip1}/{entry.equip2}/{entry.equip3}/{entry.equip4}"
        )

    # ── 전체 스캔 ─────────────────────────────────────────
    def run_full_scan(self) -> ScanResult:
        self._stop = False
        result = ScanResult()
        self.log("━━━━━ 전체 스캔 시작 ━━━━━")
        result.resources = self.scan_resources()
        result.items     = self.scan_items()
        if not self._stop:
            result.equipment = self.scan_equipment()
        if not self._stop:
            result.students  = self.scan_students_v5()
        self.log("━━━━━ 전체 스캔 완료 ━━━━━")
        return result
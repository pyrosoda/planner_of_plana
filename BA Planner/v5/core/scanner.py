"""
core/scanner.py — 스캔 자동화 엔진  V5.2

[V5.2 추가]
  - maxed_ids / maxed_cache 파라미터: 만렙 학생 스킵
  - _should_skip(): maxed_ids 에 있으면 세부 스캔 전체 건너뜀
  - scan_students_v5(): 스킵 학생은 캐시 데이터 그대로 사용

[학생 1명 스캔 순서]
  1. 학생 식별 (texture 매칭)
  1.5 만렙 스킵 판정 → maxed_ids 에 있으면 캐시 반환 후 next
  2. 스킬 스캔
  3. 무기 상태 판정
  4. 장비 스캔
  5. 레벨 스캔
  6. 성작 스캔
  7. 스탯 스캔 (Lv90 + 5★ 조건)
  8. 기본 정보 탭 복귀
  9. 다음 학생 버튼
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
    CheckFlag,
    EquipSlotFlag,
    match_student_texture,
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
    read_student_level,
    read_student_level_v5,
)
import core.ocr as ocr
import core.student_names as student_names
from core.item_names import correct_item_name
from core.equip4_students import has_equip4

# ── 상수 ──────────────────────────────────────────────────
MAX_SCROLLS         = 60
SCROLL_ITEM         = -3
SCROLL_EQUIP        = -2
SAME_THRESH         = 0.97
STUDENT_MENU_WAIT   = 3.0
MAX_CONSECUTIVE_DUP = 3
MAX_STUDENT_LEVEL   = 90

STAT_UNLOCK_LEVEL = 90
STAT_UNLOCK_STAR  = 5


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
    # 무기
    weapon_state: WeaponState | None = None
    weapon_star:  int | None         = None
    weapon_level: int | None         = None
    # 스킬
    ex_skill: int | None = None
    skill1:   int | None = None
    skill2:   int | None = None
    skill3:   int | None = None
    # 장비 티어
    equip1:   str | None = None
    equip2:   str | None = None
    equip3:   str | None = None
    equip4:   str | None = None
    # 장비 레벨 (1~3)
    equip1_level: int | None = None
    equip2_level: int | None = None
    equip3_level: int | None = None
    # 스탯
    stat_hp:   int | None = None
    stat_atk:  int | None = None
    stat_heal: int | None = None
    # 스킵 여부 (로그/분석용)
    skipped: bool = False

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


def _dict_to_student_entry(d: dict) -> StudentEntry:
    """repository 캐시 dict → StudentEntry 복원."""
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


# ── 스캐너 ────────────────────────────────────────────────
class Scanner:
    def __init__(
        self,
        regions: dict,
        on_progress: Callable[[str], None] | None = None,
        maxed_ids:   set[str] | None = None,
        maxed_cache: dict[str, dict] | None = None,
    ):
        """
        Parameters
        ----------
        regions      : load_regions() 결과
        on_progress  : 로그 콜백
        maxed_ids    : 만렙 판정된 student_id 집합 (스킵 대상)
        maxed_cache  : {student_id: dict} 형태의 기존 데이터 캐시
                       스킵 시 이 데이터를 StudentEntry로 변환해 반환
        """
        self.r           = regions
        self.log         = on_progress or print
        self._stop       = False
        self._maxed_ids  = frozenset(maxed_ids or [])
        self._maxed_cache: dict[str, dict] = maxed_cache or {}

        if self._maxed_ids:
            self.log(f"⏭ 만렙 스킵 대상: {len(self._maxed_ids)}명")

    def stop(self):
        self._stop = True

    # ── 만렙 스킵 판정 ────────────────────────────────────
    def _should_skip(self, student_id: str) -> bool:
        return student_id in self._maxed_ids

    def _make_skipped_entry(self, student_id: str) -> StudentEntry:
        """
        캐시에서 기존 데이터를 복원해 반환.
        캐시가 없으면 student_id만 채운 최소 entry 반환.
        """
        if student_id in self._maxed_cache:
            entry = _dict_to_student_entry(self._maxed_cache[student_id])
        else:
            entry = StudentEntry(
                student_id=student_id,
                display_name=student_names.display_name(student_id),
                skipped=True,
            )
        entry.skipped = True
        return entry

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
            for key, rk in [("크레딧", "credit_region"),
                             ("청휘석", "pyroxene_region")]:
                try:
                    crop = crop_ratio(img, lobby_r[rk])
                    result[key] = ocr.read_item_count(crop)
                except Exception as e:
                    result[key] = None
                    print(f"[Scanner] 재화 OCR 실패 ({key}): {e}")
        finally:
            ocr.unload()

        self.log(f"💰 청휘석={result.get('청휘석','-')}  크레딧={result.get('크레딧','-')}")
        return result

    # ── 공통 그리드 스캔 ──────────────────────────────────
    def _scan_grid(self, section: str, source: str, scroll_amount: int) -> list[ItemEntry]:
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

                entry = ItemEntry(name=name, quantity=count, source=source,
                                  index=len(items))
                k = entry.key()
                if k not in seen_keys:
                    seen_keys.add(k)
                    items.append(entry)
                    new_this += 1
                    self.log(f"  {icon} [{len(items):>3}] {name}  ×{count}")

            self.log(f"  스크롤 {scroll_i+1}회차: 신규 {new_this}개 / 누계 {len(items)}개")

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

    # ── 아이템/장비 스캔 ──────────────────────────────────
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
        self.log("━━━ 👩 학생 스캔 시작 (V5.2) ━━━")
        results: list[StudentEntry] = []

        skipped_count = 0
        scanned_count = 0

        try:
            if not self._open_student_menu():
                return []
            if not self._open_first_student():
                return []

            seen_ids: set[str]   = set()
            consecutive_dup: int = 0
            prev_id: str | None  = None

            for idx in range(500):
                if self._stop:
                    break

                # ── 학생 식별 ─────────────────────────────
                sid = self._identify_student(idx)
                if sid is None:
                    self.log(f"  ⚠️ [{idx+1}] 식별 실패 — 0.6초 후 재시도")
                    time.sleep(0.6)
                    sid = self._identify_student(idx)
                    if sid is None:
                        self.log(f"  ⚠️ [{idx+1}] 재시도도 실패 — 스캔 종료")
                        break

                # ── 중복/종료 판정 ────────────────────────
                if sid == prev_id:
                    consecutive_dup += 1
                    self.log(f"  🔁 이전과 동일: {sid} ({consecutive_dup}/{MAX_CONSECUTIVE_DUP})")
                    if consecutive_dup >= MAX_CONSECUTIVE_DUP:
                        self.log("  ✅ 연속 동일 → 마지막 학생, 스캔 종료")
                        break
                    self._restore_basic_info_tab()
                    self._move_to_next_student()
                    continue

                consecutive_dup = 0
                prev_id = sid

                if sid in seen_ids:
                    self.log(f"  🔁 이미 스캔됨: {sid} — 종료")
                    break
                seen_ids.add(sid)

                # ── 만렙 스킵 판정 ────────────────────────
                if self._should_skip(sid):
                    entry = self._make_skipped_entry(sid)
                    results.append(entry)
                    skipped_count += 1
                    self.log(
                        f"  ⏭ [{idx+1:>3}] {entry.label()} — 만렙 스킵 "
                        f"(누계 스킵:{skipped_count})"
                    )
                    # 스킵 시에도 next 버튼은 눌러야 함
                    self._restore_basic_info_tab()
                    self._move_to_next_student()
                    continue

                # ── 세부 스캔 ─────────────────────────────
                entry = StudentEntry(
                    student_id=sid,
                    display_name=student_names.display_name(sid),
                )
                self._read_skills_into(entry)
                self._read_weapon_into(entry)
                self._read_equipment_into(entry)
                self._read_level_into(entry)
                self._read_student_star_into(entry)
                self._read_stats_into(entry)

                results.append(entry)
                scanned_count += 1
                self._log_student(entry, len(results) - 1)

                self._restore_basic_info_tab()
                self._move_to_next_student()

        except Exception as e:
            self.log(f"❌ 학생 스캔 오류: {e}")
            import traceback; traceback.print_exc()
        finally:
            self._return_lobby()

        self.log(
            f"━━━ 👩 학생 스캔 완료: 총 {len(results)}명 "
            f"(스캔:{scanned_count} / 스킵:{skipped_count}) ━━━"
        )
        return results

    def scan_students(self) -> list[StudentEntry]:
        return self.scan_students_v5()

    # ─────────────────────────────────────────────────────────
    # 1. 학생 식별
    # ─────────────────────────────────────────────────────────
    def _identify_student(self, idx: int = 0) -> str | None:
        img = capture_window()
        if img is None:
            return None

        sr        = self.r["student"]
        texture_r = sr.get("student_texture_region")
        if not texture_r:
            self.log(f"  ⚠️ [{idx+1}] student_texture_region 미정의")
            return None

        sid, score = match_student_texture(crop_ratio(img, texture_r))
        if sid is not None:
            self.log(f"  🔍 [{idx+1}] {student_names.display_name(sid)} (score={score:.3f})")
            return sid

        self.log(f"  ⚠️ [{idx+1}] 텍스처 식별 실패 (score={score:.3f})")
        return None

    # ─────────────────────────────────────────────────────────
    # 2. 스킬 스캔
    # ─────────────────────────────────────────────────────────
    def _read_skills_into(self, entry: StudentEntry) -> None:
        rect = get_window_rect()
        if not rect:
            return

        sr = self.r["student"]
        skill_btn = sr.get("skill_menu_button")
        if not skill_btn:
            self.log("  ⚠️ skill_menu_button 미정의 — 스킬 스캔 생략")
            return

        click_center(rect, skill_btn, "skill_menu")
        time.sleep(0.5)

        img = capture_window()
        if img is None:
            self._close_skill_menu()
            return

        check_r = sr.get("skill_all_view_check_region")
        if check_r:
            if read_skill_check(crop_ratio(img, check_r)) == CheckFlag.FALSE:
                self.log("  🔘 스킬 일괄성장 체크 클릭")
                click_center(rect, check_r, "skill_check")
                time.sleep(0.3)
                img = capture_window()
                if img is None:
                    self._close_skill_menu()
                    return

        for field_name, region_key, tmpl_key in [
            ("ex_skill", "EX_skill",  "EX_Skill"),
            ("skill1",   "Skill_1",   "Skill1"),
            ("skill2",   "Skill_2",   "Skill2"),
            ("skill3",   "Skill_3",   "Skill3"),
        ]:
            region = sr.get(region_key)
            if region is None:
                self.log(f"  ⚠️ {region_key} 미정의 — {field_name} 생략")
                continue
            raw = read_skill(crop_ratio(img, region), tmpl_key)
            try:
                setattr(entry, field_name, int(raw))
            except (TypeError, ValueError):
                setattr(entry, field_name, None)

        self.log(
            f"  🎓 스킬: EX={entry.ex_skill} "
            f"S1={entry.skill1} S2={entry.skill2} S3={entry.skill3}"
        )
        self._close_skill_menu()

    def _close_skill_menu(self) -> None:
        press_esc()
        time.sleep(0.3)

    # ─────────────────────────────────────────────────────────
    # 3. 무기 상태 판정
    # ─────────────────────────────────────────────────────────
    def _read_weapon_into(self, entry: StudentEntry) -> None:
        img = capture_window()
        if img is None:
            entry.weapon_state = WeaponState.NO_WEAPON_SYSTEM
            return

        sr       = self.r["student"]
        weapon_r = sr.get("weapon_detect_flag_region") or sr.get("weapon_unlocked_flag")
        if not weapon_r:
            self.log("  ⚠️ weapon_detect_flag_region 미정의 → NO_WEAPON_SYSTEM")
            entry.weapon_state = WeaponState.NO_WEAPON_SYSTEM
            return

        state, score = detect_weapon_state(crop_ratio(img, weapon_r))
        entry.weapon_state = state
        self.log(f"  🗡 무기 상태: {state.name} (score={score:.3f})")

        if state == WeaponState.NO_WEAPON_SYSTEM:
            return

        if state == WeaponState.WEAPON_UNLOCKED_NOT_EQUIPPED:
            entry.weapon_star  = None
            entry.weapon_level = None
            self.log("  🗡 무기 미장착 — 레벨/성작 스킵")
            return

        rect = get_window_rect()
        if not rect:
            return

        menu_btn = sr.get("weapon_info_menu_button")
        if not menu_btn:
            self.log("  ⚠️ weapon_info_menu_button 미정의 — 무기 상세 생략")
            return

        click_center(rect, menu_btn, "weapon_info_menu")
        time.sleep(0.5)

        img = capture_window()
        if img is None:
            self._quit_weapon_menu()
            return

        star_r = sr.get("weapon_star_region")
        if star_r:
            entry.weapon_star = read_weapon_star_v5(crop_ratio(img, star_r))

        d1 = sr.get("weapon_level_digit_1") or sr.get("weapon_level_digit1")
        d2 = sr.get("weapon_level_digit_2") or sr.get("weapon_level_digit2")
        if d1 and d2:
            entry.weapon_level = read_weapon_level(img, d1, d2)
            self.log(f"  🗡 무기: {entry.weapon_star}★  Lv.{entry.weapon_level}")
        else:
            self.log("  ⚠️ weapon_level_digit 미정의 → weapon_level=None")

        self._quit_weapon_menu()

    def _quit_weapon_menu(self) -> None:
        press_esc()
        time.sleep(0.25)

    # ─────────────────────────────────────────────────────────
    # 4. 장비 스캔
    # ─────────────────────────────────────────────────────────
    def _read_equipment_into(self, entry: StudentEntry) -> None:
        rect = get_window_rect()
        if not rect:
            return

        sr        = self.r["student"]
        equip_btn = sr.get("equipment_button")
        if not equip_btn:
            self.log("  ⚠️ equipment_button 미정의 — 장비 스캔 생략")
            return

        img = capture_window()
        if img is None:
            return

        pre = read_equip_check(crop_ratio(img, equip_btn))
        if pre == CheckFlag.IMPOSSIBLE:
            self.log("  🚫 equipment_button=impossible — 장비 스캔 스킵")
            return

        click_center(rect, equip_btn, "equipment_tab")
        time.sleep(0.5)

        img = capture_window()
        if img is None:
            self._close_equipment_menu()
            return

        check_r = sr.get("equipment_all_view_check_region")
        if check_r:
            if read_equip_check_inside(crop_ratio(img, check_r)) == CheckFlag.FALSE:
                self.log("  🔘 장비 일괄성장 체크 클릭")
                click_center(rect, check_r, "equip_check")
                time.sleep(0.3)
                img = capture_window()
                if img is None:
                    self._close_equipment_menu()
                    return

        sid = entry.student_id or ""

        self._scan_equip_slot(entry, img, sr, 1,
                              skip_flags={EquipSlotFlag.EMPTY},
                              scan_level=True)
        self._scan_equip_slot(entry, img, sr, 2,
                              skip_flags={EquipSlotFlag.EMPTY, EquipSlotFlag.LEVEL_LOCKED},
                              scan_level=True)
        self._scan_equip_slot(entry, img, sr, 3,
                              skip_flags={EquipSlotFlag.EMPTY, EquipSlotFlag.LEVEL_LOCKED},
                              scan_level=True)

        # equip4: 해당 학생만 스캔, 그 외 스킵
        if has_equip4(sid):
            self._scan_equip_slot(entry, img, sr, 4,
                                  skip_flags={EquipSlotFlag.EMPTY,
                                              EquipSlotFlag.LOVE_LOCKED,
                                              EquipSlotFlag.NULL},
                                  scan_level=False)
        else:
            self.log(f"  🎒 장비4: {sid} 는 equip4 없음 — 스킵")

        self._close_equipment_menu()

    def _scan_equip_slot(
        self,
        entry: StudentEntry,
        img: Image.Image,
        sr: dict,
        slot: int,
        skip_flags: set[EquipSlotFlag],
        scan_level: bool,
    ) -> None:
        flag_r = (sr.get(f"equip{slot}_flag")
                  or sr.get(f"equip{slot}_emptyflag")
                  or sr.get(f"equip{slot}_empty_flag"))
        if flag_r:
            slot_flag = read_equip_slot_flag(crop_ratio(img, flag_r), slot)
            if slot_flag in skip_flags:
                self.log(f"  🎒 장비{slot}: {slot_flag.value} — 스킵")
                setattr(entry, f"equip{slot}", slot_flag.value)
                return

        tier_r = sr.get(f"equipment_{slot}")
        if tier_r:
            tier = read_equip_tier(crop_ratio(img, tier_r), slot)
            setattr(entry, f"equip{slot}", tier)
            self.log(f"  🎒 장비{slot} 티어: {tier}")

        if scan_level:
            d1 = sr.get(f"equipment_{slot}_level_digit_1")
            d2 = sr.get(f"equipment_{slot}_level_digit_2")
            if d1 and d2:
                lv = read_equip_level(img, slot, d1, d2)
                setattr(entry, f"equip{slot}_level", lv)
                self.log(f"  🎒 장비{slot} 레벨: {lv}")
            else:
                self.log(f"  ⚠️ equipment_{slot}_level_digit 미정의 — 생략")

    def _close_equipment_menu(self) -> None:
        press_esc()
        time.sleep(0.3)

    # ─────────────────────────────────────────────────────────
    # 5. 레벨 스캔
    # ─────────────────────────────────────────────────────────
    def _read_level_into(self, entry: StudentEntry) -> None:
        if entry.level == MAX_STUDENT_LEVEL:
            self.log(f"  ⏭ 레벨 스캔 생략: {entry.label()} (이미 Lv.90)")
            return

        rect = get_window_rect()
        if not rect:
            return

        sr     = self.r["student"]
        lv_btn = sr.get("levelcheck_button")
        if not lv_btn:
            self.log("  ⚠️ levelcheck_button 미정의 — 레벨 스캔 생략")
            return

        click_center(rect, lv_btn, "levelcheck_tab")
        time.sleep(0.4)

        img = capture_window()
        if img is None:
            self._restore_basic_info_tab()
            return

        lv = read_student_level_v5(img, sr["level_digit_1"], sr["level_digit_2"])
        entry.level = lv
        self.log(f"  📊 레벨: {entry.label()} → Lv.{lv}")

        self._restore_basic_info_tab()

    # ─────────────────────────────────────────────────────────
    # 6. 성작 스캔
    # ─────────────────────────────────────────────────────────
    def _read_student_star_into(self, entry: StudentEntry) -> None:
        if entry.weapon_state != WeaponState.NO_WEAPON_SYSTEM:
            entry.student_star = 5
            self.log(f"  ⏭ 성작 스캔 생략: {entry.label()} (무기 보유 → 5★)")
            return

        rect = get_window_rect()
        if not rect:
            return

        sr       = self.r["student"]
        star_btn = sr.get("star_menu_button")
        if star_btn:
            click_center(rect, star_btn, "star_menu")
            time.sleep(0.3)

        img = capture_window()
        if img is None:
            return

        region_key = "student_star_region" if "student_star_region" in sr else "star_region"
        star_r = sr.get(region_key)
        if star_r:
            entry.student_star = read_student_star_v5(crop_ratio(img, star_r))
            self.log(f"  ⭐ 성작: {entry.label()} → {entry.student_star}★")

    # ─────────────────────────────────────────────────────────
    # 7. 스탯 스캔 (Lv90 + 5★ 조건)
    # ─────────────────────────────────────────────────────────
    def _read_stats_into(self, entry: StudentEntry) -> None:
        level_ok = entry.level is not None and entry.level >= STAT_UNLOCK_LEVEL
        star_ok  = entry.student_star is not None and entry.student_star >= STAT_UNLOCK_STAR

        if not level_ok or not star_ok:
            self.log(
                f"  ⏭ 스탯 스캔 생략: {entry.label()} "
                f"(Lv.{entry.level} / {entry.student_star}★)"
            )
            return

        rect = get_window_rect()
        if not rect:
            return

        sr       = self.r["student"]
        stat_btn = sr.get("stat_menu_button")
        if not stat_btn:
            self.log("  ⚠️ stat_menu_button 미정의 — 스탯 스캔 생략")
            return

        click_center(rect, stat_btn, "stat_menu")
        time.sleep(0.4)

        img = capture_window()
        if img is None:
            self._close_stat_menu()
            return

        for stat_key, field_name, region_key in [
            ("hp",   "stat_hp",   "hp"),
            ("atk",  "stat_atk",  "atk"),
            ("heal", "stat_heal", "heal"),
        ]:
            region = sr.get(region_key)
            if region:
                val = read_stat_value(crop_ratio(img, region), stat_key)
                setattr(entry, field_name, val)
            else:
                self.log(f"  ⚠️ {region_key} region 미정의 — {stat_key} 생략")

        self.log(
            f"  📈 스탯: HP={entry.stat_hp} "
            f"ATK={entry.stat_atk} HEAL={entry.stat_heal}"
        )
        self._close_stat_menu()

    def _close_stat_menu(self) -> None:
        press_esc()
        time.sleep(0.3)

    # ─────────────────────────────────────────────────────────
    # 이동/로깅
    # ─────────────────────────────────────────────────────────
    def _open_student_menu(self) -> bool:
        rect = get_window_rect()
        if not rect:
            return False
        self.log("  학생 메뉴 진입...")
        click_center(rect, self.r["lobby"]["student_menu_button"], "student_menu")
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

    def _move_to_next_student(self) -> bool:
        rect = get_window_rect()
        if not rect:
            self.log("  ⚠️ 창 rect 없음")
            return False

        sr       = self.r["student"]
        next_btn = sr.get("next_student_button")
        if not next_btn:
            self.log("  ⚠️ next_student_button 미정의")
            return False

        click_center(rect, next_btn, "next_student")
        time.sleep(1.0)
        return True

    def _log_student(self, entry: StudentEntry, idx: int) -> None:
        weapon_info = ""
        if entry.weapon_state == WeaponState.WEAPON_EQUIPPED:
            weapon_info = f" | 무기:{entry.weapon_star}★ Lv.{entry.weapon_level}"
        elif entry.weapon_state == WeaponState.WEAPON_UNLOCKED_NOT_EQUIPPED:
            weapon_info = " | 무기:미장착"

        equip_info = (
            f"{entry.equip1}(Lv.{entry.equip1_level})/"
            f"{entry.equip2}(Lv.{entry.equip2_level})/"
            f"{entry.equip3}(Lv.{entry.equip3_level})/"
            f"{entry.equip4}"
        )

        self.log(
            f"  👩 [{idx+1:>3}] {entry.label()}  Lv.{entry.level}  "
            f"{entry.student_star}★{weapon_info}  "
            f"EX:{entry.ex_skill} S1:{entry.skill1} S2:{entry.skill2} S3:{entry.skill3}  "
            f"장비:{equip_info}  "
            f"스탯(HP:{entry.stat_hp}/ATK:{entry.stat_atk}/HEAL:{entry.stat_heal})"
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
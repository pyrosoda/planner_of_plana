"""
core/scanner.py — 스캔 자동화 엔진 v2
수정사항:
  - 아이템 스크롤 무한루프 방지: 슬롯 내용 해시 비교 추가
  - 장비 스크롤량 조정: -2로 축소
  - 학생 메뉴 로딩 대기: 3초
  - 학생 이름 OCR 후 이름 DB 교정
  - 전체 로그 강화
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
    read_student_star, read_weapon_star, read_weapon_unlocked,
    read_skill, read_equip_tier, read_student_level
)
import core.ocr as ocr
from core.student_names import correct_name
from core.item_names import correct_item_name

MAX_SCROLLS          = 60
SCROLL_ITEM          = -3   # 아이템 (5열×4행)
SCROLL_EQUIP         = -2   # 장비 (5열×5행, 더 촘촘)
SAME_THRESH          = 0.97
STUDENT_MENU_WAIT    = 3.0  # 학생 메뉴 로딩 대기
STUDENT_NEXT_WAIT    = 0.4
MAX_CONSECUTIVE_DUP  = 3    # 연속 중복 허용 횟수 (루프 탈출)


# ── 데이터 클래스 ──────────────────────────────────────────
@dataclass
class ItemEntry:
    name:     str | None
    quantity: str | None
    source:   str = "item"
    index:    int = 0      # 스캔 순서 (같은 이름 구별용)

    def key(self):
        # 중복 이름 허용 — index로 구분
        return f"{self.name}_{self.source}_{self.index}"


@dataclass
class StudentEntry:
    name:          str | None = None
    costume:       str | None = None   # 코스튬 버전 (수영복, 온천 등)
    level:         str | None = None
    stars:         int        = 0
    weapon_level:  str | None = None
    weapon_stars:  int        = 0
    weapon_locked: bool       = True
    ex_skill:      str        = "1"
    skill1:        str        = "1"
    skill2:        str        = "locked"
    skill3:        str        = "locked"
    equip1:        str        = "empty"
    equip2:        str        = "locked"
    equip3:        str        = "locked"
    equip4:        str        = "null"


@dataclass
class ScanResult:
    items:     list[ItemEntry]    = field(default_factory=list)
    equipment: list[ItemEntry]    = field(default_factory=list)
    students:  list[StudentEntry] = field(default_factory=list)
    resources: dict               = field(default_factory=dict)
    errors:    list[str]          = field(default_factory=list)


# ── 유틸 ──────────────────────────────────────────────────
def _img_hash(img: Image.Image) -> str:
    """이미지 해시 — 동일 화면 감지용"""
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
        self.r    = regions
        self.log  = on_progress or print
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

        self.log(f"💰 청휘석={result.get('청휘석', '-')}  크레딧={result.get('크레딧', '-')}")
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
        seen_keys:   set[str]  = set()   # 아이템 key 중복 방지
        seen_hashes: list[str] = []      # 화면 해시 히스토리 (무한루프 감지)
        icon = "📦" if source == "item" else "🔧"

        self.log(f"{icon} 그리드 스캔 시작 (슬롯 {len(slots)}개)")

        for scroll_i in range(MAX_SCROLLS):
            if self._stop:
                break

            img = capture_window()
            if img is None:
                break

            # 현재 화면 해시
            grid_crop = crop_ratio(img, grid_r)
            cur_hash  = _img_hash(grid_crop)

            # 이미 본 화면이면 루프 탈출
            if cur_hash in seen_hashes:
                self.log(f"  🔁 화면 반복 감지 → 스캔 종료 ({len(items)}개)")
                break
            seen_hashes.append(cur_hash)
            # 히스토리 최대 10개 유지
            if len(seen_hashes) > 10:
                seen_hashes.pop(0)

            new_this = 0

            for slot in slots:
                if self._stop:
                    break

                # 슬롯 상단 40% 클릭 (사용 버튼 회피)
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

            self.log(f"  스크롤 {scroll_i+1}회차: 신규 {new_this}개 / 누계 {len(items)}개")

            # 스크롤 전 그리드 저장
            before = crop_ratio(capture_window() or img, grid_r)
            scroll_at(rect, scroll_cx, scroll_cy, scroll_amount)
            time.sleep(0.15)

            after_img = capture_window()
            if after_img is None:
                break
            after = crop_ratio(after_img, grid_r)

            # 스크롤 후 화면 동일하면 끝
            if _images_similar(before, after):
                self.log(f"  ✅ 스크롤 끝 — 총 {len(items)}개")
                break

            # 새 항목 없고 3회 이상이면 종료
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

    # ── 학생 스캔 ─────────────────────────────────────────
    def scan_students(self) -> list[StudentEntry]:
        self._stop = False
        self.log("━━━ 👩 학생 스캔 시작 ━━━")

        students: list[StudentEntry] = []
        rect = get_window_rect()
        if not rect:
            return []

        sr      = self.r["student"]
        sm      = self.r["student_menu"]
        lobby_r = self.r["lobby"]

        try:
            ocr.load()

            # 학생 메뉴 진입
            self.log("  학생 메뉴 진입...")
            click_center(rect, lobby_r["student_menu_button"], "student_menu")
            time.sleep(STUDENT_MENU_WAIT)  # 로딩 대기 3초

            # 첫 학생 클릭
            self.log("  첫 학생 선택...")
            click_center(rect, sm["first_student_button"], "first_student")
            time.sleep(0.8)

            seen_names:   set[str] = set()
            dup_count:    int      = 0

            for idx in range(500):
                if self._stop:
                    break

                img = capture_window()
                if img is None:
                    break

                entry = StudentEntry()

                # 이름 OCR + 교정 (이름, 코스튬 분리)
                raw_name           = ocr.read_student_name(crop_ratio(img, sr["name_region"]))
                print(f"[RAW NAME OCR] '{raw_name}'")
                entry.name, entry.costume = correct_name(raw_name)

                # 레벨: 레벨업 탭 클릭 → digit 템플릿 매칭 → 기본 정보 탭 복귀
                click_center(rect, sr["levelcheck_button"], "levelcheck_tab")
                time.sleep(0.4)
                img_lv = capture_window()
                if img_lv:
                    entry.level = read_student_level(
                        img_lv,
                        sr["level_digit_1"],
                        sr["level_digit_2"]
                    )
                else:
                    entry.level = "?"
                # 기본 정보 탭으로 복귀 (레벨업 탭은 좌측 첫번째 탭)
                # 기본 정보 탭 좌표는 levelcheck_button 좌측에 위치
                # 스킬/무기 등을 읽기 위해 기본 탭으로 돌아가야 함
                # → 기본 정보 탭 좌표를 regions에 추가하거나 ESC로 복귀
                # 일단 같은 학생 화면 내에서 탭 전환이므로 기본정보 탭 클릭
                if "basic_info_button" in sr:
                    click_center(rect, sr["basic_info_button"], "basic_info_tab")
                    time.sleep(0.3)
                    img = capture_window() or img

                # 중복 감지
                if entry.name and entry.name in seen_names:
                    dup_count += 1
                    self.log(f"  🔁 중복: {entry.name} ({dup_count}/{MAX_CONSECUTIVE_DUP})")
                    if dup_count >= MAX_CONSECUTIVE_DUP:
                        self.log("  ✅ 연속 중복 → 스캔 종료")
                        break
                else:
                    dup_count = 0
                    if entry.name:
                        seen_names.add(entry.name)

                # 별 등급
                entry.stars = read_student_star(crop_ratio(img, sr["star_region"]))

                # 무기 (5성 이상만)
                if entry.stars >= 5:
                    unlocked = read_weapon_unlocked(
                        crop_ratio(img, sr["weapon_unlocked_flag"]))
                    entry.weapon_locked = not unlocked
                    if unlocked:
                        entry.weapon_stars = read_weapon_star(
                            crop_ratio(img, sr["weapon_star_region"]))
                        entry.weapon_level = ocr.read_weapon_level(
                            crop_ratio(img, sr["weapon_level_region"]))
                else:
                    entry.weapon_locked = True

                # 스킬 레벨
                entry.ex_skill = read_skill(crop_ratio(img, sr["ex_skill_region"]), "EX_Skill")
                entry.skill1   = read_skill(crop_ratio(img, sr["skill1_region"]),   "Skill1")
                entry.skill2   = read_skill(crop_ratio(img, sr["skill2_region"]),   "Skill2")
                entry.skill3   = read_skill(crop_ratio(img, sr["skill3_region"]),   "Skill3")

                # 장비 슬롯
                entry.equip1 = read_equip_tier(crop_ratio(img, sr["equipment1_region"]), 1)
                entry.equip2 = read_equip_tier(crop_ratio(img, sr["equipment2_region"]), 2)
                entry.equip3 = read_equip_tier(crop_ratio(img, sr["equipment3_region"]), 3)
                entry.equip4 = read_equip_tier(crop_ratio(img, sr["equipment4_region"]), 4)

                students.append(entry)
                weapon_info = ""
                if entry.stars >= 5:
                    w = "미해방" if entry.weapon_locked else f"{entry.weapon_stars}★ Lv.{entry.weapon_level}"
                    weapon_info = f" | 무기:{w}"
                costume_str = f"({entry.costume})" if entry.costume else ""
                self.log(
                    f"  👩 [{idx+1:>3}] {entry.name or '?'}{costume_str}  "
                    f"Lv.{entry.level}  {entry.stars}★{weapon_info}  "
                    f"EX:{entry.ex_skill} S1:{entry.skill1} "
                    f"S2:{entry.skill2} S3:{entry.skill3}  "
                    f"장비:{entry.equip1}/{entry.equip2}/{entry.equip3}/{entry.equip4}"
                )

                # 다음 학생
                next_btn = sr.get("next_student_button")
                if not next_btn:
                    break
                click_center(rect, next_btn, "next_student")
                time.sleep(STUDENT_NEXT_WAIT)

        except Exception as e:
            self.log(f"❌ 학생 스캔 오류: {e}")
            import traceback
            traceback.print_exc()
        finally:
            self._return_lobby()
            ocr.unload()

        self.log(f"━━━ 👩 학생 스캔 완료: {len(students)}명 ━━━")
        return students

    # ── 전체 스캔 ─────────────────────────────────────────
    def run_full_scan(self) -> ScanResult:
        self._stop = False
        result = ScanResult()
        self.log("━━━━━ 전체 스캔 시작 ━━━━━")
        result.resources = self.scan_resources()
        result.items     = self.scan_items()
        if not self._stop:
            result.equipment = self.scan_equipment()
        self.log("━━━━━ 전체 스캔 완료 ━━━━━")
        return result
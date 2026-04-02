from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from PIL import Image

# v5 프로젝트 루트를 import path에 추가
ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.config import load_regions  # noqa: E402
from core.matcher import (  # noqa: E402
    WeaponState,
    detect_weapon_state,
    match_student_texture,
    read_equip_tier,
    read_skill,
    read_student_level_v5,
    read_student_star_v5,
    read_weapon_star_v5,
)
import core.student_names as student_names  # noqa: E402


@dataclass
class OfflineStudentEntry:
    student_id: str | None = None
    display_name: str | None = None
    screenshot_path: str | None = None
    image_size: tuple[int, int] | None = None
    weapon_state: str | None = None
    weapon_state_score: float | None = None
    texture_score: float | None = None
    level: int | None = None
    student_star: int | None = None
    weapon_star: int | None = None
    ex_skill: int | None = None
    skill1: int | None = None
    skill2: int | None = None
    skill3: int | None = None
    equip1: str | None = None
    equip2: str | None = None
    equip3: str | None = None
    equip4: str | None = None
    notes: list[str] | None = None


def crop_ratio(img: Image.Image, region: dict) -> Image.Image:
    """v5 core.capture.crop_ratio와 동일한 비율 크롭."""
    w, h = img.size
    x1 = max(0, min(w, int(round(region["x1"] * w))))
    y1 = max(0, min(h, int(round(region["y1"] * h))))
    x2 = max(0, min(w, int(round(region["x2"] * w))))
    y2 = max(0, min(h, int(round(region["y2"] * h))))
    if x2 <= x1 or y2 <= y1:
        raise ValueError(f"잘못된 region: {region}")
    return img.crop((x1, y1, x2, y2))


def _safe_int(value: str | int | None) -> int | None:
    try:
        return int(value) if value not in (None, "unknown", "locked") else None
    except (TypeError, ValueError):
        return None


def _save_crop(debug_dir: Path | None, name: str, img: Image.Image) -> None:
    if debug_dir is None:
        return
    debug_dir.mkdir(parents=True, exist_ok=True)
    img.save(debug_dir / f"{name}.png")


class OfflineStudentExtractor:
    def __init__(self, debug_dir: Path | None = None):
        self.regions = load_regions()
        self.student_regions = self.regions["student"]
        self.debug_dir = debug_dir

    def extract_from_image(self, image_path: str | Path) -> OfflineStudentEntry:
        image_path = str(image_path)
        img = Image.open(image_path).convert("RGB")
        sr = self.student_regions
        notes: list[str] = []

        entry = OfflineStudentEntry(
            screenshot_path=image_path,
            image_size=img.size,
            notes=notes,
        )

        # 1) 학생 식별 (템플릿이 없으면 None 유지)
        texture_crop = crop_ratio(img, sr["student_texture_region"])
        _save_crop(self.debug_dir, "student_texture_region", texture_crop)
        sid, texture_score = match_student_texture(texture_crop)
        entry.texture_score = round(float(texture_score), 4)
        if sid is not None:
            entry.student_id = sid
            entry.display_name = student_names.display_name(sid)
        else:
            notes.append("학생 텍스처 식별 실패 또는 템플릿 부족")

        # 2) 기본 정보 화면에서 읽을 수 있는 정보
        ex_crop = crop_ratio(img, sr["ex_skill_region"])
        sk1_crop = crop_ratio(img, sr["skill1_region"])
        sk2_crop = crop_ratio(img, sr["skill2_region"])
        sk3_crop = crop_ratio(img, sr["skill3_region"])
        _save_crop(self.debug_dir, "ex_skill_region", ex_crop)
        _save_crop(self.debug_dir, "skill1_region", sk1_crop)
        _save_crop(self.debug_dir, "skill2_region", sk2_crop)
        _save_crop(self.debug_dir, "skill3_region", sk3_crop)

        entry.ex_skill = _safe_int(read_skill(ex_crop, "EX_Skill"))
        entry.skill1 = _safe_int(read_skill(sk1_crop, "Skill1"))
        entry.skill2 = _safe_int(read_skill(sk2_crop, "Skill2"))
        entry.skill3 = _safe_int(read_skill(sk3_crop, "Skill3"))

        eq1_crop = crop_ratio(img, sr["equipment1_region"])
        eq2_crop = crop_ratio(img, sr["equipment2_region"])
        eq3_crop = crop_ratio(img, sr["equipment3_region"])
        eq4_crop = crop_ratio(img, sr["equipment4_region"])
        _save_crop(self.debug_dir, "equipment1_region", eq1_crop)
        _save_crop(self.debug_dir, "equipment2_region", eq2_crop)
        _save_crop(self.debug_dir, "equipment3_region", eq3_crop)
        _save_crop(self.debug_dir, "equipment4_region", eq4_crop)

        entry.equip1 = read_equip_tier(eq1_crop, 1)
        entry.equip2 = read_equip_tier(eq2_crop, 2)
        entry.equip3 = read_equip_tier(eq3_crop, 3)
        entry.equip4 = read_equip_tier(eq4_crop, 4)

        # 3) 기본 화면에서 무기 상태 추정
        weapon_state_crop = crop_ratio(img, sr["weapon_detect_flag_region"])
        _save_crop(self.debug_dir, "weapon_detect_flag_region", weapon_state_crop)
        weapon_state, ws_score = detect_weapon_state(weapon_state_crop)
        entry.weapon_state = weapon_state.name
        entry.weapon_state_score = round(float(ws_score), 4)

        # 4) 레벨 화면 스크린샷이라면 level이 읽힘, 아니면 None일 수 있음
        level = read_student_level_v5(img, sr["level_digit_1"], sr["level_digit_2"])
        entry.level = level
        if level is None:
            notes.append("현재 스크린샷이 레벨 화면이 아니면 level=None 이 정상")

        # 5) 성작/무기성작도 해당 화면이 아닐 수 있으므로 None 가능
        student_star_crop = crop_ratio(img, sr["student_star_region"])
        weapon_star_crop = crop_ratio(img, sr["weapon_star_region"])
        _save_crop(self.debug_dir, "student_star_region", student_star_crop)
        _save_crop(self.debug_dir, "weapon_star_region", weapon_star_crop)

        entry.student_star = read_student_star_v5(student_star_crop)
        entry.weapon_star = read_weapon_star_v5(weapon_star_crop)
        if entry.student_star is None:
            notes.append("현재 스크린샷이 학생 성작 화면이 아니면 student_star=None 이 정상")
        if entry.weapon_star is None:
            notes.append("현재 스크린샷이 전용무기 화면이 아니면 weapon_star=None 이 정상")

        # 전용무기가 없다고 판정되면 무기성작은 자연스럽게 None
        if weapon_state == WeaponState.NO_WEAPON_SYSTEM:
            entry.weapon_star = None

        return entry


def entry_to_jsonable(entry: OfflineStudentEntry) -> dict[str, Any]:
    return asdict(entry)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="학생 상세 스크린샷에서 보이는 학생 정보를 추출합니다."
    )
    parser.add_argument("image", help="입력 스크린샷 경로")
    parser.add_argument(
        "--json-out",
        help="결과 JSON 저장 경로. 생략하면 콘솔에 출력합니다.",
        default=None,
    )
    parser.add_argument(
        "--debug-dir",
        help="잘라낸 리전 이미지를 저장할 폴더",
        default=None,
    )
    args = parser.parse_args()

    debug_dir = Path(args.debug_dir) if args.debug_dir else None
    extractor = OfflineStudentExtractor(debug_dir=debug_dir)
    entry = extractor.extract_from_image(args.image)
    payload = entry_to_jsonable(entry)

    if args.json_out:
        out_path = Path(args.json_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"저장 완료: {out_path}")
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

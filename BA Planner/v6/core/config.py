"""
Runtime configuration and storage-path helpers.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
TEMPLATE_DIR = BASE_DIR / "templates"
REGIONS_DIR = BASE_DIR / "regions"
CONFIG_FILE = BASE_DIR / "config.json"
PROFILES_DIR = BASE_DIR / "profiles"
LEGACY_DATA_DIR = BASE_DIR / "data"
LEGACY_DB_PATH = BASE_DIR / "ba_planner.db"
LEGACY_SCANS_DIR = BASE_DIR / "scans"

_REGION_COORD_KEYS = frozenset({"x1", "y1", "x2", "y2"})


@dataclass(frozen=True, slots=True)
class StoragePaths:
    profile_name: str
    profile_key: str
    root: Path
    data_dir: Path
    scans_dir: Path
    current_dir: Path
    history_dir: Path
    db_path: Path
    current_students_json: Path
    current_inventory_json: Path
    student_changes_json: Path
    inventory_changes_json: Path


def _is_region_dict(d: dict) -> bool:
    return _REGION_COORD_KEYS.issubset(d.keys())


def _unwrap_student_json(raw: dict) -> dict:
    if len(raw) != 1:
        return raw
    only_key = next(iter(raw))
    value = raw[only_key]
    if not isinstance(value, dict):
        return raw
    if _is_region_dict(value):
        return raw
    if all(isinstance(v, dict) for v in value.values()):
        return value
    return raw


_REGION_FILES: dict[str, str] = {
    "lobby_regions.json": "lobby",
    "menu_regions.json": "menu",
    "item_regions.json": "item",
    "equipment_regions.json": "equipment",
    "student_menu_regions.json": "student_menu",
}

_STUDENT_REGION_FILES: list[str] = [
    "student_data_regions.json",
    "student_normal_info_regions.json",
    "student_level_info_regions.json",
    "student_star_region.json",
    "student_equipment_regions.json",
    "student_skillmenu_regions.json",
    "student_statmenu_regions.json",
    "student_weaponmenu_regions.json",
]


def load_regions() -> dict:
    result: dict = {}

    for filename, top_key in _REGION_FILES.items():
        path = REGIONS_DIR / filename
        if not path.exists():
            raise FileNotFoundError(f"{filename} not found: {path}")
        raw = json.loads(path.read_text(encoding="utf-8"))
        result[top_key] = raw.get(top_key, raw)

    student: dict = {}
    for filename in _STUDENT_REGION_FILES:
        path = REGIONS_DIR / filename
        if not path.exists():
            raise FileNotFoundError(f"{filename} not found: {path}")
        raw = json.loads(path.read_text(encoding="utf-8"))
        student.update(_unwrap_student_json(raw))

    result["student"] = student
    return result


def load_app_config() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_app_config(data: dict) -> None:
    CONFIG_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def load_config() -> dict:
    return load_app_config()


def save_config(data: dict) -> None:
    save_app_config(data)


def normalize_profile_name(name: str) -> str:
    return " ".join((name or "").strip().split())


def make_profile_key(name: str) -> str:
    normalized = normalize_profile_name(name)
    if not normalized:
        raise ValueError("Profile name is empty")
    slug = re.sub(r"[^0-9A-Za-z._-]+", "_", normalized).strip("._-").lower()
    if not slug:
        slug = "profile"
    digest = hashlib.sha1(normalized.casefold().encode("utf-8")).hexdigest()[:8]
    return f"{slug}_{digest}"


def _ensure_profile_registry(config: dict) -> list[dict]:
    profiles = config.get("profiles")
    if isinstance(profiles, list):
        return profiles
    profiles = []
    config["profiles"] = profiles
    return profiles


def list_profiles() -> list[str]:
    config = load_app_config()
    profiles = _ensure_profile_registry(config)
    names: list[str] = []
    for profile in profiles:
        name = normalize_profile_name(str(profile.get("name", "")))
        if name and name not in names:
            names.append(name)
    return names


def _find_profile_entry(config: dict, name: str) -> dict | None:
    normalized = normalize_profile_name(name)
    if not normalized:
        return None
    profiles = _ensure_profile_registry(config)
    for profile in profiles:
        if normalize_profile_name(str(profile.get("name", ""))).casefold() == normalized.casefold():
            return profile
    return None


def get_active_profile_name(default: str | None = None) -> str | None:
    config = load_app_config()
    name = normalize_profile_name(str(config.get("active_profile", "")))
    if name:
        return name
    profiles = list_profiles()
    if profiles:
        return profiles[0]
    return default


def get_storage_paths(profile_name: str | None = None) -> StoragePaths:
    resolved_name = normalize_profile_name(profile_name or get_active_profile_name("") or "")
    if not resolved_name:
        raise RuntimeError("Active profile is not set")

    config = load_app_config()
    entry = _find_profile_entry(config, resolved_name)
    profile_key = str(entry.get("key")) if entry and entry.get("key") else make_profile_key(resolved_name)

    root = PROFILES_DIR / profile_key
    data_dir = root / "data"
    current_dir = data_dir / "current"
    history_dir = data_dir / "history"
    scans_dir = root / "scans"
    db_path = root / "ba_planner.db"

    return StoragePaths(
        profile_name=resolved_name,
        profile_key=profile_key,
        root=root,
        data_dir=data_dir,
        scans_dir=scans_dir,
        current_dir=current_dir,
        history_dir=history_dir,
        db_path=db_path,
        current_students_json=current_dir / "students.json",
        current_inventory_json=current_dir / "inventory.json",
        student_changes_json=history_dir / "student_changes.json",
        inventory_changes_json=history_dir / "inventory_changes.json",
    )


def ensure_profile_storage(profile_name: str) -> StoragePaths:
    paths = get_storage_paths(profile_name)

    paths.root.mkdir(parents=True, exist_ok=True)
    paths.data_dir.mkdir(parents=True, exist_ok=True)
    paths.current_dir.mkdir(parents=True, exist_ok=True)
    paths.history_dir.mkdir(parents=True, exist_ok=True)
    paths.scans_dir.mkdir(parents=True, exist_ok=True)

    defaults = {
        paths.current_students_json: "{}\n",
        paths.current_inventory_json: "{}\n",
        paths.student_changes_json: "[]\n",
        paths.inventory_changes_json: "[]\n",
    }
    for path, initial in defaults.items():
        if not path.exists():
            path.write_text(initial, encoding="utf-8")

    return paths


def _legacy_storage_has_data() -> bool:
    if LEGACY_DB_PATH.exists():
        return True
    candidates = (
        LEGACY_DATA_DIR / "current" / "students.json",
        LEGACY_DATA_DIR / "current" / "inventory.json",
        LEGACY_DATA_DIR / "history" / "student_changes.json",
        LEGACY_DATA_DIR / "history" / "inventory_changes.json",
    )
    for candidate in candidates:
        if candidate.exists() and candidate.read_text(encoding="utf-8", errors="ignore").strip() not in {"", "{}", "[]"}:
            return True
    return LEGACY_SCANS_DIR.exists() and any(LEGACY_SCANS_DIR.iterdir())


def maybe_migrate_legacy_storage(profile_name: str) -> None:
    if list_profiles():
        return
    if not _legacy_storage_has_data():
        return

    paths = ensure_profile_storage(profile_name)
    if paths.db_path.exists() and paths.db_path.stat().st_size > 0:
        return

    copy_pairs = (
        (LEGACY_DB_PATH, paths.db_path),
        (LEGACY_DATA_DIR / "current" / "students.json", paths.current_students_json),
        (LEGACY_DATA_DIR / "current" / "inventory.json", paths.current_inventory_json),
        (LEGACY_DATA_DIR / "history" / "student_changes.json", paths.student_changes_json),
        (LEGACY_DATA_DIR / "history" / "inventory_changes.json", paths.inventory_changes_json),
    )
    for source, target in copy_pairs:
        if not source.exists():
            continue
        if not target.exists():
            target_missing_or_empty = True
        elif target.suffix == ".db":
            target_missing_or_empty = target.stat().st_size == 0
        else:
            target_missing_or_empty = target.read_text(
                encoding="utf-8",
                errors="ignore",
            ).strip() in {"", "{}", "[]"}
        if target_missing_or_empty:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

    legacy_scans = LEGACY_DATA_DIR / "scans"
    if legacy_scans.exists() and not any(paths.scans_dir.iterdir()):
        for child in legacy_scans.iterdir():
            target = paths.scans_dir / child.name
            if child.is_dir():
                shutil.copytree(child, target, dirs_exist_ok=True)
            else:
                shutil.copy2(child, target)


def activate_profile(profile_name: str) -> StoragePaths:
    normalized = normalize_profile_name(profile_name)
    if not normalized:
        raise ValueError("Profile name is empty")

    config = load_app_config()
    profiles = _ensure_profile_registry(config)

    existing = _find_profile_entry(config, normalized)
    if existing is None:
        maybe_migrate_legacy_storage(normalized)
        existing = {
            "name": normalized,
            "key": make_profile_key(normalized),
        }
        profiles.append(existing)

    config["active_profile"] = existing["name"]
    save_app_config(config)
    return ensure_profile_storage(existing["name"])


def delete_profile(profile_name: str) -> bool:
    normalized = normalize_profile_name(profile_name)
    if not normalized:
        return False

    config = load_app_config()
    profiles = _ensure_profile_registry(config)
    existing = _find_profile_entry(config, normalized)
    if existing is None:
        return False

    profile_key = str(existing.get("key") or make_profile_key(normalized))
    profiles[:] = [profile for profile in profiles if profile is not existing]

    active_name = normalize_profile_name(str(config.get("active_profile", "")))
    if active_name.casefold() == normalized.casefold():
        config["active_profile"] = profiles[0]["name"] if profiles else ""

    save_app_config(config)

    profile_root = PROFILES_DIR / profile_key
    if profile_root.exists():
        shutil.rmtree(profile_root, ignore_errors=False)

    return True

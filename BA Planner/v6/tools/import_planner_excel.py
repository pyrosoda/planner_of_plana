from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET


ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


from tools.student_meta_tool import _write_students, get_students


NS_MAIN = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
NS_REL = {"rel": "http://schemas.openxmlformats.org/package/2006/relationships"}
CELL_RE = re.compile(r"([A-Z]+)(\d+)")
DEFAULT_SOURCE = ROOT_DIR / "planner_excel_temp.xlsx"
DEFAULT_OUTPUT_DIR = ROOT_DIR / "data" / "planning"


def col_to_index(col: str) -> int:
    out = 0
    for char in col:
        out = out * 26 + (ord(char) - ord("A") + 1)
    return out


def index_to_col(index: int) -> str:
    chars: list[str] = []
    value = index
    while value > 0:
        value, rem = divmod(value - 1, 26)
        chars.append(chr(ord("A") + rem))
    return "".join(reversed(chars))


def split_ref(cell_ref: str) -> tuple[str, int]:
    match = CELL_RE.fullmatch(cell_ref)
    if not match:
        raise ValueError(f"invalid cell ref: {cell_ref}")
    col, row = match.groups()
    return col, int(row)


def normalize_text(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.replace("\r", " ").replace("\n", " ").strip()
    return re.sub(r"\s+", " ", text)


def parse_number(text: str) -> Any:
    compact = text.replace(",", "").strip()
    if compact == "":
        return ""
    if re.fullmatch(r"-?\d+", compact):
        return int(compact)
    if re.fullmatch(r"-?\d+\.\d+", compact):
        number = float(compact)
        return int(number) if number.is_integer() else number
    return text


class WorkbookReader:
    def __init__(self, path: Path):
        self.path = path
        self.archive = zipfile.ZipFile(path)
        self.shared_strings = self._load_shared_strings()
        self.sheet_paths = self._load_sheet_paths()

    def close(self) -> None:
        self.archive.close()

    def _load_shared_strings(self) -> list[str]:
        if "xl/sharedStrings.xml" not in self.archive.namelist():
            return []
        root = ET.fromstring(self.archive.read("xl/sharedStrings.xml"))
        strings: list[str] = []
        for item in root.findall("main:si", NS_MAIN):
            parts = [node.text or "" for node in item.findall(".//main:t", NS_MAIN)]
            strings.append("".join(parts))
        return strings

    def _load_sheet_paths(self) -> dict[str, str]:
        workbook = ET.fromstring(self.archive.read("xl/workbook.xml"))
        rels = ET.fromstring(self.archive.read("xl/_rels/workbook.xml.rels"))
        rel_map = {
            rel.attrib["Id"]: rel.attrib["Target"]
            for rel in rels.findall("rel:Relationship", NS_REL)
        }
        paths: dict[str, str] = {}
        for sheet in workbook.findall("main:sheets/main:sheet", NS_MAIN):
            name = sheet.attrib["name"]
            rel_id = sheet.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]
            target = rel_map[rel_id]
            paths[name] = f"xl/{target.lstrip('/')}"
        return paths

    def load_sheet(self, name: str) -> dict[str, Any]:
        sheet_path = self.sheet_paths[name]
        root = ET.fromstring(self.archive.read(sheet_path))
        values: dict[str, Any] = {}
        for cell in root.findall(".//main:c", NS_MAIN):
            cell_ref = cell.attrib.get("r")
            if not cell_ref:
                continue
            cell_type = cell.attrib.get("t")
            value_node = cell.find("main:v", NS_MAIN)
            if value_node is None:
                inline = cell.find("main:is", NS_MAIN)
                if inline is not None:
                    text = "".join(node.text or "" for node in inline.findall(".//main:t", NS_MAIN))
                    values[cell_ref] = normalize_text(text)
                continue
            raw = value_node.text or ""
            if cell_type == "s":
                value = self.shared_strings[int(raw)]
            elif cell_type == "b":
                value = raw == "1"
            else:
                value = parse_number(raw)
            values[cell_ref] = normalize_text(value)
        return values


def get(sheet: dict[str, Any], ref: str, default: Any = "") -> Any:
    return sheet.get(ref, default)


def extract_rows(
    sheet: dict[str, Any],
    *,
    header_row: int,
    start_col: str,
    end_col: str,
    data_start_row: int,
    stop_when_blank_col: str,
) -> list[dict[str, Any]]:
    headers = [str(get(sheet, f"{index_to_col(col)}{header_row}", "")).strip() for col in range(col_to_index(start_col), col_to_index(end_col) + 1)]
    rows: list[dict[str, Any]] = []
    row = data_start_row
    while True:
        marker = get(sheet, f"{stop_when_blank_col}{row}", "")
        if marker in ("", None):
            break
        record: dict[str, Any] = {}
        for idx, header in enumerate(headers, start=col_to_index(start_col)):
            key = header or index_to_col(idx)
            record[key] = get(sheet, f"{index_to_col(idx)}{row}", "")
        rows.append(record)
        row += 1
    return rows


def extract_fixed_range(
    sheet: dict[str, Any],
    *,
    start_col: str,
    end_col: str,
    start_row: int,
    end_row: int,
) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for row in range(start_row, end_row + 1):
        current: list[Any] = []
        seen = False
        for col in range(col_to_index(start_col), col_to_index(end_col) + 1):
            value = get(sheet, f"{index_to_col(col)}{row}", "")
            if value not in ("", None):
                seen = True
            current.append(value)
        if seen:
            rows.append(current)
    return rows


def parse_reference_tables(sheet: dict[str, Any]) -> dict[str, Any]:
    return {
        "bd_table": {
            "title": get(sheet, "B2"),
            "rows": extract_rows(sheet, header_row=4, start_col="B", end_col="C", data_start_row=5, stop_when_blank_col="B"),
        },
        "note_table": {
            "title": get(sheet, "B2"),
            "rows": extract_rows(sheet, header_row=4, start_col="H", end_col="I", data_start_row=5, stop_when_blank_col="H"),
        },
        "credit_table_ex": {
            "title": get(sheet, "O2"),
            "rows": extract_rows(sheet, header_row=4, start_col="O", end_col="P", data_start_row=5, stop_when_blank_col="O"),
        },
        "credit_table_skill": {
            "title": get(sheet, "O2"),
            "rows": extract_rows(sheet, header_row=4, start_col="Q", end_col="R", data_start_row=5, stop_when_blank_col="Q"),
        },
        "character_weapon_level_credit": {
            "title": get(sheet, "T2"),
            "rows": extract_rows(sheet, header_row=4, start_col="T", end_col="X", data_start_row=5, stop_when_blank_col="T"),
        },
        "level_table": {
            "title": get(sheet, "AB2"),
            "rows": extract_rows(sheet, header_row=4, start_col="AB", end_col="AF", data_start_row=5, stop_when_blank_col="AB"),
        },
        "ability_unlock_table": {
            "title": "능력 개방 계산용 시트",
            "rows": extract_fixed_range(sheet, start_col="B", end_col="J", start_row=20, end_row=32),
        },
        "star_table": {
            "title": "성급 계산용 시트",
            "rows": extract_fixed_range(sheet, start_col="N", end_col="R", start_row=20, end_row=32),
        },
        "eleph_table": {
            "title": get(sheet, "AM2"),
            "rows": extract_rows(sheet, header_row=4, start_col="AM", end_col="AO", data_start_row=5, stop_when_blank_col="AM"),
        },
        "eleph_star_table": {
            "title": "엘레프 세부표",
            "rows": extract_fixed_range(sheet, start_col="N", end_col="R", start_row=36, end_row=47),
        },
    }


def parse_growth_patterns(sheet: dict[str, Any]) -> dict[str, Any]:
    family_blocks: list[tuple[str, str]] = []
    col = col_to_index("H")
    while col <= col_to_index("CF"):
        family = get(sheet, f"{index_to_col(col)}1", "")
        if family:
            family_blocks.append((index_to_col(col), str(family)))
        col += 4

    students: dict[str, dict[str, Any]] = {}
    current_name = ""
    for row in range(3, 2000):
        name = str(get(sheet, f"A{row}", "")).strip()
        if name:
            current_name = name
        if not current_name:
            continue
        skill_type = str(get(sheet, f"F{row}", "")).strip()
        level = get(sheet, f"G{row}", "")
        if skill_type == "" and level in ("", None):
            continue

        entry = students.setdefault(
            current_name,
            {
                "name": current_name,
                "base_star": get(sheet, f"B{row}", ""),
                "equipment_slots": [get(sheet, f"C{row}", ""), get(sheet, f"D{row}", ""), get(sheet, f"E{row}", "")],
                "artifact_families": [],
                "ex_rows": [],
                "normal_rows": [],
            },
        )
        materials: dict[str, list[Any]] = {}
        for start_col, family in family_blocks:
            values = [get(sheet, f"{index_to_col(col_to_index(start_col) + offset)}{row}", "") for offset in range(4)]
            if any(value not in ("", None, 0) for value in values):
                materials[family] = values
                if family not in entry["artifact_families"]:
                    entry["artifact_families"].append(family)

        row_data = {
            "level": level,
            "materials": materials,
        }
        if skill_type == "EX":
            entry["ex_rows"].append(row_data)
        else:
            entry["normal_rows"].append(row_data)

    return {
        "artifact_families": [family for _, family in family_blocks],
        "students": students,
    }


def parse_equipment_calc(sheet: dict[str, Any]) -> dict[str, Any]:
    headers = [str(get(sheet, f"{index_to_col(col)}4", "")).strip() for col in range(col_to_index("A"), col_to_index("M") + 1)]
    rows: list[dict[str, Any]] = []
    for row in range(5, 17):
        skill_level = get(sheet, f"A{row}", "")
        if skill_level in ("", None):
            continue
        entry: dict[str, Any] = {}
        for idx, header in enumerate(headers, start=col_to_index("A")):
            entry[header or index_to_col(idx)] = get(sheet, f"{index_to_col(idx)}{row}", "")
        rows.append(entry)
    return {
        "title": "장비 계산용 시트",
        "rows": rows,
    }


def parse_farmable_students(sheet: dict[str, Any]) -> dict[str, Any]:
    blocks = [("A", "F"), ("G", "L"), ("O", "T"), ("U", "Z")]
    entries: list[dict[str, Any]] = []
    names: list[str] = []
    for start_col, end_col in blocks:
        headers = [str(get(sheet, f"{index_to_col(col)}22", "")).strip() for col in range(col_to_index(start_col), col_to_index(end_col) + 1)]
        for row in range(23, 400):
            name = str(get(sheet, f"{start_col}{row}", "")).strip()
            if not name:
                continue
            entry: dict[str, Any] = {}
            for idx, header in enumerate(headers, start=col_to_index(start_col)):
                entry[header or index_to_col(idx)] = get(sheet, f"{index_to_col(idx)}{row}", "")
            entries.append(entry)
            names.append(name)
    return {
        "names": sorted(set(names)),
        "entries": entries,
    }


def update_farmable_metadata(farmable_names: list[str]) -> dict[str, Any]:
    students = get_students()
    display_name_map = {
        str(meta.get("display_name", "")).strip(): student_id
        for student_id, meta in students.items()
    }
    matched_ids: list[str] = []
    unmatched_names: list[str] = []
    for name in farmable_names:
        student_id = display_name_map.get(name)
        if student_id is None:
            unmatched_names.append(name)
            continue
        matched_ids.append(student_id)

    farmable_id_set = set(matched_ids)
    if not farmable_id_set:
        return {
            "farmable_ids": [],
            "matched_count": 0,
            "unmatched_names": unmatched_names,
            "updated_students": 0,
            "note": "No farmable student names were matched from the workbook; student metadata was left unchanged.",
        }

    changed = 0
    for student_id, meta in students.items():
        if student_id in farmable_id_set:
            if meta.get("farmable") != "yes":
                meta["farmable"] = "yes"
                changed += 1
        elif meta.get("farmable") == "yes":
            meta["farmable"] = "no"
            changed += 1

    if changed:
        _write_students(students)
    return {
        "farmable_ids": sorted(farmable_id_set),
        "matched_count": len(farmable_id_set),
        "unmatched_names": unmatched_names,
        "updated_students": changed,
    }


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def build_outputs(source_path: Path, output_dir: Path) -> dict[str, Any]:
    reader = WorkbookReader(source_path)
    try:
        sheet_data_1 = reader.load_sheet("자료1")
        sheet_data_2 = reader.load_sheet("자료2")
        sheet_equipment_calc = reader.load_sheet("자료_장비계산")
        sheet_equipment = reader.load_sheet("자료_장비")

        reference_tables = parse_reference_tables(sheet_data_1)
        growth_patterns = parse_growth_patterns(sheet_data_2)
        farmable = parse_farmable_students(sheet_equipment_calc)
        farmable_meta = update_farmable_metadata(farmable["names"])
        equipment_calc = parse_equipment_calc(sheet_equipment)
        equipment_progression = parse_equipment_calc(sheet_equipment_calc)

        write_json(output_dir / "reference_tables.json", reference_tables)
        write_json(output_dir / "student_growth_patterns.json", growth_patterns)
        write_json(output_dir / "equipment_calc.json", equipment_calc)
        write_json(output_dir / "equipment_progression.json", equipment_progression)
        write_json(
            output_dir / "farmable_students.json",
            {
                "names": farmable["names"],
                "entries": farmable["entries"],
                "metadata_update": farmable_meta,
            },
        )

        return {
            "reference_tables": str(output_dir / "reference_tables.json"),
            "student_growth_patterns": str(output_dir / "student_growth_patterns.json"),
            "equipment_calc": str(output_dir / "equipment_calc.json"),
            "equipment_progression": str(output_dir / "equipment_progression.json"),
            "farmable_students": str(output_dir / "farmable_students.json"),
            "metadata_update": farmable_meta,
        }
    finally:
        reader.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract planning data from planner_excel_temp.xlsx")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--delete-source", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = build_outputs(args.source, args.output_dir)
    if args.delete_source:
        args.source.unlink()
        result["deleted_source"] = str(args.source)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import json
import os
import csv
import re
import sqlite3
import zipfile
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape as xml_escape


TACTICAL_DATA_VERSION = 2
TACTICAL_STRIKER_SLOTS = 4
TACTICAL_SUPPORT_SLOTS = 2
XLSX_MAIN_NS = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
XLSX_REL_NS = {"rel": "http://schemas.openxmlformats.org/package/2006/relationships"}
XLSX_CELL_RE = re.compile(r"([A-Z]+)(\d+)")
TACTICAL_IMPORT_HEADERS = (
    "구분",
    "날짜",
    "시즌",
    "상대",
    "승패",
    "공격1",
    "공격2",
    "공격3",
    "공격4",
    "공격SP1",
    "공격SP2",
    "방어1",
    "방어2",
    "방어3",
    "방어4",
    "방어SP1",
    "방어SP2",
    "출처",
    "메모",
    "id",
)
TACTICAL_IMPORT_README = """# 전술대항전 가져오기 템플릿 입력법

이 파일은 `tactical_challenge_import_template.xlsx`에 데이터를 입력한 뒤 앱의 `Excel Import` 버튼으로 가져오기 위한 설명서입니다.

## 기본 흐름

1. `tactical_challenge_import_template.xlsx`를 엽니다.
2. 1행의 헤더는 지우지 않습니다.
3. 2행부터 데이터를 입력합니다.
4. 앱의 전술대항전 탭에서 `Excel Import` 버튼을 누릅니다.
5. 정상 행은 DB로 가져오고 템플릿에서 지웁니다.
6. 문제가 있는 행은 가져오지 않고 템플릿에 남깁니다. `오류` 컬럼에 확인할 내용이 표시됩니다.
7. 모든 행이 정상이라면 템플릿은 헤더만 남기고 자동으로 비워집니다.

## 공통 컬럼

- `구분`: `공격`, `방어`, `족보` 중 하나를 입력합니다. 비워두면 공격 기록으로 처리합니다.
- `날짜`: 전적 날짜입니다. 예: `2026-04-30`. 비워두면 날짜 없음 상태로 저장되며 전적 목록 맨 아래에 정렬됩니다.
- `시즌`: 시즌명입니다. 비워두면 앱에 저장된 현재 시즌을 사용합니다.
- `상대`: 상대 이름입니다. 족보 행에서는 필요 없습니다.
- `승패`: `승` 또는 `패`를 입력합니다. `win`, `loss`도 인식합니다. 비워두면 `패`로 처리합니다.
- `출처`: `내 기록`, `타인 전적`, `커뮤니티`, `영상`, `미상`처럼 데이터 출처를 입력합니다. 비워두면 `내 기록`으로 처리합니다.
- `메모`: 자유 메모입니다.
- `id`: 선택 사항입니다. 비워두면 자동 생성됩니다. 같은 id로 다시 가져오면 기존 기록을 덮어씁니다.

## 덱 입력 컬럼

공격덱은 아래 6칸에 한 명씩 입력합니다.

- `공격1`, `공격2`, `공격3`, `공격4`
- `공격SP1`, `공격SP2`

방어덱은 아래 6칸에 한 명씩 입력합니다.

- `방어1`, `방어2`, `방어3`, `방어4`
- `방어SP1`, `방어SP2`

학생 이름은 앱의 덱 입력과 같은 규칙으로 인식합니다.

- 예: `츠바키`, `네루(바니걸)`, `하나코(수영복)`
- `네루 (바니걸)`처럼 괄호 앞에 공백이 있어도 인식합니다.
- 줄임말 사전에 등록한 한 글자도 사용할 수 있습니다.
- 스트라이커 칸에는 스트라이커만, SP 칸에는 스페셜만 넣을 수 있습니다.

## 구분별 입력법

### 공격 기록

내가 공격한 전적입니다.

- `구분`: `공격` 또는 빈칸
- `공격1~공격SP2`: 내가 사용한 공격덱
- `방어1~방어SP2`: 상대 방어덱
- `상대` 필요. `날짜`를 비우면 날짜 없음 상태로 저장되고, `승패`를 비우면 패로 처리합니다.

### 방어 기록

상대가 내 방어덱을 공격한 전적입니다.

- `구분`: `방어`
- `공격1~공격SP2`: 상대 공격덱
- `방어1~방어SP2`: 내 방어덱
- `상대` 필요. `날짜`를 비우면 날짜 없음 상태로 저장되고, `승패`를 비우면 패로 처리합니다.

### 족보

방어덱과 그에 대응하는 공격덱 페어를 등록합니다.

- `구분`: `족보`
- `공격1~공격SP2`: 추천 공격덱
- `방어1~방어SP2`: 대상 방어덱
- `메모` 입력 가능
- `날짜`, `상대`, `승패`는 사용하지 않습니다.

## 한 칸 덱 문자열도 지원

기존 방식처럼 한 칸에 덱 문자열을 넣는 파일도 읽을 수 있습니다.

- `공격덱`: `츠바키,네루(바니걸),에이미,하나코(수영복)|히비키,사키`
- `방어덱`: `츠바키,네루(바니걸),에이미,하나코(수영복)|히비키,시로코(수영복)`

다만 대량 입력에는 6열 방식이 더 편합니다.
"""


@dataclass(slots=True)
class TacticalDeck:
    strikers: list[str] = field(default_factory=list)
    supports: list[str] = field(default_factory=list)


@dataclass(slots=True)
class TacticalMatch:
    id: str
    date: str
    opponent: str
    result: str
    season: str = ""
    my_attack: TacticalDeck = field(default_factory=TacticalDeck)
    opponent_defense: TacticalDeck = field(default_factory=TacticalDeck)
    my_defense: TacticalDeck = field(default_factory=TacticalDeck)
    opponent_attack: TacticalDeck = field(default_factory=TacticalDeck)
    source: str = "내 기록"
    notes: str = ""
    created_at: str = ""


@dataclass(slots=True)
class TacticalJokboEntry:
    id: str
    defense: TacticalDeck = field(default_factory=TacticalDeck)
    attack: TacticalDeck = field(default_factory=TacticalDeck)
    wins: int = 0
    losses: int = 0
    notes: str = ""
    updated_at: str = ""


@dataclass(slots=True)
class TacticalChallengeData:
    version: int = TACTICAL_DATA_VERSION
    season: str = ""
    matches: list[TacticalMatch] = field(default_factory=list)
    jokbo: list[TacticalJokboEntry] = field(default_factory=list)
    abbreviations: dict[str, str] = field(default_factory=dict)
    special_abbreviations: dict[str, str] = field(default_factory=dict)


def _clean_name(value: object) -> str:
    return " ".join(str(value or "").strip().split())


def _normalize_slots(values: list[Any], slot_count: int) -> list[str]:
    slots = [_clean_name(item) for item in list(values)[:slot_count]]
    while slots and not slots[-1]:
        slots.pop()
    return slots


def normalize_deck(deck: TacticalDeck | dict[str, Any] | None) -> TacticalDeck:
    if isinstance(deck, TacticalDeck):
        raw_strikers = deck.strikers
        raw_supports = deck.supports
    elif isinstance(deck, dict):
        raw_strikers = deck.get("strikers") or []
        raw_supports = deck.get("supports") or []
    else:
        raw_strikers = []
        raw_supports = []
    return TacticalDeck(
        strikers=_normalize_slots(list(raw_strikers), TACTICAL_STRIKER_SLOTS),
        supports=_normalize_slots(list(raw_supports), TACTICAL_SUPPORT_SLOTS),
    )


def deck_signature(deck: TacticalDeck | dict[str, Any] | None) -> str:
    normalized = normalize_deck(deck)
    strikers = "|".join(item.casefold() for item in normalized.strikers)
    supports = "|".join(item.casefold() for item in normalized.supports)
    return f"s:{strikers};p:{supports}"


def _fixed_compare_slots(values: list[str], slot_count: int) -> list[str]:
    slots = [_clean_name(item).casefold() for item in values[:slot_count]]
    slots += [""] * max(0, slot_count - len(slots))
    return slots


def _is_deck_wildcard(value: str) -> bool:
    return _clean_name(value) == "*"


def defense_deck_has_wildcard(deck: TacticalDeck | dict[str, Any] | None) -> bool:
    normalized = normalize_deck(deck)
    return any(_is_deck_wildcard(item) for item in [*normalized.strikers, *normalized.supports])


def defense_deck_matches(pattern: TacticalDeck | dict[str, Any] | None, candidate: TacticalDeck | dict[str, Any] | None) -> bool:
    pattern_deck = normalize_deck(pattern)
    candidate_deck = normalize_deck(candidate)
    if not any(pattern_deck.strikers) and not any(pattern_deck.supports):
        return True

    pattern_strikers = _fixed_compare_slots(pattern_deck.strikers, TACTICAL_STRIKER_SLOTS)
    candidate_strikers = _fixed_compare_slots(candidate_deck.strikers, TACTICAL_STRIKER_SLOTS)
    for pattern_slot, candidate_slot in zip(pattern_strikers, candidate_strikers):
        if pattern_slot == "*":
            continue
        if pattern_slot != candidate_slot:
            return False

    pattern_supports = _fixed_compare_slots(pattern_deck.supports, TACTICAL_SUPPORT_SLOTS)
    candidate_supports = _fixed_compare_slots(candidate_deck.supports, TACTICAL_SUPPORT_SLOTS)

    def _supports_match(candidate_order: list[str]) -> bool:
        for pattern_slot, candidate_slot in zip(pattern_supports, candidate_order):
            if pattern_slot == "*":
                continue
            if pattern_slot != candidate_slot:
                return False
        return True

    return _supports_match(candidate_supports) or _supports_match(list(reversed(candidate_supports)))


def defense_deck_signature(deck: TacticalDeck | dict[str, Any] | None) -> str:
    normalized = normalize_deck(deck)
    if not any(normalized.strikers) and not any(normalized.supports):
        return "s:;p:"
    strikers = "|".join(item.casefold() for item in normalized.strikers)
    support_slots = list(normalized.supports[:TACTICAL_SUPPORT_SLOTS])
    support_slots += [""] * max(0, TACTICAL_SUPPORT_SLOTS - len(support_slots))
    supports = "|".join(sorted(item.casefold() for item in support_slots))
    return f"s:{strikers};p:{supports}"


def defense_deck_template_variants(deck: TacticalDeck | dict[str, Any] | None) -> list[str]:
    normalized = normalize_deck(deck)
    base = deck_template(normalized)
    if not base:
        return []
    supports = list(normalized.supports[:TACTICAL_SUPPORT_SLOTS])
    supports += [""] * max(0, TACTICAL_SUPPORT_SLOTS - len(supports))
    swapped = deck_template(TacticalDeck(strikers=normalized.strikers, supports=list(reversed(supports))))
    return list(dict.fromkeys(template for template in (base, swapped) if template))


def deck_label(deck: TacticalDeck | dict[str, Any] | None, *, empty: str = "-") -> str:
    normalized = normalize_deck(deck)
    parts: list[str] = []
    if any(normalized.strikers):
        parts.append("STR " + " / ".join(item or "-" for item in normalized.strikers))
    if any(normalized.supports):
        parts.append("SP " + " / ".join(item or "-" for item in normalized.supports))
    return " | ".join(parts) if parts else empty


def deck_template(deck: TacticalDeck | dict[str, Any] | None) -> str:
    normalized = normalize_deck(deck)
    if not any(normalized.strikers) and not any(normalized.supports):
        return ""

    def _fixed_slots(values: list[str], slot_count: int) -> list[str]:
        slots = values[:slot_count]
        slots += [""] * max(0, slot_count - len(slots))
        return slots

    strikers = _fixed_slots(normalized.strikers, TACTICAL_STRIKER_SLOTS)
    supports = _fixed_slots(normalized.supports, TACTICAL_SUPPORT_SLOTS)
    return f"{','.join(strikers)}|{','.join(supports)}"


def parse_deck_template(value: str) -> TacticalDeck:
    raw = str(value or "").strip()
    if not raw:
        return TacticalDeck()
    if "|" in raw:
        striker_raw, support_raw = raw.split("|", 1)
    else:
        striker_raw, support_raw = raw, ""

    def _parts(part: str) -> list[str]:
        normalized = part.replace("/", ",").replace(";", ",")
        return [_clean_name(item) for item in normalized.split(",")]

    return normalize_deck(TacticalDeck(strikers=_parts(striker_raw), supports=_parts(support_raw)))


def _xlsx_col_to_index(col: str) -> int:
    out = 0
    for char in col:
        out = out * 26 + (ord(char) - ord("A") + 1)
    return out


def _xlsx_index_to_col(index: int) -> str:
    chars: list[str] = []
    value = index
    while value > 0:
        value, rem = divmod(value - 1, 26)
        chars.append(chr(ord("A") + rem))
    return "".join(reversed(chars))


def _xlsx_cell_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return _clean_name(value)


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    encoding = "utf-8-sig"
    delimiter = "\t" if path.suffix.casefold() == ".tsv" else ","
    with path.open("r", encoding=encoding, newline="") as handle:
        reader = csv.DictReader(handle, delimiter=delimiter)
        return [
            {_clean_name(key): _xlsx_cell_text(value) for key, value in row.items() if _clean_name(key)}
            for row in reader
        ]


def _xlsx_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    strings: list[str] = []
    for item in root.findall("main:si", XLSX_MAIN_NS):
        strings.append("".join(node.text or "" for node in item.findall(".//main:t", XLSX_MAIN_NS)))
    return strings


def _xlsx_first_sheet_path(archive: zipfile.ZipFile) -> str:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    rel_map = {
        rel.attrib["Id"]: rel.attrib["Target"]
        for rel in rels.findall("rel:Relationship", XLSX_REL_NS)
    }
    sheet = workbook.find("main:sheets/main:sheet", XLSX_MAIN_NS)
    if sheet is None:
        raise ValueError("엑셀 파일에 시트가 없습니다.")
    rel_id = sheet.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]
    target = rel_map[rel_id].lstrip("/")
    return target if target.startswith("xl/") else f"xl/{target}"


def _read_xlsx_rows(path: Path) -> list[dict[str, str]]:
    with zipfile.ZipFile(path) as archive:
        shared_strings = _xlsx_shared_strings(archive)
        sheet_path = _xlsx_first_sheet_path(archive)
        root = ET.fromstring(archive.read(sheet_path))
        grid: dict[int, dict[int, str]] = defaultdict(dict)
        for cell in root.findall(".//main:c", XLSX_MAIN_NS):
            ref = cell.attrib.get("r", "")
            match = XLSX_CELL_RE.fullmatch(ref)
            if not match:
                continue
            col, row_text = match.groups()
            row = int(row_text)
            column = _xlsx_col_to_index(col)
            cell_type = cell.attrib.get("t")
            value_node = cell.find("main:v", XLSX_MAIN_NS)
            if value_node is None:
                inline = cell.find("main:is", XLSX_MAIN_NS)
                if inline is None:
                    continue
                value = "".join(node.text or "" for node in inline.findall(".//main:t", XLSX_MAIN_NS))
            else:
                raw = value_node.text or ""
                if cell_type == "s":
                    value = shared_strings[int(raw)] if raw else ""
                elif cell_type == "b":
                    value = "TRUE" if raw == "1" else "FALSE"
                else:
                    value = raw
            grid[row][column] = _xlsx_cell_text(value)

    if not grid:
        return []
    header_row = min(grid)
    headers = {
        column: _clean_name(value)
        for column, value in grid[header_row].items()
        if _clean_name(value)
    }
    rows: list[dict[str, str]] = []
    for row_index in sorted(row for row in grid if row > header_row):
        row_values = grid[row_index]
        record = {
            header: _xlsx_cell_text(row_values.get(column))
            for column, header in headers.items()
        }
        if any(record.values()):
            rows.append(record)
    return rows


def read_tactical_import_rows(path: Path) -> list[dict[str, str]]:
    suffix = path.suffix.casefold()
    if suffix in {".csv", ".tsv"}:
        return _read_csv_rows(path)
    if suffix == ".xlsx":
        return _read_xlsx_rows(path)
    raise ValueError("지원하는 파일 형식은 .xlsx, .csv, .tsv 입니다.")


def _tactical_import_headers_for_rows(rows: list[dict[str, str]]) -> list[str]:
    headers = list(TACTICAL_IMPORT_HEADERS)
    for row in rows:
        for key in row:
            header = _clean_name(key)
            if header and header not in headers:
                headers.append(header)
    return headers


def _write_tactical_import_csv(path: Path, rows: list[dict[str, str]] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = rows or []
    headers = _tactical_import_headers_for_rows(rows)
    delimiter = "\t" if path.suffix.casefold() == ".tsv" else ","
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle, delimiter=delimiter)
        writer.writerow(headers)
        for row in rows:
            writer.writerow([_xlsx_cell_text(row.get(header, "")) for header in headers])


def _write_tactical_import_xlsx(path: Path, rows: list[dict[str, str]] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = rows or []
    headers = _tactical_import_headers_for_rows(rows)
    sheet_rows: list[str] = []
    for row_index, row_values in enumerate([dict.fromkeys(headers, "")] + rows, start=1):
        cells: list[str] = []
        for column_index, header in enumerate(headers, start=1):
            ref = f"{_xlsx_index_to_col(column_index)}{row_index}"
            value = header if row_index == 1 else _xlsx_cell_text(row_values.get(header, ""))
            cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{xml_escape(value)}</t></is></c>')
        sheet_rows.append(f'<row r="{row_index}">{"".join(cells)}</row>')
    sheet_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        "<sheetData>"
        + "".join(sheet_rows)
        + "</sheetData></worksheet>"
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            "</Types>",
        )
        archive.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            "</Relationships>",
        )
        archive.writestr(
            "xl/workbook.xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="Tactical Import" sheetId="1" r:id="rId1"/></sheets>'
            "</workbook>",
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            "</Relationships>",
        )
        archive.writestr("xl/worksheets/sheet1.xml", sheet_xml)


def write_tactical_import_template(path: Path) -> None:
    if path.suffix.casefold() in {".csv", ".tsv"}:
        _write_tactical_import_csv(path)
        return
    if path.suffix.casefold() == ".xlsx":
        _write_tactical_import_xlsx(path)
        return
    raise ValueError("지원하는 템플릿 형식은 .xlsx, .csv, .tsv 입니다.")


def write_tactical_import_rows(path: Path, rows: list[dict[str, str]]) -> None:
    if path.suffix.casefold() in {".csv", ".tsv"}:
        _write_tactical_import_csv(path, rows)
        return
    if path.suffix.casefold() == ".xlsx":
        _write_tactical_import_xlsx(path, rows)
        return
    raise ValueError("지원하는 템플릿 형식은 .xlsx, .csv, .tsv 입니다.")


def tactical_import_readme_path(template_path: Path) -> Path:
    return template_path.with_name("tactical_challenge_import_README.md")


def write_tactical_import_readme(template_path: Path) -> Path:
    readme_path = tactical_import_readme_path(template_path)
    readme_path.parent.mkdir(parents=True, exist_ok=True)
    readme_path.write_text(TACTICAL_IMPORT_README, encoding="utf-8")
    return readme_path


def ensure_tactical_import_readme(template_path: Path) -> Path:
    readme_path = tactical_import_readme_path(template_path)
    if not readme_path.exists() or readme_path.read_text(encoding="utf-8") != TACTICAL_IMPORT_README:
        write_tactical_import_readme(template_path)
    return readme_path


def ensure_tactical_import_template(path: Path) -> None:
    if not path.exists():
        write_tactical_import_template(path)
        ensure_tactical_import_readme(path)
        return
    try:
        if not read_tactical_import_rows(path):
            write_tactical_import_template(path)
    except Exception:
        return
    ensure_tactical_import_readme(path)


def clear_tactical_import_template(path: Path) -> None:
    write_tactical_import_template(path)


def _deck_contains_query(deck: TacticalDeck, query: str) -> bool:
    if not query:
        return True
    haystack = deck_label(deck).casefold()
    return query.casefold() in haystack


def _match_from_dict(payload: dict[str, Any]) -> TacticalMatch | None:
    try:
        valid_fields = {item.name for item in fields(TacticalMatch)}
        filtered = {key: value for key, value in payload.items() if key in valid_fields}
        filtered["my_attack"] = normalize_deck(filtered.get("my_attack"))
        filtered["opponent_defense"] = normalize_deck(filtered.get("opponent_defense"))
        filtered["my_defense"] = normalize_deck(filtered.get("my_defense"))
        filtered["opponent_attack"] = normalize_deck(filtered.get("opponent_attack"))
        filtered["id"] = _clean_name(filtered.get("id"))
        filtered["date"] = _clean_name(filtered.get("date"))
        filtered["season"] = _clean_name(filtered.get("season"))
        filtered["opponent"] = _clean_name(filtered.get("opponent"))
        filtered["result"] = _clean_name(filtered.get("result")) or "win"
        filtered["source"] = _clean_name(filtered.get("source")) or "내 기록"
        filtered["notes"] = str(filtered.get("notes") or "")
        filtered["created_at"] = _clean_name(filtered.get("created_at"))
        if not filtered["id"]:
            return None
        return TacticalMatch(**filtered)
    except Exception:
        return None


def _jokbo_from_dict(payload: dict[str, Any]) -> TacticalJokboEntry | None:
    try:
        valid_fields = {item.name for item in fields(TacticalJokboEntry)}
        filtered = {key: value for key, value in payload.items() if key in valid_fields}
        filtered["defense"] = normalize_deck(filtered.get("defense"))
        filtered["attack"] = normalize_deck(filtered.get("attack"))
        filtered["id"] = _clean_name(filtered.get("id"))
        filtered["wins"] = max(0, int(filtered.get("wins") or 0))
        filtered["losses"] = max(0, int(filtered.get("losses") or 0))
        filtered["notes"] = str(filtered.get("notes") or "")
        filtered["updated_at"] = _clean_name(filtered.get("updated_at"))
        if not filtered["id"]:
            return None
        return TacticalJokboEntry(**filtered)
    except Exception:
        return None


def _deck_to_dict(deck: TacticalDeck) -> dict[str, list[str]]:
    normalized = normalize_deck(deck)
    return asdict(normalized)


def _match_to_dict(match: TacticalMatch) -> dict[str, Any]:
    payload = asdict(match)
    for key in ("my_attack", "opponent_defense", "my_defense", "opponent_attack"):
        payload[key] = _deck_to_dict(getattr(match, key))
    return payload


def _jokbo_to_dict(entry: TacticalJokboEntry) -> dict[str, Any]:
    payload = asdict(entry)
    payload["defense"] = _deck_to_dict(entry.defense)
    payload["attack"] = _deck_to_dict(entry.attack)
    return payload


def _load_tactical_json(path: Path) -> TacticalChallengeData:
    if not path.exists():
        return TacticalChallengeData()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return TacticalChallengeData()
    matches = [
        match
        for match in (_match_from_dict(item) for item in payload.get("matches", []))
        if match is not None
    ]
    jokbo = [
        entry
        for entry in (_jokbo_from_dict(item) for item in payload.get("jokbo", []))
        if entry is not None
    ]
    return TacticalChallengeData(
        version=int(payload.get("version") or TACTICAL_DATA_VERSION),
        season=_clean_name(payload.get("season")),
        matches=matches,
        jokbo=jokbo,
        abbreviations={
            _clean_name(key): _clean_name(value)
            for key, value in (payload.get("abbreviations") or {}).items()
            if _clean_name(key) and _clean_name(value)
        },
        special_abbreviations={
            _clean_name(key): _clean_name(value)
            for key, value in (payload.get("special_abbreviations") or {}).items()
            if _clean_name(key) and _clean_name(value)
        },
    )


def _init_tactical_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS abbreviations (
            key TEXT PRIMARY KEY,
            student TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS special_abbreviations (
            key TEXT PRIMARY KEY,
            student TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS matches (
            id TEXT PRIMARY KEY,
            date TEXT NOT NULL,
            season TEXT NOT NULL,
            opponent TEXT NOT NULL,
            result TEXT NOT NULL,
            my_attack TEXT NOT NULL,
            opponent_defense TEXT NOT NULL,
            my_defense TEXT NOT NULL,
            opponent_attack TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT '내 기록',
            notes TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tactical_matches_date ON matches(date DESC, created_at DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tactical_matches_opponent ON matches(opponent COLLATE NOCASE)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS jokbo (
            id TEXT PRIMARY KEY,
            defense TEXT NOT NULL,
            attack TEXT NOT NULL,
            wins INTEGER NOT NULL DEFAULT 0,
            losses INTEGER NOT NULL DEFAULT 0,
            notes TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tactical_jokbo_defense ON jokbo(defense)")
    current_version = int(conn.execute("PRAGMA user_version").fetchone()[0] or 0)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(matches)")}
    if "source" not in columns:
        conn.execute("ALTER TABLE matches ADD COLUMN source TEXT NOT NULL DEFAULT '내 기록'")
    if current_version < 2:
        conn.execute("PRAGMA user_version = 2")


def _match_from_db_row(row: sqlite3.Row) -> TacticalMatch | None:
    return _match_from_dict(
        {
            "id": row["id"],
            "date": row["date"],
            "season": row["season"],
            "opponent": row["opponent"],
            "result": row["result"],
            "my_attack": parse_deck_template(row["my_attack"]),
            "opponent_defense": parse_deck_template(row["opponent_defense"]),
            "my_defense": parse_deck_template(row["my_defense"]),
            "opponent_attack": parse_deck_template(row["opponent_attack"]),
            "source": row["source"],
            "notes": row["notes"],
            "created_at": row["created_at"],
        }
    )


def _jokbo_from_db_row(row: sqlite3.Row) -> TacticalJokboEntry | None:
    return _jokbo_from_dict(
        {
            "id": row["id"],
            "defense": parse_deck_template(row["defense"]),
            "attack": parse_deck_template(row["attack"]),
            "wins": row["wins"],
            "losses": row["losses"],
            "notes": row["notes"],
            "updated_at": row["updated_at"],
        }
    )


def _load_tactical_sqlite(path: Path, *, load_matches: bool = True) -> TacticalChallengeData:
    if not path.exists():
        return TacticalChallengeData()
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        _init_tactical_db(conn)
        settings = {row["key"]: row["value"] for row in conn.execute("SELECT key, value FROM settings")}
        matches = []
        if load_matches:
            matches = [
                match
                for match in (_match_from_db_row(row) for row in conn.execute("SELECT * FROM matches ORDER BY CASE WHEN date = '' THEN 1 ELSE 0 END, date DESC, created_at DESC, id DESC"))
                if match is not None
            ]
        jokbo = [
            entry
            for entry in (_jokbo_from_db_row(row) for row in conn.execute("SELECT * FROM jokbo ORDER BY updated_at DESC, id DESC"))
            if entry is not None
        ]
        abbreviations = {
            _clean_name(row["key"]): _clean_name(row["student"])
            for row in conn.execute("SELECT key, student FROM abbreviations ORDER BY key")
            if _clean_name(row["key"]) and _clean_name(row["student"])
        }
        special_abbreviations = {
            _clean_name(row["key"]): _clean_name(row["student"])
            for row in conn.execute("SELECT key, student FROM special_abbreviations ORDER BY key")
            if _clean_name(row["key"]) and _clean_name(row["student"])
        }
        return TacticalChallengeData(
            version=TACTICAL_DATA_VERSION,
            season=_clean_name(settings.get("season")),
            matches=matches,
            jokbo=jokbo,
            abbreviations=abbreviations,
            special_abbreviations=special_abbreviations,
        )
    finally:
        conn.close()


def _match_db_tuple(match: TacticalMatch) -> tuple[str, str, str, str, str, str, str, str, str, str, str, str]:
    return (
        _clean_name(match.id),
        _clean_name(match.date),
        _clean_name(match.season),
        _clean_name(match.opponent),
        _clean_name(match.result) or "win",
        deck_template(match.my_attack),
        deck_template(match.opponent_defense),
        deck_template(match.my_defense),
        deck_template(match.opponent_attack),
        _clean_name(match.source) or "내 기록",
        str(match.notes or ""),
        _clean_name(match.created_at),
    )


def _jokbo_db_tuple(entry: TacticalJokboEntry) -> tuple[str, str, str, int, int, str, str]:
    return (
        _clean_name(entry.id),
        deck_template(entry.defense),
        deck_template(entry.attack),
        max(0, int(entry.wins or 0)),
        max(0, int(entry.losses or 0)),
        str(entry.notes or ""),
        _clean_name(entry.updated_at),
    )


def _delete_missing(conn: sqlite3.Connection, table: str, existing_ids: set[str], next_ids: set[str]) -> None:
    missing = sorted(existing_ids - next_ids)
    for index in range(0, len(missing), 500):
        chunk = missing[index:index + 500]
        placeholders = ",".join("?" for _ in chunk)
        conn.execute(f"DELETE FROM {table} WHERE id IN ({placeholders})", chunk)


def _sync_abbreviation_table(conn: sqlite3.Connection, table: str, abbreviations: dict[str, str]) -> None:
    existing_abbreviations = {
        row["key"]: row["student"]
        for row in conn.execute(f"SELECT key, student FROM {table}")
    }
    next_abbreviations = {
        _clean_name(key): _clean_name(value)
        for key, value in dict(abbreviations).items()
        if _clean_name(key) and _clean_name(value)
    }
    for key in sorted(set(existing_abbreviations) - set(next_abbreviations)):
        conn.execute(f"DELETE FROM {table} WHERE key = ?", (key,))
    conn.executemany(
        f"""
        INSERT INTO {table}(key, student) VALUES(?, ?)
        ON CONFLICT(key) DO UPDATE SET student = excluded.student
        """,
        [
            (key, value)
            for key, value in sorted(next_abbreviations.items())
            if existing_abbreviations.get(key) != value
        ],
    )


def _save_tactical_sqlite(path: Path, data: TacticalChallengeData, *, sync_matches: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        _init_tactical_db(conn)
        with conn:
            conn.execute(
                """
                INSERT INTO settings(key, value) VALUES('season', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (_clean_name(data.season),),
            )

            _sync_abbreviation_table(conn, "abbreviations", data.abbreviations)
            _sync_abbreviation_table(conn, "special_abbreviations", data.special_abbreviations)

            if sync_matches:
                existing_matches = {
                    row["id"]: tuple(row[key] for key in ("id", "date", "season", "opponent", "result", "my_attack", "opponent_defense", "my_defense", "opponent_attack", "source", "notes", "created_at"))
                    for row in conn.execute("SELECT * FROM matches")
                }
                next_matches = {
                    row[0]: row
                    for match in data.matches
                    for row in (_match_db_tuple(match),)
                    if row[0]
                }
                _delete_missing(conn, "matches", set(existing_matches), set(next_matches))
                _upsert_tactical_match_rows(conn, [row for match_id, row in next_matches.items() if existing_matches.get(match_id) != row])

            existing_jokbo = {
                row["id"]: tuple(row[key] for key in ("id", "defense", "attack", "wins", "losses", "notes", "updated_at"))
                for row in conn.execute("SELECT * FROM jokbo")
            }
            next_jokbo = {
                row[0]: row
                for entry in data.jokbo
                for row in (_jokbo_db_tuple(entry),)
                if row[0]
            }
            _delete_missing(conn, "jokbo", set(existing_jokbo), set(next_jokbo))
            _upsert_tactical_jokbo_rows(conn, [row for entry_id, row in next_jokbo.items() if existing_jokbo.get(entry_id) != row])
    finally:
        conn.close()


def _upsert_tactical_match_rows(conn: sqlite3.Connection, rows: list[tuple[str, str, str, str, str, str, str, str, str, str, str, str]]) -> None:
    conn.executemany(
        """
        INSERT INTO matches(
            id, date, season, opponent, result,
            my_attack, opponent_defense, my_defense, opponent_attack,
            source, notes, created_at
        ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            date = excluded.date,
            season = excluded.season,
            opponent = excluded.opponent,
            result = excluded.result,
            my_attack = excluded.my_attack,
            opponent_defense = excluded.opponent_defense,
            my_defense = excluded.my_defense,
            opponent_attack = excluded.opponent_attack,
            source = excluded.source,
            notes = excluded.notes,
            created_at = excluded.created_at
        """,
        rows,
    )


def _upsert_tactical_jokbo_rows(conn: sqlite3.Connection, rows: list[tuple[str, str, str, int, int, str, str]]) -> None:
    conn.executemany(
        """
        INSERT INTO jokbo(id, defense, attack, wins, losses, notes, updated_at)
        VALUES(?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            defense = excluded.defense,
            attack = excluded.attack,
            wins = excluded.wins,
            losses = excluded.losses,
            notes = excluded.notes,
            updated_at = excluded.updated_at
        """,
        rows,
    )


def save_tactical_metadata(
    path: Path,
    *,
    season: str,
    abbreviations: dict[str, str],
    special_abbreviations: dict[str, str],
) -> None:
    if path.suffix.casefold() not in {".db", ".sqlite", ".sqlite3"}:
        data = load_tactical_challenge(path)
        data.season = _clean_name(season)
        data.abbreviations = {
            _clean_name(key): _clean_name(value)
            for key, value in dict(abbreviations).items()
            if _clean_name(key) and _clean_name(value)
        }
        data.special_abbreviations = {
            _clean_name(key): _clean_name(value)
            for key, value in dict(special_abbreviations).items()
            if _clean_name(key) and _clean_name(value)
        }
        save_tactical_challenge(path, data)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        _init_tactical_db(conn)
        with conn:
            conn.execute(
                """
                INSERT INTO settings(key, value) VALUES('season', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (_clean_name(season),),
            )
            _sync_abbreviation_table(conn, "abbreviations", abbreviations)
            _sync_abbreviation_table(conn, "special_abbreviations", special_abbreviations)
    finally:
        conn.close()


def upsert_tactical_match(path: Path, match: TacticalMatch) -> None:
    if path.suffix.casefold() not in {".db", ".sqlite", ".sqlite3"}:
        data = load_tactical_challenge(path)
        data.matches = [item for item in data.matches if item.id != match.id] + [match]
        save_tactical_challenge(path, data)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        _init_tactical_db(conn)
        with conn:
            _upsert_tactical_match_rows(conn, [_match_db_tuple(match)])
    finally:
        conn.close()


def upsert_tactical_matches(path: Path, matches: list[TacticalMatch]) -> None:
    if not matches:
        return
    if path.suffix.casefold() not in {".db", ".sqlite", ".sqlite3"}:
        data = load_tactical_challenge(path)
        next_by_id = {match.id: match for match in data.matches}
        for match in matches:
            next_by_id[match.id] = match
        data.matches = list(next_by_id.values())
        save_tactical_challenge(path, data)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        _init_tactical_db(conn)
        with conn:
            _upsert_tactical_match_rows(conn, [_match_db_tuple(match) for match in matches])
    finally:
        conn.close()


def upsert_tactical_jokbo(path: Path, entry: TacticalJokboEntry) -> None:
    if path.suffix.casefold() not in {".db", ".sqlite", ".sqlite3"}:
        data = load_tactical_challenge(path)
        data.jokbo = [item for item in data.jokbo if item.id != entry.id] + [entry]
        save_tactical_challenge(path, data)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        _init_tactical_db(conn)
        with conn:
            _upsert_tactical_jokbo_rows(conn, [_jokbo_db_tuple(entry)])
    finally:
        conn.close()


def upsert_tactical_jokbo_entries(path: Path, entries: list[TacticalJokboEntry]) -> None:
    if not entries:
        return
    if path.suffix.casefold() not in {".db", ".sqlite", ".sqlite3"}:
        data = load_tactical_challenge(path)
        next_by_id = {entry.id: entry for entry in data.jokbo}
        for entry in entries:
            next_by_id[entry.id] = entry
        data.jokbo = list(next_by_id.values())
        save_tactical_challenge(path, data)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        _init_tactical_db(conn)
        with conn:
            _upsert_tactical_jokbo_rows(conn, [_jokbo_db_tuple(entry) for entry in entries])
    finally:
        conn.close()


def delete_tactical_match(path: Path, match_id: str) -> bool:
    if path.suffix.casefold() not in {".db", ".sqlite", ".sqlite3"}:
        data = load_tactical_challenge(path)
        before = len(data.matches)
        data.matches = [match for match in data.matches if match.id != match_id]
        if len(data.matches) == before:
            return False
        save_tactical_challenge(path, data)
        return True
    conn = sqlite3.connect(path)
    try:
        _init_tactical_db(conn)
        with conn:
            cursor = conn.execute("DELETE FROM matches WHERE id = ?", (_clean_name(match_id),))
            return cursor.rowcount > 0
    finally:
        conn.close()


def _match_search_clause(query: str) -> tuple[str, list[str]]:
    needle = query.strip()
    if not needle:
        return "", []
    like = f"%{needle}%"
    fields = ("date", "season", "opponent", "result", "source", "my_attack", "opponent_defense", "my_defense", "opponent_attack", "notes")
    return "WHERE " + " OR ".join(f"{field} LIKE ? COLLATE NOCASE" for field in fields), [like] * len(fields)


def query_tactical_matches(path: Path, query: str = "", *, limit: int = 100, offset: int = 0) -> list[TacticalMatch]:
    if path.suffix.casefold() not in {".db", ".sqlite", ".sqlite3"}:
        return filter_matches(load_tactical_challenge(path).matches, query)[offset:offset + limit]
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        _init_tactical_db(conn)
        where, params = _match_search_clause(query)
        rows = conn.execute(
            f"SELECT * FROM matches {where} ORDER BY CASE WHEN date = '' THEN 1 ELSE 0 END, date DESC, created_at DESC, id DESC LIMIT ? OFFSET ?",
            [*params, max(1, int(limit)), max(0, int(offset))],
        )
        return [match for match in (_match_from_db_row(row) for row in rows) if match is not None]
    finally:
        conn.close()


def get_tactical_match(path: Path, match_id: str) -> TacticalMatch | None:
    if path.suffix.casefold() not in {".db", ".sqlite", ".sqlite3"}:
        return next((match for match in load_tactical_challenge(path).matches if match.id == match_id), None)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        _init_tactical_db(conn)
        row = conn.execute("SELECT * FROM matches WHERE id = ?", (_clean_name(match_id),)).fetchone()
        return _match_from_db_row(row) if row is not None else None
    finally:
        conn.close()


def latest_tactical_match_for_opponent(path: Path, opponent: str, mode: str) -> TacticalMatch | None:
    target = _clean_name(opponent)
    if not target:
        return None
    mode = "defense" if mode == "defense" else "attack"
    if path.suffix.casefold() not in {".db", ".sqlite", ".sqlite3"}:
        matches = [
            match
            for match in sorted_matches(load_tactical_challenge(path).matches)
            if match.opponent.casefold() == target.casefold()
        ]
        for match in matches:
            if mode == "defense":
                if deck_template(match.my_defense) and deck_template(match.opponent_attack):
                    return match
            elif deck_template(match.my_attack) and deck_template(match.opponent_defense):
                return match
        return None
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        _init_tactical_db(conn)
        deck_clause = "my_defense != '' AND opponent_attack != ''" if mode == "defense" else "my_attack != '' AND opponent_defense != ''"
        row = conn.execute(
            f"""
            SELECT * FROM matches
            WHERE opponent = ? COLLATE NOCASE AND {deck_clause}
            ORDER BY CASE WHEN date = '' THEN 1 ELSE 0 END, date DESC, created_at DESC, id DESC
            LIMIT 1
            """,
            (target,),
        ).fetchone()
        return _match_from_db_row(row) if row is not None else None
    finally:
        conn.close()


def tactical_match_summary(path: Path, today: str) -> dict[str, int]:
    if path.suffix.casefold() not in {".db", ".sqlite", ".sqlite3"}:
        matches = load_tactical_challenge(path).matches
        wins = sum(1 for match in matches if match.result == "win")
        return {
            "total": len(matches),
            "wins": wins,
            "losses": len(matches) - wins,
            "today": sum(1 for match in matches if match.date == today),
        }
    conn = sqlite3.connect(path)
    try:
        _init_tactical_db(conn)
        total = int(conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0])
        wins = int(conn.execute("SELECT COUNT(*) FROM matches WHERE result = 'win'").fetchone()[0])
        today_count = int(conn.execute("SELECT COUNT(*) FROM matches WHERE date = ?", (_clean_name(today),)).fetchone()[0])
        return {"total": total, "wins": wins, "losses": total - wins, "today": today_count}
    finally:
        conn.close()


def tactical_match_count(path: Path, query: str = "") -> int:
    if path.suffix.casefold() not in {".db", ".sqlite", ".sqlite3"}:
        return len(filter_matches(load_tactical_challenge(path).matches, query))
    conn = sqlite3.connect(path)
    try:
        _init_tactical_db(conn)
        where, params = _match_search_clause(query)
        return int(conn.execute(f"SELECT COUNT(*) FROM matches {where}", params).fetchone()[0])
    finally:
        conn.close()


def opponent_report_from_storage(path: Path, opponent: str) -> dict[str, Any]:
    if path.suffix.casefold() not in {".db", ".sqlite", ".sqlite3"}:
        return opponent_report(load_tactical_challenge(path), opponent)
    target = _clean_name(opponent)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        _init_tactical_db(conn)
        rows = conn.execute("SELECT * FROM matches WHERE opponent = ? COLLATE NOCASE ORDER BY CASE WHEN date = '' THEN 1 ELSE 0 END, date DESC, created_at DESC, id DESC", (target,))
        matches = [match for match in (_match_from_db_row(row) for row in rows) if match is not None]
        return opponent_report(TacticalChallengeData(matches=matches), opponent)
    finally:
        conn.close()


def search_jokbo_from_storage(path: Path, data: TacticalChallengeData, defense: TacticalDeck, *, query: str = "") -> dict[str, list[dict[str, Any]]]:
    if path.suffix.casefold() not in {".db", ".sqlite", ".sqlite3"}:
        return search_jokbo(data, defense, query=query)
    signature = defense_deck_signature(defense)
    defense_templates = defense_deck_template_variants(defense)
    manual = search_jokbo(TacticalChallengeData(jokbo=data.jokbo), defense, query=query)["manual"]
    where = []
    params: list[str] = []
    if signature != "s:;p:":
        if defense_deck_has_wildcard(defense):
            fixed_terms = [
                term
                for term in [*normalize_deck(defense).strikers, *normalize_deck(defense).supports]
                if term and not _is_deck_wildcard(term)
            ]
            for term in fixed_terms:
                where.append("(opponent_defense LIKE ? COLLATE NOCASE OR my_defense LIKE ? COLLATE NOCASE)")
                like = f"%{term}%"
                params.extend([like, like])
        else:
            placeholders = ", ".join("?" for _ in defense_templates)
            where.append(f"(opponent_defense IN ({placeholders}) OR my_defense IN ({placeholders}))")
            params.extend([*defense_templates, *defense_templates])
    if query:
        like = f"%{query.strip()}%"
        where.append(
            "("
            "opponent_defense LIKE ? COLLATE NOCASE OR "
            "my_attack LIKE ? COLLATE NOCASE OR "
            "my_defense LIKE ? COLLATE NOCASE OR "
            "opponent_attack LIKE ? COLLATE NOCASE"
            ")"
        )
        params.extend([like, like, like, like])
    sql_where = "WHERE " + " AND ".join(where) if where else ""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        _init_tactical_db(conn)
        rows = conn.execute(f"SELECT * FROM matches {sql_where}", params)
        observed = search_jokbo(TacticalChallengeData(matches=[match for match in (_match_from_db_row(row) for row in rows) if match is not None]), defense, query=query)["observed"]
        return {"manual": manual, "observed": observed}
    finally:
        conn.close()


def load_tactical_challenge(path: Path, *, load_matches: bool = True) -> TacticalChallengeData:
    if path.suffix.casefold() in {".db", ".sqlite", ".sqlite3"}:
        if path.exists():
            return _load_tactical_sqlite(path, load_matches=load_matches)
        legacy_json = path.with_suffix(".json")
        if legacy_json.exists():
            data = _load_tactical_json(legacy_json)
            _save_tactical_sqlite(path, data)
            if not load_matches:
                data.matches = []
            return data
        return TacticalChallengeData()
    return _load_tactical_json(path)


def save_tactical_challenge(path: Path, data: TacticalChallengeData, *, sync_matches: bool = True) -> None:
    if path.suffix.casefold() in {".db", ".sqlite", ".sqlite3"}:
        _save_tactical_sqlite(path, data, sync_matches=sync_matches)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": TACTICAL_DATA_VERSION,
        "season": data.season,
        "matches": [_match_to_dict(match) for match in data.matches],
        "jokbo": [_jokbo_to_dict(entry) for entry in data.jokbo],
        "abbreviations": dict(data.abbreviations),
        "special_abbreviations": dict(data.special_abbreviations),
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def sorted_matches(matches: list[TacticalMatch]) -> list[TacticalMatch]:
    return sorted(matches, key=lambda item: (item.date, item.created_at, item.id), reverse=True)


def filter_matches(matches: list[TacticalMatch], query: str) -> list[TacticalMatch]:
    needle = query.strip().casefold()
    if not needle:
        return sorted_matches(matches)
    filtered: list[TacticalMatch] = []
    for match in matches:
        text = " ".join(
            (
                match.date,
                match.season,
                match.opponent,
                match.result,
                deck_label(match.my_attack),
                deck_label(match.opponent_defense),
                deck_label(match.my_defense),
                deck_label(match.opponent_attack),
                match.source,
                match.notes,
            )
        ).casefold()
        if needle in text:
            filtered.append(match)
    return sorted_matches(filtered)


def win_rate(wins: int, losses: int) -> float:
    total = max(0, wins) + max(0, losses)
    return (max(0, wins) / total * 100.0) if total else 0.0


def opponent_report(data: TacticalChallengeData, opponent: str) -> dict[str, Any]:
    target = _clean_name(opponent).casefold()
    matches = [match for match in data.matches if match.opponent.casefold() == target] if target else []
    matches = sorted_matches(matches)
    wins = sum(1 for match in matches if match.result == "win")
    losses = sum(1 for match in matches if match.result == "loss")
    defense_counts: Counter[str] = Counter()
    defense_examples: dict[str, TacticalDeck] = {}
    attack_by_defense: dict[str, TacticalDeck] = {}
    wins_by_defense: defaultdict[str, int] = defaultdict(int)
    losses_by_defense: defaultdict[str, int] = defaultdict(int)

    for match in matches:
        signature = deck_signature(match.opponent_defense)
        if signature == "s:;p:":
            continue
        defense_counts[signature] += 1
        defense_examples.setdefault(signature, match.opponent_defense)
        attack_by_defense.setdefault(signature, match.my_attack)
        if match.result == "win":
            wins_by_defense[signature] += 1
        elif match.result == "loss":
            losses_by_defense[signature] += 1

    recent_match = next((match for match in matches if deck_signature(match.opponent_defense) != "s:;p:"), None)
    top_defenses = []
    for signature, count in defense_counts.most_common(3):
        wins_for_deck = wins_by_defense[signature]
        losses_for_deck = losses_by_defense[signature]
        top_defenses.append(
            {
                "deck": defense_examples[signature],
                "count": count,
                "wins": wins_for_deck,
                "losses": losses_for_deck,
                "win_rate": win_rate(wins_for_deck, losses_for_deck),
                "attack": attack_by_defense.get(signature, TacticalDeck()),
            }
        )

    return {
        "matches": matches,
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate(wins, losses),
        "recent_defense": recent_match.opponent_defense if recent_match else TacticalDeck(),
        "recent_attack": recent_match.my_attack if recent_match else TacticalDeck(),
        "top_defenses": top_defenses,
    }


def search_jokbo(data: TacticalChallengeData, defense: TacticalDeck, *, query: str = "") -> dict[str, list[dict[str, Any]]]:
    signature = defense_deck_signature(defense)
    manual: list[dict[str, Any]] = []
    for entry in data.jokbo:
        if signature != "s:;p:" and not defense_deck_matches(defense, entry.defense):
            continue
        if query and not (_deck_contains_query(entry.defense, query) or _deck_contains_query(entry.attack, query) or query.casefold() in entry.notes.casefold()):
            continue
        manual.append(
            {
                "entry": entry,
                "wins": entry.wins,
                "losses": entry.losses,
                "win_rate": win_rate(entry.wins, entry.losses),
            }
        )
    manual.sort(key=lambda item: (item["win_rate"], item["wins"]), reverse=True)

    by_attack: dict[str, dict[str, Any]] = {}
    for match in data.matches:
        candidates = [
            (match.opponent_defense, match.my_attack, match.result),
            (
                match.my_defense,
                match.opponent_attack,
                "loss" if match.result == "win" else "win" if match.result == "loss" else match.result,
            ),
        ]
        for candidate_defense, candidate_attack, attack_result in candidates:
            if signature != "s:;p:" and not defense_deck_matches(defense, candidate_defense):
                continue
            if query and not (_deck_contains_query(candidate_defense, query) or _deck_contains_query(candidate_attack, query)):
                continue
            attack_signature = deck_signature(candidate_attack)
            if attack_signature == "s:;p:":
                continue
            bucket = by_attack.setdefault(
                attack_signature,
                {"attack": candidate_attack, "defense": candidate_defense, "wins": 0, "losses": 0},
            )
            if attack_result == "win":
                bucket["wins"] += 1
            elif attack_result == "loss":
                bucket["losses"] += 1

    observed = []
    for bucket in by_attack.values():
        observed.append(
            {
                **bucket,
                "win_rate": win_rate(int(bucket["wins"]), int(bucket["losses"])),
            }
        )
    observed.sort(key=lambda item: (item["win_rate"], item["wins"]), reverse=True)
    return {"manual": manual, "observed": observed}

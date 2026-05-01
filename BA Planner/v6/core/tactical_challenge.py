from __future__ import annotations

import json
import os
import sqlite3
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any


TACTICAL_DATA_VERSION = 1
TACTICAL_STRIKER_SLOTS = 4
TACTICAL_SUPPORT_SLOTS = 2


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
                for match in (_match_from_db_row(row) for row in conn.execute("SELECT * FROM matches ORDER BY date DESC, created_at DESC, id DESC"))
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


def _match_db_tuple(match: TacticalMatch) -> tuple[str, str, str, str, str, str, str, str, str, str, str]:
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
                    row["id"]: tuple(row[key] for key in ("id", "date", "season", "opponent", "result", "my_attack", "opponent_defense", "my_defense", "opponent_attack", "notes", "created_at"))
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


def _upsert_tactical_match_rows(conn: sqlite3.Connection, rows: list[tuple[str, str, str, str, str, str, str, str, str, str, str]]) -> None:
    conn.executemany(
        """
        INSERT INTO matches(
            id, date, season, opponent, result,
            my_attack, opponent_defense, my_defense, opponent_attack,
            notes, created_at
        ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            date = excluded.date,
            season = excluded.season,
            opponent = excluded.opponent,
            result = excluded.result,
            my_attack = excluded.my_attack,
            opponent_defense = excluded.opponent_defense,
            my_defense = excluded.my_defense,
            opponent_attack = excluded.opponent_attack,
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
    fields = ("date", "season", "opponent", "result", "my_attack", "opponent_defense", "my_defense", "opponent_attack", "notes")
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
            f"SELECT * FROM matches {where} ORDER BY date DESC, created_at DESC, id DESC LIMIT ? OFFSET ?",
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
        rows = conn.execute("SELECT * FROM matches WHERE opponent = ? COLLATE NOCASE ORDER BY date DESC, created_at DESC, id DESC", (target,))
        matches = [match for match in (_match_from_db_row(row) for row in rows) if match is not None]
        return opponent_report(TacticalChallengeData(matches=matches), opponent)
    finally:
        conn.close()


def search_jokbo_from_storage(path: Path, data: TacticalChallengeData, defense: TacticalDeck, *, query: str = "") -> dict[str, list[dict[str, Any]]]:
    if path.suffix.casefold() not in {".db", ".sqlite", ".sqlite3"}:
        return search_jokbo(data, defense, query=query)
    signature = deck_signature(defense)
    defense_template = deck_template(defense)
    manual = search_jokbo(TacticalChallengeData(jokbo=data.jokbo), defense, query=query)["manual"]
    where = []
    params: list[str] = []
    if signature != "s:;p:":
        where.append("(opponent_defense = ? OR my_defense = ?)")
        params.extend([defense_template, defense_template])
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
    signature = deck_signature(defense)
    manual: list[dict[str, Any]] = []
    for entry in data.jokbo:
        if signature != "s:;p:" and deck_signature(entry.defense) != signature:
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
            if signature != "s:;p:" and deck_signature(candidate_defense) != signature:
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

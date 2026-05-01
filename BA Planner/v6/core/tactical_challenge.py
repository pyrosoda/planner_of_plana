from __future__ import annotations

import json
import os
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


def _clean_name(value: object) -> str:
    return " ".join(str(value or "").strip().split())


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
    strikers = [_clean_name(item) for item in list(raw_strikers)[:TACTICAL_STRIKER_SLOTS]]
    supports = [_clean_name(item) for item in list(raw_supports)[:TACTICAL_SUPPORT_SLOTS]]
    return TacticalDeck(
        strikers=[item for item in strikers if item],
        supports=[item for item in supports if item],
    )


def deck_signature(deck: TacticalDeck | dict[str, Any] | None) -> str:
    normalized = normalize_deck(deck)
    strikers = "|".join(item.casefold() for item in normalized.strikers)
    supports = "|".join(item.casefold() for item in normalized.supports)
    return f"s:{strikers};p:{supports}"


def deck_label(deck: TacticalDeck | dict[str, Any] | None, *, empty: str = "-") -> str:
    normalized = normalize_deck(deck)
    parts: list[str] = []
    if normalized.strikers:
        parts.append("STR " + " / ".join(normalized.strikers))
    if normalized.supports:
        parts.append("SP " + " / ".join(normalized.supports))
    return " | ".join(parts) if parts else empty


def deck_template(deck: TacticalDeck | dict[str, Any] | None) -> str:
    normalized = normalize_deck(deck)
    return f"{','.join(normalized.strikers)}|{','.join(normalized.supports)}"


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
        return [_clean_name(item) for item in normalized.split(",") if _clean_name(item)]

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


def load_tactical_challenge(path: Path) -> TacticalChallengeData:
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
    )


def save_tactical_challenge(path: Path, data: TacticalChallengeData) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": TACTICAL_DATA_VERSION,
        "season": data.season,
        "matches": [_match_to_dict(match) for match in data.matches],
        "jokbo": [_jokbo_to_dict(entry) for entry in data.jokbo],
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
        if signature != "s:;p:" and deck_signature(match.opponent_defense) != signature:
            continue
        if query and not (_deck_contains_query(match.opponent_defense, query) or _deck_contains_query(match.my_attack, query)):
            continue
        attack_signature = deck_signature(match.my_attack)
        if attack_signature == "s:;p:":
            continue
        bucket = by_attack.setdefault(
            attack_signature,
            {"attack": match.my_attack, "defense": match.opponent_defense, "wins": 0, "losses": 0},
        )
        if match.result == "win":
            bucket["wins"] += 1
        elif match.result == "loss":
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

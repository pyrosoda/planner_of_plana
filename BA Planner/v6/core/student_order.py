"""
Helpers for deterministic owned-student ordering.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import core.student_meta as student_meta


def display_name(student_id: str, row: Mapping[str, object] | None = None) -> str:
    raw = ""
    if row is not None:
        value = row.get("display_name")
        if isinstance(value, str):
            raw = value.strip()
    return raw or student_meta.display_name(student_id)


def sort_key(student_id: str, row: Mapping[str, object] | None = None) -> tuple[str, str]:
    name = display_name(student_id, row)
    return (name.casefold(), student_id.casefold())


def ordered_owned_student_ids(current_students: Mapping[str, Mapping[str, object]]) -> list[str]:
    return sorted(current_students.keys(), key=lambda student_id: sort_key(student_id, current_students.get(student_id)))


def ordered_owned_student_rows(
    current_students: Mapping[str, Mapping[str, object]],
) -> list[tuple[str, str]]:
    ordered_ids = ordered_owned_student_ids(current_students)
    return [(student_id, display_name(student_id, current_students.get(student_id))) for student_id in ordered_ids]


def ordered_student_ids(student_ids: Sequence[str]) -> list[str]:
    return sorted(student_ids, key=lambda student_id: sort_key(student_id))


def ordered_student_rows(student_ids: Sequence[str]) -> list[tuple[str, str]]:
    ordered_ids = ordered_student_ids(student_ids)
    return [(student_id, display_name(student_id)) for student_id in ordered_ids]


def ordered_ids_from_rows(rows: Sequence[Mapping[str, object]]) -> list[str]:
    indexed: dict[str, Mapping[str, object]] = {}
    for row in rows:
        student_id = str(row.get("student_id") or "").strip()
        if student_id:
            indexed[student_id] = row
    return ordered_owned_student_ids(indexed)

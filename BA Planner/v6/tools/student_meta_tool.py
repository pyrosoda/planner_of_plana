from __future__ import annotations

import argparse
import ast
import importlib
import pprint
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk


ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


MODULE_NAME = "core.student_meta"
MODULE_PATH = ROOT_DIR / "core" / "student_meta.py"
from tools.student_meta_options import FIELD_OPTIONS

FIELD_SPECS: list[dict[str, object]] = [
    {"name": "student_id", "label": "Student ID", "required": True},
    {"name": "display_name", "label": "Display Name", "required": True},
    {"name": "template_name", "label": "Template File", "required": True},
    {"name": "group", "label": "Group", "required": True},
    {"name": "variant", "label": "Variant"},
    {"name": "school", "label": "School"},
    {"name": "rarity", "label": "Rarity"},
    {"name": "attack_type", "label": "Attack Type"},
    {"name": "defense_type", "label": "Defense Type"},
    {"name": "ex_skill_name", "label": "EX Skill"},
    {"name": "normal_skill_name", "label": "Normal Skill"},
    {"name": "passive_skill_name", "label": "Passive Skill"},
    {"name": "sub_skill_name", "label": "Sub Skill"},
    {"name": "growth_material_main", "label": "Main Growth Mat"},
    {"name": "growth_material_sub", "label": "Sub Growth Mat"},
    {"name": "equipment_slot_1", "label": "Equipment 1"},
    {"name": "equipment_slot_2", "label": "Equipment 2"},
    {"name": "equipment_slot_3", "label": "Equipment 3"},
    {"name": "combat_class", "label": "Class"},
    {"name": "cover_type", "label": "Cover"},
    {"name": "range_type", "label": "Range"},
    {"name": "role", "label": "Role"},
    {"name": "weapon_type", "label": "Weapon"},
    {"name": "position", "label": "Position"},
    {"name": "terrain_outdoor", "label": "Outdoor"},
    {"name": "terrain_urban", "label": "Urban"},
    {"name": "terrain_indoor", "label": "Indoor"},
    {"name": "has_favorite_item", "label": "Favorite Item"},
    {"name": "favorite_item_name", "label": "Favorite Item Name"},
]


def _load_module():
    return importlib.import_module(MODULE_NAME)


def _reload_module():
    module = _load_module()
    return importlib.reload(module)


def _normalize_value(value: str | None) -> str | None:
    if value is None:
        return None
    trimmed = value.strip()
    if trimmed == "":
        return None
    if trimmed.lower() in {"none", "null", "-"}:
        return None
    return trimmed


def _sorted_unique(values: list[str]) -> tuple[str, ...]:
    return tuple(sorted({value for value in values if value}))


def _collect_existing_field_values(students: dict[str, dict], field_name: str) -> tuple[str, ...]:
    if field_name == "student_id":
        return _sorted_unique(list(students.keys()))
    return _sorted_unique(
        [str(meta.get(field_name)) for meta in students.values() if meta.get(field_name)]
    )


def build_field_options(students: dict[str, dict]) -> dict[str, tuple[str, ...]]:
    options: dict[str, tuple[str, ...]] = {}
    for spec in FIELD_SPECS:
        field_name = str(spec["name"])
        base_values = list(FIELD_OPTIONS.get(field_name, ()))
        dynamic_values = list(_collect_existing_field_values(students, field_name))
        merged = _sorted_unique(base_values + dynamic_values)
        options[field_name] = ("",) + merged
    return options


def _replace_students_block(source: str, rendered_assignment: str) -> str:
    tree = ast.parse(source)
    target = None
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == "STUDENTS":
                target = node
                break
        if isinstance(node, ast.Assign):
            for single_target in node.targets:
                if isinstance(single_target, ast.Name) and single_target.id == "STUDENTS":
                    target = node
                    break
    if target is None:
        raise RuntimeError("STUDENTS assignment not found in core.student_meta")

    lines = source.splitlines()
    start = target.lineno - 1
    end = target.end_lineno
    replaced = lines[:start] + rendered_assignment.rstrip("\n").splitlines() + lines[end:]
    return "\n".join(replaced) + "\n"


def _write_students(students: dict[str, dict]) -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")
    rendered = "STUDENTS: dict[str, StudentMeta] = " + pprint.pformat(
        students,
        width=100,
        sort_dicts=False,
    )
    updated = _replace_students_block(source, rendered)
    MODULE_PATH.write_text(updated, encoding="utf-8")


def get_students() -> dict[str, dict]:
    module = _reload_module()
    return {sid: dict(meta) for sid, meta in module.STUDENTS.items()}


def upsert_student(student_id: str, updates: dict[str, str | None]) -> dict[str, object]:
    module = _reload_module()
    students = dict(module.STUDENTS)
    current = dict(students.get(student_id, {}))
    required = {"display_name", "template_name", "group"}
    candidate = dict(current)
    candidate.update(updates)
    if not required.issubset(candidate):
        missing = ", ".join(sorted(required - set(candidate)))
        raise ValueError(f"required fields missing: {missing}")

    if "variant" not in candidate:
        candidate["variant"] = None
    students[student_id] = candidate
    _write_students(students)
    module = _reload_module()
    return dict(module.STUDENTS[student_id])


def delete_student(student_id: str) -> None:
    module = _reload_module()
    students = dict(module.STUDENTS)
    if student_id not in students:
        raise KeyError(student_id)
    students.pop(student_id)
    _write_students(students)


def command_get(args: argparse.Namespace) -> int:
    module = _reload_module()
    meta = module.get(args.student_id)
    if meta is None:
        print(f"student_id not found: {args.student_id}")
        return 1
    pprint.pprint(dict(meta), sort_dicts=False)
    return 0


def command_upsert(args: argparse.Namespace) -> int:
    updates: dict[str, str | None] = {}
    for spec in FIELD_SPECS:
        name = spec["name"]
        if name == "student_id":
            continue
        raw = getattr(args, name)
        if raw is not None:
            updates[name] = _normalize_value(raw)
    saved = upsert_student(args.student_id, updates)
    pprint.pprint(saved, sort_dicts=False)
    print(f"saved: {args.student_id}")
    return 0


def command_delete(args: argparse.Namespace) -> int:
    try:
        delete_student(args.student_id)
    except KeyError:
        print(f"student_id not found: {args.student_id}")
        return 1
    print(f"deleted: {args.student_id}")
    return 0


class StudentMetaToolApp:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Student Meta Tool")
        self.root.geometry("1180x760")

        self.students = get_students()
        self.field_options = build_field_options(self.students)
        self.selected_student_id: str | None = None
        self.vars: dict[str, tk.StringVar] = {}
        self.widgets: dict[str, ttk.Combobox] = {}

        self._build_ui()
        self._refresh_student_list()
        self._new_student()

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=0)
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(0, weight=1)

        left = ttk.Frame(self.root, padding=12)
        left.grid(row=0, column=0, sticky="ns")
        left.rowconfigure(2, weight=1)

        ttk.Label(left, text="Students").grid(row=0, column=0, sticky="w")
        self.search_var = tk.StringVar()
        search_entry = ttk.Entry(left, textvariable=self.search_var, width=28)
        search_entry.grid(row=1, column=0, sticky="ew", pady=(6, 8))
        search_entry.bind("<KeyRelease>", lambda _event: self._refresh_student_list())

        self.student_list = tk.Listbox(left, width=32, exportselection=False)
        self.student_list.grid(row=2, column=0, sticky="nsew")
        self.student_list.bind("<<ListboxSelect>>", self._on_select_student)

        left_buttons = ttk.Frame(left)
        left_buttons.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(left_buttons, text="New", command=self._new_student).grid(row=0, column=0, padx=(0, 6))
        ttk.Button(left_buttons, text="Reload", command=self._reload_students).grid(row=0, column=1)

        right = ttk.Frame(self.root, padding=(4, 12, 12, 12))
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)

        ttk.Label(right, text="Editor").grid(row=0, column=0, sticky="w")

        canvas = tk.Canvas(right, highlightthickness=0)
        canvas.grid(row=1, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(right, orient="vertical", command=canvas.yview)
        scrollbar.grid(row=1, column=1, sticky="ns")
        canvas.configure(yscrollcommand=scrollbar.set)

        form = ttk.Frame(canvas, padding=(0, 8, 0, 8))
        form.columnconfigure(1, weight=1)
        canvas.create_window((0, 0), window=form, anchor="nw")
        form.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind_all("<MouseWheel>", lambda event: canvas.yview_scroll(int(-event.delta / 120), "units"))

        for row, spec in enumerate(FIELD_SPECS):
            name = str(spec["name"])
            label = str(spec["label"])
            required = bool(spec.get("required", False))

            display = f"{label} *" if required else label
            ttk.Label(form, text=display, width=18).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=4)

            var = tk.StringVar()
            self.vars[name] = var
            widget = ttk.Combobox(
                form,
                textvariable=var,
                values=self.field_options.get(name, ("",)),
                state="readonly",
            )
            widget.grid(row=row, column=1, sticky="ew", pady=4)
            self.widgets[name] = widget

        action_bar = ttk.Frame(right)
        action_bar.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        ttk.Button(action_bar, text="Save", command=self._save_current).grid(row=0, column=0, padx=(0, 6))
        ttk.Button(action_bar, text="Delete", command=self._delete_current).grid(row=0, column=1, padx=(0, 6))
        ttk.Button(action_bar, text="Duplicate as New", command=self._duplicate_current).grid(row=0, column=2)

        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(right, textvariable=self.status_var).grid(row=3, column=0, sticky="w", pady=(10, 0))

    def _refresh_student_list(self) -> None:
        query = self.search_var.get().strip().lower()
        self.student_list.delete(0, tk.END)
        self._list_ids: list[str] = []
        for student_id in sorted(self.students):
            meta = self.students[student_id]
            display_name = str(meta.get("display_name", ""))
            haystack = f"{student_id} {display_name}".lower()
            if query and query not in haystack:
                continue
            self._list_ids.append(student_id)
            self.student_list.insert(tk.END, f"{student_id} | {display_name}")

    def _clear_form(self) -> None:
        for var in self.vars.values():
            var.set("")

    def _load_student_into_form(self, student_id: str) -> None:
        self.selected_student_id = student_id
        meta = self.students[student_id]
        self._clear_form()
        self.vars["student_id"].set(student_id)
        for spec in FIELD_SPECS:
            name = str(spec["name"])
            if name == "student_id":
                continue
            value = meta.get(name)
            self.vars[name].set("" if value is None else str(value))
        self.status_var.set(f"Loaded: {student_id}")

    def _on_select_student(self, _event=None) -> None:
        selection = self.student_list.curselection()
        if not selection:
            return
        idx = selection[0]
        student_id = self._list_ids[idx]
        self._load_student_into_form(student_id)

    def _new_student(self) -> None:
        self.selected_student_id = None
        self._clear_form()
        self.status_var.set("New student form")

    def _refresh_field_options(self) -> None:
        self.field_options = build_field_options(self.students)
        for field_name, widget in self.widgets.items():
            widget["values"] = self.field_options.get(field_name, ("",))

    def _duplicate_current(self) -> None:
        current_id = self.vars["student_id"].get().strip()
        if not current_id:
            messagebox.showinfo("Duplicate", "Load a student first.")
            return
        self.vars["student_id"].set(f"{current_id}_copy")
        self.status_var.set("Duplicated into new draft")

    def _collect_form_data(self) -> tuple[str, dict[str, str | None]]:
        student_id = self.vars["student_id"].get().strip()
        if not student_id:
            raise ValueError("student_id is required")

        updates: dict[str, str | None] = {}
        for spec in FIELD_SPECS:
            name = str(spec["name"])
            if name == "student_id":
                continue
            value = _normalize_value(self.vars[name].get())
            if spec.get("required") and value is None:
                raise ValueError(f"{spec['label']} is required")
            if value is not None:
                updates[name] = value
        return student_id, updates

    def _save_current(self) -> None:
        try:
            student_id, updates = self._collect_form_data()
            saved = upsert_student(student_id, updates)
        except Exception as exc:
            messagebox.showerror("Save failed", str(exc))
            return

        self.students = get_students()
        self._refresh_field_options()
        self._refresh_student_list()
        self._load_student_into_form(student_id)
        self.status_var.set(f"Saved: {student_id}")
        messagebox.showinfo("Saved", f"{student_id} saved successfully.")

    def _delete_current(self) -> None:
        student_id = self.vars["student_id"].get().strip()
        if not student_id:
            messagebox.showinfo("Delete", "No student selected.")
            return
        if student_id not in self.students:
            messagebox.showinfo("Delete", "Student does not exist.")
            return
        if not messagebox.askyesno("Delete", f"Delete '{student_id}'?"):
            return
        try:
            delete_student(student_id)
        except Exception as exc:
            messagebox.showerror("Delete failed", str(exc))
            return

        self.students = get_students()
        self._refresh_field_options()
        self._refresh_student_list()
        self._new_student()
        self.status_var.set(f"Deleted: {student_id}")

    def _reload_students(self) -> None:
        self.students = get_students()
        self._refresh_field_options()
        self._refresh_student_list()
        self.status_var.set("Reloaded from core.student_meta")

    def run(self) -> int:
        self.root.mainloop()
        return 0


def command_gui(_args: argparse.Namespace | None = None) -> int:
    app = StudentMetaToolApp()
    return app.run()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Add, edit, or inspect student metadata.")
    subparsers = parser.add_subparsers(dest="command")

    gui_parser = subparsers.add_parser("gui", help="Open the metadata editor UI.")
    gui_parser.set_defaults(func=command_gui)

    get_parser = subparsers.add_parser("get", help="Show metadata for one student.")
    get_parser.add_argument("student_id")
    get_parser.set_defaults(func=command_get)

    upsert_parser = subparsers.add_parser("upsert", help="Create or update student metadata.")
    upsert_parser.add_argument("student_id")
    for spec in FIELD_SPECS:
        name = str(spec["name"])
        if name == "student_id":
            continue
        upsert_parser.add_argument(f"--{name.replace('_', '-')}")
    upsert_parser.set_defaults(func=command_upsert)

    delete_parser = subparsers.add_parser("delete", help="Delete student metadata.")
    delete_parser.add_argument("student_id")
    delete_parser.set_defaults(func=command_delete)
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        return command_gui()

    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        return command_gui()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

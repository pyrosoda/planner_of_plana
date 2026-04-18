# Student Planner Handoff Guide

This document explains how the current student planner works so other AI tools and developers can safely continue work on the GUI and statistics areas without changing core behavior.

## Scope

- Intended edit targets:
  - `gui/viewer_app_qt.py`
  - `gui/student_stats.py`
  - `gui/student_filters.py`
- Out of scope:
  - New product features
  - Rewriting scan/storage logic
  - Reinterpreting growth-cost formulas unless absolutely necessary

If the task is only about GUI or statistics, it is safest to reuse existing calculation functions instead of modifying `core/planning_calc.py`.

## Main Data Flow

The app currently works in this order:

1. Scan results are saved.
   - Current students: profile-specific `current/students.json`
   - Current inventory: profile-specific `current/inventory.json`
   - SQLite cache: profile-specific `ba_planner.db`
2. The viewer loads student rows in `gui/viewer_app_qt.py` via `load_students()`.
3. Loaded rows are enriched with metadata from `core/student_meta.py`.
4. Filters are applied through `gui/student_filters.py`.
5. The statistics tab always uses `self._filtered_students`.
6. The planner stores target values in profile-specific `current/growth_plan.json`.
7. Cost calculation compares current student state against planner targets through `core/planning_calc.py`.

Important:
Statistics are based on the students currently visible in the Students tab, not on the full roster.

## Where Data Comes From

### Current student state

Loaded by `load_students()` in [viewer_app_qt.py](C:/Users/brigh/planner_of_plana/BA Planner/v6/gui/viewer_app_qt.py).

These fields come from scan data and represent the current owned state:

- `level`
- `student_star`
- `weapon_state`
- `weapon_star`
- `weapon_level`
- `ex_skill`, `skill1`, `skill2`, `skill3`
- `equip1`, `equip2`, `equip3`, `equip4`
- `equip1_level`, `equip2_level`, `equip3_level`
- `stat_hp`, `stat_atk`, `stat_heal`

Use these for "what the player currently has".

### Static student metadata

Stored in [student_meta.py](C:/Users/brigh/planner_of_plana/BA Planner/v6/core/student_meta.py).

Typical metadata fields:

- `display_name`
- `school`
- `rarity`
- `attack_type`
- `defense_type`
- `combat_class`
- `role`
- `position`
- `weapon_type`
- `cover_type`
- `range_type`
- `farmable`
- growth material references

Use these for filtering, grouping, labels, and material lookup.

### Planner target data

Defined in [planning.py](C:/Users/brigh/planner_of_plana/BA Planner/v6/core/planning.py).

Stored at profile-specific `current/growth_plan.json`.

Important target fields:

- `target_level`
- `target_star`
- `target_weapon_level`
- `target_weapon_star`
- `target_ex_skill`
- `target_skill1`, `target_skill2`, `target_skill3`
- `target_equip1_tier`, `target_equip2_tier`, `target_equip3_tier`
- `target_equip1_level`, `target_equip2_level`, `target_equip3_level`
- `target_equip4_tier`
- `target_stat_hp`, `target_stat_atk`, `target_stat_heal`

Use these only when computing "current to target" cost deltas.

### Inventory

Stored in profile-specific `current/inventory.json`.

Current planner cost output is gross requirement, not net shortage. In other words:

- `calculate_goal_cost()` and `calculate_plan_totals()` compute total required resources
- they do not subtract owned inventory directly

If a new stats panel needs shortage data, keep these three concepts separate:

- required amount
- owned amount
- shortage amount

Do not overwrite the meaning of existing total-cost fields.

## StudentRecord Is The UI View Model

`StudentRecord` in [viewer_app_qt.py](C:/Users/brigh/planner_of_plana/BA Planner/v6/gui/viewer_app_qt.py) is effectively the UI-facing merged model.

It combines:

- current scan state
- ownership state
- metadata fallbacks from `student_meta`

For GUI and statistics work, treat `StudentRecord` as the default source object.

When a new stat is needed, decide which bucket it belongs to:

1. current scanned state
2. static metadata
3. plan target
4. derived calculation result
5. inventory-based derived value

Keeping these buckets separate prevents many bugs.

## Cost Calculation Guide

The two main entry points are in [planning_calc.py](C:/Users/brigh/planner_of_plana/BA Planner/v6/core/planning_calc.py):

- `calculate_goal_cost(record, goal)`
- `calculate_plan_totals(records_by_id, plan)`

### Input contract

- `record` means the student's current state
- `goal` means the student's target state

The cost system always means "current -> target delta".

### Output contract

Costs are accumulated in `PlanCostSummary`.

Main numeric totals:

- `credits`
- `level_exp`
- `equipment_exp`
- `weapon_exp`

Main grouped material maps:

- `star_materials`
- `equipment_materials`
- `level_exp_items`
- `equipment_exp_items`
- `weapon_exp_items`
- `skill_books`
- `ex_ooparts`
- `skill_ooparts`
- `stat_materials`

Extra context:

- `stat_levels`
- `warnings`

### Safe rules when touching cost code

1. Keep calculation and presentation separate.
   - Calculation belongs in `planning_calc.py`
   - Formatting belongs in `_format_cost_summary()` inside `viewer_app_qt.py`
2. Do not mix total requirement with shortage logic.
3. Keep metadata lookups keyed by `student_id`.
4. Empty targets should continue to behave like "keep current value".
5. Do not make calculation functions depend on GUI state like filters or tabs.

### Functions that are better left alone during GUI-only work

- `_calculate_star_cost`
- `_calculate_single_equipment_cost`
- `_calculate_weapon_level_cost`
- `_calculate_skill_book_cost`
- `_calculate_ex_ooparts`
- `_calculate_skill_ooparts`
- `_calculate_single_stat_cost`

These functions already define the meaning of each material group. Editing them for layout work is high risk.

## Statistics Guide

Statistics logic currently lives in:

- [student_stats.py](C:/Users/brigh/planner_of_plana/BA Planner/v6/gui/student_stats.py)
- `_refresh_stats_tab()` inside [viewer_app_qt.py](C:/Users/brigh/planner_of_plana/BA Planner/v6/gui/viewer_app_qt.py)

### Base dataset

The stats tab always works from `self._filtered_students`.

That means the stats change when any of these change:

- search query
- selected filters
- "show unowned" toggle

Sorting changes card order but should not change counts.

### Current statistics

Summary cards:

- visible students
- owned students
- planned students
- average level
- average star

Distribution charts:

- `owned`
- `school`
- `combat_class`
- `attack_type`
- `defense_type`
- `role`

### Rules for adding new statistics

1. Decide the data source first.
   - direct `StudentRecord` field
   - metadata fallback
   - planner result
   - inventory-derived result
2. Decide whether it is:
   - a distribution stat, or
   - a numeric aggregate
3. Decide how unowned students should be handled before implementation.
4. Keep missing-value behavior consistent.
   - current distribution code uses `(Missing)` when value is empty
5. Reuse label formatting where possible.
   - `FILTER_FIELD_LABELS`
   - `format_filter_value()`

### If statistics need planner-cost data

Do not reimplement the formulas inside the stats tab.

Use this pattern instead:

1. Start from the relevant student set
2. find matching `StudentGoal`
3. call `calculate_goal_cost()` or `calculate_plan_totals()`
4. display the returned summary

## Filter Guide

Filter logic is centered in [student_filters.py](C:/Users/brigh/planner_of_plana/BA Planner/v6/gui/student_filters.py).

Key pieces:

- `FILTER_FIELD_ORDER`
- `FILTER_FIELD_LABELS`
- `META_FILTER_KEYS`
- `get_student_value()`
- `matches_student_filters()`
- `build_filter_options()`

### Current meaning

- `student_star` and `weapon_state` come from current student state
- most other filter fields come from `student_meta`

So when adding a new filter, first decide whether the value is:

- dynamic current-state data, or
- static metadata

### Safe procedure for adding a new filter

1. Add the field to `core/student_meta.py` if it is metadata.
2. Add the field to `StudentRecord` and `_row_to_record()` in `viewer_app_qt.py`.
3. Add it to `FILTER_FIELD_ORDER`.
4. Add its label to `FILTER_FIELD_LABELS`.
5. If needed, add formatting logic to `format_filter_value()`.
6. If the stats tab should use it too, add it to the appropriate chart or stat config.

## Metadata Extension Guide

If student filters need more metadata, use these rules.

### Good candidates for metadata

Metadata should be stable and classification-oriented, for example:

- academy grouping
- content role
- damage profile
- support tag
- special mechanic tags

### Bad candidates for metadata

Do not store frequently changing values in `student_meta`, such as:

- current level
- current star
- current equipment tier
- current scanned quantities

Those belong to scan data or derived calculations.

### Naming rules

Use:

- lowercase snake_case keys
- normalized enum-like strings when possible
- lists only when true multi-value classification is needed

Examples:

- single value: `content_role = "raid_support"`
- multi value: `content_tags = ["aoe", "debuffer", "outdoor_focus"]`

### Compatibility rules

New metadata fields should be optional-safe.

The existing code already tolerates missing metadata by falling back to `None` or empty strings. Keep that behavior so older entries do not break the UI.

### Tooling

If metadata will be edited regularly, update these too:

- [student_meta_tool.py](C:/Users/brigh/planner_of_plana/BA Planner/v6/tools/student_meta_tool.py)
- [student_meta_options.py](C:/Users/brigh/planner_of_plana/BA Planner/v6/tools/student_meta_options.py)

That keeps the editor in sync with the schema.

## Recommended Boundaries For Parallel Work

To reduce merge conflicts, split work like this:

Safe parallel areas:

- statistics layout and visual polish
- stats cards and chart composition
- filter UI and option presentation
- metadata expansion and metadata editor support

Higher-conflict areas:

- `core/planning_calc.py`
- shared large methods inside `gui/viewer_app_qt.py`

Recommended split:

- one tool edits statistics presentation
- another edits filter/metadata support
- avoid concurrent edits inside the same large method whenever possible

## Quick Checklist

For GUI/statistics changes:

- confirm the stat uses `filtered_students` intentionally
- confirm how unowned students are handled
- reuse cost functions instead of rewriting formulas
- keep labels aligned with actual data meaning

For new metadata/filter fields:

- add metadata field
- wire it into `StudentRecord`
- add filter label/order/formatting
- keep missing values safe
- update metadata tooling if the field will be edited often

For resource-based statistics:

- separate total required
- separate owned inventory
- separate shortage

Do not collapse those into one overloaded field.

## Short Operational Summary

- `StudentRecord` is the main UI model
- `StudentGoal` is the planner target model
- `calculate_goal_cost()` is the single-student cost entry point
- `calculate_plan_totals()` is the whole-plan cost entry point
- statistics use `filtered_students`
- `core/student_meta.py` is the single source of truth for static student metadata

If those boundaries are preserved, the GUI and statistics layers can change quite freely without breaking planner math or storage behavior.

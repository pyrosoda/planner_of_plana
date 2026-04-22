# Inventory Sorting Rules

This document records the scan/display order expected by the inventory scanner.
The code source of truth is `core.inventory_profiles`, with item ID lists coming
from `core.oparts` and `core.equipment_items`.

## Storage Key

Inventory quantities are stored by `item_id` when an ID is available. Display
names are metadata only. Name keys are used only as a fallback for profiles that
do not have stable IDs yet.

## Scan Profiles

### Tech Notes

Profile ID: `tech_notes`

Order:

1. School order:
   `Hyakkiyako`, `RedWinter`, `Trinity`, `Gehenna`, `Abydos`, `Millennium`,
   `Arius`, `Shanhaijing`, `Valkyrie`, `Highlander`, `Wildhunt`.
2. For each school, tier order is `0`, `1`, `2`, `3`.
3. Final item is `Item_Icon_SkillBook_Ultimate_Piece`.

ID pattern:

```text
Item_Icon_SkillBook_{School}_{Tier}
```

### Tactical BD

Profile ID: `tactical_bd`

Order:

1. Same school order as tech notes.
2. For each school, tier order is `0`, `1`, `2`, `3`.

ID pattern:

```text
Item_Icon_Material_ExSkill_{School}_{Tier}
```

### Ooparts

Profile ID: `ooparts`

Order:

1. `OPART_DEFINITIONS` declaration order in `core.oparts`.
2. For each opart family, tier index order is `0`, `1`, `2`, `3`.
3. Then workbook items in `OPART_WB_ITEMS` order.

ID pattern:

```text
Item_Icon_Material_{IconKey}_{TierIndex}
```

### Equipment

Profile ID: `equipment`

Order:

1. Equipment exp stones in `EQUIPMENT_EXP_ITEMS` order:
   `Equipment_Icon_Exp_3`, `Equipment_Icon_Exp_2`,
   `Equipment_Icon_Exp_1`, `Equipment_Icon_Exp_0`.
2. For each equipment series in `EQUIPMENT_SERIES` declaration order, tiers
   `10` down to `2`.
3. For each equipment series again, tier `1`.
4. Weapon growth parts in `WEAPON_PART_ITEMS` order: `Z`, `C`, `B`, `A`.
5. For each weapon part, tiers `4` down to `1`; the ID suffix is zero-based,
   so those become suffixes `3`, `2`, `1`, `0`.

ID patterns:

```text
Equipment_Icon_{SeriesIconKey}_Tier{Tier}
Equipment_Icon_WeaponExpGrowth{PartKey}_{TierMinusOne}
```

### Coins

Profile ID: `coins`

Coins currently use the explicit `_COIN_NAMES` list in `core.inventory_profiles`.
They do not have stable item IDs in the profile yet, so storage falls back to
the normalized name.

### Activity Reports

Profile ID: `activity_reports`

Reports currently use the explicit `_REPORT_NAMES` list in
`core.inventory_profiles`. They do not have stable item IDs in the profile yet,
so storage falls back to the normalized name.

## Gap Recovery

When profile gap recovery runs, the scanner compares captured detail crops
against the ordered list above. Missing ordered positions are written as
quantity `0`; matched positions use the canonical `item_id` for that profile.

## Viewer Group Sorting

The Qt inventory viewer groups items before sorting:

1. Equipment tier items are grouped by equipment series and sorted by tier
   descending.
2. Ooparts, workbooks, exp stones, reports, weapon parts, tech notes, and BD
   each use their profile order map.
3. Unknown items fall back to display label alphabetical order.

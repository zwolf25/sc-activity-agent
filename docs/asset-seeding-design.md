# Asset seeding design (B-67)

Status: draft for review, 2026-11-02. Nothing is built. Research and verified API facts are in `asset-seeding-research.md`; this file decides how the feature works.

## Scope

In:
- Trades that carry assets: HVAC, Electrical, Plumbing.
- Create assets at a location until it meets the target per trade.
- Audit a location: counts per trade, and assets with empty fields.
- Enrich: fill empty fields on existing assets.
- A one-time load for existing Production locations, then on command for each new location.

Out:
- Warranty (B-68). Seeded assets get no warranty.
- Doors, Janitorial and General Maintenance assets.
- Attaching assets to WOs (B-23, B-24).
- Creating asset types by default. See "Asset types" below: creation is an opt-in step.
- Circuits and components (parent and child assets).
- Deleting assets.

## Commands

All commands take `--location <store id>` (or `--all`). Writes go through the normal rate-limited client, so 50 assets take about 4 minutes at 15 calls a minute.

| Command | Writes | What it does |
|---|---|---|
| `agent assets plan` | no | Builds the plan and prints it: per trade, the asset type, tag, brand, model, serial, install date, condition and value that would be created, and the assets that already exist. Saves nothing. |
| `agent assets seed` | yes | Runs the plan. Creates each asset with `POST /assets` and records it in the `assets` table. Stops on the first error that is not a per-asset validation error. |
| `agent assets audit` | no | Lists the location's assets per trade against the targets and flags empty fields (no install date, value, area, model or serial). |
| `agent assets enrich` | yes | Prints a before and after diff for assets whose fields are empty, then applies it with `PUT /assets`. Only agent-created assets by default. `--include <asset id>` adds a named asset the agent did not create. |

Rules shared by `seed` and `enrich`:
- `plan` output is the dry run. `seed` and `enrich` print the same table first and wait for `--yes` on the command line. Without `--yes` they exit after printing, so a script cannot write by accident.
- Production needs `--yes` and a one-time approval per location recorded in settings (`assets.approved_locations`). Zac sets it with `agent set`. Without it the command refuses on a Production instance. SB2 needs no approval.
- `enrich` never overwrites a field that already has a value. It only fills empty fields. Condition counts as empty only when the asset has no install date to compare against.
- Idempotent: an asset is identified by its tag. A tag already present at the location (found via `GET /assets?locationId=`) is skipped, whoever created it.

## Asset types

SB2 and Production hold the same asset types (read-only check on Production, 2026-11-02: 69 types, identical to SB2; HVAC 15, Electrical 3 (Generator, Monitor, Electrical - Meter), Plumbing 2 (Dishwasher, Water Heater), and no types for lighting, panels, exit and emergency lights, backflow preventers, pumps or fixtures). Production has two locations: HQ-NYC (2 assets, both outside our trades) and ZW123 (none).

Decision (Zac, 2026-11-02): the agent may create realistic asset types. `POST /assettypes` works. So `seed` creates the catalog types an account lacks, in the same run. The plan lists each type to create by name and primary trade before anything is written, like the assets. Created types are recorded in the `assets` table family (`asset_types`, see State) so `audit` can tell them from the account's own. Only types in the catalog are created, only in the trades that carry assets. No other settings are touched.

## Catalog

A data file shipped in the package: `sc_activity_agent/assets_catalog.json`. Adding a type or a make is a data edit, not code.

Per trade, a list of entries. One entry:

```json
{
  "type": "RTU",                  // matched by name against GET /assettypes at the location
  "code": "RTU",                  // tag code
  "weight": 3,                    // share of the trade's draw
  "max": 6,                       // cap per location
  "life_years": 15,
  "value": [12000, 28000],        // original value range
  "areas": ["Roof"],
  "refrigerant": true,            // sends UsesRefrigerant 1
  "models": [
    {"brand": "Carrier", "model": "48TCED08A2A5-0A0G0", "serial": "carrier"},
    {"brand": "Trane", "model": "YHC060", "serial": "generic"}
  ]
}
```

- `brand` is matched by name against `GET /assets/brands` (cached in the data dir, refreshed weekly). A brand that does not match is skipped with a warning. The brand must resolve before create (error 503 otherwise). The list holds about 40,000 user-entered names with many near-duplicates (`Lennox RTU`, `Carrier (PACKAGED)`), so substring matching is wrong. Each catalog brand carries a `brand_name` that must match case-insensitively and exactly, and the catalog keeps the canonical SB2 id as a check (SB2, 2026-11-02): Carrier 8, Trane 22, Lennox 6, YORK 21, Bradford White 178, RHEEM 27, A.O. SMITH 402 (`A.O.SMITH` is 167), Lithonia 3720, Sure-Lites 15302, Square D (Schneider Electric) 366, Generac 1230, Watts 1661, Zurn 386, SLOAN 2824. A mismatch of name or id on Production stops the plan.
- `serial` names a formatter. Manufacturer-sourced: `rheem` (month, year, plant letter, five digits), `aosmith` (year, week, digits), `bradford` (year letter, month letter, digits, from Bradford White's chart), `trane` (year, week, sequence, factory letter; layout partly inferred). Documented in a write-up Zac supplied (not checked against a real nameplate): `lennox` (plant 2 digits, year 2 digits, month letter A to M skipping I, 5 digit sequence: `5614A01234`) and `york` (plant letter, first year digit, month letter A to N skipping I and J, second year digit, 6 digit sequence: `N0L4123456`; installs from October 2004 on). Forum-sourced: `carrier` (week, year, a letter, five digits: `5021P43556`). Brands with no source (Lithonia, Sure-Lites, Square D, Generac) use `generic`: a plausible alphanumeric that does not claim to decode. The serial date always matches the install date, and the serial's year/month is the manufacture date, so install is 1 to 6 months after it.
- Lennox models use complete strings only: `LGH060U4ES1Y` (3 to 6 ton) and `LGH120H4BS1Y` (7.5 to 12.5 ton); older `TGA036S2B` only for installs before 2010 (R-22). Never seed the prefixes `LGH036H4B` or `LGH092H4B`. York Predator models (`ZJ061`, `ZJ090` and so on, sizes 037, 049, 061, 078, 090, 102, 120, 150) are marked `unverified` in the catalog until a full string is confirmed; York gets no `YC` models.
- Per-trade targets (assets per location, drawn once per location with a seeded random from the store id, so a re-run draws the same number): HVAC 3 to 8, Electrical 8 to 20, Plumbing 6 to 14.
- Targets count assets already at the location in the same trade, so a location with 5 HVAC assets only gets the difference.

Catalog content is a starting point from general industry knowledge. It must be checked by someone with facilities knowledge before the first Production run (this is the first item in the rollout below).

## Realism rules in the generator

1. Install date: uniform over 0 to `life_years` back from today, nudged toward the middle (average of two draws), plus a 5% chance of an asset past its life. Time of day 08:00.
2. Condition (0 to 100): from age as a fraction of life, `100 - 60 * fraction`, plus a draw of plus or minus 8, clamped to 5 to 100. Past-life assets land under 40.
3. Purchase date: install date minus 3 to 30 days.
4. Original value: random in the entry's range, rounded to the nearest 50.
5. Tag: `<STORE>-<CODE>-<NN>` with the store id stripped of dashes, for example `HQNYC-RTU-01`. `AssetTag` equals `Tag`. The number is the next free one for that code at the location.
6. Area: from the entry's `areas`.
7. Every field is filled. Zac's rule (2026-11-02): no empty serial, purchase date or other field. Each seeded asset has tag, asset tag, type, brand, model, serial, install date, purchase date, original value, condition, area and a description (type, make and model in one line, for example `Carrier 48TCED08A2A5 rooftop unit, 7.5 ton`). Model and serial go in `ModelNo` and `SerialNo` (confirmed stored). `audit` flags any asset with an empty field, and `enrich` fills it.
8. A seeded random keyed on store id and tag makes `plan` repeatable: the same location always plans the same assets until the targets change.
9. Batches: assets of one type are created in batches. A batch of two to four shares brand, model and an install date within a month, with serials in sequence. Different batches differ in age and sometimes in brand, so a site reads as installed over time. Single-unit types (a water heater) are one-offs.

## State

New table, added as an append-only entry in `store.MIGRATIONS`:

```sql
CREATE TABLE IF NOT EXISTS assets(
  id INTEGER PRIMARY KEY,        -- ServiceChannel asset id
  location TEXT NOT NULL,        -- store id
  tag TEXT NOT NULL,
  trade TEXT NOT NULL,
  type TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(location, tag)
);
```

A second table, added in the same migration, records the asset types the agent created:

```sql
CREATE TABLE IF NOT EXISTS asset_types(
  id INTEGER PRIMARY KEY,        -- ServiceChannel asset type id
  name TEXT NOT NULL,
  trade TEXT NOT NULL,
  created_at TEXT NOT NULL
);
```

Why: `audit` and `enrich` must tell agent-created assets from real ones, and the platform has no marker field. The table is the only record. A restored backup restores it with the rest of the database.

## Where it lives in the code

- `sc_activity_agent/assets.py`: catalog loading, plan builder, seed and enrich runners, audit. Pure functions for the plan so tests need no API.
- `sc_activity_agent/assets_catalog.json`: the catalog.
- `sc_activity_agent/cli.py`: the `assets` sub-commands.
- Console: a later step, not part of the first release. The Locations page gets an "Assets" panel (counts per trade, Seed button) once the CLI is proven. A new location prompt ("seed assets for this location?") follows then.
- Docs updated in the same pass: ARCHITECTURE (module table, the table-as-marker decision), README (commands), CHANGELOG, api-notes (final field list).

## Tests

- Plan: same location gives the same plan twice; counts respect targets; existing assets reduce the need; tags are unique.
- Generator: condition falls with age; dates are inside life; values are in range.
- Seed: fake client records the `POST` bodies, a rerun creates nothing, a 400 on one asset is logged and the run continues.
- Enrich: fills only empty fields; skips assets not in the `assets` table without `--include`.
- Migration: opens an old database and adds the table.

## Rollout

1. Check the catalog (a person with facilities knowledge, or me with a second source). Fix gaps.
2. Build and release behind the CLI only (version number is Zac's call). SB2 first: seed HQ-NYC and read the results back in the SB2 console.
3. Run the SB2 spike items that remain (below) before the Production run. Do not guess in Production.
4. Production: `plan` for one location, Zac reviews the table, Zac sets the approval for that location, seed it, check it in the console. Then the rest of the locations.
5. Ask before touching Production at every step. Reads in Production need Zac's go-ahead too.

## Answers to the earlier open questions (2026-11-02)

1. Production asset types: read (Zac approved read-only). Identical to SB2, so the type-creation decision above applies to both.
2. `ModelNo` and `SerialNo` are stored and returned on `GET`, to Subscriber and Provider users.
3. Omitting a field on `PUT /assets` keeps its value (tested across ten updates). The core fields must be sent.
4. Rate: seeding takes 5 calls a minute when the engine is running, all 15 when it is not. `--rate` option with that default.
5. Provider users see assets created by the Subscriber, with model, serial and condition.

## Remaining open questions

1. Brand coverage: done on SB2 (all 14 catalog brands exist, ids in the Catalog section). Still open: read the same list on Production (read-only, your go-ahead given for reads) to confirm the ids match.
2. Lennox and York serial formats come from a write-up Zac supplied (cited manufacturer documents, not fetched by me) and are not checked against a real nameplate. The York full model string is approximate. A real nameplate per brand, with a known manufacture date, would close this.
3. A facilities person should check the catalog before the first Production run.

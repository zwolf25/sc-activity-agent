# Asset seeding research (B-67)

Status: research draft, 2026-11-02. Nothing here has been run against Production. API details marked "open" need an SB2 spike once SB2 is back (it returned 500 on every call for the whole session of 2026-11-02).

## Why

WOs with assets (B-23), providers attaching assets (B-24) and per-asset checklists (B-22) need enough realistic assets, per trade we work, at each location. HQ-NYC on SB2 has two assets (a Pizza Oven, KITCHEN EQUIPMENT, and a Monitor, ELECTRICAL). Neither is in a trade our provider holds there.

## Which trades carry assets (decision, 2026-11-02)

Not every trade has equipment worth tracking. Zac's call: Doors and Janitorial do not carry asset types; Electrical does. Asset types and seeded assets exist only for trades that carry assets, and WOs in the other trades are never created with an asset (B-23) or have one attached (B-24).

| Trade | Carries assets | Status |
|---|---|---|
| Electrical | Yes | Decided by Zac |
| Doors | No | Decided by Zac |
| Janitorial | No | Decided by Zac |
| HVAC | Yes | Confirmed: the core equipment trade (RTUs, split systems) |
| Plumbing | Yes | Confirmed: water heaters, pumps, backflow preventers |
| General Maintenance | No for now | Confirmed: items are too generic and mixed to make a stable catalog; revisit if B-23 needs it |

Zac confirmed the proposed rows (2026-11-02). Consequences: on SB2 the existing `xoi`, `door test` (Doors) and `Tables (All)` (Janitorial) types are test data and stay unused; the Doors asset 10889508 was a test of the attach rule and is not a model for seeding. Warranty is out of scope (B-68): seeded assets get no warranty.

Trades that matter:
- SB2: Doors, General Maintenance, HVAC.
- Production: Doors, General Maintenance, HVAC, Electrical, Janitorial, Plumbing.

## What a ServiceChannel asset holds

Sources: the shared Second Brain wiki `asset-setup-and-tracking`, the SC Mobile "Asset Tagging" help page, and one `GET /assets?locationId=` response on SB2.

Fields seen in the API response (SB2, 2026-11-02): `Id`, `Tag`, `Manufacturer`, `LocationId`, `StoreId`, `Trade`, `TradeId`, `Type`, `AssetTypeId`, `BrandId`, `InstallDate`, `InstallDateVal`, `PurchaseDate`, `UsesRefrigerant`, `Active`, `IsLeased`, `Condition` (100) with `ConditionString` ("excellent"), `HasLeakDetector`, `HasTagged`, `Warranty{Priority, Category, Provider, Expiration}`, `IsReplaceEquipment`, `AssetAttributesMap`, `CustomAttributes`, `AssetStatus`, `AssetValidated`, `AssetValidationStatus`, `HasChilds`, `HasCircuits`, `HasComponents`, `IsCircuit`.

Fields from the UI and wiki that the API response did not show as filled: Model Number, Serial Number, Asset Tag (the scannable value, separate from Tag ID), Area, Work Order Area, Original Value, Warranty Months, lease period and start date. The Condition Analysis report needs four inputs: Installation Date, Original Value, Committed Spend (derived from NTE and invoices) and Warranty Period. Without them the report is empty, so seeding must fill install date, original value and warranty.

Rules from the wiki:
- Tag ID, Location, Brand and Install Date are required. Which other fields are required is set on the Asset Type, not per asset.
- Primary Trade on the Asset Type must match the trade used for routing. Warranty details take precedence over trade-based dispatch while the warranty runs. Seeded warranties therefore change who a WO routes to. Seeded assets get no warranty (B-68), so this routing override never fires.
- Changing the type of an existing asset drops the readings and attributes tied to the old type.
- Complex assets can have circuits and components, created parent first. Not needed for seeding at first.
- There is a UI bulk import (Imported Assets, three templates). Whether the API has an equivalent is open.

## Realism rules (proposal)

1. Match the trade: the asset type's primary trade is the trade of the WO it can attach to. Seed only trades that carry assets (see the decision above) and that the location's provider holds.
2. Counts per location, retail or office: HVAC 3 to 8, Electrical 8 to 20, Plumbing 6 to 14. About 20 to 40 assets in total. Exact numbers come from a per-trade range and a seeded random draw so a re-run does not add more.
3. Install dates spread over the equipment's life, weighted to the middle: not all new, not all at end of life. Reasonable spread: 0 to 20 years for HVAC, 0 to 15 for doors and plumbing, 0 to 12 for lighting. A few assets sit past typical life.
4. Condition follows age. Proposed bands: under 40% of life is excellent, 40 to 75% good, 75 to 100% fair, past life poor. Add noise. The numeric scale behind `Condition` is open (100 means excellent; need the other values).
5. Manufacturer and model are paired from a catalog, never mixed at random. Serial numbers are plausible and consistent with the install year. Only claim a decodable format where the format is known (A.O. Smith water heaters begin with month and year as MMYY in one source; Rheem formats vary by era). Otherwise use a plausible alphanumeric and do not pretend it decodes.
6. Warranty: none. Out of scope (B-68).
7. Original value: a range per type, so the Condition Analysis works.
8. Tag ID scheme per location: store id plus a type code plus a sequence number (for example `HQNYC-RTU-01`), unique and stable. Asset Tag equals Tag ID, as the help page says they should match.
9. Area: a plausible physical area per type (RTUs on the roof, doors at the entrance or dock, water heaters in the back of house).
10. The agent records every asset it creates (id, location, tag, catalog key). Re-runs skip a tag that already exists, so seeding is idempotent, and `audit` can tell the agent's assets from real ones.

## Catalog by trade (starting point, to verify)

Doors, Janitorial and General Maintenance rows were removed (see the trade decision above). Confidence: the equipment types, brands and use of model families come from general industry knowledge, not from a ServiceChannel source or a manufacturer document. The web searches returned mostly weak sources and no authoritative useful-life tables. Treat life spans as plausible, and have a facilities person or the manufacturer literature check the catalog before Production.

| Trade | Asset types (examples) | Makes (examples) | Typical life (plausible) |
|---|---|---|---|
| HVAC | Rooftop unit (3 to 25 ton), split system or mini-split, thermostat or controller, exhaust fan, unit heater | Carrier, Trane, Lennox, York, Daikin, Mitsubishi, Greenheck, Modine | RTU 15 to 20 years, mini-split 12 to 15, controller 10 to 15, fans 15 to 20 |
| Electrical | LED light fixture, emergency or exit light, electrical panel, lighting controller, transfer switch, generator, digital monitor | Lithonia, Cooper (Eaton), Philips, Sure-Lites, Square D, Eaton, Siemens, GE, Lutron, Generac, Cummins | Fixtures 10 to 15 (LED), panels 30 plus, emergency lights 8 to 12 (batteries 3 to 5), generators 20 plus |
| Plumbing | Water heater (gas or electric, 40 to 100 gal), toilet or urinal, sensor faucet, mop sink, floor drain, backflow preventer, sump pump | A.O. Smith, Rheem, Bradford White, Kohler, American Standard, Sloan, Zurn, Watts, Zoeller | Water heaters 10 to 15, fixtures 20 plus, valves and pumps 10 to 15 |

Examples that came from search results (treat as leads): a Carrier rooftop model code of the form `48TCQ036`, and a Trane code of the form `TWR048C100A3VBA` (that one may be a residential heat pump family).

## SB2 spike results (2026-11-02, after SB2 recovered)

- `GET /assets/brands` returns the brand list (Id, Name; over 1.5 MB, so cache it). `/brands` and `/assetbrands` are 404.
- `GET /assettypes` returns about 21 KB. SB2 types by primary trade: HVAC 15 (RTU, Condenser, Compressor, Window AC, Minni Split, Direct Vent Boiler and others), Plumbing 2 (Dishwasher, Water Heater), Electrical 3 (Generator, Monitor, Electrical - Meter), Doors 2 (`xoi`, `door test`), General Maintenance 2 (Standard Circuit, Conveyor), Janitorial 1 (Tables (All)), plus Kitchen Equipment 12 and Refrigeration 18. Doors and Janitorial have no realistic types on SB2, so seeding there needs new asset types. Whether the API can create a type is open.
- `GET /assettypes/{id}` returns Id, Name, PrimaryTrade, TradeId, AdditionalTrades, BrandIds. Attribute, status and condition lookups (`/assettypes/{id}/attributes`, `/assets/attributes`, `/assetattributes`, `/assetstatuses`, `/assets/conditions`) are all 404.
- `GET /assets/{id}` works. The response carries the fields listed above. Model and serial (`ModelNo`, `SerialNo`) appear once set; the two pre-existing assets have none.
- A seeded brand name shows in `Manufacturer` (the Pizza Oven has "#1 Carrier").

## SB2 write probes (2026-11-02, test asset 10889537 at HQ-NYC)

- `POST /assets` returns `{"Id": n}`. Fields that stick on create: `Tag`, `AssetTag`, `AssetTypeId`, `BrandId`, `Manufacturer`, `InstallDate`, `PurchaseDate`, `OriginalValue`, `Condition` (number, 0 to 100), `Area` (read back as `Area` and `Location`), `UsesRefrigerant`.
- A refrigerant asset type (such as RTU, which has a `RefrigerantPurposeId`) fails with error 5028 "Uses Refrigerant attribute is required" unless `UsesRefrigerant` is 1.
- Update is `PUT /assets` with `Id` plus the required core fields (`LocationId`, `AssetTypeId`, `BrandId`, `Tag`, `UsesRefrigerant`) in the body. `PUT /assets/{id}` returns 500 "Multiple actions were found" and `PATCH` returns UnsupportedApiVersion. A `PUT` returns the Id with 200, and a `GET` shows what changed. Condition, `IsLeased` and `LeasePeriod` update this way.
- Model and serial: `ModelNo` and `SerialNo` are accepted and stored (a later `GET /assets/{id}` returns them, for the Subscriber and for the Provider user). `Model`, `ModelNumber`, `Serial` and `SerialNumber` are ignored. `Description` is accepted and stored.
- Omitting a field on `PUT /assets` keeps its value: install date, area, condition and purchase date stayed unchanged across ten updates that left them out. The core fields (`Id`, `LocationId`, `AssetTypeId`, `BrandId`, `Tag`, `UsesRefrigerant`) must be sent.
- A Provider user at the owning provider sees assets created by the Subscriber (`GET /assets?locationId=` and `GET /assets/{id}`), including model, serial and condition.
- Asset types can be created: `POST /assettypes` with `Name`, `PrimaryTrade`, `TradeId` and `IsActive` returns `{"Id", "ErrorCode": 0}` (test type 38779 "LED Light Fixture" on SB2). Fields of a type: Id, Name, PrimaryTrade, TradeId, AdditionalTrades, AssetTypeGroupId, IsCircuit, ParentId, RefrigerantPurposeId, BrandIds.
- Warranty: `Warranty.PriorityId` 1 stores "Normal". `WarrantyMonths`, `WarrantyPeriod` and the expiration shapes tried did nothing, and an unknown Priority string fails with 503 "Invalid PriorityId". Category and Expiration formats remain open.
- No lookup endpoints for warranty priorities and categories (404 on four guesses).
- There is no DELETE tried yet, so the seeded asset stays; `Active: false` through `PUT` is untested.

## SB2 asset types in our asset trades (2026-11-02)

- HVAC (TradeId 120881): RTU (refrigerant, comfort cooling), Refrigerated Circuit, Condenser, Compressor, HVAC, Window AC, Portable Air Conditioner, Central Air Conditioner, Ground Level Air Conditioner, Minni Split (refrigerant), Minni Split circuit, Direct Vent Boiler, plus test types.
- Plumbing (TradeId 112194): Dishwasher, Water Heater. Nothing for fixtures, backflow preventers or pumps.
- Electrical (TradeId 112195): Generator, Monitor, Electrical - Meter. Nothing for lighting, panels or emergency lights.
- Consequence: the catalog below needs types that SB2 lacks (panelboard, light fixture, exit and emergency light, backflow preventer, sump pump, fixtures). Either the seed creates the missing types (`POST /assettypes` works), or Electrical and Plumbing seeding is limited to the few existing types. Production's types are not known; reading them needs Zac's go-ahead.

## Second research pass: realistic records (2026-11-02)

Verified from manufacturer or distributor sources unless marked "knowledge" (my own industry knowledge, no source found) or "conflict" (sources disagree).

HVAC
- Carrier 48TC gas/electric rooftop, 3 to 15 tons. Model strings in Carrier product data: `48TCED08A2A5-0A0G0`, `48TCED12A2A5-0A0G0`, `48TCED09A2A6-0A0G0`. Digits 7 and 8 are the size (04, 05, 06, 07, 08, 09, 12, 14, 16 map to 3, 4, 5, 6, 7.5, 8.5, 10, 12.5, 15 tons: knowledge); heat level is the fifth letter (D low, E medium, F high); the 17th character is the electrical option. Serial: first two digits week, next two year, then a letter and digits (example `5021P43556` is week 50 of 2021: one forum source, treat as probable). Carrier's own note: a serial starting at 3112 or higher is July 2012 or later.
- Lennox: rooftop models are built from unit type, family, voltage, heat level, tonnage and efficiency; sample `TGA090H2B` (2008 engineering bulletin, T-class, 7.5 tons). Newer families (Energence LGH/LCH) are knowledge. Serial date format: conflict, so use a generic serial.
- Trane Precedent `YHC036` to `YHC120` and `YSC` (knowledge); York `ZF`/`ZJ` Sunline series (knowledge). Neither has a source for nomenclature or serial format: conflict. Use generic serials.
- Service life: Building Center puts packaged rooftop design life at 10 to 15 years, 15 to 20 with good maintenance. Keep RTU life at 15 (range 10 to 20), not 18.

Plumbing
- Bradford White `RG250T6N`: 50 gal, 40,000 BTU, atmospheric vent, 6-year tank warranty. Sold as a residential-style unit, but common in light-commercial retail. Serial: first letter year, second letter month, from a 20-letter cycle that skips I, O, Q, R, U and V (manufacturer chart in the third pass). Use it for Bradford White.
- Rheem: first four digits are month and year, for example `1209D01234` is December 2009 (one source; another source says week and year: conflict). A.O. Smith: year and week (`1719` is week 19 of 2017) per one source, two letters per another: conflict. Use generic for A.O. Smith.
- No source found for A.O. Smith BTX-100, Watts 007, Zurn Wilkins 975XL or Sloan Royal models. Those names are knowledge; keep only what a facilities person confirms.
- Service life: Building Center gives storage-tank water heaters 10 to 12 years. ASHRAE's service-life database (costdatabase.ashrae.org) has medians per system type, not fetched in full: gas domestic water heaters show 15 years median for replaced units.

Electrical
- Lithonia LED troffers: `2GTL4 A12 120 LP840` (2x4, 4,000 lm, 4000K) and `2GTL2 A12 120 LP840` (2x2, 2,200 lm, 4000K) from distributor listings; STACK line (`STAK 2X4 ...`) also listed.
- Sure-Lites emergency and exit units: `APC7RG` (combination LED exit sign and emergency light, 90-minute run time), `LPX7DH` (combo, discontinued), `CHXC` series, `EUX6G` (edge-lit exit sign), `LPX6` (die-cast exit sign). The batteries are the short-life part.
- Square D panelboards: `NQ442L2C` (NQ panelboard interior, 225 A, 42 spaces, three-phase) suits retail; `QO142M200PRB` and `QO120M100` are residential-style load centers (small stores and back rooms).
- Generators and meters: knowledge only (Generac, Cummins, Kohler; utility meters).
- Service life for lighting and panelboards: no source found. Keep as knowledge: LED fixtures 12 to 15 years, panelboards 30 or more, emergency batteries 4 to 5 years.

Realism behaviors found from how real sites look (knowledge, to confirm with a facilities person)
- Units installed together look alike: a store with four rooftop units usually has the same brand and model, one install date (within a month) and serial numbers that run in sequence. Seeding should create these in batches, not four independent draws.
- Not every asset has every field. Real sites have gaps: old units without a purchase date, some without a serial. A small share (about 10%) with empty serial or purchase date reads as more real than 100% complete.
- Replacements break the pattern: a site may have one newer unit among older ones.
- Tags follow the customer's own scheme (store number and a type code), not random IDs.

## Third research pass: manufacturer sources, via Scrapling (2026-11-02)

Fetched from the manufacturers' own pages. These replace the earlier "conflict" and "knowledge" entries where they overlap.

Serial number formats (manufacturer-confirmed unless marked)
- Rheem water heaters ([rheem.com serial number page](https://www.rheem.com/how-to-locate-and-read-your-rheem-water-heating-serial-numbers/)): ten characters, month (2 digits), year (2 digits), plant line code (1 letter), consecutive number (5 digits). Example `1209D01234` is December 2009.
- A.O. Smith ([aosmithinternational.com](https://aosmithinternational.com/manufacturing-date-device/)): first two digits the year, next two the week. Example: serial starting `2037` is week 37 of 2020. (This page covers the BFC Cyclone line; the same year-week form is what the consumer lookup pages describe for tank heaters.)
- Bradford White ([bradfordwhite.com](https://www.bradfordwhite.com/my-water-heater/)): the first two characters are year and month. Year letters skip I, O, Q, R, U, V: A=2004 or 2024, B=2005, C=2006, D=2007, E=2008, F=2009, G=2010, H=2011, J=2012, K=2013, L=2014, M=2015, N=2016, P=2017, S=2018, T=2019, W=2020, X=2021, Y=2022, Z=2023. Month letters: A=January through H=August, J=September, K=October, L=November, M=December. The rest is a sequence number.
- Trane light commercial ([Trane support article](https://support.trane.com/hc/en-us/articles/44514808922893-How-to-read-a-Light-Commercial-Unit-Serial-Number-Date-Code)): year code then week code. From 2010 the year code is the two-digit year (10, 11, ... 24); from 2002 to 2009 it is one digit (2 to 9). The page shows the full layout (sequence number and factory) only in an image that could not be read, so use year (2 digits) + week (2 digits) + a sequence + a letter factory code for 2010 and later, marked as partly inferred.
- Carrier: first two digits week, next two year (forum source, plausible; Carrier's own page found only the 2012 cutoff note). Keep.
- Lennox and York: no manufacturer page found by search or by fetching the Lennox support FAQs (they list where the plate is, not the date format). Third-party decoders disagreed. Zac supplied a documented answer later the same day: see "Fourth research pass".

Models and sizes (manufacturer pages)
- Watts 007 double check valve: `007M1-QT` size 1 inch exists (discontinued, replaced by `007M1-QT-FZ`), with sizes 1/2 to 2 inch. Use `007M1-QT-FZ` as the current model.
- Zurn Wilkins `975XL2` reduced pressure principle assembly, 3/4 to 2 inch, listed as a best seller.
- Sloan `Royal 111` exposed flushometer, with the 1.28 gpf version (`111-1.28`).
- Generac Protector standby generators: `RG02224ANAX` (22 kW), `XG04845ANAC` (48 kW), `RD04833ADAL` (48 kW diesel), plus a 100 kW Protector spec sheet (distributor and Generac listings).
- Trane Precedent: model digits 1 to 3 give unit type, efficiency and airflow, digits 4 to 6 the nominal capacity (036, 048, 060 for 3, 4, 5 tons); `YHC` is DX cooling with gas heat (Trane catalog and the older Precedent guide). Capacity codes through `YHC120` (10 tons) stay from knowledge.
- Lennox TGA090H2B and Lennox rooftop identifier sheets remain the sourced Lennox models.

Not fetchable: PDF manuals (Scrapling returned empty text for PDFs: the Trane IOM, the Lennox identifier sheet), the Rheem equipment-age calculator (script page) and Lennox or York date formats.

## Fourth research pass: Lennox and York, supplied by Zac (2026-11-02)

Source: a research write-up Zac pasted in chat. It cites Lennox bulletins 210764 and 210555, the Lennox model and serial nomenclature guide, JCI warranty manual 036-63001-003 and York technical guides 5167795-YTG-O-0120 and 5168277-YTG-I-0118. I have not fetched those documents (they are PDFs or script pages), so the facts below are documented by that write-up, not checked by me. Neither brand's format has been checked against a real nameplate with a known manufacture date.

Lennox serial: `PPYYMSSSSS`, ten characters. Characters 1 to 2 plant code, 3 to 4 year, 5 month letter, then a production sequence. Example `5614A01234` is plant 56, January 2014. Month letters A to M skipping I: A=Jan, B=Feb, C=Mar, D=Apr, E=May, F=Jun, G=Jul, H=Aug, J=Sep, K=Oct, L=Nov, M=Dec. The write-up says the week-based reading seen elsewhere is confusion with other brands. Plant codes are historical, not universal.

Lennox models (the write-up says to decode only the full string):
- Energence LGH, 3 to 6 ton, ultra high efficiency: `LGH060U4ES1Y`. L Energence, G gas heat with electric cooling, H generation, 060 nominal capacity (5 ton), U ultra high efficiency, 4 R-410A, E direct-drive ECM blower, S standard single-stage gas heat, 1 revision, Y 208/230 V three-phase. Sizes 036, 048, 060, 074 are 3, 4, 5, 6 ton.
- Energence LGH, 7.5 to 12.5 ton: `LGH120H4BS1Y`. H high efficiency, B belt-drive constant-air-volume blower, S standard two-stage gas heat. Sizes 092, 102, 120, 150 are 7.5, 8.5, 10, 12.5 ton.
- `LGH036H4B` and `LGH092H4B` are incomplete prefixes. Do not seed them.
- Older T-class: `TGA036S2B`. T, G gas heat, A generation, 036 (3 ton), S standard efficiency, 2 R-22, B belt-drive. R-22 means installs before 2010 only.

York serial after 6 October 2004: `P Y M Y SSSSSS`, ten characters. Position 1 plant, 2 first year digit, 3 month letter, 4 second year digit, 5 to 10 a six-digit sequence. Example `N0L4123456` is Norman, October 2004. Month letters skip I and J: A=Jan, B=Feb, C=Mar, D=Apr, E=May, F=Jun, G=Jul, H=Aug, K=Sep, L=Oct, M=Nov, N=Dec. Active plants named: N Norman OK, W Wichita KS, A Apodaca Mexico, S "Source 1". Historical: E Elyria OH, Y York PA, X Monterrey Mexico. The write-up found no later universal serial change after the 2005 JCI acquisition.

York models: Predator R-410A, 3 to 12.5 ton. Shape `ZJ090N18B2A1AAA1A2` is approximate in the write-up. Field 1 `Z` packaged R-410A, field 2 `F`/`H`/`J`/`R` family, fields 3 to 5 nominal capacity (037=3, 049=4, 061=5, 078=6.5, 090=7.5, 102=8.5, 120=10, 150=12.5 ton), the rest heat, blower, voltage (2 is 208/230 V, 4 is 460 V, 5 is 575 V) and options. The nomenclature changed by product generation; the 15 to 25 ton Sunline changed on 1 February 2016. Our earlier examples fail: `ZF036N10A` is not a standard Predator model (ZF starts at 078), `ZJ060` should be `ZJ061`, and `YC036` is a different family with no source.

Checks I ran afterward (2026-11-02): Lennox bulletin 210764 (fetched, text extracted with `pdftotext`) confirms the `LGH060U4ES1Y` key: L Energence, G packaged gas heat with electric cooling, H first generation, 060 = 5 ton (036, 048, 060, 074 = 3, 4, 5, 6 ton), U ultra high efficiency, 4 R-410A, E direct-drive ECM, S standard 1-stage gas heat, 1 first revision, Y 208/230 V 3 phase (G is 460 V). The Lennox legacy nomenclature PDF has an empty "Serial Numbering System" section, so the Lennox serial format is still the write-up only. The JCI warranty manual (doczz.net) returned 403, then 429, so the York serial and model facts are still the write-up only. Brand ids were read on Production and match SB2 (40,148 brands there, 40,141 on SB2).

Open after this pass: the York full model string is only approximate, so York models in the catalog are marked unverified; `YC` is unsourced and not used; neither serial format is checked against a real nameplate.

## Open questions for an SB2 spike

1. Brands: where do `BrandId` values come from? `POST /assets` needs a brand (400 error 503 "Brand (Manufacturer) is empty"). Probes of `/brands`, `/assetbrands` and `/assets/brands` were not completed (SB2 down).
2. (Mostly answered, see write probes.) Still open: custom attributes, and warranty category and expiration.
3. Condition scale: values and strings.
4. (Answered: `PUT /assets` with Id and core fields; see write probes.) Confirm that an update never wipes fields it omits (not tested: omitted fields kept their values in these probes).
5. Is there a bulk create or import call, or only one `POST` per asset? At the 15 calls a minute limit, 50 assets at 10 locations is about 35 minutes, which is acceptable for a one-time load.
6. Asset types available per trade on SB2 and Production (`GET /assettypes`, 50-plus on SB2, with `PrimaryTrade`), and whether the agent may create new asset types or must reuse existing ones. Prefer reuse.
7. Delete or deactivate: how to remove a seeded asset (`Active: false`)?
8. Where does the Production list of types differ (Electrical, Janitorial, Plumbing)? Read-only calls only, and only with Zac's go-ahead.
9. B-24: the request schema for `PUT /assets/workorders/attachassets` (see `api-notes.md`).

## Proposed shape of the feature

- `agent assets plan --location HQ-NYC`: dry run. Shows what would be created per trade (type, tag, make, model, install date, condition, warranty, value) and what already exists. Writes nothing.
- `agent assets seed --location HQ-NYC`: creates the planned assets, rate-limited, recording each in the DB. SB2 freely. Production only after Zac approves the plan for that location.
- `agent assets audit`: lists the location's assets per trade, flags gaps against the target counts and fields that are empty.
- `agent assets enrich`: proposes changes to existing assets (fill empty fields, make values plausible) as a before-and-after diff. Touches only assets the agent created, or assets Zac names in that run.
- A Locations-page action and an offer when a location is added, so a new location gets seeded on command.
- Catalog stored as data (a JSON or YAML file under the package), so adding a type or a make needs no code change.

## Sources

- Shared Second Brain wiki `asset-setup-and-tracking` and `asset-management` (fields, trade rules, warranty precedence, bulk import, Condition Analysis inputs).
- ServiceChannel Confluence help: "Asset Tagging in SC Mobile" (Tag ID, Location, Brand and Install Date required; Tag ID and Asset Tag should match).
- SB2 `GET /assets?locationId=` and `GET /assettypes` responses (2026-11-02), recorded in `docs/api-notes.md`.
- Web searches on equipment serial formats and useful life: weak sources, no authoritative tables. Not relied on for numbers.

# SC Activity Agent: enhancement backlog

Ordered list of enhancements after v1. The order is the priority: rank 1 is next. Anyone who changes this file keeps the order current.

## How to maintain this file
- Every item has an ID (`B-nn`, never reused), a size (S under 1 day, M 1-3 days, L 3-10 days, XL more), and a one-line reason.
- Rank by value to users first, then risk reduced, then size (small wins break ties). Re-rank whenever an item is added, finished or learned about.
- "Spike" means the API calls are not yet known. Run an SB2 spike and record it in `docs/api-notes.md` before building.
- Finished items move to **Done** with the release version. Dropped items move to **Dropped** with the reason.
- `sc-activity-agent-release` checks this file at every release.
- Source tags: **Zac** = idea from Zac, **Claude** = idea from Claude.

## Backlog (priority order)

| Rank | ID | Enhancement | Size | Why | Source |
|------|----|-------------|------|-----|--------|
| 1 | B-57 | Production rollout check for v0.10.0 to v0.11.x. Zac has switched on checklists and photos in Prod. Left: look at one Prod WO each for checklist answers, before photo and after photo in ServiceChannel, and the update page, Activity days, week switch and the in-app update banner for the latest tag. Also check the B-25 paths once a rating slider is above 0: one rated WO, one reworked WO, and the Unsatisfactory stage on the Dashboard. Checked 2026-11-03 (read-only): Prod is on v0.14.2 after one update press; checklist answers and photos confirmed in ServiceChannel on WO 368314564 (DOORS, ZW123); WO 368232717 (General Maintenance) has no checklist because ZW123 has none for that trade, so nothing was answered, as intended. Still open: a before or after photo from a creator-made WO (`photo_before` is 10% on Prod, none rolled yet), the B-25 paths, and a WO created with an asset (`asset_on_create` is 30% on Prod; none of the 4 creator-made WOs since 11-02 had a matching seeded asset type). Ask Zac before touching Prod | S | Four releases of new write paths have only run on SB2. Prod is where a mistake is visible to real users | Claude |
| 2 | B-69 | Create WOs from the selected dashboard without needing it active on the Subscriber user. SB2 spike 2026-11-03 (HQ-NYC, HVAC, test WO 368877480): `POST /workorders` resolves the issue on the token user's active dashboard; `IssueListHeaderId` does not override it (an item only on dashboard 3151 failed with 502 while dashboard 2751 was selected). The same body with `IssueRequestInfo`, `IssueListHeaderId` and `ProblemCode` left out creates an OPEN WO with the trade, category, priority, NTE and the contracted provider, but an empty `ProblemCode`. Build: send the issue-list fields only when the user's dashboard serves the item, otherwise create without them (the issue text stays in Description), and show on the console which path ran. Decide first whether an empty `ProblemCode` is acceptable on Production WOs | M | Today a dashboard change needs a manual "active dashboard" step per user in ServiceChannel, and a mismatch leaves a VOID shell per failed create | Zac |
| 3 | B-82 | Open transactions outside the loop: web request threads and the Telegram poller can still leave a write transaction open (v0.17.3 settles only the loop pieces and the sweep). Find a hook for FastAPI's worker threads; wait for the collaborator's lock log first | S | A leaked transaction blocks every other writer for up to 30 s | Claude |
| 4 | B-83 | Issue lists with no CategoryId: v0.17.2 skips such problems. Look the id up from the category name (or the dashboard's category list) once the collaborator's problem list shows what is missing. Also confirm on SB2 whether a create without CategoryId is accepted (SB2 issuechoice returned 500 on 2026-11-04) | S | Skipping silently shrinks the issue rotation | Claude |
| 5 | B-15 | Provider-side PM WOs: find PM WOs and move them through the process. Subscribers cannot create PMs through the API, so the agent only picks up existing ones | L, spike | PM is a large share of real volume | Zac |
| 6 | B-26 | PM compliance flows: pass and fail documentation, and the related follow-up | L, spike | Builds on B-15 | Zac |
| 7 | B-27 | Linked WOs (parent and child) | M, spike | Common for multi-visit and multi-trade jobs | Zac |
| 8 | B-28 | Recall WOs | M, spike | Rework against a closed WO. Pairs with B-25 | Zac |
| 9 | B-65 | Rework variety: a second rework round, and the provider sending a proposal on the return visit. Today one round at most, and the return is always check-in then check-out | S | Real rework is not always one clean extra visit. Pairs with B-28 (recall WOs) | Claude |
| 10 | B-05 | Per-location behavior overrides | M | Locations should differ in volume and trade mix | Claude |
| 11 | B-07 | Seasonal and holiday weighting (HVAC in summer, quiet holidays) | M | Flat weekday activity is an easy tell | Claude |
| 12 | B-80 | Asset condition after repair: when a WO with an attached asset closes, the provider updates the asset (condition up, last service date) on a share of WOs, and an old repeat-repair asset gets a replacement. Spike which fields a Provider may change | M, spike | Asset history that never changes after a repair looks seeded; pairs with B-13 | Claude
| 13 | B-77 | Split `web/app.py` (622 lines: routes, SLIDERS, page context, helpers) into route modules by page, after B-62. Behavior unchanged | M | Every console change touches this one file | Claude
| 14 | B-29 | Avoided WOs: Guided Troubleshooting resolves the issue, and duplicate WOs are detected and avoided | L, spike | Tests the "WO never gets created" paths | Zac |
| 15 | B-30 | Site audits that result in WOs created | L, spike | A second source of WOs besides the issue list | Zac |
| 16 | B-31 | Snow and landscaping WOs done by providers with CIWO | L, spike | CIWO has its own check-in model | Zac |
| 17 | B-32 | Quarterly RFP: a Subscriber runs an RFP with several bidding providers, then issues WOs to the winners | XL, spike | Needs several provider connections and contract changes | Zac |
| 18 | B-33 | FTM techs and FTM WOs through the process | L, spike | Needs the FTM product model first | Zac |
| 19 | B-04 | Deep link from the console to the WO in the ServiceChannel Subscriber view, in place of a WO detail page | S, spike | Finds the WO URL pattern. Keeps the console small | Zac |
| 20 | B-09 | Scenario presets (quiet week, busy week, storm surge) | S | One click to change load | Claude |
| 21 | B-16 | Clock speed-up mode for demos on SB2 | M | A full lifecycle in minutes | Claude |
| 22 | B-13 | Repeat issues on the same asset | M | Needs B-23. Feeds repeat-repair reports | Claude |
| 23 | B-81 | Photo library size: about 19 MB of JPEG in the repo, a third of it `_both` composites that are just before and after side by side. Option: build the composite at runtime (needs Pillow, a new dependency) or keep the files and re-save at a lower size. Decide before the library grows further | S | Every clone and update downloads the whole library | Claude
| 24 | B-68 | Warranty workflow for assets. Seeded assets carry no active warranty (B-67 sets none). This item covers warranty data on assets (priority, category, expiration, provider; the API shape is only partly known, see `docs/asset-seeding-research.md`), and WOs that route or behave differently while a warranty runs (warranty provider overrides trade dispatch) | L, spike | Out of scope of B-67 by decision (2026-11-02) | Zac |
| 25 | B-22 | Complete checklists on WOs. Built (v0.10.0, Settings toggle) and verified on SB2. Now sends the answering user's `AuthUserID` (read from the profile) and traces required questions it cannot answer. Verified on SB2 (2026-11-01): the profile gives `AuthUserId` and the answers are recorded. Required question left open on SB2 (2026-11-01): check-out still succeeds, nothing recorded. Left: per-asset questions (needs B-23/B-24) | S | Required questions block submitting the checklist (engineering), so unanswerable ones are the open gap | Zac |
| 26 | B-34 | RT workflows | XL, spike | Very hard. Last on purpose | Zac |

## Ideas waiting for a spec
None yet. Zac's new ideas go here first, then get sized and ranked.

## Done
| ID | Item | Version |
|----|------|---------|
| B-84 | Smoke run no longer stores a setting as null: a key that did not exist is deleted after the run (`Store.drop`) | 0.17.4 |
| B-62 | Split `handlers.py` into the `handlers/` package by area (runtime, common, guard, notes, field, checklists, review, invoices, proposals). Behavior unchanged | 0.17.4 |
| B-78 | Scheduled SB2 smoke run (`smoke.py`): an SB2 instance runs a full WO with photos, checklists and rework every 7 days and sends the result as an alert; Settings toggle and Run now. Needs Telegram set up on the SB2 instance to arrive | 0.17.0 |
| B-74 | Sleep-gap shifting (`Engine.snap`, `apply_gap`) and the rework return read activity hours in the location's time zone; plans, the Creator and clean-up already did | 0.16.0 |
| B-79 | Errors page groups failed steps by kind and error (digits blurred) with count, first and last time, WO list, hints for 1104 and 403/100, and Retry all / Skip all | 0.16.0 |
| B-76 | Dropped the unused `roles` table (migration 4, database version 4); migration 1 now creates it itself | 0.16.0 |
| B-71 | Daily limits on WOs created (40) and API calls (3000): reaching one pauses the agent and sends an alert; set on Behavior, 0 = off | 0.15.0 |
| B-72 | `agent get` shows `***` for tokens, secrets, passwords and encrypted values | 0.15.0 |
| B-73 | CI and release workflows use `actions/checkout@v6` and `actions/setup-python@v6` (Node 24) | 0.15.0 |
| B-75 | Photo rotation: a new pick avoids the sets of the last 10 WOs at the same location (usage counts on the console not built) | 0.15.0 |
| B-14 | Photos match the trade and issue (`BY_ISSUE`), 64 sets. Closed 2026-11-03 by Zac: the 40 older sets still show cables in the background; replace them only if someone complains | 0.14.3 |
| B-63 | Dropped the unused `contracts` table by migration (database version 3) and fixed stale lines in the docs | 0.14.3 |
| B-67 | Asset seeding finished: `audit` and `enrich` read the asset list once, and a Dashboard and Locations banner shows where a Rank 1 trade has no seeded assets, with Dismiss (earlier work in 0.13.0) | 0.14.3 |
| B-64 | Dashboard stage tiles open a list of the WOs in that stage | 0.14.2 |
| B-70 | Dashboard mismatch warning (selected dashboard vs the Subscriber user's active one) and the setup note | 0.14.2 |
| B-23 | WOs can be created with a seeded asset attached (Behavior slider, default 0) | 0.14.0 |
| B-24 | Providers attach a seeded asset at first check-in (Behavior slider, default 0) | 0.14.0 |
| B-54 | Cleanup sweep follows Activity days (it skipped weekends whatever days were picked) | 0.11.3 |
| B-55 | `scripts/bump_version.py` sets all version files together; the sync test now also checks `Cargo.lock` and `package-lock.json` | 0.11.3 |
| B-56 | `scripts/live_sb2.py`: one full work order run on SB2 as a release check (refuses Production) | 0.11.3 |
| B-59 | Dashboard remembers Hide done and Hide skipped (`dashboard_hide`) | 0.11.3 |
| B-66 | Blocked steps no longer starve the tick: `Engine.due` leaves out steps behind a failed or not-yet-due earlier step of the same WO, so stuck plans cannot fill the per-tick window. Steps that are all due still run in order in one tick, so catch-up after sleep is unchanged | 0.12.2 |
| B-60 | A rated review reads the live WO first: already CONFIRMED = done, any status other than COMPLETED parks the step on the Errors page (feedback is refused outside COMPLETED / PENDING CONFIRMATION). Also fixed: the engine now re-reads a step's row before running it, so steps a handler inserts mid-tick (rework, invoice resubmit) run before the steps that followed | 0.12.2 |
| B-61 | `scripts/live_sb2.py --rework`: rates every review and makes the first one unsatisfactory, through the return visit to a second rated review and on to payment. PASS on SB2 | 0.12.2 |
| B-25 | Star ratings and rework: Behavior sliders `star_rating` and `rework` (default 0). A rated review posts feedback; 1 or 2 stars sets the WO to Unsatisfactory, the provider returns onsite, and the Subscriber reviews again (one round at most). Verified on SB2 | 0.12.0 |
| B-58 | Retired the desktop app (Tauri shell, packaging, installers, welcome page, desktop CI and the Python code only it used). The source install is the supported path; rebuild later if there is a reason to pivot (git history keeps it, last shipped in 0.11.3) | 0.12.0 |
| B-52 | Before photos attached when a WO is created, picked by trade from the photo library, as the Behavior slider `photo_before` (default 0). Verified on SB2. Prod check is in B-57 | 0.11.0, slider in 0.11.1 |
| B-53 | After photos on the provider's closing note, from the same set as the before photo, as the Behavior slider `photo_after` (default 0). Verified on SB2. Prod check is in B-57 | 0.11.0, slider in 0.11.1 |
| B-51 | Pick up WOs people create by hand at our locations and give them a plan (hourly, Settings toggle, on by default). Guards: held by our provider, trade where Rank 1 is ours, created in the last 7 days, no protect label; foreign-provider WOs ignored. Ran on SB2 (planned 10 WOs, accept for OPEN ones). Not run on Prod; the IN PROGRESS path was only unit-tested | 0.9.0 |
| B-12 | Invoice variety and validation: line-item invoices (labor at time on site and agreed rate, materials), rate-mismatch and extra-hours flaws, Subscriber rejects on API flags or hours, Provider resubmits. Over-NTE (error 1104), partial and credit memo on one WO (error 1105) dropped: the API refuses them. Not tried: negative lines in one invoice, a separate spike if wanted | 0.8.0 |
| B-39 | Pick up manual changes: proposal and invoice decisions, user-cancelled or completed WO, user check-in, a live-WO read before every write, a rescheduled WO (visit and later steps shift), NTE and priority edits read into the plan, and an unrecognized status or provider parks the plan on the Errors page. Not tried live: changing NTE or priority in ServiceChannel (only the read is confirmed) | 0.7.0, 0.7.1 |
| B-08 | Emergency timing: read WO priority and ETA. Any WO with an ETA under 8 hours gets more activity, including back-and-forth notes that confirm provider availability before the visit (Done on branch v0.7: ETA-driven emergency plans for created and finishing-cleanup WOs) | 0.7.0 |
| B-11 | Provider declines (low rate) and reschedules (higher rate). A reschedule is the Provider moving the scheduled date later than the original date set by the issue list (Done on branch v0.7: sliders default 0; spike in api-notes) | 0.7.0 |
| B-20 | Reassign WOs between providers, for example after a decline or a no-show (Built on branch v0.7 for the decline path: slider default 0; spike in api-notes. Live-tested on SB2: decline path, no-show path (setting Provider no-shows %), and the API accepts a reassign after check-in. Not built: a plan setting that reassigns mid-job on purpose) | 0.7.0 |
| B-48 | Spike: two-tech visits on Prod. A second check-in on an occupied WO works; the first tech out must use PartsOnOrder so the WO stays open for the second (fixed in 0.6.1) | 0.6.1 |
| B-47 | Capabilities on users replace the Roles page: Can do checkboxes on Connections, random pick among users of the WO's provider, same tech checks in and out of a visit, optional two-tech visits (Behavior slider, default 5%). Second-tech check-in on an occupied WO is not yet verified on SB2 (see B-48) | 0.6.0 |
| B-03 | Database backups: Back up now, last 10 kept, backup before each clean-up run, CLI restore. Machine move = copy the data folder (no separate settings export) | 0.6.0 |
| B-21 | Mark approved invoices as PAID (`POST /invoices/{id}/Payment`, verified on SB2) | 0.6.0 |
| B-40, B-41 | Idle-WO clean-up: preview and cancel, Clean up now, daily sweep (cancel or finish), protect label | 0.5.0 |
| B-46 | Add several locations at once (checkboxes plus pasted store IDs or CSV) | unreleased (0.4.2) |
| B-02 | Contract resync and skipped-trades report (daily refresh already existed; added Refresh now and the Skipped trades table) | unreleased (0.4.2) |
| B-42a, B-42b | Telegram alerts and action buttons (in-app setup guide, one bot per instance) | unreleased (0.4.0) |
| B-45 | One app for Production and SB2 (SB2 copy on demand inside the app's data folder, tray switch, update and quit cover both) | unreleased (0.4.0) |
| B-44 | Desktop app (Tauri shell + frozen Python agent, welcome page, tray, in-app updates) | 0.3.0, updated through 0.3.5 |
| B-35 | Fix failing creates: pre-check the location dashboard lookup | unreleased (0.1.0) |
| B-38 | Proposal create, link and approve; invoice reject | unreleased (0.1.0) |
| B-43 | Location picker from the Subscriber's locations | 0.2.0 |
| B-36 | Setup page card for the Subscriber/Provider check-in permission: per-Provider status and a ready-to-send support request | 0.3.4 |
| B-37 | Provider resubmits a corrected invoice after a reject, with its own invoice number (the reject and resubmit path has not run live on SB2 yet: no WO has rolled it) | 0.3.4 |

## Dropped
| ID | Item | Reason |
|----|------|--------|
| B-49, B-50 | Mac killing the ad-hoc signed desktop app, and Developer ID signing and notarization | Desktop app retired (B-58); the source install is not affected |
| B-06 | Realism report | Zac: not wanted |
| B-01 | Locations lookup by store ID, plus CSV bulk add | Lookup is covered by the loaded locations list with search (v0.2.x); the bulk part became B-46 |
| B-10 | Daily digest to Slack or email | Zac: not wanted |
| B-17 | Schedule heatmap on Day plan | Zac: not wanted |
| B-18 | Native app wrapper | Zac: not wanted. Reversed 2026-10-26, now B-44 |
| B-19 | Bulk auto-cleanup of leftover WOs | Replaced by B-41 (one-time clean-up) and B-40 (abandoned sweep) |

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
| 1 | B-101 | Network-fault circuit breaker: when several calls in a row fail with SSL EOF, handshake or read timeouts, stop running steps (a soft pause), probe `login` every minute, and resume on success. Network errors must not use up a step's 3 attempts. Queue Telegram alerts that could not be sent and resend them on recovery. Today an outage of a few minutes fails steps for good: 8 Prod steps on 2026-11-10 needed a manual retry, and the same evening Telegram could not be reached either | M | The agent runs on a laptop behind Zscaler, so short outages are normal. Without this, each one ends in failed steps, a blocked WO and manual retries | Claude |
| 2 | B-105 | Verify the Seed button with a real seed: 0.20.13 shipped after a read-only SB2 wiring check only. Run it on a new or emptied SB2 location, check the assets in ServiceChannel, the progress and error banners and Retry, then note the result in `docs/api-notes.md`. Do the Prod run on the next new location | S | A write path to Production shipped with no live run | Claude |
| 3 | B-109 | Make blocked WOs visible: a failed step stops every later step of that WO (`Engine.tick` skips them), so a WO can sit with due steps and no sign on the Dashboard. Show "N steps waiting" on the failed step's Errors row and on the WO, and add the count to `doctor.py` (`overdue_pending` did not show it on 2026-11-12) | S | One failed check-in held 12 steps of WO 369403628 without any other signal | Claude |
| 4 | B-57 | Production rollout check for v0.10.0 to v0.11.x. Zac has switched on checklists and photos in Prod. Left: look at one Prod WO each for checklist answers, before photo and after photo in ServiceChannel, and the update page, Activity days, week switch and the in-app update banner for the latest tag. Also check the B-25 paths once a rating slider is above 0: one rated WO, one reworked WO, and the Unsatisfactory stage on the Dashboard. Checked 2026-11-03 (read-only): Prod is on v0.14.2 after one update press; checklist answers and photos confirmed in ServiceChannel on WO 368314564 (DOORS, ZW123); WO 368232717 (General Maintenance) has no checklist because ZW123 has none for that trade, so nothing was answered, as intended. Still open: a before or after photo from a creator-made WO (`photo_before` is 10% on Prod, none rolled yet), the B-25 paths, and a WO created with an asset (`asset_on_create` is 30% on Prod; none of the 4 creator-made WOs since 11-02 had a matching seeded asset type). Update 2026-11-12: the B-25 rated and Unsatisfactory paths have now run on Prod (two WOs moved to Unsatisfactory on 2026-11-11, seen by Zac), so that part is covered; the new wording is in 0.20.14. Ask Zac before touching Prod | S | Four releases of new write paths have only run on SB2. Prod is where a mistake is visible to real users | Claude |
| 5 | B-88 | Database lock root cause: still unknown (v0.17.3 diagnostics, v0.17.5 settle fixes). Grep Prod and SB2 `agent.log` for `left a database transaction open` and `database is locked. Threads with a transaction open` after 2 weeks of running 0.17.5+. Which path leaked decides the fix (e.g. one writer thread). Close it if the log stays clean | S | The one stability issue with no explained cause | Claude |
| 6 | B-83 | Issue lists with no CategoryId: v0.17.2 skips such problems. Look the id up from the category name (or the dashboard's category list) once the collaborator's problem list shows what is missing. Also confirm on SB2 whether a create without CategoryId is accepted (SB2 issuechoice returned 500 on 2026-11-04) | S | Skipping silently shrinks the issue rotation | Claude |
| 7 | B-94 | Answer the refrigerant prompt through the API so refrigerant assets (RTU) can be attached again: a check-out on a refrigerant asset leaves the WO at COMPLETED / PENDING REFRIGERANT USE (review 940, invoice 904). ON HOLD until Zac gets setup help from Jim Smith. SB2 spike 2026-11-06: `RefrigerantWasUsed` on `universalCheckOut` is accepted and ignored. A refrigerant asset also needs its charge set (the leak and usage flow measures against it) and the API shows no charge field on the asset (`GET /assets/{id}`), so the working flow is not known. Next: capture the real calls (HAR) while the flow is done once in Provider Automation | S, on hold | Seen on Prod 2026-11-06 (WO 369197573); until then 0.20.3 skips refrigerant assets | Claude |
| 8 | B-106 | Manual-action audit: for each step kind, list what a person doing the same thing in ServiceChannel would make fail (approve or pay the invoice, complete or cancel the WO, change the provider, add a note, close a checklist) and add a test per case. B-97 (1105) and B-100 (second tech) were two cases found only in Prod; `guarded()` today only handles a cancelled WO, a completed WO for field steps and a check-in when the tech is already on site | M | Prod is used by people at the same time as the agent. Each surprise so far has been a case nobody listed | Claude |
| 9 | B-108 | Release prep script in the repo (`scripts/release_prep.py`): rename Unreleased in CHANGELOG, bump the version, run the tests and print the doctor gate. The doctor digest stamp stays manual because the digest lives in the skill. On 2026-11-07 the digest was 8 versions behind because a release skipped that step | S | The release checklist has 9 manual steps and every skipped one has cost a later cleanup | Claude |
| 10 | B-95 | DONE in 0.20.9 (flag + forced before photo + 10 Kitchen/Freight photo sets); left: confirm the flag on Prod. Meet error 916 on create ("At least one attachment required") by sending the before photo in the `CreateWoRequest.Attachments` field. Spike on SB2 first (does the field work, does the account setting exist on SB2), then a retry-free change in `Creator.create`: attach at create when the location has answered 916 before. A rejected create leaves a VOID shell, so never retry blindly | S | Prod ZW123 rejected 3 creates on 2026-11-07; 0.20.8 only adds the hint | Claude |
| 11 | B-96 | Jitter in `Engine.snap` (sleep-gap shift, rework return): it still snaps to the exact window start, so after a gap many steps land on 08:00:00. Keep check-out after check-in and the same-day rule | S | Found with the 0.20.8 `_fit` jitter | Claude |
| 12 | B-77 | Split `web/app.py` (751 lines: routes, SLIDERS, page context, helpers) into route modules by page, after B-62. Behavior unchanged | M | Every console change touches this one file | Claude |
| 13 | B-110 | WO-specific wording beyond ratings (follow-up to B-99): provider and subscriber notes, proposal and invoice text, and the invoice reject reason name the WO's equipment, area and visit day, with a catalog per trade and a generic fallback. Test that two WOs of the same trade do not get identical text | M | Zac asked for unique, WO-related text after two WOs went Unsatisfactory; ratings are done, other texts still repeat | Zac |
| 14 | B-15 | Provider-side PM WOs: find PM WOs and move them through the process. Subscribers cannot create PMs through the API, so the agent only picks up existing ones | L, spike | PM is a large share of real volume | Zac |
| 15 | B-26 | PM compliance flows: pass and fail documentation, and the related follow-up | L, spike | Builds on B-15 | Zac |
| 16 | B-27 | Linked WOs (parent and child) | M, spike | Common for multi-visit and multi-trade jobs | Zac |
| 17 | B-28 | Recall WOs | M, spike | Rework against a closed WO. Pairs with B-25 | Zac |
| 18 | B-65 | Rework variety: a second rework round, and the provider sending a proposal on the return visit. Today one round at most, and the return is always check-in then check-out | S | Real rework is not always one clean extra visit. Pairs with B-28 (recall WOs) | Claude |
| 19 | B-05 | Per-location behavior overrides | M | Locations should differ in volume and trade mix | Claude |
| 20 | B-07 | Seasonal and holiday weighting (HVAC in summer, quiet holidays) | M | Flat weekday activity is an easy tell | Claude |
| 21 | B-80 | Asset condition after repair: when a WO with an attached asset closes, the provider updates the asset (condition up, last service date) on a share of WOs, and an old repeat-repair asset gets a replacement. Spike which fields a Provider may change | M, spike | Asset history that never changes after a repair looks seeded; pairs with B-13 | Claude |
| 22 | B-29 | Avoided WOs: Guided Troubleshooting resolves the issue, and duplicate WOs are detected and avoided | L, spike | Tests the "WO never gets created" paths | Zac |
| 23 | B-30 | Site audits that result in WOs created | L, spike | A second source of WOs besides the issue list | Zac |
| 24 | B-31 | Snow and landscaping WOs done by providers with CIWO | L, spike | CIWO has its own check-in model | Zac |
| 25 | B-32 | Quarterly RFP: a Subscriber runs an RFP with several bidding providers, then issues WOs to the winners | XL, spike | Needs several provider connections and contract changes | Zac |
| 26 | B-33 | FTM techs and FTM WOs through the process | L, spike | Needs the FTM product model first | Zac |
| 27 | B-04 | Deep link from the console to the WO in the ServiceChannel Subscriber view, in place of a WO detail page | S, spike | Finds the WO URL pattern. Keeps the console small | Zac |
| 28 | B-09 | Scenario presets (quiet week, busy week, storm surge) | S | One click to change load | Claude |
| 29 | B-16 | Clock speed-up mode for demos on SB2 | M | A full lifecycle in minutes | Claude |
| 30 | B-13 | Repeat issues on the same asset | M | Needs B-23. Feeds repeat-repair reports | Claude |
| 31 | B-81 | Photo library size: about 19 MB of JPEG in the repo, a third of it `_both` composites that are just before and after side by side. Option: build the composite at runtime (needs Pillow, a new dependency) or keep the files and re-save at a lower size. Decide before the library grows further | S | Every clone and update downloads the whole library | Claude |
| 32 | B-68 | Warranty workflow for assets. Seeded assets carry no active warranty (B-67 sets none). This item covers warranty data on assets (priority, category, expiration, provider; the API shape is only partly known, see `docs/asset-seeding-research.md`), and WOs that route or behave differently while a warranty runs (warranty provider overrides trade dispatch) | L, spike | Out of scope of B-67 by decision (2026-11-02) | Zac |
| 33 | B-22 | Complete checklists on WOs. Built (v0.10.0, Settings toggle) and verified on SB2. Now sends the answering user's `AuthUserID` (read from the profile) and traces required questions it cannot answer. Verified on SB2 (2026-11-01): the profile gives `AuthUserId` and the answers are recorded. Required question left open on SB2 (2026-11-01): check-out still succeeds, nothing recorded. Left: per-asset questions (needs B-23/B-24) | S | Required questions block submitting the checklist (engineering), so unanswerable ones are the open gap | Zac |
| 34 | B-34 | RT workflows | XL, spike | Very hard. Last on purpose | Zac |

## Ideas waiting for a spec
Zac's new ideas go here first, then get sized and ranked.

- Console filters in a side drawer (2026-11-12): the Dashboard, Audit and Locations filters take a lot of room. Three mockups (slide-over, docked panel, slide-over with quick views) were built in `ZacAI/working/filter-mockups/` but not reviewed, and Zac set the idea aside. Pick this up if the console gets crowded again.

## Done
| ID | Item | Version |
|----|------|---------|
| B-107 | CI macOS 3.11 flake: root cause was a test, not the runner. Adding a Subscriber user in the web tests made a real dashboard call to SB2 that stalled 60 s+ on slow networks (127 s on Python 3.11 locally, hung on the macOS runner). The test fixture now stubs the transport: 5 s | 0.20.16 |
| B-102 | Refrigerant stopgap: a WO at COMPLETED / PENDING REFRIGERANT USE now fails the step at once with one clear message (record usage or cancel in ServiceChannel, then Close out) instead of running later steps into 921/904. Spike: the six hold WOs carry no asset id in the agent (`equipment` is the generic label, `asset_tried` set), so the RTU did not come from an agent-attached asset; where it came from on the ServiceChannel side is still unknown | 0.20.16 |
| B-103 | Close out WO button on the Errors page: skips the WO's open steps and marks it cancelled in the agent, with a confirm dialog; writes nothing to ServiceChannel | 0.20.16 |
| B-104 | Engine error hygiene: `Skip` is handled once in `Engine.tick`; a step error is never blank (exception class shown); the alert uses the same text | 0.20.16 |
| B-100 | A second-tech check-in/out with no second tech available failed with a blank error: `guarded()` now treats the user pick's Skip as done, because the live-WO read raises it before `checkio` can catch it | 0.20.15 |
| B-99 | Star-rating and rework messages name the work order: low-rating comment, provider return note and second review use the WO's trade, equipment, store, area and last-visit day; generic issue labels are not quoted | 0.20.14 |
| B-98 | Seed assets from the console: a Seed button per location on the unseeded-assets banner approves the location and seeds in the background, with progress and Retry | 0.20.13 |
| B-97 | A person approves an invoice before the agent's reject: `invoice_decide` skips the planned resubmit steps, and a resubmit refused with 1105 ends as done, not failed | 0.20.12 |
| B-90 | Recorded-response tests: `scripts/record_fixtures.py` saves one real response per endpoint the agent reads (personal data removed) into `tests/fixtures/`; `tests/test_recorded.py` runs the parsers against them in CI | 0.20.5 |
| B-89 | Factory reset and restore wait for the step in progress (`reset.quiesced`); Restore button in Settings > Backups (`restore_live`); backups in the same second no longer overwrite each other | 0.20.0 |
| B-87 | Check setup button on Setup: live sign-in, dashboard and Rank 1 tests with a fix next to each problem | 0.19.0 |
| B-86 | Alert after 3 failed creates in a row (`create_failed` event) | 0.19.0 |
| B-85 | Setup audit: guided checklist with help per step (Provider ID, enabled location, Rank 1), actionable error hints, validated connection flows; Factory reset in Settings with backup, typed confirmation and warnings | 0.18.0 |
| B-82 | Open transactions outside the loop are committed: the Telegram poller after each pass, clean-up threads when they end, and web request threads by a middleware once no request is in flight. Each logs which one leaked | 0.17.5 |
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
| B-91 | Dashboard dropdown removed: the Subscriber user's own dashboard is read from the profile and shown on Connections; B-70 banner and sample check removed | 0.20.0 |
| B-93 | Per-user Check dashboard button on Connections; a Subscriber user is checked on add; no dashboard means no Create WOs | 0.20.2 |
| B-92 | A create uses one Subscriber user from pool to POST; Connections and Check setup show every Subscriber user's dashboard | 0.20.1 |
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
| B-69 | Create WOs without the issue fields when the user's dashboard does not serve the item | Zac 2026-11-05: an empty ProblemCode is not acceptable on Production WOs. The mismatch is already handled without it: `Creator._resolves` asks issuechoice (which follows the user's active dashboard) before each create and redraws, and the B-70 banner shows when the selected and active dashboards differ. The remaining gap is B-91 |
| B-01 | Locations lookup by store ID, plus CSV bulk add | Lookup is covered by the loaded locations list with search (v0.2.x); the bulk part became B-46 |
| B-10 | Daily digest to Slack or email | Zac: not wanted |
| B-17 | Schedule heatmap on Day plan | Zac: not wanted |
| B-18 | Native app wrapper | Zac: not wanted. Reversed 2026-10-26, now B-44 |
| B-19 | Bulk auto-cleanup of leftover WOs | Replaced by B-41 (one-time clean-up) and B-40 (abandoned sweep) |

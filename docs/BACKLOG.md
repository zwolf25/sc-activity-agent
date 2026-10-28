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
| 1 | B-39 | [Target 0.7.0] (Done: proposal and invoice decisions, user-cancelled or completed WO, user check-in; live-tested on SB2 2026-10-26 for cancel and check-in. Still open: other user changes such as a rescheduled WO or edits to NTE or priority, and a periodic status read instead of reacting to failures) Pick up manual changes: before each step, read the live WO, proposal and invoice status. If the user already did the planned action (approved, checked in, completed), mark the step done and continue. If the user did something different (rejected a proposal, cancelled the WO, completed it early), re-plan from the new state instead of erroring: rejected proposal runs the revised-proposal branch, a cancelled WO ends its plan, anything unrecognized parks the plan and shows it on the Errors page. Spike result (2026-10-26): the API lets a planned approve overturn a user's rejection, and assignWO fails on an already approved proposal, so the status read must come first | L, spike | Real users click around demo data. Today a step that finds the object already changed fails or repeats | Zac |
| 2 | B-08 | [Target 0.7.0] Emergency timing: read WO priority and ETA. Any WO with an ETA under 8 hours gets more activity, including back-and-forth notes that confirm provider availability before the visit | M | Urgent WOs are where flat timing looks most fake | Zac |
| 3 | B-11 | [Target 0.7.0] Provider declines (low rate) and reschedules (higher rate) | L, spike | Real queues have refusals and date changes. Reschedules re-time the plan | Zac |
| 4 | B-20 | [Target 0.7.0] Reassign WOs between providers, for example after a decline or a no-show | L, spike | Completes the decline path. Adds no-show as an outcome | Zac |
| 5 | B-49 | Find why macOS kills the agent child about 2 s after the console opens when the app is launched from Finder or `open` (works from a terminal and from a launchd job; started 2026-10-28 08:52; ad-hoc signed app, security software on the machine). First read the new `[shell ...]` exit line in agent.log (signal 9 vs a code). If it is a system kill, try a LaunchAgent that runs `agent-core run` directly | M, spike | The app cannot be opened normally on Zac's machine | Zac |
| 5 | B-12 | Invoice variety and validation: time on site and labor rate flags, over-NTE, partial, credit memo. Subscriber approves or rejects based on the flags | L, spike | Exercises the invoice validation logic and rejection paths | Zac + Claude |
| 6 | B-22 | Complete checklists on WOs | M, spike | Checklists are part of real completion | Zac |
| 7 | B-23 | Create WOs with assets attached | M, spike | Asset-linked work is the normal case in many accounts | Zac |
| 8 | B-24 | Providers attach assets to WOs when onsite | M, spike | Pairs with B-23 | Zac |
| 9 | B-14 | Photos on WOs: relevant to the trade and issue only, with variety (several images per issue type) | M, spike | Real WOs carry photos. Needs a curated image set per issue type, with licensing checked | Zac |
| 10 | B-25 | Star ratings on WOs. A low rating moves the WO to Unsatisfactory and the provider returns onsite to finish | L, spike | Adds a rework loop | Zac |
| 11 | B-15 | Provider-side PM WOs: find PM WOs and move them through the process. Subscribers cannot create PMs through the API, so the agent only picks up existing ones | L, spike | PM is a large share of real volume | Zac |
| 12 | B-26 | PM compliance flows: pass and fail documentation, and the related follow-up | L, spike | Builds on B-15 | Zac |
| 13 | B-27 | Linked WOs (parent and child) | M, spike | Common for multi-visit and multi-trade jobs | Zac |
| 14 | B-28 | Recall WOs | M, spike | Rework against a closed WO. Pairs with B-25 | Zac |
| 15 | B-29 | Avoided WOs: Guided Troubleshooting resolves the issue, and duplicate WOs are detected and avoided | L, spike | Tests the "WO never gets created" paths | Zac |
| 16 | B-30 | Site audits that result in WOs created | L, spike | A second source of WOs besides the issue list | Zac |
| 17 | B-31 | Snow and landscaping WOs done by providers with CIWO | L, spike | CIWO has its own check-in model | Zac |
| 18 | B-32 | Quarterly RFP: a Subscriber runs an RFP with several bidding providers, then issues WOs to the winners | XL, spike | Needs several provider connections and contract changes | Zac |
| 19 | B-33 | FTM techs and FTM WOs through the process | L, spike | Needs the FTM product model first | Zac |
| 20 | B-05 | Per-location behavior overrides | M | Locations should differ in volume and trade mix | Claude |
| 21 | B-07 | Seasonal and holiday weighting (HVAC in summer, quiet holidays) | M | Flat weekday activity is an easy tell | Claude |
| 22 | B-04 | Deep link from the console to the WO in the ServiceChannel Subscriber view, in place of a WO detail page | S, spike | Finds the WO URL pattern. Keeps the console small | Zac |
| 23 | B-09 | Scenario presets (quiet week, busy week, storm surge) | S | One click to change load | Claude |
| 24 | B-16 | Clock speed-up mode for demos on SB2 | M | A full lifecycle in minutes | Claude |
| 25 | B-13 | Repeat issues on the same asset | M | Needs B-23. Feeds repeat-repair reports | Claude |
| 26 | B-34 | RT workflows | XL, spike | Very hard. Last on purpose | Zac |

## Ideas waiting for a spec
None yet. Zac's new ideas go here first, then get sized and ranked.

## Done
| ID | Item | Version |
|----|------|---------|
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
| B-06 | Realism report | Zac: not wanted |
| B-01 | Locations lookup by store ID, plus CSV bulk add | Lookup is covered by the loaded locations list with search (v0.2.x); the bulk part became B-46 |
| B-10 | Daily digest to Slack or email | Zac: not wanted |
| B-17 | Schedule heatmap on Day plan | Zac: not wanted |
| B-18 | Native app wrapper | Zac: not wanted. Reversed 2026-10-26, now B-44 |
| B-19 | Bulk auto-cleanup of leftover WOs | Replaced by B-41 (one-time clean-up) and B-40 (abandoned sweep) |

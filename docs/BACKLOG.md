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
| 1 | B-22 | Complete checklists on WOs | M, spike | Checklists are part of real completion | Zac |
| 2 | B-23 | Create WOs with assets attached | M, spike | Asset-linked work is the normal case in many accounts | Zac |
| 3 | B-24 | Providers attach assets to WOs when onsite | M, spike | Pairs with B-23 | Zac |
| 4 | B-14 | Photos on WOs: relevant to the trade and issue only, with variety (several images per issue type) | M, spike | Real WOs carry photos. Needs a curated image set per issue type, with licensing checked | Zac |
| 5 | B-25 | Star ratings on WOs. A low rating moves the WO to Unsatisfactory and the provider returns onsite to finish | L, spike | Adds a rework loop | Zac |
| 6 | B-15 | Provider-side PM WOs: find PM WOs and move them through the process. Subscribers cannot create PMs through the API, so the agent only picks up existing ones | L, spike | PM is a large share of real volume | Zac |
| 7 | B-26 | PM compliance flows: pass and fail documentation, and the related follow-up | L, spike | Builds on B-15 | Zac |
| 8 | B-27 | Linked WOs (parent and child) | M, spike | Common for multi-visit and multi-trade jobs | Zac |
| 9 | B-28 | Recall WOs | M, spike | Rework against a closed WO. Pairs with B-25 | Zac |
| 10 | B-29 | Avoided WOs: Guided Troubleshooting resolves the issue, and duplicate WOs are detected and avoided | L, spike | Tests the "WO never gets created" paths | Zac |
| 11 | B-30 | Site audits that result in WOs created | L, spike | A second source of WOs besides the issue list | Zac |
| 12 | B-31 | Snow and landscaping WOs done by providers with CIWO | L, spike | CIWO has its own check-in model | Zac |
| 13 | B-32 | Quarterly RFP: a Subscriber runs an RFP with several bidding providers, then issues WOs to the winners | XL, spike | Needs several provider connections and contract changes | Zac |
| 14 | B-33 | FTM techs and FTM WOs through the process | L, spike | Needs the FTM product model first | Zac |
| 15 | B-05 | Per-location behavior overrides | M | Locations should differ in volume and trade mix | Claude |
| 16 | B-07 | Seasonal and holiday weighting (HVAC in summer, quiet holidays) | M | Flat weekday activity is an easy tell | Claude |
| 17 | B-04 | Deep link from the console to the WO in the ServiceChannel Subscriber view, in place of a WO detail page | S, spike | Finds the WO URL pattern. Keeps the console small | Zac |
| 18 | B-09 | Scenario presets (quiet week, busy week, storm surge) | S | One click to change load | Claude |
| 19 | B-16 | Clock speed-up mode for demos on SB2 | M | A full lifecycle in minutes | Claude |
| 20 | B-13 | Repeat issues on the same asset | M | Needs B-23. Feeds repeat-repair reports | Claude |
| 21 | B-34 | RT workflows | XL, spike | Very hard. Last on purpose | Zac |

## On hold
Paused by Zac on 2026-10-29. Not ranked; return them to the backlog when he says so.
| ID | Item | Size | Why | Source |
|----|------|------|-----|--------|
| B-49 | Partly answered 2026-10-28: a Python source install survives the same launch paths (launchd, Finder-style open), so the Python install path (install.sh) is the workaround, and the cause is the ad-hoc signed bundle (B-50). Still ask IT whether Falcon/Rapid7 blocked it. Original question: find why macOS kills the agent child about 2 s after the console opens when the app is launched from Finder or `open` (works from a terminal and from a launchd job; started 2026-10-28 08:52; ad-hoc signed app, security software on the machine). First read the new `[shell ...]` exit line in agent.log (signal 9 vs a code). If it is a system kill, try a LaunchAgent that runs `agent-core run` directly | M, spike | The app cannot be opened normally on Zac's machine | Zac |
| B-50 | Apple Developer ID signing and notarization of the desktop app (US$99 a year) so it opens from Finder and Gatekeeper without a workaround; B-49 shows the ad-hoc signed app is killed on Zac's machine | M | Wider rollout of the desktop app | Zac |

## Ideas waiting for a spec
None yet. Zac's new ideas go here first, then get sized and ranked.

## Done
| ID | Item | Version |
|----|------|---------|
| B-51 | Pick up WOs people create by hand at our locations and give them a plan (hourly, Settings toggle, off by default). Guards: held by our provider, trade where Rank 1 is ours, created in the last 7 days, no protect label; foreign-provider WOs ignored. Ran on SB2 (planned 10 WOs, accept for OPEN ones). Not run on Prod; the IN PROGRESS path was only unit-tested | next release |
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
| B-06 | Realism report | Zac: not wanted |
| B-01 | Locations lookup by store ID, plus CSV bulk add | Lookup is covered by the loaded locations list with search (v0.2.x); the bulk part became B-46 |
| B-10 | Daily digest to Slack or email | Zac: not wanted |
| B-17 | Schedule heatmap on Day plan | Zac: not wanted |
| B-18 | Native app wrapper | Zac: not wanted. Reversed 2026-10-26, now B-44 |
| B-19 | Bulk auto-cleanup of leftover WOs | Replaced by B-41 (one-time clean-up) and B-40 (abandoned sweep) |

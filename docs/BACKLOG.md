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
| 1 | B-44 | (Built; macOS app tested by hand 2026-10-26, Windows build is checked by CI only; ships in 0.3.0) Desktop app: a downloadable `.dmg` and Windows installer with the agent bundled (Tauri shell + frozen Python program), a first-run welcome page for Production or SB2, tray icon, start at login, and in-app updates from GitHub Releases with the Hub's updater. Reverses B-18 | XL | Setup needed Python and a terminal, and `agent update` ran pip. Other people will use this, so install and update must be one click | Zac |
| 2 | B-39 | (Done: proposal and invoice decisions, user-cancelled or completed WO, user check-in; live-tested on SB2 2026-10-26 for cancel and check-in. Still open: other user changes such as a rescheduled WO or edits to NTE or priority, and a periodic status read instead of reacting to failures) Pick up manual changes: before each step, read the live WO, proposal and invoice status. If the user already did the planned action (approved, checked in, completed), mark the step done and continue. If the user did something different (rejected a proposal, cancelled the WO, completed it early), re-plan from the new state instead of erroring: rejected proposal runs the revised-proposal branch, a cancelled WO ends its plan, anything unrecognized parks the plan and shows it on the Errors page. Spike result (2026-10-26): the API lets a planned approve overturn a user's rejection, and assignWO fails on an already approved proposal, so the status read must come first | L, spike | Real users click around demo data. Today a step that finds the object already changed fails or repeats | Zac |
| 3 | B-40 | Abandoned WO sweep: find WOs with no activity or updates for N days (Settings slider, default 14). Cancel them or give them a short finishing plan, per a setting. A WO carrying a protect label is never touched (label name is a setting, default `do not touch`) | L, spike | Demo locations fill with WOs users started and left. The spike must find how to read last-activity time and how to read and set a WO label through the API | Zac |
| 4 | B-41 | One-time clean-up run (manual button and `agent cleanup`): batch-finish or cancel every stalled WO, proposal and invoice at the chosen locations so the location is back to demo ready. Preview list first, then run. Same protect label as B-40. Replaces the old bulk auto-cleanup idea (B-19) | L, spike | Resets a location before a demo. Shares the finish-or-cancel logic with B-40, so build B-40 first or together | Zac |
| 5 | B-42 | Optional Telegram alerts: the user adds a bot token and chat id in Settings (with a Test message button). The agent sends a message whenever something needs the user: a step failed after its retries, a parked plan (B-39), a missing check-in permission, a connection or login failure, the agent stopped or paused after a crash. Off by default. Messages name the WO, the step and the error, and link to the Errors page. Token stored encrypted like other secrets. Rate-limited so one outage sends one message, not hundreds | M | An unattended agent only helps if the user hears about problems. Today errors wait on the Errors page until someone looks | Zac |
| 6 | B-36 | Setup wizard step for the Subscriber/Provider pair permission: show a ready-to-send support request with the real IDs, and mark the pair 'permission pending' until a first check-in succeeds | S | Every new pair needs ServiceChannel support to enable check-in/out. Users will hit this on day one | Zac |
| 7 | B-08 | Emergency timing: read WO priority and ETA. Any WO with an ETA under 8 hours gets more activity, including back-and-forth notes that confirm provider availability before the visit | M | Urgent WOs are where flat timing looks most fake | Zac |
| 8 | B-37 | Provider resubmits a corrected invoice after a rejection (reject now works, but the plan ends there) | S | A rejected invoice dead-ends today; real flow is reject, fix, resubmit, approve | Claude |
| 9 | B-11 | Provider declines (low rate) and reschedules (higher rate) | L, spike | Real queues have refusals and date changes. Reschedules re-time the plan | Zac |
| 10 | B-20 | Reassign WOs between providers, for example after a decline or a no-show | L, spike | Completes the decline path. Adds no-show as an outcome | Zac |
| 11 | B-01 | Locations lookup by store ID through the API, plus CSV bulk add | M | Typing DB id and lat/lon by hand blocks onboarding | Claude |
| 12 | B-02 | Scheduled contract resync and a "trades skipped" report | S | Rank 1 can change. Stale contracts send WOs to the wrong provider | Claude |
| 13 | B-12 | Invoice variety and validation: time on site and labor rate flags, over-NTE, partial, credit memo. Subscriber approves or rejects based on the flags | L, spike | Exercises the invoice validation logic and rejection paths | Zac + Claude |
| 14 | B-21 | Mark approved invoices as PAID | S, spike | Closes the money lifecycle | Zac |
| 15 | B-22 | Complete checklists on WOs | M, spike | Checklists are part of real completion | Zac |
| 16 | B-23 | Create WOs with assets attached | M, spike | Asset-linked work is the normal case in many accounts | Zac |
| 17 | B-24 | Providers attach assets to WOs when onsite | M, spike | Pairs with B-23 | Zac |
| 18 | B-14 | Photos on WOs: relevant to the trade and issue only, with variety (several images per issue type) | M, spike | Real WOs carry photos. Needs a curated image set per issue type, with licensing checked | Zac |
| 19 | B-25 | Star ratings on WOs. A low rating moves the WO to Unsatisfactory and the provider returns onsite to finish | L, spike | Adds a rework loop | Zac |
| 20 | B-15 | Provider-side PM WOs: find PM WOs and move them through the process. Subscribers cannot create PMs through the API, so the agent only picks up existing ones | L, spike | PM is a large share of real volume | Zac |
| 21 | B-26 | PM compliance flows: pass and fail documentation, and the related follow-up | L, spike | Builds on B-15 | Zac |
| 22 | B-27 | Linked WOs (parent and child) | M, spike | Common for multi-visit and multi-trade jobs | Zac |
| 23 | B-28 | Recall WOs | M, spike | Rework against a closed WO. Pairs with B-25 | Zac |
| 24 | B-29 | Avoided WOs: Guided Troubleshooting resolves the issue, and duplicate WOs are detected and avoided | L, spike | Tests the "WO never gets created" paths | Zac |
| 25 | B-30 | Site audits that result in WOs created | L, spike | A second source of WOs besides the issue list | Zac |
| 26 | B-31 | Snow and landscaping WOs done by providers with CIWO | L, spike | CIWO has its own check-in model | Zac |
| 27 | B-32 | Quarterly RFP: a Subscriber runs an RFP with several bidding providers, then issues WOs to the winners | XL, spike | Needs several provider connections and contract changes | Zac |
| 28 | B-33 | FTM techs and FTM WOs through the process | L, spike | Needs the FTM product model first | Zac |
| 29 | B-05 | Per-location behavior overrides | M | Locations should differ in volume and trade mix | Claude |
| 30 | B-07 | Seasonal and holiday weighting (HVAC in summer, quiet holidays) | M | Flat weekday activity is an easy tell | Claude |
| 31 | B-03 | Settings export/import and DB backup/restore | S | Recovery from a bad update, or a machine move | Claude |
| 32 | B-04 | Deep link from the console to the WO in the ServiceChannel Subscriber view, in place of a WO detail page | S, spike | Finds the WO URL pattern. Keeps the console small | Zac |
| 33 | B-09 | Scenario presets (quiet week, busy week, storm surge) | S | One click to change load | Claude |
| 34 | B-16 | Clock speed-up mode for demos on SB2 | M | A full lifecycle in minutes | Claude |
| 35 | B-13 | Repeat issues on the same asset | M | Needs B-23. Feeds repeat-repair reports | Claude |
| 36 | B-34 | RT workflows | XL, spike | Very hard. Last on purpose | Zac |

## Ideas waiting for a spec
None yet. Zac's new ideas go here first, then get sized and ranked.

## Done
| ID | Item | Version |
|----|------|---------|
| B-35 | Fix failing creates: pre-check the location dashboard lookup | unreleased (0.1.0) |
| B-38 | Proposal create, link and approve; invoice reject | unreleased (0.1.0) |
| B-43 | Location picker from the Subscriber's locations | 0.2.0 |

## Dropped
| ID | Item | Reason |
|----|------|--------|
| B-06 | Realism report | Zac: not wanted |
| B-10 | Daily digest to Slack or email | Zac: not wanted |
| B-17 | Schedule heatmap on Day plan | Zac: not wanted |
| B-18 | Native app wrapper | Zac: not wanted. Reversed 2026-10-26, now B-44 |
| B-19 | Bulk auto-cleanup of leftover WOs | Replaced by B-41 (one-time clean-up) and B-40 (abandoned sweep) |

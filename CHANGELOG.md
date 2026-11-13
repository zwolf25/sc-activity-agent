# Changelog

## Unreleased

## v0.22.0 - 2026-11-13

- Changed: when a person sets an invoice to NO CHARGE in ServiceChannel, or the first invoice submit is refused with 1105, the agent ends the invoice steps instead of failing them. The invoice decide and pay steps do nothing when there is no invoice.
- Changed: proposal, invoice, invoice-fix and invoice-reject notes now name the work order's equipment, area and location, so two WOs of one trade no longer read the same.
- Changed: after a sleep gap or on a rework return, steps land 0 to 90 minutes after the window opens, and steps that would share a time spread 1 to 10 minutes apart, instead of all landing at 08:00:00.
- New (for developers): `scripts/release_prep.py X.Y.Z` does the CHANGELOG rename, version bump and test run.
- Restart the agent after updating; nothing pauses and no migration.

## v0.21.0 - 2026-11-13

- New: a network outage no longer fails steps. A failed connection (SSL error, timeout, reset) does not use up a step's 3 attempts. After 3 of them within 2 minutes the agent stops running steps, shows "Network is down since ..." on every page, tries one step a minute, and resumes by itself when ServiceChannel answers. Your own Pause is separate and is never undone by this.
- New: Telegram alerts that could not be sent during an outage are kept (the last 20) and sent when the network is back, with one "network is back" message.
- New: a failed step's row on the Errors page says how many later steps of that WO are waiting behind it.
- Checked: no database lock lines in the Prod log since 0.17.5, so that backlog item is closed.
- Restart the agent after updating; nothing pauses and no migration.

## v0.20.16 - 2026-11-12

- New: a **Close out WO** button on the Errors page stops the agent's plan for a WO you finished or cancelled in ServiceChannel. It skips the open steps and marks the WO cancelled in the agent, and sends nothing to ServiceChannel.
- Changed: a WO waiting at COMPLETED / PENDING REFRIGERANT USE now fails its next step at once with a plain message (record the usage or cancel the WO in ServiceChannel, then Close out), instead of running into 921 and 904 errors.
- Fixed: a step error is never blank any more. When an exception has no message, the Errors page and the Telegram alert show its type. A second-tech step with nobody to run it is now ended in one place in the engine. Restart the agent after updating; nothing pauses and no migration.

## v0.20.15 - 2026-11-12

- Fixed: a second-technician check-in or check-out failed with a blank error when the provider has only one technician. The step now ends as done without a call, as intended, instead of failing three times and alerting. Restart the agent after updating; nothing pauses and no migration.

## v0.20.14 - 2026-11-12

- Changed: the star-rating and rework messages now name the work order. The Subscriber's low-rating comment says what is still wrong with the equipment, in words that fit the trade (for example "the Water Heater is leaking again"), and mentions the store, the area and the day of the last visit. The provider's return note answers the same complaint, and the second review after a return visit has its own wording. Issue labels that name no problem ("Other Issues") are no longer quoted. Restart the agent after updating; no migration.

## v0.20.13 - 2026-11-11

- New: seed assets from the console. The "No assets seeded yet" banner on Dashboard and Locations now has a Seed button for each location. It asks for confirmation, approves that location for Production (assets.approved_locations) and seeds in the background, with a progress banner and a Retry button on error. The `agent assets` commands still work. Restart the agent after updating; no migration.

## v0.20.12 - 2026-11-10

- Fixed: a rejected-invoice plan failed with 1105 "Invoice exists" when someone approved the invoice before the agent's reject. The decide step now skips the planned resubmit when the invoice is already APPROVED or PAID, and a resubmit that still gets 1105 ends as done instead of failed. Restart the agent after updating; nothing pauses and no migration.

## v0.20.11 - 2026-11-08

- New: the issue list we build and test against, `SCActivityAgentIssueList.xlsx`, ships with the agent and is attached to every release. Settings > Issue list downloads it, in case you lose your copy. Load it on your Subscriber's dashboard to run the same setup.
- Nothing to do on update.

## v0.20.10 - 2026-11-08

- Fixed a stall where overdue steps never ran. Each loop pass runs a limited number of due steps. Steps queued behind an unfinished earlier step of the same work order used up those slots and were then skipped, so the earlier step, which had a later due time, never got a turn. This showed on SB2 after a sleep gap: 311 steps overdue and nothing run since Nov 5. Only the first unfinished step of each work order now takes a slot.
- Restart the agent to update. Nothing pauses.

## v0.20.9 - 2026-11-08

- Error 916 ("At least one attachment required to create this WorkOrder") is fixed. ServiceChannel marks some issues in the issue list as RequireAttachment. The agent now tells ServiceChannel to skip that check for those issues and attaches the before photo right after the create, whatever the before-photo slider says. The 916 hint on the Errors page was wrong (it blamed an account setting) and now names the issue flag.
- Eleven new photo sets (Kitchen Equipment and Freight Equipment): fryer installs, dial scales, digital scales and a forklift battery. Every issue that requires an attachment now has a matching set. A WO in a trade with no photo set still gets no photo.
- Work orders finished by clean-up or pickup (B-51) now also get an invoice payment step, a few weeks after the approval, so they no longer stay in Payment due with nothing pending.
- Restart the agent to update. Nothing pauses. Existing Payment due work orders with nothing pending need a one-time backfill (done by hand on Production).

## v0.20.8 - 2026-11-07

- Steps planned outside activity hours no longer all land on exactly the opening minute (for example 08:00:00). A step moved to the start of the next activity window now lands up to 90 minutes after it, so the audit log looks less mechanical. Plans already saved keep their times.
- The Errors page now explains error 916 ("At least one attachment required to create this WorkOrder"): ServiceChannel wants an attachment at create, and the agent adds its photo after the create, so the fix is on the ServiceChannel side. Seen on Production at ZW123 on 2026-11-07. The agent still does not retry a failed create.
- Restart the agent to update. Nothing pauses.

## v0.20.7 - 2026-11-07

- Updates now stop the right agent. If the saved process number is out of date, the update finds the running agent by its lock file, and it waits for the agent to exit. If the old agent will not exit, the Updating page says so and names the process instead of waiting for a restart that never happens.
- Restart the agent to update. Nothing pauses.

## v0.20.6 - 2026-11-07
- Invoice and proposal approvals now go only to a Subscriber user whose invoice or proposal limit in ServiceChannel covers the total. The agent reads each user's limits from their profile (cached for an hour). If no user's limit is high enough, the step fails with a message saying so. If a user is still refused over their limit, the step switches user at once instead of retrying three times.
- A work order that has no saved provider is no longer given to a random capable user when two providers could take it. The step fails with a clear message instead of retrying against a user who cannot see the work order.
- Restart the agent to update. Nothing pauses. Set each Subscriber user's invoice and proposal limits in ServiceChannel so a user with a low limit is skipped.

## v0.20.5 - 2026-11-06

- Tests now also run against real ServiceChannel responses saved in `tests/fixtures/` (B-90). Nothing changes when the agent runs.
- Restart the agent to update. Nothing pauses.

## v0.20.4 - 2026-11-06

- The Updating page now shows the release notes of the version being installed, so there is something to read while the agent restarts.
- The agent now checks who ServiceChannel gave each new work order to. Before, it trusted its Rank 1 read. On 2026-11-06 two Production HVAC work orders at ZW123 went to AHS Services Co, a provider the agent has no login for, and every accept failed with 502 "Work order is not found". Now such a work order is cancelled at once, the trade is skipped at that location, and the Errors page says which provider took it. Press Re-read contracts on Locations to let the agent try that trade again. A work order that goes to another of your own providers is planned for that provider.
- Restart the agent to update. Nothing pauses.

## v0.20.3 - 2026-11-06

- Connections: the dashboard of each Subscriber user now sits on its own line under the user, with the Check dashboard button at its right. Before, the button wrapped to two lines and squeezed the user's row.
- A work order whose invoice or review is refused because it waits for refrigerant usage (error 904 or 940) now fails at once, with a hint on the Errors page, instead of retrying three times. Seeded refrigerant assets (the RTU) are no longer attached to new work orders: a check-out on one leaves the work order in COMPLETED / PENDING REFRIGERANT USE, which blocks the review and the invoice, and the API call that answers it is not known yet. Work orders already in that state need the usage recorded in ServiceChannel (Provider Automation), then Retry.
- The hourly status check no longer stays on a work order it cannot read (a deleted one returns 404); it moves on to the next.
- A checklist that is not active on a work order stops after the first refused answer, not eleven.
- Restart the agent to update. Nothing pauses.

## v0.20.2 - 2026-11-06

- Connections: each Subscriber user's row shows that user's dashboard and issue list, with its own Check dashboard button. The Subscriber ID is now a small form on its own (Save and check users).
- A Subscriber user is checked when you add it. A user with no dashboard cannot be set to Create WOs, because ServiceChannel creates the WO from that dashboard and the create would fail. Assign a dashboard to the user in ServiceChannel, then press Check dashboard.
- Restart the agent to update. Nothing pauses. After the update, press Save and check users once so existing users show their dashboard; Create WOs stays ticked for users who already had it.

## v0.20.1 - 2026-11-05

- Fixed: with more than one Subscriber user ticked to create WOs, a create could read the issue list as one user and send the WO as another user with a different dashboard. That fails with "Cannot find issue choice" and leaves a VOID shell. A create now uses one Subscriber user from start to finish and that user's own dashboard.
- Connections and Check setup now show and test the dashboard and issue list of every Subscriber user, one row each.
- Restart the agent to update. Nothing pauses.

## v0.20.0 - 2026-11-05

- Factory reset now pauses the agent and waits for the step in progress to finish before it deletes anything. If the step does not finish within a minute, nothing is reset and the pause is undone.
- New: Settings > Backups > Restore. It restores a backup while the agent runs: it pauses, waits for the current step, saves the current database, then loads the backup. You type RESTORE and tick a box to confirm. The environment and port stay as they are. Before, restoring needed a terminal with the agent stopped (that command still works).
- Fixed: two backups made in the same second overwrote each other. A restore saves the current database first, so the backup you were restoring could be replaced by the current data. Backup names now get a suffix when they collide.
- Connections: the dashboard dropdown is gone. The agent now uses the issue list of the Subscriber user's own dashboard, which is the one ServiceChannel applies when it creates a WO, and shows it next to the Subscriber ID. Press Check dashboard after you change the user's dashboard in ServiceChannel. Any issue list works. The old dashboard mismatch banner is gone because the mismatch can no longer happen.
- Restart the agent to update. Nothing pauses.

## v0.19.0 - 2026-11-05

- New alert: "Work order creation failed several times in a row". After 3 failed creates in a row the Telegram alert names the location, the error and the fix. Before, a creation problem (no Rank 1 provider, dashboard not assigned) only showed on the Errors page, and nothing alerted you while the agent made no activity. It follows the alert settings and the 6 hour repeat limit; switch it off under Settings > Telegram alerts.
- New: Setup > Check setup. One click tests every sign-in, the Subscriber's issue list dashboards and the Rank 1 trades at your first 5 enabled locations, and shows the fix next to each problem. It only reads from ServiceChannel and creates nothing.
- Restart the agent to update. Nothing pauses.

## v0.18.0 - 2026-11-05

- New: Settings > Danger zone > Factory reset. It clears all connections, users, locations, tracked work orders, the audit log and every setting, so the agent starts setup from scratch without a reinstall. It saves a database backup first, keeps the environment, port and secret key, and needs the typed word RESET plus a tick box. Work orders already in ServiceChannel are not deleted (run Clean-up first to cancel them). It refuses while a clean-up or update is running.
- The Setup checklist now says what to do for each open step, and has new steps: every Provider needs its numeric Provider ID, at least one enabled location, and a Provider you control must be Rank 1 at a location (confirmed by the first creation pass; it does not hold back the Dashboard). The Dashboard banner names the next step.
- Provider connections now require a numeric Provider ID (before, a missing one made creation fail later with "no eligible trade").
- Clearer errors with the fix: login failures, unreachable ServiceChannel (internet, VPN, proxy), dashboard and location load failures, and the Errors page now shows a hint under each work order creation error (no Rank 1 provider, dashboard not assigned, billing 1145, check-in 804). Deleting a connection also forgets its cached login.
- Restart the agent to update. Nothing pauses.

## v0.17.5 - 2026-11-05

- The Setup page and the Dashboard banner said a Subscriber and Provider pair needed linking after any 403 on check-in. They now say so only for error 804. Any other refusal shows as "Last check-in failed" with ServiceChannel's reason, and no link request is offered.
- A database transaction left open by a web page, the clean-up thread or the Telegram poller is now committed as soon as that work ends, and the log says which one did it. An open transaction blocks every other write, which is how `database is locked` happens.
- Restart the agent after updating. Nothing pauses. No migration.

## v0.17.4 - 2026-11-04

- The scheduled SB2 smoke run no longer leaves a Behavior or checklist setting stored as empty (null) when it did not exist before; it deletes the setting again. This was the likely cause of the v0.17.1 Settings crash.
- Internal: the step executors moved from one `handlers.py` into a `handlers/` package, split by area. Behavior is unchanged.
- Restart the agent after updating. Nothing pauses and plans keep running.

## v0.17.3 - 2026-11-04

- When the database reports `database is locked`, the agent log now names the threads that hold a transaction open and where they are (at most once a minute). This is to find what still locks the database on one machine.
- The agent commits a transaction that a loop step or the clean-up sweep leaves open, and logs a line saying which one did. An open transaction blocks every other write.
- The clean-up sweep runs one at a time, where before it started a new thread on every 30-second loop pass. An error in it is logged as one line instead of a traceback.
- Update needs a restart and pauses nothing. No migration.

## v0.17.2 - 2026-11-04

- Fixed `database is locked` errors, seen when "Refresh now" on the Locations page ran while the agent was busy. The database now uses SQLite WAL mode, so the web page, the clean-up sweep and the Telegram poller no longer wait on the step loop. The data folder gains `agent.db-wal` and `agent.db-shm` files; that is normal.
- Backups and restore now work with WAL mode (the backup uses SQLite's own copy, restore removes the old WAL files).
- Fixed `create loop error: KeyError: 'CategoryId'` on dashboards whose issue list has problems with no `CategoryId`. The agent now skips those problems instead of failing.
- Update needs a restart and pauses nothing. No migration.

## v0.17.1 - 2026-11-04

- Fixed an Internal Server Error on the Settings page when a setting had been cleared and stored as empty. An empty stored setting now falls back to its default. No migration; the update needs a restart and pauses nothing.

## v0.17.0 - 2026-11-04

- SB2 smoke run: a test (SB2) instance can run one full work order every 7 days (photos, checklists and a rework on) and send the pass or fail result as an alert. Turn it on under Settings > SB2 smoke run, where Run now starts one at once and the last result is shown. The agent does nothing else for the few minutes a run takes. Production instances never show or run it.
- `scripts/live_sb2.py` uses the same code.
- The update needs the usual restart. No database change; nothing pauses.

## v0.16.0 - 2026-11-03

- The Daily limits card moved from Behavior to Settings.
- Errors page: failed steps with the same error are one row with a count, the first and last time and the work orders, plus a hint for known causes (over the NTE, a second asset attach, rate limit). Retry all and Skip all act on the whole row.
- Time zones: after a sleep gap, and when a rework plans the return visit, steps are placed in the work order's own store time zone, not the instance zone. A Denver instance no longer shifts New York visits two hours.
- Housekeeping: the unused `roles` table is dropped by a migration (database version 4). The update needs the usual restart; nothing pauses.

## v0.15.0 - 2026-11-03

- Daily limits: the agent pauses and sends an alert when it has created 40 work orders or made 3000 API calls in one day (instance time zone). Change or turn off (0) each limit under Behavior > Daily limits, which also shows today's usage and the expected work orders per day. A banner shows why the agent paused. After raising a limit, press Resume.
- `agent get` no longer prints tokens, secrets or passwords; it shows `***`.
- New photos avoid the sets used on the last 10 work orders at the same location, so the same image repeats less.
- CI and release workflows use newer GitHub Actions (Node 24).
- The update needs the usual restart. No database change; nothing pauses.

## v0.14.3 - 2026-11-03

- Twelve new photo sets with no cable clutter (generator battery, pylon sign, lifted floor, dock threshold, flagpole, overhead door, backflow preventer, flushometer, water heater pilot, burnt contactor, fence, roof drain). The library has 64 sets.
- Before, after and checklist photos now match the issue, not only the trade (a water heater leak gets the water heater photo, a clogged filter gets the filter photo). Issues with no matching scene still get a photo of the trade.
- `agent assets audit` and `enrich` read the asset list once instead of one request per asset.
- The Dashboard and Locations pages show a banner when a location has a trade we hold Rank 1 for but no seeded assets, with the command to run. Dismiss hides it for those locations and trades.
- Housekeeping: the unused `contracts` table is dropped by a migration (database version 3). The update needs the usual restart; nothing pauses.

## v0.14.2 - 2026-11-03

- New warning when the dashboard you select is not the one assigned to the Subscriber user. ServiceChannel creates work orders from the user's dashboard, so the issue and NTE can differ from what the agent planned. The agent checks a sample of issues when you change the dashboard, daily, and every 10 minutes while the warning shows, and a banner on every page says what to fix.
- Dashboard stage tiles are links. Each opens a list of the work orders in that stage with their trade, location and next step.

- Every date and time on every page now uses one format and the instance's time zone, for example "Tue Nov 03, 14:05": the Audit log Time column, Last activity in the clean-up preview, the Backups Saved column, "Last read" on Locations and "found" in the clean-up preview. Before, some showed a raw number, a bare date, or the computer's own time zone.
- Audit log: only Time, User and Call wrap, so Role, WO, Action, HTTP and ms stay on one line, and the header lines up with the columns.

## v0.14.1 - 2026-11-03

- Taking an update needs one press. The progress page no longer shows a second "Update now" button, and other pages show "Updating to vX" with a link to progress while an update runs. The progress page has a moving bar and says whether it is installing or restarting.

- The Cleanup page table "Work orders the agent created" has a Created column with the date and time.

- Work order creation errors on the Errors page show the date and time (for example "Tue Nov 03, 14:05") instead of a raw number.

- The Audit log table wraps long values (call paths, users) instead of scrolling sideways.

- The Locations page table "Trades we can create" has a new column, "Set up for assets": Yes with the count of agent-seeded assets, or No, per location and trade.

## v0.14.0 - 2026-11-03

- Two new Behavior sliders, both default 0 (no change until raised): "WOs created with an asset %" sends a seeded asset of the issue's equipment type (HVAC RTU, Generator, Electrical Panel, Exit Signs, Lighting, Water Heater, Backflow Preventer, Flushometer Valve) when the new WO is created. "Provider attaches an asset on site %" has the provider attach an asset at the first check-in of a WO that has none: the issue's equipment type, or any seeded asset in the WO's trade at that location. An attach the API refuses is skipped and the visit continues.
- Asset seeding no longer stops when a newly created asset type is not yet in the list: it uses the id the create returns, or retries the lookup. This stopped the first Production run after two types were created.

## v0.13.0 - 2026-11-02

- New `agent assets plan | seed | audit | enrich` commands create realistic assets (HVAC, Electrical, Plumbing) at a location: real brands and model numbers from a bundled catalog, matching serial numbers, install and purchase dates, condition, value, area and description. `plan` is a dry run; `seed` and `enrich` write only with `--yes`. Reruns create only what is missing, and one bad asset is logged without stopping the run. Production needs the location in the `assets.approved_locations` setting first. The update adds two database tables; restart the agent after updating, nothing pauses.

## v0.12.4 - 2026-11-02

- A step that fails three times because of its user (no permission, over the approval limit, an unexplained refusal) now tries another user who can do it. The step fails and sends the alert only when every capable user has failed. The Errors page shows the switch in the step's error text.
- Retry from the Errors page starts again with a fresh choice of user.
- Restart needed; nothing pauses and no migration runs.

## v0.12.3 - 2026-11-02

- Fix: each step now keeps one user. Before, every call in a step could use a different user, so one account's missing permission or approval limit failed the step on some retries and not others. A step's user is chosen the first time it runs and kept for its retries.
- Fix: a star-rated review no longer fails with "Invalid WorkOrder status" when the work order is COMPLETED but not waiting for confirmation; it confirms the work order plainly. A retry also keeps the rated or plain choice.
- Restart needed; nothing pauses and no migration runs. Steps already planned get their user the first time they run.

## v0.12.2 - 2026-11-01

- Fix: work orders whose plan is stuck (a failed step waiting on the Errors page) no longer crowd other work orders out of the agent's per-pass limit, so one stuck plan cannot slow the rest.

- Fix: a rated review now reads the work order first. If a person already confirmed it, the step is done; if it is in a status that cannot take a rating, the step stops on the Errors page instead of failing and retrying.
- Fix: steps added while a tick is running (the return visit after an unsatisfactory review, a resubmitted invoice) now run before the steps that followed them. Only a busy tick could run them out of order.

- Change: the sliders on the Behavior page now follow the life of a work order, from creation through payment, with the activity hours last.

## v0.12.1 - 2026-11-01

- Fix: a work order rated unsatisfactory now shows as Unsatisfactory on the Dashboard (a new stage tile) until the provider returns, instead of Invoice due.

## v0.12.0 - 2026-11-01

- New: star ratings and rework. Two Behavior sliders, both 0 by default. "Star rating on review %" is the share of reviews that carry a star rating (the rest are a plain confirm). "Unsatisfactory work % of rated reviews" is the share of those that get 1 or 2 stars with a comment, the rest get 3 to 5. A low rating sets the WO to In Progress / Unsatisfactory; the provider then returns onsite, checks out again, and the Subscriber reviews a second time. The invoice follows the last review. Needs a restart; nothing pauses.
- Removed: the desktop app. Install with Python (`install.sh` or `install.ps1`); updates and the Update now button work as before. Releases no longer carry the installers or `latest.json`.

- Fix: an invoice posted after 7 PM US Eastern is now paid. ServiceChannel dates such an invoice the next day and refused a payment dated earlier (error 1178), so the payment date is now never before the invoice date.

## v0.11.3 - 2026-11-01

- Fix: the daily Cleanup sweep now follows the Activity days from Behavior. It used to skip Saturday and Sunday whatever days you picked.
- Change: the Dashboard remembers Hide done and Hide skipped. Both start hidden, and your last choice stays until you change it.
- Change: checklist answers are now sent under the answering user's own ServiceChannel id instead of a fixed technician 1. If the id cannot be read the agent still sends technician 1. A required question the agent cannot answer is written to the audit log so an open checklist is visible.
- Developer: `scripts/bump_version.py` sets the version in every file, and `scripts/live_sb2.py` runs one full work order on an SB2 instance as a release check.

## v0.11.2 - 2026-10-31

- New: the Dashboard's week table switches between This week and Next week, with the dates shown. The choice is remembered, and when a new week starts the table goes back to This week on its own.

- Fix: Update now (source installs) no longer needs several clicks and a manual refresh. One click starts the update, a progress page waits while the agent restarts, and the dashboard opens on the new version. Extra clicks while an update runs do nothing. Restart the agent after updating; no migration.

## v0.11.1 - 2026-10-30

- Changed: the photo options moved from Settings checkboxes to Behavior sliders ("Before photo on new WOs %", "After photo on closing note %"), both 0 by default. If you ticked either checkbox in v0.11.0, set the slider instead; the old checkbox is ignored.
- New: Behavior > Activity days. Pick any days of the week, weekends included; the agent creates and works on work orders only on those days. Default is Monday to Friday. Work orders per month is spread over the days you pick.
- Changed: activity hours show as 12-hour times with AM and PM. Restart the agent after updating; no migration.

## v0.11.0 - 2026-10-30

- New: Settings > "Attach a before photo to new work orders" and "Attach an after photo to the provider's closing note" (both off by default). The photos match the WO's trade and come from the same scene. The closing note is an extra provider note posted after the final check-out. Verified on SB2 (a full create-to-check-out run); not run on Production. Restart the agent after updating; no migration.

## v0.10.0 - 2026-10-30

- New: a library of 52 before and after photo sets (HVAC, Electrical, Plumbing, Doors, General Maintenance, Janitorial), each with a before, an after and a side-by-side image. Shipped inside the app.
- New: Settings > "Answer checklists at check-out" (off by default). When the provider checks out, the agent answers the checklists your Subscriber set up for that trade and location, with a photo where a picture is asked for. It does nothing where no checklist exists. Verified on SB2; not run on Production. Restart the agent after updating; no migration.
- Fix: the packaged desktop app now bundles the photo library, so check-out does not fail on a missing image.

## v0.9.0 - 2026-10-29

- New: the agent can plan work orders that people create by hand at your locations. On by default; turn it off in Settings ("Plan work orders people create by hand"). Once an hour it finds WOs from the last 7 days that are held by one of your providers, in a trade where your provider is Rank 1, and that do not carry the protect label. Each gets a short plan (accept if still open, a visit, review, invoice, decision). WOs held by other providers are left alone. It acts as the Provider and Subscriber on those WOs. After you update, it starts within an hour; switch it off first in Settings if you do not want that. Restart the agent after updating; no migration.
- Changed: `install.ps1` (Windows) takes the data folder from `SC_AGENT_DATA` when set, as `install.sh` already does. Checked by reading only; not run on Windows.
- A work order with an NTE of 0 is no longer invoiced (ServiceChannel refuses it). The Subscriber closes it as COMPLETED / NO CHARGE and the plan ends. Restart the agent after updating; no migration.
## v0.8.0 - 2026-10-29

- Invoices are now line items: labor hours match time on site at the provider's agreed rate, plus 0 to 2 materials lines, always under the NTE. The agent learns the agreed rate from the first invoice.
- New settings, both default 0: "Invoices with a wrong rate %" and "Invoices billing extra hours %". A flawed first invoice is rejected and resubmitted clean.
- The Subscriber now rejects any invoice that ServiceChannel flags for a rate mismatch, or that bills well over the time on site, even when the plan meant to approve, and the Provider resubmits. Restart the agent after updating; no migration.
- Fixed: `agent status`, `get`, `plan`, `pause`, `resume`, `tick`, `step`, `set`, `cleanup` and `backup` no longer create an empty instance (folder, key and database) at a mistyped or wrong `--data-dir`. They exit with "no agent instance at <path>". Only `init`, `run`, `open` and `install-app` create a folder. (Shipped in 0.7.1; changelog line added afterwards.)

## v0.7.1 - 2026-10-29

- Update note: restart the agent after updating. No database migration and no pause needed.
- The agent follows changes users make to a WO in ServiceChannel. If the scheduled date moves later, the visit and every step after it move with it (inside activity hours, on a weekday), and a check-in that was due waits for the new time. A changed NTE or priority is picked up for later invoice and proposal amounts and notes. If a WO gets a status the plan does not know, or is moved to a provider the plan was not built for, its plan parks: the step fails at once and shows on the Errors page instead of retrying. Needs the usual restart; nothing pauses.
- New: Behavior setting "Provider no-shows %" (default 0). The provider accepts, then never arrives. A few hours after the visit time the Subscriber adds a note about the missed visit, then moves the WO to another provider connection that holds a contract for the trade (the same step as "Reassign after a decline %"), and that provider's work is planned as normal. With no such provider the WO is cancelled with a no-show note.
- Fixed: when a WO moves to another provider, the old plan's pending steps (for example a check-out) are skipped, so they no longer run as the new provider.
- Fixed: with more than one Provider connection, a WO could be created without its provider recorded when the Rank 1 cache was older than the provider list, so its steps ran as a random provider's user and failed with "WorkOrder not found". An older cache entry is now re-read, and adding or removing a connection clears the cache.
- Changed: tables page in the browser. Locations 10, Add locations 20, Trades we can create 10 (with Location and Trade filters), Skipped trades 10, Audit log 20, both Errors tables 20, both Cleanup tables 10, Backups 10. The Add locations list now holds up to 1000 matches (was 50), and ticks survive paging.
- Changed: Connections shows one row per user, with a Can do dropdown of checkboxes instead of a second row of boxes. Audit log Call text wraps instead of being cut off. Errors has a "Failed steps" header.
- Changed: Cleanup settings sit inline, and the daily-choice dropdown is no longer full width.
- Changed: the Dashboard hides done steps by default, as it already did for skipped ones.
- Changed: the hourly status check is now a toggle in Settings named "Catch cancellations early", on by default, instead of a 0 to 1 slider in Behavior named "Background status check" that was off. Once an hour the agent reads one active WO; if a user cancelled it in ServiceChannel, its plan ends then instead of when the next step comes due. It only reads. An instance that had the old slider set uses the new default (on); switch it off in Settings.
## v0.7.0 - 2026-10-29
- Update note: restart the agent after updating. No database migration and no pause needed. New Behavior settings (declines, reschedules, reassign, background check) default to 0 or off. Keep this Mac awake is on by default on macOS source installs.
- New: Behavior setting "Reassign after a decline %" (default 0). Of the WOs the provider declines, this share is moved by the Subscriber to another provider connection that holds a contract for the trade at the location, and that provider's work is planned as normal. A decline with no such provider is cancelled 1 to 3 days later, as before. The new provider needs its own connection and a user who can accept.
- Fixed: the launcher and Start at login could each start an agent, so two ran on one data folder and every step could run twice. An agent now takes a lock on its data folder at start; a second one exits with a message.
- Fixed: the periodic WO status check (B-39) never ran, because its import sat in the wrong function.
- New: Keep this Mac awake for the Python install (macOS only, on by default, Settings). The agent runs `caffeinate` for as long as it runs, so the Mac does not idle-sleep on power and plans keep running. It does not cover lid-close or battery sleep. The desktop app keeps its own switch in the tray menu.
- Changed: `install.sh` takes the data folder from `SC_AGENT_DATA` when set, so it can install on top of an existing instance.
- New: Behavior settings "Provider declines %" and "Reschedules %" (both default 0, so nothing changes until you raise them). A declining provider sends the decline (WO becomes OPEN / DECLINED) and the Subscriber cancels the WO 1 to 3 days later. A reschedule is the Provider moving the scheduled date 1 to 3 business days later than the original date; the WO is created with the original date and the visits follow the new one. A decline only stays OPEN / DECLINED when the trade's auto-reassign setting is off in ServiceChannel; with it on, SC hands the WO to another provider and the agent cancels it.
- New: before every write the agent reads the live WO. A WO a user cancelled in ServiceChannel ends its plan with no further writes; a WO a user already completed skips the field steps (accept, check-in, check-out, proposal) but still gets its review and invoice. Writes that still fail re-read the WO as before. Optional Behavior setting "Background status check" (default off) also reads one active WO per hour so the dashboard notices sooner.
- New: emergency plans, decided by the gap between the call date and the original ETA (scheduled date), not the priority label. New Behavior setting "Treat as emergency up to (hours)" (default 8, 0 = never) sets the threshold (a gap equal to it counts). For WOs the agent creates, an EMERGENCY issue gets a same-day ETA; for WOs picked up by a finishing clean-up, the real CallDate and ScheduledDate decide (a visit already in the past never counts). An emergency plan has: the provider accepts within 2 to 15 minutes, the subscriber asks for confirmation and the provider confirms availability, and the first visit happens within about 8 hours (the next morning if raised after hours). Emergency WOs get no proposal and no late arrival.

## v0.6.2 - 2026-10-28
- Update note: restart the agent after updating. No database migration and no pause needed.
- New: one-command install for macOS, Linux and Windows (`install.sh`, `install.ps1`). It checks for Python 3.11 or newer and, if it is missing, prints how to install it (Homebrew or python.org on macOS, winget or python.org on Windows). It then installs the latest release into its own environment, creates the instance and the double-click launcher. The launcher starts the agent if it is not running and opens the console in your browser. If the agent cannot start, it shows a message that names agent.log instead of opening a dead page.
- New: Settings > Updates and support has Check for updates and Copy diagnostics (version, platform, state and the end of the log, for a support message).
- Changed: updating a source install now restarts the agent by itself, unless Start at login already does. If the new version does not start, the previous version and the database are both put back (before, only the database was). Updates install from the release archive, so git is no longer needed on the machine.
- Fixed: a pip install of the agent had no console pages (the templates and styles were not packaged), so `agent update` on a source install would have left a console that cannot open.
- Fixed: the desktop app could sit on its loading screen with no clue why. The agent's log was buffered, so a process the system killed left nothing behind (the log showed nothing after 08:52 on 2026-10-28). The log is now written line by line and a native crash is reported there. The app also watches the agent program: if it exits abnormally it writes the exit status to agent.log (a signal means the system killed it) and starts it again, waiting longer after each quick failure.
- Known: on one machine macOS kills the agent program a few seconds after it starts when the app is opened from Finder or the Dock (it still runs from a terminal). The new log shows the exit status when that happens (B-49).

## v0.6.1 - 2026-10-28
- Update note: restart the agent after updating. No database migration and no pause needed.
- Fixed: two-technician visits. When two techs worked a visit, the first tech's check-out completed the WO and the second tech's check-out failed with error 921. The first tech now leaves with the Parts on Order status and the second completes the WO. This was found by testing on Prod with two SydeTech users; if you saw a failed check-out on a two-tech visit, retry it from the Errors page.
- Fixed: the Provider column in the clean-up preview was blank. It now shows the provider name.

## v0.6.0 - 2026-10-27
- Changed: the Roles page is gone. Each user on the Connections page now has **Can do** checkboxes. The agent picks randomly among the users who can do an action and belong to the WO's provider, so several technicians across several provider accounts take turns. A check-out is done by the same tech who checked in on that visit; separate visits can use different techs. Your existing Roles convert automatically on update (per-location overrides are dropped; none were in use). The first user added to a connection can do everything; later users start with nothing ticked.
- New: Behavior setting "Two-technician visits %" (default 5): share of visits where a second tech checks in a few minutes after the first and both check out. With fewer than two check-in techs on the provider, those visits stay single-tech.
- Changed: the setup checklist replaces "Roles mapped" with "Every action has a user" and "Every Provider has a check-in tech". A WO with no capable user for its provider now fails with a clear message instead of a 403.
- New: user labels show next to the username on Connections and in the Audit log. Old WOs created before this update have no recorded provider and use any capable user.
- Changed: Add user now signs in first. If the login fails, the user is not saved and the page shows the reason (for example wrong password or a client that is not registered in this environment). The Test button stays for users already added.
- New: a user's Label on the Connections page can be edited after the user is added (type, then Save).
- New: Settings has a Backups card (Back up now, and a list of the last 10 copies). The agent also saves a copy before every clean-up run. `agent backup` makes one from the command line, and `agent backup <file>` restores one while the agent is stopped.
- New: every plan now ends with the Subscriber marking the approved invoice as paid, about 30 days after the approval (Net 30 terms, varying by about a quarter either way; the Behavior setting "Average days to pay" changes it). The payment amount equals the invoice total. If the invoice was rejected or already paid by a user, the step does nothing. If your Subscriber is not allowed to record payments, the step is skipped without an error. Plans already saved are not changed.
- Changed: the Behavior setting "Time on site factor" is now "Average time on site (hours)", default 2 hours. Visit lengths vary around that average. The old factor is ignored, so every instance moves to 2 hours on update (the old default of 1.0 was also about 2 hours).
- New: `agent cleanup --limit N` acts on only the oldest N idle work orders, for testing the clean-up on a few at a time.
- Fix: the engine, console and clean-up sweep no longer share one database connection. Before, two of them touching the database at the same moment could fail with "bad parameter or other API misuse" (seen on the Resync locations button). Each thread now has its own connection. Needs a restart; nothing pauses.

## v0.5.1 - 2026-10-27
- Fix: the daily clean-up choice now has its own Save button with a confirm box, and saving it never starts a run: the first run is a day later. Before, saving the setting from the Preview button could start a sweep within minutes. "Finish ours" is no longer offered on Production and never runs automatically there. Finishing plans no longer start with an accept step, because most idle work orders are past acceptance and the API refuses it (error 904).

## v0.5.0 - 2026-10-27
- New: the daily sweep (B-40). Choose on the Cleanup page what happens to idle work orders every weekday: nothing, cancel them, or finish the ones held by your own providers and cancel the rest. At most 100 work orders a day.
- New: on-demand clean-up of old work orders (B-41). The Cleanup page and `agent cleanup [--days N] [--run]` list open work orders at your enabled locations that the agent did not create and that have had no activity for N days (default 14). Review the list, tick the box and cancel them all. Each work order is re-read just before it is cancelled, so anything touched since the preview is skipped. A work order carrying the protect label (default `do not touch`, set the label in ServiceChannel) is never touched. A paused agent cancels nothing. To skip the review there is a Clean up now button (`agent cleanup --run --auto`) that selects every idle work order itself, and a daily choice (B-40) that does the same every weekday on its own, up to 100 work orders a day: cancel idle work orders, or finish the ones held by your own providers with a short plan (accept, visit, review, invoice, approve) and cancel the rest. Needs a restart after the update.
- Fix: the console now loads its stylesheet with the version in the address, so an update shows its new look right away instead of the old cached styles. The Telegram setup steps have clear spacing and its option groups are lettered A to C. A finished step shows its Done line (with a check mark) on its own line.

## v0.4.2 - 2026-10-27
- Fix: a new release now shows the Update banner within an hour. The check was cached for a day, so a fresh release could stay hidden.
- New: add several locations at once. Tick rows in the search results, or paste store IDs as a list or CSV, then click Add selected. Locations already added keep their on/off setting.
- New: the Locations page has Refresh now, which re-reads Rank 1 contracts immediately (they still refresh daily by themselves), and a Skipped trades table that lists trades on the issue list where another provider is Rank 1.
- Change: the Telegram alerts form is clearer. Each option is on its own line in three groups: a master switch (Send Telegram alerts), which alert types to send, and the optional action buttons.

## v0.4.1 - 2026-10-27
- Fix: Telegram setup failed behind a company proxy (Zscaler) with a certificate error. Telegram connections now trust the operating system's certificates, so the token check works on managed networks.

## v0.4.0 - 2026-10-27
- New: optional Telegram alerts. Settings > Telegram alerts has a step-by-step setup with a check at each step. You get a message when a step fails after its retries, check-in is blocked (804), a login fails, or the agent was offline over an hour. Optional action buttons: Retry, Skip step, Pause agent, Cancel WO (asks first). Off by default; the bot token is stored encrypted; each instance has its own bot; at most 10 messages an hour and no repeat of the same alert within 6 hours. Messages include the WO, location, step and error text.
- New: one desktop app covers Production and SB2. On a Production instance, Connections > Open SB2 test instance creates and starts an SB2 copy inside the app's data folder (own database, key, port and logins; nothing is shared with Production). It runs only when you start it. The tray menu has Production console and SB2 console. One app update and one Quit cover both: both are paused and backed up before an update, and the SB2 copy comes back by itself if it was running.

## v0.3.6 - 2026-10-27
- New (macOS): the tray menu has Keep Mac awake (while plugged in), on by default and remembered. It stops the Mac from idle-sleeping so plans keep their times; it ends when the app quits. It does not stop sleep when the lid is closed or on battery.
- Fix: the Dashboard notice about time the agent was not running now shows readable local times, how long it was, and what was done about it. It has a Dismiss button, and Dismiss all when there are several. Before, it showed raw numbers and could not be cleared.
- Fix: a laptop that sleeps and wakes again and again (about every 17 minutes overnight) no longer adds one notice per wake. One notice now covers the whole stretch.

## v0.3.5 - 2026-10-27
- Fix (macOS): clicking the app icon while the window is hidden in the menu bar now brings the window back. Before, only the tray menu did.
- Docs: the README explains how to move an existing command-line instance into the desktop app.

## v0.3.4 - 2026-10-27
- New: the Setup page has a Check-in permission card. It shows, for each Provider, whether check-in works yet (Confirmed after the first successful check-in, Blocked after error 804) and a ready-to-send request for ServiceChannel support with your real Subscriber and Provider IDs. A blocked pair also shows a banner on the Dashboard. It never blocks setup.
- Fix: when an invoice is rejected, the resubmitted invoice now gets its own number (INV-<WO>-2) instead of repeating the first one. Plans already in flight keep working.
- Fix: after an update, the "Update available" banner kept showing the version you had just installed until the next daily check. It now disappears as soon as the running version matches.

## v0.3.3 - 2026-10-27
- No behavior change. Exists to prove the desktop app's Update now button end to end.

## v0.3.2 - 2026-10-27
- Fix: the desktop app could not verify HTTPS certificates, so the update banner never appeared and ServiceChannel calls would have failed. It now ships its own certificate bundle (`certifi`). Desktop users on 0.3.0 or 0.3.1 must reinstall once from the release page; later updates are one click.

## v0.3.1 - 2026-10-27
- Fix: no behavior change. First release delivered through the desktop app's Update now button, to prove the update path.

## v0.3.0 - 2026-10-27
- New: a desktop app. Download a `.dmg` (macOS, Apple silicon) or a Windows installer from the release page and open it. No Python or terminal. It asks Production or SB2 on first run, starts at login, lives in the tray, and updates itself from the Update now banner. The `pip` install and `agent update` still work for source installs.

## v0.2.2 - 2026-10-26
Restart the agent after updating. Nothing is paused and no data changes.
- Dashboard: "This week" swaps the Trade column for Context: the kind of note, whether a proposal or invoice will be approved or rejected, visit number, and whether a check-in is late (plans created from this version on; older plans show no late flag).
- Dashboard: "This week" has a "Hide skipped" filter, on by default, for steps left over when a WO is cancelled. Also, the activity-hours drop-downs sit side by side on the Behavior page.

## v0.2.1 - 2026-10-26
Restart the agent after updating. Nothing is paused and no data changes.
- Dashboard: the "Today" table is now "This week". It lists every step planned for the current calendar week (Monday to Sunday), 10 per page, with a "Hide done" filter. The "API calls in the last hour" tile is gone.
- Behavior: activity start and end are two time drop-downs in one row instead of two sliders. The end is always after the start.
- Roles: each cell is a single drop-down. A cell that held several users before keeps only the first on the next save.
- Settings: the drop-down is no longer full width; each setting is a label with a hint and its control.
- Header: the Running/Paused status sits next to the Pause button.
- Fixed work orders being worked at night and on weekends. Every planned step now falls inside your activity hours on a business day, and the order of steps is unchanged. Plans created before this update keep their old times.
- Locations page: the trades table now shows the trades where your provider is Rank 1 at each location. It always said "Not synced yet" before.

## v0.2.0 - 2026-10-26
Restart the agent after updating. Nothing is paused and no data changes.
- Locations page: load every location the Subscriber can see, search it and add or remove with one click. You no longer type the location id, coordinates or time zone.
- Fixed a log message that repeated every 30 seconds (`update loop error: TypeError`). It was harmless but filled the log.

## v0.1.0 - 2026-10-26
First release. Runs on macOS, Windows and Linux (checked in CI). Restart is needed to run it; nothing is paused. There is no older version to migrate from.

- Work order lifecycle engine: create from the dashboard issue list, notes, check-in and check-out, proposals, review, invoice and approval, all from a saved plan per work order.
- Rank 1 contract check, so work orders are created only for trades our provider connections hold.
- Console: Dashboard, Behavior, Locations, Connections, Roles, Audit log, Errors, Cleanup, Settings, and a setup checklist.
- Sleep and shutdown gap handling, Start at login, launcher with icon, SB2 test instance, update banner and `agent update`.
- Work order creation checks that the location's dashboard can resolve the issue before creating it, so no failed creates or VOID shells.
- Cleanup cancels work orders as COMPLETED/CANCELED. Audit log has a failures-only filter and Errors links to it.
- Check-in and check-out errors name the missing Subscriber/Provider permission. README lists it as a prerequisite.
- Review step sets the WO to COMPLETED/CONFIRMED. Invoice id is read from the API response key `Id`. Verified end to end on SB2.
- Connections added after the agent starts are picked up without a restart.
- One failing loop (step, update check, creator) is logged and no longer stops the agent.
- Invoice reject is verified on SB2 (204, invoice Status REJECTED).
- Proposals work end to end on SB2: provider creates, subscriber links and approves, then check-in, invoice and approval. A handler bug now fails its step instead of retrying forever.
- API request timeout is 90 s (the dashboard issue list is 145 KB and timed out at 30 s).
- Fixed a planner bug: after a rejected proposal, a late revised-proposal decision could schedule check-out before check-in. The visit now moves to the next business day. Proposal reject and the revised-proposal path are verified on SB2.
- Proposal numbers include the step number, so a revised proposal on the same WO no longer hits 'This proposal number already exists'.
- Proposal and invoice decisions read the live status first, so a decision the user already made is respected and a rejected proposal gets a revised one instead of stalling or being overturned (first part of B-39).
- A work order the user cancelled ends its plan quietly, a WO the user completed skips the field steps, and a check-in the user already did counts as done (finishes B-39 for now).
- Command line: `agent get`, `agent set`, `agent plan` and `agent step` to read and change settings and plans. Changes are logged.

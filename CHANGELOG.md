# Changelog

## Unreleased

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

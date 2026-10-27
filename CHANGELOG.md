# Changelog

## Unreleased
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

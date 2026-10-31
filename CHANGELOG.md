# Changelog

## Unreleased

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

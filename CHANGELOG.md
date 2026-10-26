# Changelog

## Unreleased
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

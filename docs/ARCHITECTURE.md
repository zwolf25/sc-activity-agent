# Architecture

How the SC Activity Agent works and why it is built this way. Update this file with every change that alters a decision below.

## What it is for
It creates believable ServiceChannel activity for demos, testing and training. Believable means two things. Every action goes through the API as the right kind of user (Subscriber or Provider), so the audit trail looks like real work. And each work order follows a full lifecycle at human pace, with notes that fit the situation.

## Shape of the system
One Python process runs two things: an engine loop and a localhost web console. Everything it knows is in one SQLite file per instance. The desktop app wraps that same process; see "Desktop app" below.

```
 console (FastAPI + Jinja)  --reads/writes-->  SQLite (agent.db)  <--reads/writes--  engine loop
                                                                                       |-- Creator: makes new WOs
                                                                                       |-- Engine: runs due plan steps
                                                                                       '-- ScApp: OAuth, rate limit, audit log
```

| Module | Job |
|---|---|
| `store.py` | SQLite schema, encrypted secrets, settings, versioned migrations |
| `client.py` | OAuth password grant per user, token cache, rate limiter, audit log, pause guard |
| `planner.py` | Builds the whole plan for one WO, with times, before the WO exists |
| `engine.py` | Runs due steps in order, retries with backoff, handles pauses and sleep gaps |
| `handlers.py` | One executor per step kind; picks the mapped user and calls the API |
| `creator.py` | Rolls daily WO counts, picks issues, creates WOs, saves their plans |
| `generator.py` | Pure helpers: issue flattening, Rank 1 trades, picking, payloads |
| `content.py` | Note templates keyed by role and situation |
| `status.py` | Dashboard counts, the This week table, step context text |
| `web/` | The console (routes in `app.py`, Jinja templates, one stylesheet) |
| `autostart.py`, `launcher.py`, `cli.py` | Start at login, launcher, commands (source installs; the desktop app does its own login start) |
| `update.py` | Daily release check, the pending-update banner, `agent update` for source installs |
| `welcome.py` | First-run environment choice in the desktop app |
| `src-tauri/` | Desktop shell (Tauri v2, Rust): window, tray, sidecar control, updater, login start |
| `packaging/` | `sidecar.py` entry point and `build_sidecar.sh` (PyInstaller) |
| `desktop/` | The loading page the window shows until the agent is ready |
| `.github/workflows/` | `ci.yml` tests, `release.yml` builds and attaches the release files, `desktop-check.yml` builds the installers unsigned on every change to desktop code |

### Desktop app (since 0.3.0)
The desktop app is a second way to run the same agent, for people without Python. Two programs ship together. `src-tauri/` is a small Tauri shell (Rust). `packaging/build_sidecar.sh` freezes the Python agent with PyInstaller into one executable, `agent-core`, which Tauri bundles next to its own binary.

The shell starts `agent-core --data-dir <app data folder> run` with `SC_AGENT_PACKAGED=1`, waits for the agent to write its port to `<data folder>/port`, then points its window at `http://127.0.0.1:<port>/`. Closing the window hides it; the tray keeps the agent running. Quit asks the agent to stop with `POST /shutdown` (the frozen program is two processes, a PyInstaller loader and Python, so killing the loader would leave the port taken), then kills it if it does not stop in 5 s.

The app's data folder is the OS app-data folder for the bundle id `com.zackwolf.sc-activity-agent` (macOS `~/Library/Application Support/`, Windows `%APPDATA%`). It holds `agent.db`, `secret.key`, `port`, `agent.log`, `first-run-done` and the update backups. Each copy of the app is one instance with one locked environment, like a source install; for the other environment a person uses a source install or a second data folder.

`PACKAGED` mode changes four things: the agent picks the first free port from 8080 and records it; a first-run welcome page (`welcome.py`) asks Production or SB2 and locks the choice, as `agent init` does; `/shutdown` and `/update/prepare` exist; the Settings login switch is hidden, because the tray menu owns Start at login (the Tauri autostart plugin; the first launch turns it on, as the Hub does). The tray also has Open console and Quit. One launch at a time is enforced with the single-instance plugin: opening the app again shows the existing window.

On an update the shell stops the old agent through `/shutdown`, and on every start it replaces a stale agent still holding the port. The welcome page only moves on by itself when its own button was clicked in the window; if the environment was set another way, relaunch the app.

Updates use the Tauri updater with the Hub's design: `latest.json` on the latest GitHub Release, signed with a minisign key whose public half is in `tauri.conf.json` and whose private half is a repo secret. The console's Update now button calls `/update/prepare` (pause, copy the database, set `resume_after_update`), runs the updater, calls `/shutdown`, then relaunches. The new version resumes the agent on start only if the update paused it. A page served from `127.0.0.1` can call the updater because `capabilities/default.json` lists that origin as remote. The banner comes from the agent's own daily check of GitHub Releases (`update.pending` hides a cached release once the running version has caught up), so a new release can take up to a day to show; the updater itself looks at `latest.json`.

**Release pipeline.** Publishing a GitHub Release runs `release.yml`: the Python wheel and sdist on Linux, and on macOS and Windows the sidecar build, then `tauri-action`, which attaches the `.dmg`, the Windows `.exe` and `.msi`, their `.sig` files, the updater tarball and `latest.json`. The version lives in four files (`__init__.py`, `tauri.conf.json`, `package.json`, `Cargo.toml`) and a test fails if they differ. Secrets: `TAURI_SIGNING_PRIVATE_KEY` (empty password, so no password secret). A tag and Release cannot be redone, so run `desktop-check.yml` before tagging.

TLS: the frozen Python has no system CA bundle, so `client.SSL_CONTEXT` verifies against `certifi` for both the ServiceChannel calls and the update check. This was found when the 0.3.0 app never showed the update banner.

Why a shell and not PyInstaller alone: replacing a running executable on Windows is the hard part of an updater, and Tauri already solves it. The macOS sidecar needs the `disable-library-validation` entitlement (`entitlements.plist`): Tauri re-signs it ad hoc, and macOS then refuses to load the Python framework PyInstaller unpacks.

Not done on purpose: Apple notarization and Windows code signing (cost; same choice as the Hub), an Intel Mac build (`macos-latest` runners are Apple silicon), Linux. The update cycle ran for real on macOS arm64 (0.3.2 to 0.3.3 through the Update now button: pause, backup, install, relaunch, resume). The Windows installer and updater have only been built on CI, not run on a Windows machine. A browser-downloaded Mac app also meets Gatekeeper (right-click Open), which was not part of the local test.

## Decisions and the reasons

**Two instances, no environment switch.** Production and SB2 each get their own data folder, database, key and port. The environment is chosen at `init` and locked. A switch would risk pointing a running Production plan at the sandbox, or the reverse. Integration apps are registered per environment anyway, so nothing could be shared.

**A saved plan per work order.** `planner.build_plan` rolls every outcome once (visits, late arrival, proposal, rejections) and stores the timed steps. The engine only executes them. This makes the agent restart-safe, makes behavior inspectable, and lets sleep-gap handling re-time steps without re-rolling.

**Subscriber and Provider act separately.** `handlers.py` takes the user for each action from the Roles table (per-location override, then the default). Subscriber steps use Subscriber users, Provider steps use Provider users.

**Only trades where we are Rank 1.** SC assigns a new WO to the Rank 1 provider for that trade and location. If another provider holds Rank 1, SC accepts the WO without error and assigns it to them, and the agent could not move it forward. So `creator.our_trades` checks Rank 1 through the rank endpoints (cached for a day) and never creates other trades.

**Never retry a failed create.** A rejected create leaves a VOID shell WO that the API cannot remove. The creator drops the slot on failure and records the error. Steps for existing WOs do retry, with backoff.

**Check that an issue resolves before creating it.** `POST /workorders` looks the issue up on the location's own dashboard, not on the `IssueListHeaderId` we send. Dashboard 3151 holds many issues that the location's dashboard lacks, and creating one fails with "Cannot find issue choice" and leaves a permanent VOID shell. `GET /issuelist/issuechoice` without `setupId` does the same lookup read-only, so `creator._resolves` calls it first (400 means skip, cached) and redraws up to 8 times. The `setupId` form is not a valid check, because it validates against the named dashboard and passed for every failing issue.

**Check-in needs a pair-level permission.** ServiceChannel enables XML or GPS check-in/out per Subscriber and Provider pair, not per user. Without it the API returns 403 (804). The handler turns that into an error that names the permission. A pre-flight check is not possible without a write, so the first check-in is the test. The Setup page reads the audit log: a pair is Confirmed after a successful `universalCheckIn` by one of its users, Blocked when the latest one returned 403, and otherwise not confirmed yet. It is a card, not a setup step, because the first check-in can be days away and the setup gate would trap new users on the Setup page.

**Cancel is COMPLETED/CANCELED.** The API cannot set VOID. `handlers.cancel_wo` sets that status as the Subscriber and skips the plan's remaining steps. The Cleanup page uses it. The API rejects VOID with error 904 for any value.

**Audit log and Errors answer different questions.** Audit is every API call (what happened). Errors is the queue of failed steps and creates with Retry and Skip (what needs a person). The Audit log has a failures-only filter, and Errors links into it by WO.

**NTE and category come from the issue list.** The dashboard issue list is the source of truth for trade, category, priority and NTE, so they are not settings. The dashboard is a setting on the Subscriber connection because dashboards belong to users in ServiceChannel, not to locations. The agent reads the chosen dashboard explicitly. `storedashboards/current` follows whichever dashboard the token user last used, which is not stable.

**No LLM at runtime.** Notes come from templates filled with WO details and seeded phrase variation. This costs nothing per run and gives the same behavior every time.

**Pause is the only control.** There is no kill switch or dry run. Pause blocks every write at the client, so no code path can skip it. Resuming applies a gap policy to the overdue steps.

**Sleep gaps.** The engine records a heartbeat each tick. A gap over ten minutes is recorded and the remaining steps of affected WOs shift forward by the gap, snapped to activity hours, so spacing and order survive and check-out stays after check-in on the same day. The Dashboard shows the gap so it can be re-resolved.

**Updates are opt-in.** The agent checks GitHub Releases daily and shows a banner; nothing installs by itself. Source installs run `agent update`: pause, back up the database, `pip install` the tag, let the new code migrate the schema, resume, and restore the backup if the new version fails to start. The desktop app does the same steps with the Tauri updater (see above) and treats its own sidecar and shell as one unit, so they always update together.

**Localhost only, secrets encrypted.** The console binds to 127.0.0.1 with no login. Secrets are Fernet-encrypted in SQLite with a key file in the data folder.

## Data model
`connections` and `users` hold integration apps and their users. `roles` maps actions to users per location (the Roles page offers one user per cell as a drop-down; the `pick` column still allows a random choice among several). `locations` describes where the agent works. `work_orders` and `steps` hold each WO and its plan. `api_log` is the audit trail. `settings` holds everything else as JSON.

## Known limits
- The invoice reject-then-resubmit path (B-37) is unit-tested but has not run live: no SB2 WO has rolled the 5% reject branch yet. The invoice number includes a per-WO counter so the resubmission is not a duplicate.
- `docs/api-notes.md` lists what is verified on SB2 and in Production. Production check-in and invoices were still untested at the time of writing.
- Locations come from a list the app loads from the Subscriber (`GET /odata/locations`, paged 50 at a time, cached in the `locations_cache` setting). The user adds or removes from it, so nobody types ids; a typed Prod id that differs from SB2 would break the contract check and every create. Verified on SB2: 50 locations, response wrapped in `value`, paging stops on an empty page.
- **No import tool; moving an instance is a folder copy.** The desktop app starts empty. To adopt an existing instance, stop it, copy its data folder (`agent.db`, `secret.key`) into the app's data folder, and start the app. The environment and port live in the DB, so the welcome page is skipped and the app reuses the port once the old process has released it. Done once for Prod on 2026-10-27 (see CHANGELOG); the old login item must be removed so two agents never act on the same plans.
- **Step failures:** the engine fails any step whose handler raises, not only API errors, so a handler bug cannot loop on one step forever. Each loop in `agent run` (steps, update check, creator) also catches its own errors so one failure never stops the others.
- **Proposals:** the Provider creates the proposal (it has no WO field), and the Subscriber links it with assignWO before approving, because assignWO is Subscriber-only.
- **The user may act first:** `proposal_decide` and `invoice_decide` read the live status before acting. If the user already did what the plan wanted, the step is done and the plan continues. If the user rejected a proposal the plan meant to approve, the plan adds a revised proposal and decision (at most 3 times, then the step fails for the Errors page). A decision the user already made is never overturned, because the API allows an approve after a reject. Other steps do not yet check live state (B-39).
- **One command surface for changes:** settings and plan edits (`get`, `set`, `plan`, `step`) go through the CLI and the same SQLite store the console uses, and each change is logged in the `changes` setting. A person, the console or an assistant acting for the user all use it, so nobody edits the database by hand. The handlers also stop at a WO the user cancelled or completed (`guarded` in `handlers.py`).
- The `contracts` table is unused. Rank 1 trades live in the `rank1` setting (written by the creator, cached a day), and the Locations page reads them from there. Drop the table with a migration when convenient.
- **Every planned step is fitted to the activity window.** The planner draws times by adding random offsets to the creation time, so notes, review and invoices used to land at night and on weekends. `planner._fit` moves any step outside the window to the start of the next business day and keeps the order, spreading consecutive moved steps a few minutes apart. Moving by time-of-day was tried first and failed: evening steps landed late in the afternoon and pushed the next morning's check-in past closing. Plans already saved keep their old times; re-time them by hand (`agent step <id> due ...`) if it matters.

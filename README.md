# SC Activity Agent

Generates realistic ServiceChannel activity through the public API: work orders, proposals and invoices, with Subscriber actions done as Subscribers and Provider actions done as Providers, so the audit trail reads like real work.

You run it on your own machine, connect your own integration apps, and choose your own locations. It creates work orders only where one of your provider connections holds Rank 1 for the trade, then walks each work order from creation to a paid invoice.

## Prerequisites

- One Subscriber integration app and one Provider integration app per environment. Clients do not cross environments.
- **Check-in/out permission for each Subscriber and Provider pair.** ServiceChannel must enable XML check-in/out (between that Subscriber and Provider) or GPS check-in/out (for the Subscriber). Without it, check-in returns 403 error 804 and the Errors page says so. Repeat for every new pair. The Setup page shows each pair's status and the request text to send.
- **Provider billing exemption.** If the first invoice returns error 1145 (outstanding balance), a Super Admin must open Fixxbook > CSA Billing, mark the provider "paid by check" and extend its grace period. Demo providers hit this.

A ServiceChannel support team member sets up the check-in/out permission, so ask early. Request text: "Please link Subscriber ID <subscriber id> with Provider ID <provider id> for API work and enable XML check-in/out (and GPS check-in/out if a radius is wanted) for this pair."

## Quick start

**Desktop app (recommended).** Download the app for your system from the [latest release](https://github.com/zwolf25/sc-activity-agent/releases/latest): the `.dmg` for macOS (Apple silicon) or the `-setup.exe` for Windows. Open it. There is no Python and no terminal.

- macOS: drag the app to Applications. The app is not notarized by Apple, so the first launch needs right-click, then Open (or `xattr -cr "/Applications/SC Activity Agent.app"` once).
- Windows: run the installer. SmartScreen may warn because the installer is not signed: choose More info, then Run anyway.

On first launch the app asks whether it works in **Production** or **SB2** (the choice is locked for that copy), turns on Start at login, and opens the setup checklist. It keeps running from the tray (menu bar on macOS) when you close the window. **Quit** in the tray menu stops the agent. When a new version is out, a banner offers Update now: the app pauses, installs and restarts, and your data is untouched.

**Install with Python (no desktop app).** You need Python 3.11 or newer; the installer checks and tells you how to get it if it is missing.

- macOS or Linux: `curl -fsSL https://raw.githubusercontent.com/zwolf25/sc-activity-agent/main/install.sh | sh` (add `-s sb2` after `sh` for an SB2 instance; the default is Production)
- Windows (PowerShell): `irm https://raw.githubusercontent.com/zwolf25/sc-activity-agent/main/install.ps1 | iex`

It creates a launcher named SC Activity Agent (in `~/Applications` on macOS, the Start menu on Windows). Double-click it: it starts the agent if needed and opens the console in your browser. The agent keeps running when you close the tab. Turn on Start at login in Settings so it runs after a restart. Update from Settings > Check for updates, or with `agent update`. An update pauses the agent, saves a backup, installs the release and restarts; if the new version does not start, the old version and your data come back.

**By hand (developers).** `pip install "https://github.com/zwolf25/sc-activity-agent/archive/refs/tags/<tag>.zip"`, then `agent init --env sb2` (or `prod`; locked per data folder), then `agent install-app` or `agent run`.

**Setup.** The console walks you through:

1. Add one **Subscriber** connection (an integration app: client ID and secret) and a Subscriber user.
2. Enter the Subscriber ID, load your dashboards and choose the issue list dashboard. The dashboard must be assigned to that Subscriber user in ServiceChannel.
3. Add one **Provider** connection per provider you play, with its Provider ID and users.
4. Add your locations: on the Locations page click Load, search the list, tick several rows (or paste store IDs as a list or CSV) and click Add selected. Ids, coordinates and time zone come from ServiceChannel. The Locations page also shows the trades the agent can create, the trades it skips because another provider is Rank 1, and a Refresh now button that re-reads Rank 1 straight away (otherwise it refreshes daily).
5. On Connections, tick **Can do** for each user. The first user on a connection starts with every action; later users start empty. Each action needs at least one user, and every Provider needs a user who can check in. Add several Provider users to look like a real crew: the agent picks randomly among the users who can do an action and belong to the WO's provider, and a check-out is done by the tech who checked in.
6. Review the **Behavior** settings.

**Checklists.** If your Subscriber has checklists set up in ServiceChannel for a trade and location, Settings > "Answer checklists at check-out" makes the provider answer them when it checks out, with a before-and-after photo where a picture is asked for. It is off by default, and it does nothing where no checklist exists. The agent cannot create checklists; set them up in ServiceChannel.

**Photos.** Two Behavior sliders, both 0 by default: "Before photo on new WOs %" and "After photo on closing note %". The photos come from a library that ships with the app, matched to the WO's trade, and a WO's before and after photos come from the same scene.

Work order creation only runs while the agent runs. If the machine sleeps, the agent notices the gap and moves the remaining steps forward. Settings chooses how. In the desktop app, Start at login is in the tray menu. In the source install it is on the Settings page. Neither can wake a sleeping machine.

## Production and test

Production and SB2 are two separate instances with their own data, keys and ports (8080 and 8081). Nothing switches between them. On a Production instance, Connections has an **Open SB2 test instance** button that starts the SB2 copy. In the desktop app the SB2 copy lives in an `sb2` folder inside the app's data folder, starts only when you ask, and is switched with the tray menu (Production console, SB2 console). One install, one update and one Quit cover both. Integration apps are registered per environment, so the SB2 copy needs SB2 apps.

### Moving a command-line instance into the desktop app

1. Pause the instance and stop it (and remove its login item, so only one agent acts on the plans).
2. Install the app, quit it before the welcome page, and copy `agent.db` and `secret.key` from the old data folder into the app's data folder (macOS: `~/Library/Application Support/com.zackwolf.sc-activity-agent`, Windows: `%APPDATA%\com.zackwolf.sc-activity-agent`). Copy both files; the key decrypts the saved credentials.
3. Start the app. It skips the welcome page, keeps the saved environment and port, and resumes from the saved plans.

## Telegram alerts (optional)

Settings > Telegram alerts walks you through it, with a check at each step:

1. In Telegram, message @BotFather, send `/newbot`, and copy the token.
2. Paste the token in Settings. The app shows the bot's name.
3. Open the bot in Telegram, press **Start**, then click **Find my chat** in Settings.
4. Click **Send test message**, then tick the alerts you want and **Send alerts**.

Alerts cover a step that failed after its retries, check-in blocked (error 804), a connection or login failure, and the agent coming back after being offline over an hour. A message names the WO, the location, the step and the error text, so that text goes to Telegram. Nothing else is sent. The token is stored encrypted. The same alert is not repeated within 6 hours, and at most 10 go out per hour.

**Action buttons** (optional) add Retry, Skip step, Pause agent and Cancel WO to an alert. The agent reads taps by asking Telegram (outbound only; no open port). Only the chat saved in Settings can tap. Cancel WO asks for a yes first. Each tap is logged in the `changes` setting.

Each instance has its own bot. Set up Production on its Settings page. To get SB2 alerts, set up a second bot on the SB2 instance's Settings page; messages start with [PROD] or [SB2]. Buttons need one bot per instance, because one bot's taps can be read by only one program.

## Commands

| Command | What it does |
|---|---|
| `agent init --env prod\|sb2` | Create an instance and lock its environment |
| `agent run` | Run the engine and the console |
| `agent open` | Start the agent if needed and open the console |
| `agent install-app` | Create a launcher with an icon |
| `agent login on\|off\|status` | Start at login |
| `agent pause` / `agent resume` | Block or allow writes |
| `agent status` | Counts and state |
| `agent update` | Install the latest GitHub Release |
| `agent get [key]` / `agent set key value` | Show or change a setting, for example `agent set behavior.proposal_rate 10`. A running agent uses it on the next tick |
| `agent plan <WO id>` | List a work order's steps |
| `agent step <id> retry\|skip\|due +2h` | Retry, skip or reschedule one step |

Every `set` and `step` change is recorded in the `changes` setting (`agent get changes`). These commands are also how an AI assistant such as Claude Code changes settings or plans for you: ask it in plain words, and it runs them.

Use `--data-dir` (or `SC_AGENT_DATA`) to choose where an instance keeps its data. The default is `~/.sc-activity-agent`.

## Safety

- The console listens on 127.0.0.1 only.
- Client secrets and passwords are encrypted in the instance's database. The key stays in the data folder.
- The agent never retries a failed work order create, because ServiceChannel leaves a VOID shell behind.
- Before each create the agent checks that the location's dashboard can resolve the issue, and redraws if not.
- Pause blocks every write.
- The API cannot set VOID. Cleanup cancels a work order as Completed / Canceled.
- **Clean up old work orders.** Cleanup page (or `agent cleanup --days 14`, add `--run` to cancel): lists open work orders at your enabled locations that the agent did not create and that have had no activity for N days. Cancel runs only after you preview and confirm, and skips any work order with the label `do not touch` (change the name on the page; labels are set in ServiceChannel, not by the agent). The list is picked for you. **Clean up now** (or `agent cleanup --run --auto`) skips the review, and the weekday setting (own Save button and confirm box; first run a day later) does it daily on its own, 100 work orders at most per day. "Finish ours" (not offered on Production) gives work orders held by your own providers a short plan and cancels the rest.

## More

- How it works and why: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- What is planned: [docs/BACKLOG.md](docs/BACKLOG.md)
- API findings: [docs/api-notes.md](docs/api-notes.md)
- Changes: [CHANGELOG.md](CHANGELOG.md)

Develop with `pip install -e ".[dev]"` and `pytest`.

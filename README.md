# SC Activity Agent

Generates realistic ServiceChannel activity through the public API: work orders, proposals and invoices, with Subscriber actions done as Subscribers and Provider actions done as Providers, so the audit trail reads like real work.

You run it on your own machine, connect your own integration apps, and choose your own locations. It creates work orders only where one of your provider connections holds Rank 1 for the trade, then walks each work order from creation to an approved invoice.

## Prerequisites

- One Subscriber integration app and one Provider integration app per environment. Clients do not cross environments.
- **Check-in/out permission for each Subscriber and Provider pair.** ServiceChannel must enable XML check-in/out (between that Subscriber and Provider) or GPS check-in/out (for the Subscriber). Without it, check-in returns 403 error 804 and the Errors page says so. Repeat for every new pair.
- **Provider billing exemption.** If the first invoice returns error 1145 (outstanding balance), a Super Admin must open Fixxbook > CSA Billing, mark the provider "paid by check" and extend its grace period. Demo providers hit this.

A ServiceChannel support team member sets up the check-in/out permission, so ask early. Request text: "Please link Subscriber ID <subscriber id> with Provider ID <provider id> for API work and enable XML check-in/out (and GPS check-in/out if a radius is wanted) for this pair."

## Quick start

You need Python 3.11 or newer.

1. Install: `pip install "git+https://github.com/zwolf25/sc-activity-agent"`
2. Create an instance. Use `prod` for ServiceChannel Production or `sb2` for the sandbox. The choice is locked for that data folder.
   `agent init --env sb2`
3. Start it and open the console: `agent install-app` once, then double-click the launcher. Or run `agent run` and open the address it prints.
4. The console walks you through setup:
   1. Add one **Subscriber** connection (an integration app: client ID and secret) and a Subscriber user.
   2. Enter the Subscriber ID, load your dashboards and choose the issue list dashboard. The dashboard must be assigned to that Subscriber user in ServiceChannel.
   3. Add one **Provider** connection per provider you play, with its Provider ID and users.
   4. Add your locations: on the Locations page click Load, search the list and click Add. Ids, coordinates and time zone come from ServiceChannel.
   5. Map each action to a user on the **Roles** page.
   6. Review the **Behavior** sliders.
5. Optional: **Settings** has a Start at login switch, so the agent keeps running after a restart. It cannot wake a sleeping machine.

Work order creation only runs while the agent runs. If the machine sleeps, the agent notices the gap and moves the remaining steps forward. Settings chooses how.

## Production and test

Production and SB2 are two separate instances with their own data, keys and ports (8080 and 8081). Nothing switches between them. On a Production instance, Connections has an **Open SB2 test instance** button that starts the SB2 copy. Integration apps are registered per environment, so the SB2 copy needs SB2 apps.

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

## More

- How it works and why: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- What is planned: [docs/BACKLOG.md](docs/BACKLOG.md)
- API findings: [docs/api-notes.md](docs/api-notes.md)
- Changes: [CHANGELOG.md](CHANGELOG.md)

Develop with `pip install -e ".[dev]"` and `pytest`.

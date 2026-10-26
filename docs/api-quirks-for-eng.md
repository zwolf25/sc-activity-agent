# ServiceChannel API: issues and quirks found while building the SC Activity Agent

Written for: ServiceChannel engineering, to review and triage.

We built an agent that creates and moves work orders, proposals and invoices through the v3 API as a Subscriber and as a Provider. This list is what surprised us. Everything below was reproduced on SB2 between 2026-10-23 and 2026-10-26 (Subscriber 2014917582, Provider SydeTech 2000078685, location HQ-NYC 2006964438). Items are ordered by how much they cost us. Each has what happens, what we expected, and a suggested fix where we have one.

## High impact

### 1. `POST /workorders` ignores `IssueListHeaderId`, `AreaId` and `ExtendedAreaName`
- **What happens:** the issue is looked up on the location's own issue-list dashboard, not on the dashboard we send. An issue that exists on dashboard 3151 but not on the location's dashboard fails with 502 `Cannot find issue choice for AreaName = ''`.
- **Expected:** the dashboard and area in the body decide the lookup, or the docs say they are ignored.
- **Impact:** most creates failed until we found this. Examples that failed: Windows/Glass Repairs > Tinting, Doors > Exterior Door, Baler.
- **Suggestion:** document the lookup rule, or honor `IssueListHeaderId`.

### 2. A failed create leaves a VOID shell WO that cannot be removed
- **What happens:** every rejected `POST /workorders` (400 or 502) still creates a WO with status VOID / CREATING. We have more than 7 of them on SB2. `PUT /workorders/{id}/status` with `Primary: VOID` returns 904 `Invalid WorkOrder status` for any Extended value, and `GET /workorders/statuses` does not list VOID.
- **Expected:** a failed create leaves nothing behind, or the shell can be cancelled or deleted.
- **Impact:** test and demo locations fill with unremovable junk, and the agent can never safely retry a create.
- **Suggestion:** create the WO only after validation passes, or let a Subscriber delete a VOID/CREATING WO.

### 3. There is no clean way to check an issue before creating the WO
- **What happens:** `GET /issuelist/issuechoice?problemType=&equipmentType=&problemCode=&locationId=` without `setupId` runs the same lookup as the create and returns 400 for exactly the failing issues. With `setupId=3151` it returns 200 for the same issues.
- **Impact:** the obvious pre-check (pass the dashboard) gives a false pass. We only found the working form by comparing both against real creates.
- **Suggestion:** a documented validate-only endpoint that mirrors `POST /workorders`.

### 4. Check-in returns 403 error 804 `User has no permissions` when the real cause is a pair-level setting
- **What happens:** `POST /workorders/{id}/universalCheckIn` fails with 804 for a Provider user that has every user permission. The cause is that XML or GPS check-in/out is not enabled for that Subscriber/Provider pair. Only ServiceChannel support can enable it. Changing user permissions did not help (retested with a fresh token).
- **Impact:** we lost time on user permissions. Every new Subscriber/Provider pair needs a support ticket, and an integrator has no way to see the status.
- **Suggestion:** return a distinct error naming the pair-level setting, and expose the pair's check-in status (for example in `validateCheckIn`).

### 5. Invoice create fails with 1145 for providers with an outstanding balance, and the fix is outside the API
- **What happens:** `POST /invoices` returns 400 error 1145 (`outstanding balance ... update your Payment Method in Fixxbook`). The body was correct. It cleared only after a Super Admin marked the provider "paid by check" and extended the grace period in Fixxbook CSA Billing.
- **Impact:** every demo or test provider can hit this. The message points at a payment method, not at the account state.
- **Related:** `CanCreateInvoice` stays `false` on the WO after it is CONFIRMED, yet the invoice create succeeds once the block is cleared. The flag does not match behavior.

## Medium impact

### 6. Proposal create is under-documented
- Swagger shows the `CreateProposal` body as `{}`. Everything we know came from the endpoint's description text.
- `GET /proposals/CheckProposalCreation` is meant to supply the request model, but it returns a string in single quotes with inline comments (`''/*each,sq. ft,feet,linear feet*/`). It is not valid JSON.
- The example in the `CreateProposal` description uses labor line names such as `Regular Service Hours`. The call requires `Regular Hours`, `Overtime Hours`, `Double Time / Holiday Hours`, `Helper Regular Hours`, `Helper Overtime Hours`, `Helper Double Time / Holiday Hours` and `Subcontractor Labor`. Using the example names returns 503, and the message lists the missing names.
- The response is a bare integer (the proposal id), not an object.
- A repeated `proposalNumber` returns 503 `This proposal number already exists.` The number must be unique across the account, not just per WO.

### 7. A proposal has no work order field, and only the Subscriber can link one
- `CreateProposal` takes no WO id. The link is `PUT /proposals/{id}/assignWO` with a bare integer body, Subscriber only (204).
- **Impact:** a Provider cannot create a proposal for a WO in one step. The two sides have to coordinate.

### 8. Ambiguous routes return 500
`Multiple actions were found that match the request` (500) on:
- `GET /proposals/{id}`
- `GET /odata/locations({id})/providers`
- `GET /api/subscribers/{sub}/storedashboards/{id}/issuelist/areas/{areaId}/items` without the exact query shape

We read proposals through `GET /odata/proposals?$filter=Id eq {id}` instead.

### 9. Create body: `Status` and the NTE warning
- Any `Status` value in the create body returns 503 `Invalid work order status`. Omitting it works (status OPEN).
- A successful create returns `Warning: "Failed to verify NTE"` even when the NTE matches the issue-list NTE.

### 10. `storedashboards/current` follows the token user, not the location
- `current` returns the dashboard of the calling user (the test user's was a hotel demo list). The create uses the location's dashboard. The two can disagree silently, which feeds into item 1.

### 11. Error messages that hide the cause
- 502 `Cannot find issue choice for AreaName = ''` is returned for a bad issue, a bad area and a bad dashboard alike, and the area name is blank even when `AreaId` was sent.
- A create for a trade where the Subscriber has no contract with us does not fail: it assigns to whichever provider is Rank 1 (we saw Brad's Demo Co). That is reasonable, but nothing in the response says so. The true "no contract at all" error never appeared in our tests.

### 12. A rejected proposal can be approved again, and an approved one cannot be linked
- `PUT /proposals/{id}/approve` on a proposal that was already rejected returns 204 and flips it to Approved. `PUT /proposals/{id}/assignWO` on an already approved proposal returns 400 `Proposal already approved`.
- **Expected:** the same guard on both calls, or a clear status error. As it stands, an integration that acts on a stale view can overturn a user's rejection without any warning.

## Minor

- **Mixed key casing:** WO create returns `{"id": ...}`, invoice create returns `{"Id": ...}`.
- **Provider shape:** `GET /workorders/{id}` nests the provider as `Provider.Id`. There is no `ProviderId` key.
- **`validateCheckIn` without coordinates:** missing `latitude`/`longitude` returns `IsOutsideGeolocation: true` instead of a 400. A WO scheduled days out reports `IsOutsideAcceptableTimeframe`.
- **Review has no endpoint:** the Subscriber confirms completed work with `PUT /workorders/{id}/status` set to COMPLETED / CONFIRMED. We found it by trial.
- **Cancel after approval:** cancelling (COMPLETED / CANCELED) a WO with an approved invoice returns 400.
- **`GET /contracts`:** returns only contract ids. `locationId` returned 503 `Location is not found`, while `locationDbId` works.
- **Rate limits:** the docs say about 20 calls/min. We saw an app limit of 40/min (429 with `Retry-After`).
- **Slow responses:** the full issue list for one dashboard is about 145 KB and exceeded 30 seconds once. SB2 also had a short outage on 2026-10-26 (500s and hangs) that cleared on its own.
- **OAuth password grant:** a bad client id returns a 302, a bad user returns 400. Useful for diagnosis, but undocumented.

## Verified working (no issue)
Accept (`PUT /workorders/{id}/accept`), notes for both roles, `universalCheckIn` / `universalCheckOut` once the pair setting is enabled, invoice create / approve / reject, proposal create / link / approve / reject (a revised proposal on the same WO also works).

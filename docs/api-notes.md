# ServiceChannel API notes (from the spike)

Swagger JSON: `https://developer.servicechannel.com/api/docs?name=ServiceAutomation` (663 paths, v3). Base: SB2 `https://sb2api.servicechannel.com/v3`, token `https://sb2login.servicechannel.com/oauth/token` (password grant, Basic client auth).
Rate limit ~20 calls/min per integration app (429 + Retry-After).

## Verified live on SB2 (Subscriber app, read-only)
- Auth works with the sc-workorders MCP Subscriber app.
- HQ-NYC: `GET /odata/locations?$filter=contains(StoreId,'HQ')` -> Id 2006964438, SubscriberId 2014917582, StoreId HQ-NYC, name Union Square, tz America/New_York.
- Location trades: `GET /odata/locations(2006964438)/trades` -> GENERAL MAINTENANCE 112193, ELECTRICAL 112195, DOORS 112196, HVAC 120881.
- `GET /contracts?locationDbId=&providerId=` returns only `{Contracts:[{Id}]}`. Provider 2000078685 (SydeTech) has 3 contracts at HQ-NYC (matches DOORS, GENERAL MAINTENANCE, HVAC). Ids only, so rank detail needs another call (open).
- `GET /GetPrimaryRankedProviders/{subscriberId}`, `/GetPrimaryRankedProviderTrades/{subscriberId}/{providerId}`, `/GetPrimaryRankedProviderLocations/{subscriberId}/{providerId}/{tradeId}` work and return Rank 1 data (Locations one not yet called).
- `GET /odata/locations(id)/providers` is broken (500, ambiguous route).

## Write endpoints (from Swagger, not yet exercised)
| Step | Role | Call | Key fields |
|---|---|---|---|
| Create WO | Subscriber | `POST /workorders` | ContractInfo{SubscriberId,LocationId,TradeName,[TradeId],[ProviderId]}, Category, CallDate, Description, ProblemCode, Nte, ScheduledDate, Priority, IssueRequestInfo{AreaId}, Status{Primary,Extended}, DispatchSettingsInfo.IsTest |
| Accept WO | Provider | `PUT /workorders/{id}/accept` | Note |
| Note | both | `POST /workorders/{id}/notes` | Note, Visibility, Actor, ActionRequired |
| Check-in | Provider | `POST /workorders/{id}/universalCheckIn` | Latitude*, Longitude*, UserId, TechsCount, CheckInTime, WorkTypeId |
| Check-out | Provider | `POST /workorders/{id}/universalCheckOut` | Latitude*, Longitude*, PrimaryStatus, Resolution, CheckOutTime, UserId |
| Validate | Provider | `GET /workorders/{id}/validateCheckIn`, `validateCheckOut` | pre-check |
| Status | either | `PUT /workorders/{id}/status` | Status{Primary,Extended}, Note |
| Proposal create | Provider | `POST /proposals/CreateProposal` | body schema not in Swagger (open) |
| Proposal decide | Subscriber | `PUT /proposals/{id}/approve` / `reject` | Comment, RejectReasonCodeId; `GET /proposals/RejectionReasons`, `ApprovalReasons` |
| Invoice create | Provider | `POST /invoices` | InvoiceNumber*, WoIdentifier*, InvoiceTotal, InvoiceAmountsDetails, Labors[], Materials[] |
| Invoice decide | Subscriber | `PUT /invoices/{id}/approve?approvalCode&comments&category` / `reject?comments` | `GET /invoices/{subscriberId}/InvoiceRejectionReasons` |
| Issue list | Subscriber | `GET /subscribers/current/storedashboards/current/issuelist/areas`, `.../areas/{areaId}/problemcodes`, `/issuelist/issuechoice` | to find ProblemCode, AreaId, NTE per issue |
| Contracts | either | `GET /contracts` | locationId, locationDbId, providerId, trade, tradeId |

## Open questions for next spike steps
1. How the issue list yields NTE and ProblemCode for a trade (issuechoice).
2. Whether Provider actions need technician (UserId) objects, and lat/long (use the location's coordinates).
3. Proposal create body (Swagger shows `{}`), and the rule that check-in is blocked until a proposal is approved.
4. Does creating a WO without ProviderId auto-assign Rank 1 (expected).
5. Invoice requirements (`/invoices/{subscriberId}/InvoiceRequirements`) and approvalCode/category values.

## Issue list at HQ-NYC on SB2 (probed 2026-10-23)
- Areas: 13. Only BATHROOM and MECHANICAL return problem types, and only `Electrical` / `Lighting`. All other areas are empty.
- 12 issuechoice entries found, all Trade ELECTRICAL. Provider is ranked for DOORS, GENERAL MAINTENANCE, HVAC on SB2, so issue-list WOs would have no contract.
- Open: create a WO without an issue-list choice (free-form Trade/Category/Priority/NTE), or add HVAC/DOORS/GM issues to the SB2 issue list. Needs user decision after SB2 refresh.
- Full-tree crawl is too slow at 15 calls/min. Probe per area instead (`problemtypes` first, skip empty).

## Issue list dashboards (SB2 subscriber 2014917582)
- `GET /v3/api/subscribers/{sub}/issuelist/headers` lists dashboards: 2751, 2752, 3151, 3498, 4448, 5216 (each has `DashboardId`, xlsx `IssueListUrl`).
- Chosen for testing: 3151 "Asset Dashboard 61526.xlsx". Its xlsx has Doors, HVAC, General Maintenance and Electrical.
- `storedashboards/current` for HQ-NYC returns only Electrical/Lighting, so HQ-NYC is probably not assigned to 3151. Unconfirmed.
- Explicit `.../storedashboards/3151/issuelist/fields` works; `areas/{id}/items` returns 500 (ambiguous route).
- Setting planned: per-location "Issue list dashboard" (default `current`).

## Choosing the dashboard explicitly (resolved)
- `storedashboards/current` follows the token user's active dashboard (ProductTeam's is a hotel demo list). Do not use it.
- `GET /v3/api/subscribers/{sub}/storedashboards/{dashboardId}/issuelist` returns the whole issue list in one call. No crawl needed.
- Shape: `ProblemTypes[].Items[].Problems[]` with `Name, Trade, TradeId, Priority, Category.Default, CategoryId, Nte, ApprovalCode`.
- Dashboard 3151 on SB2: HVAC 18, DOORS 21, GENERAL MAINTENANCE 39 problems (also ELECTRICAL 35, REFRIGERATION 52, KITCHEN EQUIPMENT 12). Example HVAC: Heating/Air Conditioning > HVAC RTU > Coil Cleaning, NORMAL, NTE 50, TradeId 120881.
- Setting: dashboard ID per Subscriber connection (dropdown from `/api/subscribers/{sub}/issuelist/headers`), replaces the per-user idea.
- Open: this response has no area. Check what WO create needs for area/location fields.

## First SB2 WO create (2026-10-23, WO 367411660, HQ-NYC, HVAC)
Working `POST /v3/workorders` body (Subscriber token):
`ContractInfo{SubscriberId, LocationId, StoreId, TradeName, TradeId}`, `Category`, `CategoryId`, `Priority`, `Nte`, `CallDate`, `ScheduledDate`, `Description`, `ProblemCode`, `IssueRequestInfo{AreaId, ProblemType, AssetType=item name}`, `IssueListHeaderId` (110058 for dashboard 3151), `DispatchSettingsInfo{IsTest, NotificationDisabled}`, `ApiRequest: true`.
- `IssueListHeaderId` is what selects the issue list; without it error 502 "Cannot find issue choice" (it uses the user's active dashboard).
- Do NOT send `Status`: every value gave 503 "Invalid work order status". Omitted: created 201, status OPEN.
- Response `{"id": ..., "Warning": "Failed to verify NTE"}`. WO NTE = 50 as sent.
- Each failed attempt (400) still leaves a VOID/CREATING shell WO (367411653..659 here). Validate before posting; the agent must not retry blindly.
- AreaId taken from `current` area list (18806 MECHANICAL). Not validated against dashboard 3151.

## Area, no-contract and validation tests (SB2, 2026-10-23)
- DOORS (Doors > Automatic Door > Making loud noise, area 3 SALES FLOOR): 201, WO 367411673.
- Bad AreaId 999999: 502 "Cannot find issue choice" (same text as a bad issue; area is part of the lookup). Leaves a VOID shell.
- ELECTRICAL (Appliance > Refrigerator, area 18806): 502 same text, so the no-contract error was NOT reached; the issue-choice lookup fails first. No-contract error still unobserved.
- Valid items per area: `GET /v3/api/subscribers/{sub}/storedashboards/{id}/issuelist/areas/{areaId}/items?problemType=&locationId=`. Areas 3 and 18806 both return every problem type/item of our 3 trades, so either works for HVAC, DOORS, GENERAL MAINTENANCE.
- Area IDs are global per name (SALES FLOOR=3). The 3151 area names (SALES FLOOR, MACHINE ROOM, FRONT END, ROOFTOP, ...) have no ID lookup from the API; only IDs from the user's `current` list are known. Agent plan: validate (area, problemType, item) via the `items` route, cache, and pick only validated combos.
- Notes endpoint: `/workorders/{workorderId}/notes` (schema not read yet).

## No-contract / foreign-provider test and subscriber notes (SB2)
- ELECTRICAL at HQ-NYC (Electrical > Electrical Panel > Breaker Issues, area 3): 201, WO 367411678, auto-assigned to **Brad's Demo Co (2000056978)**, not our provider. So a trade with no contract for us is not an error when another provider holds Rank 1. The agent MUST filter by Rank 1 = ours before creating, or it leaves WOs it cannot progress.
- True "no valid contract at all" error still unobserved (needs a trade nobody is ranked for).
- Subscriber note: `POST /v3/workorders/{id}/notes` body `{"Note", "NotifyFollowers": false, "DoNotSendEmail": true}` -> 201 `{id, documentId}`. `GET .../notes` returns `Notes[]` with `CreatedBy`, `NoteData`.
- SC adds a system note on dispatch: "Service Request has been dispatched to <provider> ... with USD <nte> NTE."
- `GET /v3/contracts?locationId=...&trade=...` returned 503 "Location is not found"; use the params that worked in the earlier contracts spike (`locationDbId`).

## Rank 1 eligibility (verified)
`GET /GetPrimaryRankedProviderTrades/{sub}/{provider}` then `GET /GetPrimaryRankedProviderLocations/{sub}/{provider}/{tradeId}` (list of location ids). HQ-NYC (2006964438) is in DOORS, GENERAL MAINTENANCE and HVAC and not in ELECTRICAL or PLUMBING, matching why the Electrical test WO went to Brad's Demo Co. Implemented as `generator.rank_one_trades`.

## Write endpoint schemas read from Swagger (2026-10-23)
- Proposal approve/reject: `PUT /proposals/{id}/approve|reject` body `{Comment, RejectReasonCodeId, ReasonString, Actor, PinNote}`. Reject reasons: `GET /proposals/RejectionReasons` -> {1 More information required, 2 Change in scope of work, 3 Total Amount (Higher than expected), 4 Materials, 5 Labor, 6 Other, 7 Work no longer needed}.
- Proposal create: `POST /proposals/CreateProposal` body schema is untyped in Swagger. Needs a Provider-side spike. `GET /proposals/ApprovalReasons` needs Trade/TradeId.
- Invoice create: `POST /invoices` body `{InvoiceNumber*, WoIdentifier*, InvoiceDate, InvoiceTotal, InvoiceAmountsDetails{Labor,Material,Travel,Freight,Other}, Labors[], Materials[], ...}`. Requirements: `GET /invoices/{sub}/InvoiceRequirements`.
- Invoice approve: `PUT /invoices/{id}/approve?approvalCode=&comments=&category=` (query params, all required). Reject: `PUT /invoices/{id}/reject?comments=&isNotifyProvider=`. Rejection reasons: `GET /invoices/{sub}/InvoiceRejectionReasons`.
- Provider: `PUT /workorders/{id}/accept {Note}`, `POST .../universalCheckIn {Latitude*, Longitude*, WorkTypeId, UserId, TechsCount, CheckInTime}`, `POST .../universalCheckOut {Latitude*, Longitude*, PrimaryStatus(Completed|WaitingForQuote|PartsOnOrder|Incomplete|InProgress|NoStatusChange), ActionStatus(Complete|Cancel), Resolution, CheckOutTime}`, `POST .../resolution {Resolution}`.
- Subscriber review/complete: no dedicated endpoint; `PUT /workorders/{id}/status {Status{Primary,Extended}, Note}` (valid values unknown; Completed is reached via provider check-out `PrimaryStatus: Completed`).
- Cancel: `PUT /workorders/{id}/status {"Status":{"Primary":"COMPLETED","Extended":"CANCELED"},"Note":...}` returns 200 (verified on SB2, WO 367411678, Subscriber token). VOID is NOT settable through the API: `{Primary:"VOID"}` gives 904 "Invalid WorkOrder status" with any Extended value. `GET /workorders/statuses` lists only OPEN, IN PROGRESS (7 extended), COMPLETED (CANCELED, CONFIRMED, NO CHARGE, ...). VOID appears only on failed-create shells (Primary VOID, Extended CREATING). Zac asked for VOID: needs UI or a different permission, so the agent uses COMPLETED/CANCELED.

## Create fails for many issues: cause found (2026-10-23)
`POST /v3/workorders` returns 502 `Cannot find issue choice for AreaName = ''` for issues that exist on dashboard 3151 but not on the
location's own dashboard (Windows/Glass Repairs > Tinting, Doors > Exterior Door, Baler), and leaves an unremovable VOID shell.
The POST resolves the issue on the location's dashboard and ignores `IssueListHeaderId`/`AreaId`/`ExtendedAreaName`.
`GET /issuelist/issuechoice?problemType=&equipmentType=&problemCode=&locationId=` WITHOUT `setupId` runs the same lookup read-only and
returns 400 for exactly the failing issues. With `setupId=3151` it returns 200 for them, so it is not a valid pre-check. The creator
calls the no-`setupId` form before each create. Verified live: HVAC RTU, Doors > Automatic Door and General Repairs > Sheetrock all
created; WOs 367411794, 799-801 assigned to SydeTech where checked and cancelled via the cleanup path.

## Provider spikes on SB2 (2026-10-26)
Provider app and user (SydeTech, Production app does not exist on SB2; a separate SB2 app was registered) work.
- `PUT /workorders/{id}/accept {Note}` verified: 200, WO becomes IN PROGRESS / DISPATCH CONFIRMED.
- `POST /workorders/{id}/notes` as Provider verified: 201.
- `GET /workorders/{id}/validateCheckIn` needs `latitude`/`longitude` query params, else `IsOutsideGeolocation` is true. A WO scheduled 2 days out reports `IsOutsideAcceptableTimeframe` true.
- `POST .../universalCheckIn` returns 403 error 804 "User has no permissions" for WorkTypeId 1 and 2 even with a valid timeframe and geolocation. Swagger says Repair and Travel work types need a special check-in/out permission on the user. Blocked until the provider user is granted it.
- Check-in permissions are subscriber/provider relationships, not user rights (guide /guides/checkin/before-you-start/): XML check-in/out (enabled between a subscriber and one provider by ServiceChannel after the contractor request form; also allows passing check-in/out dates) and GPS check-in/out (enabled for the whole subscriber by ServiceChannel, sets the GPS radius). A user permission change did not clear the 804 (retested with a fresh token, 2026-10-26).

## Provider lifecycle on SB2 after check-in permission (2026-10-26, WO 367500971)
- `universalCheckIn` {Latitude, Longitude, TechsCount, CheckInTime}: 200 `{MechanicId}`, WO becomes IN PROGRESS / ON SITE. Works once ServiceChannel support enables check-in/out for the Subscriber/Provider pair.
- `universalCheckOut` {Latitude, Longitude, CheckOutTime, PrimaryStatus: Completed, ActionStatus: Complete, Resolution, TechsCount}: 200, WO becomes COMPLETED / PENDING CONFIRMATION. Same MechanicId as the check-in.
- Subscriber review: `PUT /workorders/{id}/status {Status:{Primary:COMPLETED, Extended:CONFIRMED}, Note}` returns 200 (COMPLETED/PENDING CONFIRMATION to COMPLETED/CONFIRMED). The handler's review step must use this, not only a note.
- `POST /invoices` (handler body) returns 400 error 1145: the provider "has an outstanding balance with ServiceChannel... update your Payment Method in Fixxbook". Provider account setup issue, not a body error. Blocks invoice, approve and reject spikes. `CanCreateInvoice` stayed false after CONFIRMED.
- Fixxbook block cleared (2026-10-26): a Super Admin opened Fixxbook CSA Billing, marked the provider "paid by check" and extended the grace period. Needed for every demo provider that hits error 1145. Added to README Prerequisites.
- `POST /invoices` (WoIdentifier, InvoiceNumber, InvoiceDate, InvoiceTotal, InvoiceAmountsDetails{LaborAmount, MaterialAmount}) returns 201 `{"Id": 180704845}`. Key is `Id`, capital I. WO stayed COMPLETED/CONFIRMED with CanCreateInvoice false, but the create still worked.
- `PUT /invoices/{id}/approve?approvalCode=&comments=&category=REPAIR` as Subscriber returns 204; `GET /invoices/{id}` Status APPROVED. Empty approvalCode accepted.
- Full SB2 lifecycle verified end to end on WO 367500998: create, accept, check-in, check-out, review, invoice, approve. Reject and proposals still unexercised.

## Invoice reject (verified on SB2, 2026-10-26)
`PUT /invoices/{id}/reject?comments=&isNotifyProvider=true` returns 204 and the invoice Status becomes `REJECTED`. The WO stays COMPLETED/CONFIRMED.

## Proposals (verified on SB2, 2026-10-26)
- `GET /proposals/CheckProposalCreation?subscriberId&providerId&locationId&tradeId&currency` returns the request model as a pseudo-JSON string. `POST /proposals/CreateProposal` (Provider) needs `version, subscriberId, providerId, locationId, tradeId, currency, proposalNumber, description, notificationEmails, costsIncurredToDate, materials[], materialsAnswer, installationLabor[], installationLaborFlatFeeLabor, nonInstallationExpenses{travel{ofTrips,charge},fees,nonInstallationLabor}, nonInstallationExpensesOther, freight, freightOther, tax{...}`. Returns the bare proposal id (200). All seven installationLabor lines are required (error 503 names the missing ones): Regular Hours, Overtime Hours, Double Time / Holiday Hours, Helper Regular Hours, Helper Overtime Hours, Helper Double Time / Holiday Hours, Subcontractor Labor.
- The create call has no WO field. The Subscriber links it with `PUT /proposals/{id}/assignWO` (body is the bare WO id, 204, Subscriber only), then `PUT /proposals/{id}/approve` (204). Proposal Status becomes Approved.
- Check-in after the approved proposal succeeded in the engine run (WO 367501276).
- A WO payload nests the provider as `Provider.Id` (no `ProviderId` key).
- Reject verified (WO 367501315): `PUT /proposals/{id}/reject {Comment, ActionSource, RejectReasonCodeId}` returns 204. A second CreateProposal for the same WO then worked, was linked and approved, and the plan continued to check-in, invoice and approval.

## B-39 spike: user acts before the automation (SB2, 2026-10-26)
- User approved a proposal first: the planned `assignWO` returns 400 error 503 `Proposal already approved`. The step retried, so a plan stalls on its own proposal step. The agent must read the proposal status before acting.
- User rejected a proposal and the plan still said approve: `assignWO` returned 204 and `approve` returned 204, so the agent silently approved a proposal the user had rejected (proposal 26954064 ended Approved). The API allows approve after reject. The agent must never act on a proposal that is no longer in its pending state.
- Read a proposal's status with `GET /odata/proposals?$filter=Id eq {id}` (`Status.Primary`: Approved, Rejected, ...). `GET /proposals/{id}` returns 500.

## Locations list (B-43, verified 2026-10-26)
`GET /odata/locations?$select=Id,SubscriberId,StoreId,Name,Latitude,Longitude,TimeZoneIanaName,Status,City,State&$top=50&$skip=N&$orderby=StoreId` returns 200 with `{"@odata.context", "value": [...]}`. The Subscriber has 50 locations on SB2 (`$count=true` gives `@odata.count`); `$skip=50` returns an empty `value`. HQ-NYC is `Id 2006964438`. Six locations have no latitude or longitude, so the app refuses to add them. Some time zones look wrong (store "0042 Bancroft" in Walnut Creek, CA is `America/Vancouver`), so check the time zone of each location you add. During the first attempt SB2 returned 500 on every call for a while (a short outage).

## B-40 / B-41 spike: last activity and labels (SB2, read-only, 2026-10-27)
- **Last activity:** every WO carries `UpdatedDate` (v3 GET shows UTC, OData shows the location offset). On a cancelled test WO it moved to the same instant as the cancellation note, so it moves on notes and status changes. Not checked for every activity type (check-in, proposal, invoice).
- **Server-side age filter works:** `GET /odata/workorders?$filter=UpdatedDate lt 2026-10-01T00:00:00Z and Status/Primary eq 'OPEN'&$count=true&$top=50&$select=Id,UpdatedDate,Status`. The SB2 Subscriber has 2646 OPEN WOs not updated since 2026-10-01 (all locations). `GET /odata/locations({locationId})/workorders` narrows to one location, so the sweep can filter to the agent's locations.
- **Labels, read:** a WO has `Labels: [{"Id": 10739, "Label": "regulatory"}]`. A WO with no label shows `[{"Id": 0}]`. OData filters by label name: `$filter=Labels/any(l: l/Label eq 'regulatory')` returns the matches, and an unknown name returns an empty list (so the protect-label filter is safe to build into the query).
- **Labels, write:** the Swagger has no endpoint to add or remove a label on an existing WO. `CreateWoRequest` takes `Labels` (names) and `LabelId` at creation only. Webhook events `WorkOrderLabelAdded` and `WorkOrderLabelDeleted` exist, so users set labels in the ServiceChannel UI. The agent only reads the protect label; it can never set one.
- **Foreign-provider cancel works (verified 2026-10-27):** Subscriber `PUT /workorders/358214917/status` with `{"Status":{"Primary":"COMPLETED","Extended":"CANCELED"},"Note":...}` returned 200 on an OPEN WO held by provider FAHEY REFRIG CO, which the agent has no credentials for. The WO ended Completed / Canceled.
- **Open:** (1) the full list of WO status values (only OPEN, IN PROGRESS and ON HOLD are used as "active" by the clean-up); (2) a short finishing plan needs the WO's provider credentials, so it only applies to WOs assigned to the agent's providers, and everything else can only be cancelled.

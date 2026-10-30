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

- **Accept refused (Prod, 2026-10-27):** `PUT /workorders/{id}/accept` returns 400 / error 904 "Work Order is in status that not allow to perform this action" on idle WOs that are already past acceptance (In Progress and similar). A plan for an existing WO must not start with accept.

- **Invoice payment verified (SB2, 2026-10-27):** Subscriber `POST /invoices/{id}/Payment` with `{"PaymentDate","PaymentNumber","PaymentAmount"}` returned 204 on an APPROVED invoice (180704845, total 320.00); `GET /invoices/{id}` then showed `Status: PAID` and a `Payments[]` entry. Swagger error 1178 covers: only approved invoices, already paid, amount above the invoice total, amount not above zero, date before approval, and "Pay not allowed for this subscriber" (not seen on SB2; unknown on Prod).

## Two technicians on one visit (verified on Prod 2026-10-27, WOs 368258499 and 368258511, cancelled after)
- A second tech (another user of the same provider) can `universalCheckIn` on a WO that is already ON SITE: 200 with its own MechanicId.
- A `universalCheckOut` with PrimaryStatus Completed by the first tech completes the WO. The second tech's check-out then fails with 400 error 921 "Cannot update work order in 'completed' status."
- Working order: first tech out with PrimaryStatus PartsOnOrder, second tech out with Completed. Both return 200 with their MechanicId; the WO ends COMPLETED.

## Decline and reschedule (SB2 spike, 2026-10-28, WOs 367578620/622/661/663, all cancelled)
- **Decline:** `PUT /workorders/{id}/decline` as the Provider, body `{DeclineReasonId, CustomDeclineReason?, Note?}` (reasons 1 Can't make ETA, 2 Trade not serviced, 3 Location not serviced, 4 Not under warranty, 5 Other, 6 NTE too low; Swagger lists no GET for them). Returns 204 with `{DeclineReasonId: 1}` alone.
- **Resolved (Zac, 2026-10-28): the switch is the TRADE's auto-reassign setting in SC admin** (it was on only for DOORS; all three declined WOs in this spike were DOORS). With it off, declines of DOORS, HVAC and General Maintenance WOs all gave `OPEN / DECLINED` with the Provider unchanged (WOs 367578698, 701, 717), and the Subscriber can cancel them (`OPEN/DECLINED` to `COMPLETED/CANCELED`). The subscriber features list (`GET /users/current/subscriberFeatures`) shows `AutoReassignment` and `DeclineHistoryWO` on for SB2 but no `WOMultipleAutoReassign`. Prod trade settings are unknown.
- **SB2 auto-reassigns on decline (trade setting on):** the WO stayed `OPEN` (never `OPEN / DECLINED`) and its Provider changed from SydeTech to "Brad's Demo Co" within 3 seconds, with a new scheduled date about 6 days out. The Swagger text says a decline becomes automatic reassignment when the subscriber's *WOMultipleAutoReassign* flag is on, so that flag is on for the SB2 subscriber. After the decline the WO belongs to a provider the agent has no credentials for, so its plan must end. Whether Prod's subscriber has the flag is unknown.
- **`Note` on decline fails:** a body with `Note` returns 400 error 501 "Failed to add work order note", yet the decline and reassignment still happened. Send the reason id only.
- **Reschedule:** `PUT /workorders/{id}/scheduledate?rescheduleReasonCode=1` as the Provider, body `{Value: "2026-11-05T11:09:00", Actor}` returns 200 `{id}`; the scheduled date moved 2 days later and the status was unchanged. Reasons: `GET /subscribers/{subscriberId}/workOrderRescheduleReasons` (1 [NONE], 6 Updating to original scheduled date, 7 Subscriber corporate requested, 8 Weather, 10 Provider awaiting parts, 11 Area inaccessible, 12 Provider scheduling conflict, 13 Provider equipment issues, 14 Subscriber store manager requested). Needs the `WorkOrderScheduledDateChange` permission; the SB2 Provider user has it.
- **Reassign:** `PUT /workorders/{id}/reassign` (subscriber or provider; reasons `GET /workorders/reassign/reasons`; provider lookup `GET /workorders/providerforreassignment`). Not exercised yet.
- **End-to-end through the agent (SB2, 2026-10-28):** a decline plan on HVAC WO 367578768 ran `decline` (OPEN / DECLINED, provider unchanged) then the Subscriber `cancel` (COMPLETED / CANCELED). A reschedule plan on General Maintenance WO 367578760 was created with the original date (2026-10-30), `accept`, then `reschedule` moved it to 2026-11-04 with reason code 12 and a provider note; status became IN PROGRESS / DISPATCH CONFIRMED after the accept. Both WOs were cancelled afterwards.

## Reassign (B-20 spike, SB2, 2026-10-28, WOs 367579857 and 367579859, both cancelled after)
- `PUT /workorders/{id}/reassign` as the Subscriber, body `{"ProviderId": <int>, "ReasonId": <int>}`. Success returns `{"id": <wo id>}`. The WO stays OPEN and `Provider.Id` changes at once. A `Note` field is ignored.
- Checks, in the order they fire: reason first (`Invalid WO reassignment reason` with a missing or unknown ReasonId), then WO status (`Invalid work order status` on a cancelled WO), then the provider (`Invalid provider`), then the contract (`Contract is required for this operation`).
- The target provider needs a contract for the WO's trade at its location. The target held a DOORS contract only, so a General Maintenance WO failed with the contract error and a DOORS WO succeeded. Find eligible targets with `GET /contracts?locationDbId=&providerId=&trade=` (an empty `Contracts` list means no). Trade names must match exactly (`DOORS`, not `DOOR` or `DOOR/LOCK`; a wrong name returns `Trade not found`).
- `GET /workorders/reassign/reasons` returns `[{Id, Name, Value}]`: 1 Trade not serviced, 2 Location not serviced, 3 Can`t make ETA, 4 HVAC Monitor, 5 Not Under Warranty, 6 Energy Monitor, 7 Assigned to Facilities Manager, 8 Assigned to Vendor, 9 Landlord/Mall Issue, 10 Assigned to Corporate, 11 Assigned to Construction, 12 Weather, and more.
- `GET /workorders/providerforreassignment` was not found to list providers: with `locationId` and `tradeId` it returned the priority list, and with a WO id it fails with a routing clash. Use `/contracts` instead.
- Live, through the agent (SB2, 2026-10-29, WO 367579886, DOORS at HQ-NYC): the Provider declined, the `reassign` step looked up contracts for each other provider connection, `PUT /reassign` returned 200, and the new provider's user then accepted the WO with `PUT /accept` (200). A reassigned WO stays OPEN and the new provider accepts it normally, so a fresh plan starting with an accept is right.
- The WO's saved context may not hold the provider (routing is by contract rank), so the step reads `Provider.Id` from `GET /workorders/{id}`. Without that it picked the current provider and got 400 `Invalid provider id` (ErrorCode 101) for reassigning to the provider already on the WO.
- Reassign after check-in (SB2, 2026-10-29, WO 367579886): a WO IN PROGRESS / ON SITE reassigns with 200. The provider changes and the WO returns to OPEN with an empty extended status, so the new provider accepts and visits from scratch. Nothing in the API stops it, so the handler works from any point in a plan.
- No-show (SB2, 2026-10-29, WO 367624710): the provider accepted and never checked in. A Subscriber note, then `PUT /reassign` (reason 3) returned 200, and the new provider accepted the WO.

## B-39 follow-up: what a live WO read exposes (SB2, 2026-10-29, WO 367624710)
- `GET /workorders/{id}` carries `ScheduledDate` (UTC, `Z`), `Nte`, `Priority` ("Normal"), `Provider.Id` and `Status.Primary`/`Extended`, enough to notice a reschedule, an NTE or priority edit, a provider change and a status the plan does not know.
- A provider reschedule (`PUT /scheduledate`, reason 12) moved `ScheduledDate` and the agent shifted the pending visit steps on the next write step; a check-in that came due was held back until its new time. The NTE and priority edits were not exercised live, only read.

## B-12 spike: invoice line items and validation (SB2, 2026-10-29, WO 367625039, DOORS, NTE 500)
- **Line-item body** (from the developer guide, verified): `POST /invoices` with `InvoiceNumber, WoIdentifier, InvoiceDate, InvoiceTotal, InvoiceAmountsDetails{LaborAmount, MaterialAmount, ...}`, `Labors[{SkillLevel:"2", LaborType:"1", NumOfTech:"1", HourlyRate, Hours, Amount}]`, `Materials[{Description, PartNum, UnitType:"7", UnitPrice, Quantity, Amount}]` returned 201 `{Id}`. A labor line without `SkillLevel` fails with 400 error 1194 "Invalid Labor Skill Level" (every guess at other field names gave the same error). SkillLevel 1 and 2 and LaborType 1 and UnitType 7 are the only values seen in the guide; the full lists were not found.
- **The API checks the totals:** `InvoiceTotal` that does not equal labor + material + travel + freight + other + tax returns 1103 "Invalid Total". A total above the WO's NTE returns 1104 "Invoice Total > NTE 500.0000". So an over-NTE invoice cannot be created at all; the real route is a proposal (already built) or the Subscriber raising the NTE first.
- **One invoice per WO:** while any invoice exists in OPEN or APPROVED, a second `POST /invoices` returns 1105 "Invoice exists" (a negative total or a credit memo too). After a reject, a new invoice with a new number is accepted. So a partial invoice followed by a balance invoice is not possible, and a credit memo cannot be a second invoice on the same WO. Not verified: negative lines inside a single invoice (the Subscriber has `IsInvoiceNegativeFeatureEnabled`).
- **WO state:** the create needs the WO COMPLETED with an empty or CONFIRMED extended status; an IN PROGRESS WO returns 904 "Invalid State".
- **The API computes the rate flags:** `GET /invoices/{id}` shows per labor line `AgreedRate` and `IsRateDiscrepancy`, and on the invoice `WithMismatchedRates`. An invoice billed at 100.00 an hour against an agreed 4.00 came back `WithMismatchedRates: true`, line `IsRateDiscrepancy: true`. Resubmitted at 4.00 (new number) the flags were false. Materials carry `IsMarkUpDiscrepancy` and `IsPartPriceDiscrepancy`. The agreed rate is only visible after the invoice exists (read it from the rejected invoice's `Labors[].AgreedRate`).
- **Reject:** `PUT /invoices/{id}/reject?comments=&isNotifyProvider=true` returns 204 and Status REJECTED. An extra `reasonId` param was accepted but nothing on the invoice shows it (`DisputeReason` stays empty). Reasons list: `GET /invoices/{sub}/InvoiceRejectionReasons` gives 1 Work order not invoiceable, 2 Invoice requires correction, 3 Other.
- **Not checked by the API:** hours billed against time on site. Nothing compared the 2 billed hours with the check-in and check-out times, so that flag would be the agent's own.

- **COMPLETED/NO CHARGE (SB2, 2026-10-29, WO 359213720):** Subscriber `PUT /workorders/{id}/status {Status:{Primary:COMPLETED, Extended:"NO CHARGE"}, Note}` returns 200 ("changed from COMPLETED/CONFIRMED to COMPLETED/NO CHARGE") on a WO with Nte 0. Such a WO shows `Status.CanCreateInvoice: false`, and an invoice POST returns 1104 "Invoice Total > NTE 0.0000".

- **Hand-made WO pickup (SB2, 2026-10-29, B-51):** `GET /odata/locations({dbId})/workorders?$filter=CreatedDate gt <utc> and (Status/Primary eq 'OPEN' or ...)&$expand=Provider($select=Id)&$select=Id,Trade` works and returns the provider id. `GET /workorders/{id}` has no `CreatedDate` (it has `CallDate`). A fresh WO is `OPEN` with `Extended` empty; after the Provider accepts it is `IN PROGRESS` / `DISPATCH CONFIRMED`. So the plan adds an accept step only for `OPEN`.

## Checklists spike (B-22, SB2, 2026-10-29, verified)

- Definitions: `GET /checklists/detail` with `tradeName` or `tradeid`, optional `categoryName`, `storeId` or `locationId`. A Provider must add `subscriberId` (2014917582 on SB2). A checklist is tied to a trade (and optionally a category): with no checklist for the WO's trade at the location, every submit fails with 503 "active checklist ... is not found". Zac created checklist 2457 "Test" for Doors at HQ-NYC, which made submits work. No create endpoint exists, so a checklist is set up in the ServiceChannel UI.
- Read: `GET /workorders/{id}/checklists-responses` returns `{"Responses": [...]}` (each with question, selected option, answer, pictures).
- Submit: `POST /checklists/CheckListResponse`, multipart/form-data. Part `CheckListResponseRequest` (JSON, content type application/json) holds `CheckListQuestionID`, `ProviderID`, `TechnicianID`, `EntityID` (WO id), `Attempt`, and `Answer`. A Selector sends `CheckListQuestionOptionID` and no `Answer`. A picture is a second part named `file`. `ScApp.call` is JSON only, so a build needs a multipart path.
- Verified on WO 367625663 (Doors, IN PROGRESS, as the Provider): selector 201, text 201, numeric 201, acknowledgement 201 with `"on"`, picture question 201 with a PNG in `file` (without it: 503 "The picture is required!").
- Acknowledgement accepts `on`; `"yes"` returned the misleading 503 "checklist ... not found", so send `on`.
- A question can be answered once per `Attempt` (503 "already been answered for this attempt number"). `Attempt` is the visit number.
- `TechnicianID` 0 gives 503 "Whether TechnicianId or AuthUserId must be specified"; any nonzero value is accepted (1 worked), and our users have no stored `sc_user_id`.
- Text answers come back lowercased on the first letter ("Door closer" became "door closer").
- Question types: 0 acknowledgement (maybe with a URL), 1 selector, 2 text, 4 numeric. `PictureFlag` 2 means a picture is required. `AnswerRequired`, `CheckListTimingType` 1 or 2.
- Checklists with `DisplayForEachAsset` (such as 2380 Asset Transfer) are per asset and need B-23/B-24 first.
- Built into `check_out` (2026-10-30) and run live on SB2 on a new Doors WO (accept, check-in, then check-out): `GET /checklists/detail` 200 (the Subscriber id comes from our location row), five answers 201 (acknowledgement, selector, text, numeric, text with a JPEG), then `universalCheckOut` 200. The read-back showed all five with `TechnicianId` 1, and the picture answer carried a `Pictures` entry. The answers went in while the WO was IN PROGRESS, before the check-out. A WO already COMPLETED is not tested for submits.
- Not tested: completing a WO with unanswered required questions (whether check-out is blocked), a Subscriber submitting, Prod.

# SC Activity Agent issue list

[`SCActivityAgentIssueList.xlsx`](../sc_activity_agent/SCActivityAgentIssueList.xlsx) (also downloadable from the agent's Settings page) is the issue list the agent is built and tested against, in ServiceChannel's issue list file format (sheets Areas, Issues, Fields, Conditions). It holds 187 issue rows: 172 distinct equipment and problem pairs across General Maintenance, Refrigeration, Electrical, Doors, HVAC, Plumbing, Kitchen Equipment and Freight Equipment.

The agent never creates or changes an issue list. It reads the list on the Subscriber user's own dashboard (`GET /storedashboards/{id}/issuelist`) and takes trade, category, priority, NTE and the attachment flag from it. To run the same setup as ours, load this file as the issue list of the dashboard your Subscriber user uses, in your own ServiceChannel environment. Without it the agent still works, but only with whatever your list contains.

## Attachment-required issues

Seven issues are marked AttachmentRequired. ServiceChannel refuses a create for them (error 916) unless the call says to skip the check, so the agent sends `IgnoreAttachmentsRequiredFlag` and attaches a before photo right after the create:

| Equipment | Problem | Photo sets |
|---|---|---|
| Fryer | Installation | `kitchen-fryer-install`, `-b` |
| Hanging Dial Scale | Broken Chain | `kitchen-dial-scale-chain`, `-b` |
| Hanging Dial Scale | Needle not working | `kitchen-dial-scale-needle`, `-glass` |
| Digital Hanging Scale | Display out | `kitchen-digital-scale-display`, `kitchen-digital-scale` |
| Digital Hanging Scale | No Power | `kitchen-digital-scale-nopower` |
| Digital Hanging Scale | Buttons Not Working | `kitchen-digital-scale` |
| Fork Lift | Battery | `freight-forklift-battery`, `-b` |

## Keeping it current

This file is the source of truth for the list. When the issue list changes (a new issue, a changed trade, NTE or attachment flag), update the file in the same commit as the code and photo changes, and attach it to the release. `tests/test_issue_list.py` fails if an AttachmentRequired row has no matching photo set.

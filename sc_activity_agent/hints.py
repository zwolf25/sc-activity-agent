"""Known error text mapped to the fix, shown on the Errors page, in connection messages and in alerts."""
import re

# B-79: known causes, matched against the error text
ERROR_HINTS = [(re.compile(r"\b1104\b"), "The invoice or proposal is over the NTE. Skip it, or raise the NTE on the WO in ServiceChannel."),
               (re.compile(r"\b403\b.*\b100\b|\b100\b.*\b403\b"), "ServiceChannel refused a second attach on the same asset. Skip it."),
               (re.compile(r"\b429\b"), "Rate limited. Retry later; lower the calls per minute if it repeats."),
               (re.compile(r"\b804\b"), "Check-in is not enabled for this Subscriber and Provider pair. Open Setup, copy the request under Check-in permission and send it to ServiceChannel support."),
               (re.compile(r"\b1145\b"), "ServiceChannel blocks this Provider on billing. Fix the Provider's billing in Fixxbook (CSA Billing), then retry."),
               (re.compile(r"no eligible trade at"), "No Provider you control is Rank 1 for any trade at this location. In ServiceChannel Contracts, rank one of your Providers 1 for a trade there, or use another location. Then press 'Re-read contracts' on Locations. Also check that each Provider connection has its Provider ID."),
               (re.compile(r"no issue resolves on the dashboard"), "The issue list dashboard has no problem for this location's trades. In ServiceChannel, assign the dashboard to the Subscriber user, then reload dashboards on Connections."),
               (re.compile(r"Client ID or secret rejected"), "ServiceChannel does not accept this integration app. Check the Client ID and secret, and that the app is registered in this environment (SB2 apps do not work in Production). Delete the connection on Connections and add it again."),
               (re.compile(r"Username or password rejected"), "ServiceChannel does not accept this user's login. Delete the user on Connections and add it again with the current password."),
               (re.compile(r"Could not reach ServiceChannel"), "The computer cannot reach ServiceChannel. Check the internet connection, VPN or proxy, then retry.")]


def hint(text):
    return next((h for rx, h in ERROR_HINTS if rx.search(text or "")), "")

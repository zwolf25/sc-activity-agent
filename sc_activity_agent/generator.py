"""Picks what WO to create: eligible trades (Rank 1 is ours), weighted issue choice, and the POST /workorders payload."""
import datetime as dt


def issues(issue_list):
    """Flatten the dashboard issue list (GET .../storedashboards/{id}/issuelist) to one dict per problem."""
    return [{"problem_type": pt["Name"], "item": it["Name"], "problem": p["Name"], "trade": p["Trade"],
             "trade_id": p["TradeId"], "priority": p["Priority"], "category": p["Category"]["Default"],
             "category_id": p["CategoryId"], "nte": float(p["Nte"] or 0)}
            for pt in issue_list["ProblemTypes"] for it in pt["Items"] for p in it["Problems"] if p["Trade"]]


def rank_one_trades(get, subscriber_id, provider_id, location_id):
    """Trades where this provider is Rank 1 at the location. get(path) -> parsed JSON (Subscriber token).
    1 + N calls (N = provider trades); cache the result and refresh on demand."""
    out = set()
    for t in get(f"/GetPrimaryRankedProviderTrades/{subscriber_id}/{provider_id}"):
        if location_id in get(f"/GetPrimaryRankedProviderLocations/{subscriber_id}/{provider_id}/{t['TradeId']}"):
            out.add(t["Trade"])
    return out


def eligible(all_issues, ours):
    """ours: set of trade names where Rank 1 at this location is one of our provider connections."""
    return [i for i in all_issues if i["trade"] in ours]


def pick(rng, pool, mix=None):
    """mix: {trade: weight}. Trade is drawn by weight, then an issue uniformly within it. None if no pool."""
    trades = sorted({i["trade"] for i in pool})
    if not trades:
        return None
    trade = rng.choices(trades, [(mix or {}).get(t, 1) for t in trades])[0]
    return rng.choice([i for i in pool if i["trade"] == trade])


def payload(issue, loc, header_id, area_id, scheduled, now, test=False):
    """loc: {subscriber_id, id, store_id}. Status is deliberately omitted (SB2 rejects every value)."""
    f = "%Y-%m-%dT%H:%M:%S"
    return {
        "ContractInfo": {"SubscriberId": loc["subscriber_id"], "LocationId": loc["id"], "StoreId": loc["store_id"],
                         "TradeName": issue["trade"], "TradeId": issue["trade_id"]},
        "Category": issue["category"], "CategoryId": issue["category_id"], "Priority": issue["priority"],
        "Nte": issue["nte"],
        "CallDate": now.strftime(f), "ScheduledDate": scheduled.strftime(f),
        "Description": f"{issue['problem']} - {issue['item']}", "ProblemCode": issue["problem"],
        "IssueRequestInfo": {"AreaId": area_id, "ProblemType": issue["problem_type"], "AssetType": issue["item"]},
        "DispatchSettingsInfo": {"IsTest": test, "NotificationDisabled": test},
        "ApiRequest": True, "IssueListHeaderId": header_id,
    }


def daily_count(rng, per_month, day):
    """WOs to create on this date: weekdays only, mean per_month/21, with Poisson-like variation."""
    if day.weekday() >= 5:
        return 0
    lam, n, p, L = per_month / 21, 0, 1.0, 2.718281828 ** -(per_month / 21)
    while True:
        p *= rng.random()
        if p <= L:
            return n
        n += 1

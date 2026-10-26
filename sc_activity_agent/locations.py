"""Pulls the Subscriber's locations so the user picks them from a list instead of typing ids."""

FIELDS = "Id,SubscriberId,StoreId,Name,Latitude,Longitude,TimeZoneIanaName,Status,City,State"


def fetch(call, subscriber_id=None, page=50, cap=5000):
    """call(path, params) -> parsed JSON. Pages with $top/$skip (the API caps $top at 50). Returns normalized rows.
    ponytail: stops at `cap` rows; raise it or add server-side filtering if a Subscriber has more stores."""
    out, skip = [], 0
    while skip < cap:
        rows = call("/odata/locations", {"$select": FIELDS, "$top": page, "$skip": skip, "$orderby": "StoreId"})
        rows = rows.get("value", []) if isinstance(rows, dict) else rows or []
        for r in rows:
            if subscriber_id and r.get("SubscriberId") != subscriber_id:
                continue
            out.append({"store_id": r.get("StoreId") or str(r["Id"]), "db_id": r["Id"], "subscriber_id": r.get("SubscriberId"),
                        "name": r.get("Name") or "", "lat": r.get("Latitude"), "lon": r.get("Longitude"),
                        "tz": r.get("TimeZoneIanaName") or "America/New_York", "city": r.get("City") or "",
                        "state": r.get("State") or "", "status": r.get("Status") or ""})
        if len(rows) < page:
            break
        skip += page
    return out

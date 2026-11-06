"""Helpers for equipment targets stored in schedule records."""

from . import store


def scope_ips(item: dict, assignments: list[dict] | None = None) -> list[str]:
    """Return all selected IPs, including exclusions, for editing a schedule."""
    if item.get("target_mode") == "all":
        if assignments is None:
            assignments = store.load_assignments()
        ips = [a["ip"] for a in assignments]
    else:
        ips = item.get("ips")
    if not isinstance(ips, list):
        ips = [item["ip"]] if item.get("ip") else []
    return list(dict.fromkeys(ip for ip in ips if isinstance(ip, str) and ip))


def included_ips(item: dict, assignments: list[dict] | None = None) -> list[str]:
    """Return the selected IPs that are not excluded from a schedule."""
    excluded = set(item.get("excluded_ips", []))
    return [ip for ip in scope_ips(item, assignments) if ip not in excluded]

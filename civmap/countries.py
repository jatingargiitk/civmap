"""Find a country in Natural Earth by ISO code or name."""
from __future__ import annotations


def _props_codes(p: dict) -> tuple[str, str]:
    iso2 = p.get("ISO_A2_EH") or p.get("ISO_A2") or ""
    iso3 = p.get("ADM0_A3") or p.get("ISO_A3_EH") or p.get("ISO_A3") or ""
    if iso2 == "-99":
        iso2 = p.get("ISO_A2") if p.get("ISO_A2") not in (None, "-99") else ""
    return iso2, iso3


def _norm(s: str) -> str:
    return "".join(ch for ch in s.lower() if ch.isalnum())


def find_country(features: list[dict], query: str) -> dict:
    """Return the Natural Earth feature matching ``query``.

    ``query`` may be an ISO 3166-1 alpha-2 or alpha-3 code or an English name
    ("IN", "IND", "India", "united kingdom").
    """
    q = query.strip()
    nq = _norm(q)
    best = None
    for f in features:
        p = f["properties"]
        iso2, iso3 = _props_codes(p)
        if len(q) == 2 and q.upper() == iso2:
            return f
        if len(q) == 3 and q.upper() in (iso3, p.get("ISO_A3"), p.get("ISO_A3_EH")):
            return f
        names = [p.get(k) or "" for k in ("NAME", "NAME_LONG", "ADMIN", "NAME_EN", "FORMAL_EN", "NAME_SORT")]
        if any(_norm(n) == nq for n in names if n):
            return f
        if best is None and any(nq and _norm(n).startswith(nq) for n in names if n):
            best = f
    if best is not None:
        return best
    raise KeyError(f"no country matches {query!r}")


def codes(feature: dict) -> tuple[str, str, str]:
    p = feature["properties"]
    iso2, iso3 = _props_codes(p)
    return iso2, iso3, p.get("NAME_EN") or p.get("NAME") or p.get("ADMIN")

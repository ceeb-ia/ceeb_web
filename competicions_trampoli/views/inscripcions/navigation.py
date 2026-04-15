from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


INTERNAL_RETURN_URL_QUERY_KEYS = frozenset(
    {
        "__fragments",
        "__panel_key",
        "__active_group_key",
    }
)


def sanitize_inscripcions_return_url(raw_url, fallback_url):
    fallback = str(fallback_url or "").strip()
    candidate = str(raw_url or "").strip()
    if not candidate:
        return fallback

    try:
        parsed = urlsplit(candidate)
        query_items = [
            (key, value)
            for key, value in parse_qsl(parsed.query or "", keep_blank_values=True)
            if key not in INTERNAL_RETURN_URL_QUERY_KEYS
        ]
    except Exception:
        return fallback

    cleaned_url = urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            urlencode(query_items, doseq=True),
            parsed.fragment,
        )
    ).strip()
    return cleaned_url or fallback


__all__ = [
    "INTERNAL_RETURN_URL_QUERY_KEYS",
    "sanitize_inscripcions_return_url",
]

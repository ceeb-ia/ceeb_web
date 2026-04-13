from __future__ import annotations

import re
import unicodedata

from ..models import Address


_WHITESPACE_RE = re.compile(r"\s+")


def _clean_component(value) -> str:
    text = str(value or "").strip()
    if text.lower() in {"nan", "none"}:
        return ""
    text = _WHITESPACE_RE.sub(" ", text)
    text = re.sub(r"\s*,\s*", ", ", text)
    return text.strip(" ,")


def normalize_address_text(value) -> str:
    cleaned = _clean_component(value)
    normalized = unicodedata.normalize("NFKD", cleaned)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    ascii_text = ascii_text.lower()
    ascii_text = re.sub(r"[^a-z0-9, ]+", " ", ascii_text)
    ascii_text = _WHITESPACE_RE.sub(" ", ascii_text)
    return ascii_text.strip(" ,")


def build_address_payload(*, domicile=None, municipality=None, text=None) -> dict:
    domicile_text = _clean_component(domicile)
    municipality_text = _clean_component(municipality)
    if text is not None:
        display_text = _clean_component(text)
        if not municipality_text and "," in display_text:
            municipality_text = _clean_component(display_text.rsplit(",", 1)[-1])
    else:
        parts = [part for part in (domicile_text, municipality_text) if part]
        display_text = ", ".join(parts)

    return {
        "text": display_text,
        "normalized_text": normalize_address_text(display_text),
        "municipality": municipality_text,
        "domicile": domicile_text,
    }


def resolve_address(*, domicile=None, municipality=None, text=None) -> Address | None:
    payload = build_address_payload(domicile=domicile, municipality=municipality, text=text)
    if not payload["text"] or not payload["normalized_text"]:
        return None

    address, _created = Address.objects.get_or_create(
        normalized_text=payload["normalized_text"],
        defaults={
            "text": payload["text"],
            "municipality": payload["municipality"] or None,
        },
    )

    update_fields = []
    if payload["text"] and address.text != payload["text"]:
        address.text = payload["text"]
        update_fields.append("text")
    if payload["municipality"] and address.municipality != payload["municipality"]:
        address.municipality = payload["municipality"]
        update_fields.append("municipality")
    if address.normalized_text != payload["normalized_text"]:
        address.normalized_text = payload["normalized_text"]
        update_fields.append("normalized_text")
    if update_fields:
        address.save(update_fields=update_fields)
    return address


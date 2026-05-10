import hashlib
import unicodedata


def _normalize_entity_name(name):
    text = unicodedata.normalize("NFKC", str(name)).casefold().strip()
    return " ".join(text.split())


def _mk_id(row):
    nom = _normalize_entity_name(row.get("Nom", ""))
    lliga = _normalize_entity_name(row.get("Nom Lliga", ""))
    cat = _normalize_entity_name(row.get("Categoria", ""))
    key = f"{nom}|{lliga}|{cat}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:10].upper()


def ensure_team_ids(df):
    if "Id" in df.columns:
        return df

    result = df.copy()
    result["Id"] = result.apply(_mk_id, axis=1)
    return result

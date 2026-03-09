import os
import re
import unicodedata
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Set


DEFAULT_MEDIA_MATCHING_CONFIG = {
    "weights": {
        "nom": 60,
        "entitat": 20,
        "sexe": 10,
        "subcategoria": 10,
    },
    "thresholds": {
        "auto_score_min": 0.85,
        "review_score_min": 0.65,
        "auto_margin_min": 0.12,
    },
}


_SEXE_F_KEYS = {"f", "femeni", "femeni", "femenino", "female", "dona", "girl", "w"}
_SEXE_M_KEYS = {"m", "masculi", "masculi", "masculino", "male", "home", "boy"}


@dataclass
class MatchCandidate:
    inscripcio_id: int
    label: str
    nom_tokens: Set[str]
    entitat_tokens: Set[str]
    sexe_key: str
    subcategoria_tokens: Set[str]


def _safe_float(value, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _safe_int(value, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def normalize_media_matching_config(raw_config: Optional[dict]) -> dict:
    cfg = raw_config if isinstance(raw_config, dict) else {}
    raw_weights = cfg.get("weights") if isinstance(cfg.get("weights"), dict) else {}
    raw_thresholds = cfg.get("thresholds") if isinstance(cfg.get("thresholds"), dict) else {}

    weights = {
        "nom": max(0, _safe_int(raw_weights.get("nom"), DEFAULT_MEDIA_MATCHING_CONFIG["weights"]["nom"])),
        "entitat": max(0, _safe_int(raw_weights.get("entitat"), DEFAULT_MEDIA_MATCHING_CONFIG["weights"]["entitat"])),
        "sexe": max(0, _safe_int(raw_weights.get("sexe"), DEFAULT_MEDIA_MATCHING_CONFIG["weights"]["sexe"])),
        "subcategoria": max(0, _safe_int(raw_weights.get("subcategoria"), DEFAULT_MEDIA_MATCHING_CONFIG["weights"]["subcategoria"])),
    }

    thresholds = {
        "auto_score_min": min(1.0, max(0.0, _safe_float(raw_thresholds.get("auto_score_min"), DEFAULT_MEDIA_MATCHING_CONFIG["thresholds"]["auto_score_min"]))),
        "review_score_min": min(1.0, max(0.0, _safe_float(raw_thresholds.get("review_score_min"), DEFAULT_MEDIA_MATCHING_CONFIG["thresholds"]["review_score_min"]))),
        "auto_margin_min": min(1.0, max(0.0, _safe_float(raw_thresholds.get("auto_margin_min"), DEFAULT_MEDIA_MATCHING_CONFIG["thresholds"]["auto_margin_min"]))),
    }
    if thresholds["review_score_min"] > thresholds["auto_score_min"]:
        thresholds["review_score_min"] = thresholds["auto_score_min"]

    return {"weights": weights, "thresholds": thresholds}


def _normalize_text(value) -> str:
    txt = str(value or "").strip()
    if not txt:
        return ""
    txt = "".join(
        c for c in unicodedata.normalize("NFKD", txt)
        if not unicodedata.combining(c)
    )
    txt = txt.casefold()
    txt = re.sub(r"[^a-z0-9]+", " ", txt)
    txt = re.sub(r"\s+", " ", txt).strip()
    return txt


def _tokenize(value) -> Set[str]:
    txt = _normalize_text(value)
    if not txt:
        return set()
    return {token for token in txt.split(" ") if token}


def _normalize_sexe(value) -> str:
    token = _normalize_text(value)
    if not token:
        return ""
    if token in _SEXE_F_KEYS:
        return "f"
    if token in _SEXE_M_KEYS:
        return "m"
    return token


def _filename_base_tokens(filename: str) -> Set[str]:
    stem = os.path.splitext(str(filename or ""))[0]
    # Prefixos tipics de ranking: "1 - -", "12__", etc.
    stem = re.sub(r"^\s*\d+\s*[-_ ]+\s*", "", stem)
    return _tokenize(stem)


def _extract_filename_sexe_key(tokens: Set[str]) -> str:
    if not tokens:
        return ""
    if tokens & _SEXE_F_KEYS:
        return "f"
    if tokens & _SEXE_M_KEYS:
        return "m"
    return ""


def _overlap_score(candidate_tokens: Set[str], file_tokens: Set[str]) -> Optional[float]:
    if not candidate_tokens:
        return None
    if not file_tokens:
        return 0.0
    inter = len(candidate_tokens.intersection(file_tokens))
    return inter / max(1, len(candidate_tokens))


def build_inscripcio_media_match_candidates(inscripcions: Iterable) -> List[MatchCandidate]:
    out: List[MatchCandidate] = []
    for ins in inscripcions:
        nom = str(getattr(ins, "nom_i_cognoms", "") or "").strip()
        entitat = str(getattr(ins, "entitat", "") or "").strip()
        subcategoria = str(getattr(ins, "subcategoria", "") or "").strip()
        sexe = str(getattr(ins, "sexe", "") or "").strip()
        meta_parts = [p for p in [entitat, subcategoria, sexe] if p]
        label = nom if not meta_parts else f"{nom} ({' · '.join(meta_parts)})"
        out.append(
            MatchCandidate(
                inscripcio_id=int(ins.id),
                label=label,
                nom_tokens=_tokenize(nom),
                entitat_tokens=_tokenize(entitat),
                sexe_key=_normalize_sexe(sexe),
                subcategoria_tokens=_tokenize(subcategoria),
            )
        )
    return out


def _score_candidate(file_tokens: Set[str], file_sexe_key: str, candidate: MatchCandidate, cfg: dict) -> dict:
    weights = cfg["weights"]

    def _weighted(field_key: str, component: Optional[float]) -> tuple:
        if component is None:
            return 0.0, 0.0
        w = float(max(0, weights.get(field_key, 0)))
        return (w * component), w

    nom_component = _overlap_score(candidate.nom_tokens, file_tokens)
    ent_component = _overlap_score(candidate.entitat_tokens, file_tokens)
    sub_component = _overlap_score(candidate.subcategoria_tokens, file_tokens)

    sexe_component = None
    if candidate.sexe_key:
        if not file_sexe_key:
            sexe_component = 0.5
        elif candidate.sexe_key == file_sexe_key:
            sexe_component = 1.0
        else:
            sexe_component = -1.0

    numer = 0.0
    denom = 0.0
    field_scores = {}
    for field_key, component in (
        ("nom", nom_component),
        ("entitat", ent_component),
        ("subcategoria", sub_component),
        ("sexe", sexe_component),
    ):
        part_num, part_den = _weighted(field_key, component)
        numer += part_num
        denom += part_den
        field_scores[field_key] = None if component is None else round(float(component), 4)

    if denom <= 0:
        total = 0.0
    else:
        total = numer / denom
    total = max(0.0, min(1.0, total))

    return {
        "score": round(total, 4),
        "field_scores": field_scores,
    }


def _status_from_scores(score: float, margin: float, cfg: dict) -> str:
    t = cfg["thresholds"]
    if score >= t["auto_score_min"] and margin >= t["auto_margin_min"]:
        return "auto"
    if score >= t["review_score_min"]:
        return "review"
    return "unmatched"


def match_media_files_to_inscripcions(
    files: Sequence[dict],
    candidates: Sequence[MatchCandidate],
    config: Optional[dict] = None,
    top_k: int = 3,
) -> List[dict]:
    cfg = normalize_media_matching_config(config)
    out: List[dict] = []
    kk = max(1, int(top_k or 1))

    for raw in (files or []):
        row = raw if isinstance(raw, dict) else {}
        key = str(row.get("key") or "").strip()
        filename = str(row.get("filename") or "").strip()
        rel = str(row.get("relative_path") or "").strip()
        size = _safe_int(row.get("size"), 0)

        file_tokens = _filename_base_tokens(filename)
        file_sexe_key = _extract_filename_sexe_key(file_tokens)

        scored = []
        for cand in candidates:
            s = _score_candidate(file_tokens, file_sexe_key, cand, cfg)
            scored.append(
                {
                    "inscripcio_id": cand.inscripcio_id,
                    "label": cand.label,
                    "score": s["score"],
                    "field_scores": s["field_scores"],
                }
            )
        scored.sort(key=lambda x: (x["score"], -x["inscripcio_id"]), reverse=True)

        top = scored[:kk]
        best = top[0] if top else None
        second = top[1] if len(top) > 1 else None
        best_score = float(best["score"]) if best else 0.0
        margin = best_score - (float(second["score"]) if second else 0.0)
        status = _status_from_scores(best_score, margin, cfg)

        reason = []
        if best:
            fs = best.get("field_scores") or {}
            if fs.get("nom") is not None:
                reason.append(f"nom={fs['nom']}")
            if fs.get("entitat") is not None:
                reason.append(f"entitat={fs['entitat']}")
            if fs.get("sexe") is not None:
                reason.append(f"sexe={fs['sexe']}")
            if fs.get("subcategoria") is not None:
                reason.append(f"subcategoria={fs['subcategoria']}")

        out.append(
            {
                "key": key,
                "filename": filename,
                "relative_path": rel or filename,
                "size": size,
                "status": status,
                "score": round(best_score, 4),
                "margin": round(margin, 4),
                "suggested_inscripcio_id": best["inscripcio_id"] if best else None,
                "suggested_label": best["label"] if best else "",
                "top_candidates": [
                    {
                        "inscripcio_id": c["inscripcio_id"],
                        "label": c["label"],
                        "score": c["score"],
                    }
                    for c in top
                ],
                "reason": ", ".join(reason),
            }
        )
    return out


import heapq
import os
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Set


DEFAULT_MEDIA_MATCHING_CONFIG = {
    "weights": {
        "nom": 60,
        "entitat": 20,
        "sexe": 10,
        "subcategoria": 10,
        "categoria": 0,
    },
    "thresholds": {
        "auto_score_min": 0.85,
        "review_score_min": 0.60,
        "auto_margin_min": 0.08,
    },
}


_SEXE_F_KEYS = {"f", "femeni", "femeni", "femenino", "female", "dona", "girl", "w"}
_SEXE_M_KEYS = {"m", "masculi", "masculi", "masculino", "male", "home", "boy"}


@dataclass
class MatchCandidate:
    inscripcio_id: int
    label: str
    categoria_tokens: Set[str]
    nom_tokens: Set[str]
    entitat_tokens: Set[str]
    sexe_key: str
    subcategoria_tokens: Set[str]


@dataclass
class MediaMatchCandidateIndex:
    candidates: List[MatchCandidate]
    token_to_candidate_indexes: Dict[str, List[int]]
    candidate_count: int

    @classmethod
    def from_candidates(cls, candidates: Sequence[MatchCandidate]) -> "MediaMatchCandidateIndex":
        candidate_list = list(candidates or [])
        token_to_candidate_indexes = defaultdict(list)
        for idx, candidate in enumerate(candidate_list):
            for token in _candidate_shortlist_tokens(candidate):
                token_to_candidate_indexes[token].append(idx)
        return cls(
            candidates=candidate_list,
            token_to_candidate_indexes=dict(token_to_candidate_indexes),
            candidate_count=len(candidate_list),
        )

    def shortlist_indexes_for_file(self, file_tokens: Set[str]) -> List[int]:
        usable_tokens = {token for token in (file_tokens or set()) if _is_shortlist_token(token)}
        if not usable_tokens or self.candidate_count <= 0:
            return []

        counts = Counter()
        for token in usable_tokens:
            candidate_indexes = self.token_to_candidate_indexes.get(token, ())
            if len(candidate_indexes) > max(64, int(self.candidate_count * 0.2)):
                continue
            for idx in candidate_indexes:
                counts[idx] += 1

        if not counts:
            return []

        shortlist_size = len(counts)
        if shortlist_size >= self.candidate_count:
            return []
        if shortlist_size > max(64, int(self.candidate_count * 0.8)):
            return []

        return [idx for idx, _count in counts.most_common()]


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
        "categoria": max(0, _safe_int(raw_weights.get("categoria"), DEFAULT_MEDIA_MATCHING_CONFIG["weights"]["categoria"])),
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


def _is_shortlist_token(token: str) -> bool:
    token = str(token or "").strip()
    if len(token) < 2:
        return False
    if token.isdigit():
        return False
    if token in _SEXE_F_KEYS or token in _SEXE_M_KEYS:
        return False
    return True


def _candidate_shortlist_tokens(candidate: MatchCandidate) -> Set[str]:
    return {
        token
        for token in (
            candidate.categoria_tokens
            | candidate.nom_tokens
            | candidate.entitat_tokens
            | candidate.subcategoria_tokens
        )
        if _is_shortlist_token(token)
    }


def build_inscripcio_media_match_candidates(inscripcions: Iterable) -> List[MatchCandidate]:
    out: List[MatchCandidate] = []
    for ins in inscripcions:
        nom = str(getattr(ins, "nom_i_cognoms", "") or "").strip()
        categoria = str(getattr(ins, "categoria", "") or "").strip()
        entitat = str(getattr(ins, "entitat", "") or "").strip()
        subcategoria = str(getattr(ins, "subcategoria", "") or "").strip()
        sexe = str(getattr(ins, "sexe", "") or "").strip()
        meta_parts = [p for p in [categoria, entitat, subcategoria, sexe] if p]
        label = nom if not meta_parts else f"{nom} ({' · '.join(meta_parts)})"
        out.append(
            MatchCandidate(
                inscripcio_id=int(ins.id),
                label=label,
                categoria_tokens=_tokenize(categoria),
                nom_tokens=_tokenize(nom),
                entitat_tokens=_tokenize(entitat),
                sexe_key=_normalize_sexe(sexe),
                subcategoria_tokens=_tokenize(subcategoria),
            )
        )
    return out


def build_inscripcio_media_match_candidate_index(candidates: Sequence[MatchCandidate]) -> MediaMatchCandidateIndex:
    return MediaMatchCandidateIndex.from_candidates(candidates)


def _score_candidate(
    file_tokens: Set[str],
    file_sexe_key: str,
    candidate: MatchCandidate,
    cfg: dict,
    *,
    include_field_scores: bool = True,
):
    weights = cfg["weights"]

    def _weighted(field_key: str, component: Optional[float]) -> tuple:
        if component is None:
            return 0.0, 0.0
        w = float(max(0, weights.get(field_key, 0)))
        return (w * component), w

    nom_component = _overlap_score(candidate.nom_tokens, file_tokens)
    cat_component = _overlap_score(candidate.categoria_tokens, file_tokens)
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
    field_scores = {} if include_field_scores else None
    field_breakdown = {} if include_field_scores else None
    for field_key, component in (
        ("nom", nom_component),
        ("categoria", cat_component),
        ("entitat", ent_component),
        ("subcategoria", sub_component),
        ("sexe", sexe_component),
    ):
        part_num, part_den = _weighted(field_key, component)
        numer += part_num
        denom += part_den
        if field_scores is not None:
            field_scores[field_key] = None if component is None else round(float(component), 4)
            field_breakdown[field_key] = {
                "score": None if component is None else round(float(component), 4),
                "weight": int(max(0, weights.get(field_key, 0))),
                "contribution": round(float(part_num), 4),
            }

    if denom <= 0:
        total = 0.0
    else:
        total = numer / denom
    total = max(0.0, min(1.0, total))

    if include_field_scores:
        return {
            "score": round(total, 4),
            "field_scores": field_scores or {},
            "field_breakdown": field_breakdown or {},
        }
    return round(total, 4)


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
    candidate_index: Optional[MediaMatchCandidateIndex] = None,
    detail_level: str = "compact",
) -> List[dict]:
    cfg = normalize_media_matching_config(config)
    expanded = str(detail_level or "").strip().lower() == "expanded"
    out: List[dict] = []
    kk = max(1, int(top_k or 1))
    candidate_list = list(candidates or [])
    index = candidate_index or build_inscripcio_media_match_candidate_index(candidate_list)
    indexed_candidates = index.candidates if index.candidates else candidate_list

    for raw in (files or []):
        row = raw if isinstance(raw, dict) else {}
        key = str(row.get("key") or "").strip()
        filename = str(row.get("filename") or "").strip()
        rel = str(row.get("relative_path") or "").strip()
        size = _safe_int(row.get("size"), 0)

        file_tokens = _filename_base_tokens(filename)
        file_sexe_key = _extract_filename_sexe_key(file_tokens)
        shortlist_indexes = index.shortlist_indexes_for_file(file_tokens) if index else []
        scored_candidates = indexed_candidates
        if shortlist_indexes:
            scored_candidates = [indexed_candidates[idx] for idx in shortlist_indexes]

        scored = heapq.nlargest(
            kk,
            (
                (
                    _score_candidate(file_tokens, file_sexe_key, cand, cfg, include_field_scores=False),
                    -cand.inscripcio_id,
                    cand,
                )
                for cand in scored_candidates
            ),
        )

        best_tuple = scored[0] if scored else None
        second_tuple = scored[1] if len(scored) > 1 else None
        best = best_tuple[2] if best_tuple else None
        second_score = float(second_tuple[0]) if second_tuple else 0.0
        best_details = _score_candidate(file_tokens, file_sexe_key, best, cfg, include_field_scores=True) if best else {"score": 0.0, "field_scores": {}, "field_breakdown": {}}
        best_score = float(best_details["score"])
        margin = best_score - second_score
        status = _status_from_scores(best_score, margin, cfg)

        reason = []
        if best:
            fs = best_details.get("field_scores") or {}
            if fs.get("nom") is not None:
                reason.append(f"nom={fs['nom']}")
            if fs.get("categoria") is not None:
                reason.append(f"categoria={fs['categoria']}")
            if fs.get("entitat") is not None:
                reason.append(f"entitat={fs['entitat']}")
            if fs.get("sexe") is not None:
                reason.append(f"sexe={fs['sexe']}")
            if fs.get("subcategoria") is not None:
                reason.append(f"subcategoria={fs['subcategoria']}")

        top_candidates = []
        for score, _neg_inscripcio_id, cand in scored:
            candidate_row = {
                "inscripcio_id": cand.inscripcio_id,
                "label": cand.label,
                "score": round(float(score or 0.0), 4),
            }
            if expanded:
                details = _score_candidate(file_tokens, file_sexe_key, cand, cfg, include_field_scores=True)
                candidate_row["field_scores"] = details.get("field_scores") or {}
                candidate_row["field_breakdown"] = details.get("field_breakdown") or {}
            top_candidates.append(candidate_row)

        out.append(
            {
                "key": key,
                "filename": filename,
                "relative_path": rel or filename,
                "size": size,
                "status": status,
                "score": round(best_score, 4),
                "margin": round(margin, 4),
                "suggested_inscripcio_id": best.inscripcio_id if best else None,
                "suggested_label": best.label if best else "",
                "top_candidates": top_candidates,
                "reason": ", ".join(reason),
            }
        )
        if expanded:
            out[-1]["breakdown"] = {
                "field_scores": best_details.get("field_scores") or {},
                "field_breakdown": best_details.get("field_breakdown") or {},
                "top_candidate_count": len(top_candidates),
            }
    return out


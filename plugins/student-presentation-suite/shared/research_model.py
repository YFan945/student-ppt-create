"""Derive research bookkeeping from one set of content records."""
from __future__ import annotations

import copy


def normalize(pack: dict, task: dict | None = None) -> dict:
    """Fill optional metadata and unambiguous links; never invent source support."""
    pack = copy.deepcopy(pack)
    pack.setdefault("queries", [])

    def rows(key: str) -> list:
        value = pack.get(key, [])
        return value if isinstance(value, list) else []

    for source in rows("sources"):
        if not isinstance(source, dict):
            continue
        source.setdefault("type", "other")
        source.setdefault("tier", "C")
        source.setdefault("independence_group", source.get("origin_id") or source.get("id", ""))
    entities = {e.get("id"): e for kind in ("findings", "data_points", "quotes")
                for e in rows(kind) if isinstance(e, dict) and isinstance(e.get("id"), str)}
    for kind in ("findings", "data_points"):
        for entity in rows(kind):
            if isinstance(entity, dict):
                entity.setdefault("confidence", "medium")
    if pack.get("evidence_contract") == "text-bound-v1":
        return pack
    for eid, entity in entities.items():
        checks = [entity.get("support_check", {})] + [b.get("support_check", {})
                  for b in rows("evidence") if isinstance(b, dict) and b.get("entity_id") == eid]
        limitations = [str(entity.get("limitations") or "")]
        limitations.extend(str(c.get("limitations") or "") for c in checks if isinstance(c, dict))
        if entity.get("source_value") is not None and entity.get("transformation"):
            limitations.append(f"来源原值 {entity['source_value']}；{entity['transformation']}")
        notes = list(dict.fromkeys(part.strip() for s in [str(entity.get("notes") or ""), *limitations]
                                   for part in s.split("；") if part.strip()))
        if notes:
            entity["notes"] = "；".join(notes)
    claims = pack.get("must_verify")
    if claims is None and task:
        claims = [{"id": c["id"], "claim": c["claim"]} for c in task.get("claims", [])]
        pack["must_verify"] = claims
    for claim in rows("must_verify"):
        if not isinstance(claim, dict):
            continue
        linked = [eid for eid, entity in entities.items() if entity.get("claim_id") == claim.get("id") and claim.get("id")]
        if not claim.get("entity_ids") and linked:
            claim["entity_ids"] = linked
        for eid in claim.get("entity_ids", []):
            if isinstance(eid, str) and eid in entities and claim.get("id"):
                entities[eid].setdefault("claim_id", claim["id"])
        if "status" not in claim:
            claim["status"] = "usable" if claim.get("entity_ids") else "unresolved"
    for eid, entity in entities.items():
        if "source_ids" not in entity and "source_id" not in entity:
            refs = list(dict.fromkeys(b.get("source_id") for b in rows("evidence")
                                      if isinstance(b, dict) and b.get("entity_id") == eid and isinstance(b.get("source_id"), str)))
            if refs:
                entity["source_ids"] = refs
    return pack

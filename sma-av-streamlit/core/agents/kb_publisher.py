import json
from typing import List, Optional, Dict, Any, Sequence

from core.tools import servicenow as sn
from core.guards.kb_article_schema import KB_SCHEMA, sanitize_html, content_fingerprint

try:
    from jsonschema import validate, ValidationError  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    validate = None  # type: ignore
    ValidationError = Exception  # type: ignore


class KBPublisherAgent:
    """Agent that plans, publishes, and verifies ServiceNow KB articles."""

    def __init__(self, llm_chat_fn):
        self.chat = llm_chat_fn  # signature: chat(messages, json_mode=False) -> str/json

    # ---------------------------------------------------------------------
    # Planning helpers
    # ---------------------------------------------------------------------
    def _plan_from_sop(
        self,
        sop_markdown: str,
        kb_base_sys_id: str,
        category: Optional[str],
        tags: Sequence[str],
    ) -> Dict[str, Any]:
        system = (
            "You extract structured fields for a ServiceNow KB article. "
            "Return ONLY JSON matching this schema: "
            + json.dumps(KB_SCHEMA)
        )
        tag_list = ", ".join(tags) if tags else "<none provided>"
        user = (
            f"SOP (Markdown)\n---\n{sop_markdown}\n\n"
            f"Constraints\n---\n"
            f"- KB Base sys_id: {kb_base_sys_id}\n"
            f"- Default category: {category or '<none provided>'}\n"
            f"- Default tags: {tag_list}\n"
            "Return JSON only."
        )
        raw = self.chat(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            json_mode=True,
        )
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:  # pragma: no cover - defensive logging aid
            raise RuntimeError(f"LLM did not return valid JSON: {raw}") from exc

        if not isinstance(data, dict):
            raise RuntimeError(f"Expected JSON object from LLM, got: {type(data)!r}")

        # Ensure required defaults are present
        data.setdefault("kb_base_sys_id", kb_base_sys_id)
        if category and not data.get("category"):
            data["category"] = category

        plan_tags: List[str] = []
        if isinstance(data.get("tags"), list):
            plan_tags.extend(str(t).strip() for t in data["tags"] if str(t).strip())
        if tags:
            plan_tags.extend(str(t).strip() for t in tags if str(t).strip())
        if plan_tags:
            # Deduplicate while preserving order
            seen = set()
            deduped = []
            for tag in plan_tags:
                if tag not in seen:
                    seen.add(tag)
                    deduped.append(tag)
            data["tags"] = deduped
        elif "tags" in data:
            data["tags"] = []

        return data

    def _normalize_plan(self, plan: Dict[str, Any]) -> Dict[str, Any]:
        normalized = dict(plan)
        normalized["html"] = sanitize_html(normalized.get("html", ""))
        # Ensure tags are always a list of strings
        tags = normalized.get("tags", [])
        if isinstance(tags, list):
            normalized["tags"] = [str(t).strip() for t in tags if str(t).strip()]
        else:
            normalized["tags"] = [str(tags).strip()] if tags else []
        return normalized

    def _validate_plan(self, plan: Dict[str, Any]) -> None:
        if not validate:
            return
        try:
            validate(plan, KB_SCHEMA)  # type: ignore[arg-type]
        except ValidationError as exc:  # pragma: no cover - runtime feedback only
            raise ValueError(f"Plan failed schema validation: {exc.message}") from exc

    # ---------------------------------------------------------------------
    # Acting & verification helpers
    # ---------------------------------------------------------------------
    def _act_publish(
        self,
        plan: Dict[str, Any],
        attachments: Sequence[str],
        existing_sys_id: Optional[str],
    ) -> Dict[str, Any]:
        short_description = plan["short_description"]
        html = plan["html"]
        kb_base_sys_id = plan["kb_base_sys_id"]
        category = plan.get("category")
        valid_to = plan.get("valid_to")
        tags = plan.get("tags") or []
        if isinstance(tags, list):
            tag_value: Optional[str] = ",".join(tags) if tags else None
        else:
            tag_value = str(tags) if tags else None

        extra: Dict[str, Any] = {}
        if category:
            extra["category"] = category
        if valid_to:
            extra["valid_to"] = valid_to
        if tag_value:
            extra["tags"] = tag_value

        if existing_sys_id:
            record = sn.kb_update(
                existing_sys_id,
                short_description=short_description,
                text=html,
                kb_knowledge_base=kb_base_sys_id,
                **extra,
            )
            mode = "update"
            sys_id = existing_sys_id
        else:
            record = sn.kb_create(
                short_description=short_description,
                html_text=html,
                kb_base_sys_id=kb_base_sys_id,
                **extra,
            )
            mode = "create"
            sys_id = record.get("sys_id")

        attachment_results = []
        for path in attachments:
            attachment_results.append(sn.kb_attach(sys_id, path))

        record = dict(record)
        record.setdefault("sys_id", sys_id)
        record.setdefault("mode", mode)
        if attachment_results:
            record["attachments"] = attachment_results
        return record

    def _verify(self, sys_id: str) -> Dict[str, Any]:
        try:
            record = sn.kb_get(sys_id)
        except Exception as exc:  # pragma: no cover - network/runtime errors
            return {"ok": False, "error": str(exc), "record": None}

        normalized: Dict[str, Any] = {
            "sys_id": record.get("sys_id", sys_id),
            "number": record.get("number"),
            "short_description": record.get("short_description", ""),
            "html": record.get("text") or record.get("article_body") or "",
            "kb_base_sys_id": record.get("kb_knowledge_base"),
        }
        if record.get("category"):
            normalized["category"] = record.get("category")
        if record.get("valid_to"):
            normalized["valid_to"] = record.get("valid_to")
        tags = record.get("tags")
        if isinstance(tags, list):
            normalized["tags"] = tags
        elif isinstance(tags, str) and tags.strip():
            normalized["tags"] = [t.strip() for t in tags.split(",") if t.strip()]

        candidate = {
            k: normalized[k]
            for k in ("short_description", "html", "kb_base_sys_id", "category", "tags", "valid_to")
            if k in normalized
        }
        ok = True
        errors: List[str] = []
        if validate:
            try:
                validate(candidate, KB_SCHEMA)  # type: ignore[arg-type]
            except ValidationError as exc:  # pragma: no cover
                ok = False
                errors.append(exc.message)

        normalized["fingerprint"] = content_fingerprint(
            {
                "short_description": normalized.get("short_description", ""),
                "html": normalized.get("html", ""),
            }
        )

        return {
            "ok": ok,
            "errors": errors,
            "record": record,
            "normalized": normalized,
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def run(
        self,
        sop_markdown: str,
        kb_base_sys_id: str,
        category: Optional[str] = None,
        tags: Optional[Sequence[str]] = None,
        attachments: Optional[Sequence[str]] = None,
        publish_if_allowed: bool = True,
        existing_sys_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        tags = list(tags or [])
        attachments = list(attachments or [])

        plan = self._plan_from_sop(sop_markdown, kb_base_sys_id, category, tags)
        plan = self._normalize_plan(plan)
        self._validate_plan(plan)
        fingerprint = content_fingerprint(plan)

        result: Dict[str, Any] = {
            "plan": plan,
            "fingerprint": fingerprint,
            "mode": "update" if existing_sys_id else "create",
            "published": False,
        }

        if not publish_if_allowed:
            return result

        publish_record = self._act_publish(plan, attachments, existing_sys_id)
        sys_id = publish_record.get("sys_id")
        verification = self._verify(sys_id) if sys_id else {"ok": False, "error": "Missing sys_id"}

        result.update(
            {
                "published": True,
                "service_now": publish_record,
                "verification": verification,
            }
        )
        return result

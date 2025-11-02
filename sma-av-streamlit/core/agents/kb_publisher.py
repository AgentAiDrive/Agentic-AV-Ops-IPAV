"""ServiceNow knowledge base publisher agent."""
import json
from typing import List, Optional, Dict, Any, Callable

from core.tools import servicenow as sn
from core.guards.kb_article_schema import KB_SCHEMA, sanitize_html, content_fingerprint

try:  # Optional dependency used when available
    from jsonschema import validate, ValidationError  # type: ignore
except Exception:  # pragma: no cover - jsonschema is optional
    validate = None  # type: ignore
    ValidationError = Exception  # type: ignore


class KBPublisherAgent:
    """Orchestrates SOP → ServiceNow KB publication workflow."""

    def __init__(self, llm_chat_fn: Callable[..., Any]):
        self.chat = llm_chat_fn  # signature varies per runtime integration

    # ------------------------------------------------------------------
    # LLM planning helpers
    # ------------------------------------------------------------------
    def _strip_code_fences(self, text: str) -> str:
        stripped = text.strip()
        if stripped.startswith("```"):
            lines = stripped.splitlines()
            if lines:
                first = lines.pop(0)
                if first.startswith("```") and lines:
                    if lines[-1].strip() == "```":
                        lines.pop()
                stripped = "\n".join(lines).strip()
        return stripped

    def _call_llm(self, system_prompt: str, user_prompt: str) -> Any:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        attempts = [
            lambda: self.chat(messages, json_mode=True),
            lambda: self.chat(messages),
            lambda: self.chat(system_prompt, messages),
            lambda: self.chat(system_prompt, messages, True),
        ]

        errors: List[str] = []
        for attempt in attempts:
            try:
                return attempt()
            except TypeError as exc:
                errors.append(str(exc))
        raise TypeError(
            "llm_chat_fn signature not supported. Attempted variants yielded: "
            + "; ".join(errors)
        )

    def _plan_from_sop(
        self,
        sop_markdown: str,
        kb_base_sys_id: str,
        category: Optional[str],
        tags: List[str],
    ) -> Dict[str, Any]:
        system = (
            "You extract structured fields for a ServiceNow KB article. "
            "Return ONLY JSON matching this schema: " + json.dumps(KB_SCHEMA)
        )
        user = (
            "SOP (Markdown):\n" + sop_markdown.strip() + "\n\n"
            f"KB base sys_id: {kb_base_sys_id}\n"
            f"Suggested category: {category or 'unknown'}\n"
            f"Suggested tags: {', '.join(tags) if tags else 'none'}"
        )

        raw = self._call_llm(system, user)
        if isinstance(raw, dict):
            plan = raw
        else:
            text = self._strip_code_fences(str(raw))
            try:
                plan = json.loads(text)
            except json.JSONDecodeError as exc:  # pragma: no cover - defensive path
                raise ValueError(f"LLM response is not valid JSON: {text}") from exc

        if not isinstance(plan, dict):
            raise ValueError(f"LLM response must be a JSON object, got: {type(plan)!r}")

        normalized = dict(plan)
        normalized.setdefault("kb_base_sys_id", kb_base_sys_id)
        if not normalized.get("kb_base_sys_id"):
            normalized["kb_base_sys_id"] = kb_base_sys_id

        if category and not normalized.get("category"):
            normalized["category"] = category
        elif category and normalized.get("category"):
            normalized["category"] = str(normalized["category"]) or category

        plan_tags = normalized.get("tags")
        norm_tags: List[str]
        if isinstance(plan_tags, list):
            norm_tags = [str(t).strip() for t in plan_tags if str(t).strip()]
        elif isinstance(plan_tags, str):
            candidates = [part.strip() for part in plan_tags.replace(";", ",").split(",")]
            norm_tags = [t for t in candidates if t]
        else:
            norm_tags = []
        for t in tags:
            tt = str(t).strip()
            if tt and tt not in norm_tags:
                norm_tags.append(tt)
        normalized["tags"] = norm_tags

        if validate:
            try:
                validate(normalized, KB_SCHEMA)
            except ValidationError as exc:  # pragma: no cover - depends on optional pkg
                raise ValueError(f"LLM output failed schema validation: {exc.message}") from exc

        return normalized

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------
    def _prepare_record(self, plan: Dict[str, Any]) -> Dict[str, Any]:
        record = {
            "short_description": str(plan["short_description"]).strip(),
            "html": sanitize_html(str(plan["html"])),
            "kb_base_sys_id": str(plan["kb_base_sys_id"]).strip(),
        }
        if plan.get("category"):
            record["category"] = str(plan["category"]).strip()
        if plan.get("valid_to"):
            record["valid_to"] = str(plan["valid_to"]).strip()
        if plan.get("tags"):
            record["tags"] = list(plan["tags"])
        return record

    def _create_article(self, record: Dict[str, Any]) -> Dict[str, Any]:
        extra = {}
        if record.get("category"):
            extra["category"] = record["category"]
        if record.get("valid_to"):
            extra["valid_to"] = record["valid_to"]
        return sn.kb_create(
            short_description=record["short_description"],
            html_text=record["html"],
            kb_base_sys_id=record["kb_base_sys_id"],
            **extra,
        )

    def _update_article(self, sys_id: str, record: Dict[str, Any]) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "short_description": record["short_description"],
            "text": record["html"],
        }
        if record.get("category"):
            payload["category"] = record["category"]
        if record.get("valid_to"):
            payload["valid_to"] = record["valid_to"]
        return sn.kb_update(sys_id, **payload)

    def _attach_files(self, sys_id: str, attachments: List[str]) -> List[Dict[str, Any]]:
        results = []
        for path in attachments:
            attachment_result = sn.kb_attach(sys_id, path)
            results.append({"file": path, "result": attachment_result})
        return results

    def _maybe_publish(self, sys_id: str, publish: bool) -> Dict[str, Any]:
        if not publish:
            return {"attempted": False}
        try:
            result = sn.kb_update(sys_id, workflow_state="published")
            return {"attempted": True, "status": "success", "result": result}
        except Exception as exc:  # pragma: no cover - depends on SN behaviour
            return {"attempted": True, "status": "failed", "error": str(exc)}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def run(
        self,
        sop_markdown: str,
        kb_base_sys_id: str,
        category: Optional[str] = None,
        tags: Optional[List[str]] = None,
        attachments: Optional[List[str]] = None,
        publish_if_allowed: bool = False,
        existing_sys_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        tags = list(tags or [])
        attachments = list(attachments or [])

        plan = self._plan_from_sop(sop_markdown, kb_base_sys_id, category, tags)
        record = self._prepare_record(plan)
        fingerprint = content_fingerprint(record)

        if existing_sys_id:
            action_result = self._update_article(existing_sys_id, record)
            sys_id = existing_sys_id
            mode = "update"
        else:
            action_result = self._create_article(record)
            sys_id = str(action_result.get("sys_id", "")).strip() or existing_sys_id
            if not sys_id:
                raise RuntimeError("ServiceNow create response missing sys_id")
            mode = "create"

        attachment_results = self._attach_files(sys_id, attachments) if attachments else []
        publish_info = self._maybe_publish(sys_id, publish_if_allowed)
        verification = sn.kb_get(sys_id)

        return {
            "plan": plan,
            "record": record,
            "action": {"mode": mode, "result": action_result},
            "attachments": attachment_results,
            "publish": publish_info,
            "verify": verification,
            "fingerprint": fingerprint,
        }

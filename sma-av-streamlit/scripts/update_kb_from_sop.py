"""Update an existing ServiceNow KB article using SOP markdown as the source."""
import argparse
import json
from pathlib import Path
from typing import Any, Optional

from core.agents.kb_publisher import KBPublisherAgent
from core.llm.client import chat
from core.tools import servicenow as sn


def _resolve_reference(value: Any) -> Optional[str]:
    if isinstance(value, dict):
        return value.get("value") or value.get("sys_id") or value.get("display_value")
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sop_path", help="Path to the SOP markdown file")
    parser.add_argument("kb_sys_id", help="ServiceNow sys_id of the KB article to update")
    parser.add_argument(
        "--kb-base-sys-id",
        dest="kb_base_sys_id",
        help="Override the KB base sys_id (auto-detected when omitted)",
    )
    parser.add_argument(
        "--category",
        help="Override the article category (falls back to existing record)",
    )
    parser.add_argument(
        "--tag",
        dest="tags",
        action="append",
        default=[],
        help="Tag to associate with the article (can be repeated)",
    )
    parser.add_argument(
        "--attachment",
        dest="attachments",
        action="append",
        default=[],
        help="Path to a file to attach after updating (can be repeated)",
    )
    parser.add_argument(
        "--publish",
        action="store_true",
        help="Attempt to move the article to the published state",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    sop = Path(args.sop_path).read_text(encoding="utf-8")

    existing_record = sn.kb_get(args.kb_sys_id)

    kb_base_sys_id = args.kb_base_sys_id or _resolve_reference(
        existing_record.get("kb_knowledge_base")
    )
    if not kb_base_sys_id:
        raise SystemExit(
            "Unable to determine kb_base_sys_id; pass --kb-base-sys-id explicitly."
        )

    category = args.category or _resolve_reference(existing_record.get("category"))

    agent = KBPublisherAgent(llm_chat_fn=chat)
    result = agent.run(
        sop_markdown=sop,
        kb_base_sys_id=kb_base_sys_id,
        category=category,
        tags=args.tags,
        attachments=args.attachments,
        publish_if_allowed=args.publish,
        existing_sys_id=args.kb_sys_id,
    )
    result["previous_record"] = existing_record
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

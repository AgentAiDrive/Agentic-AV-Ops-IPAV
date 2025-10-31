"""Utility script to update an existing ServiceNow KB article from an SOP."""

import argparse
import json
from pathlib import Path

from core.agents.kb_publisher import KBPublisherAgent
from core.llm.client import chat


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sop", help="Path to the SOP markdown file")
    parser.add_argument("kb_base_sys_id", help="Target KB base sys_id")
    parser.add_argument("kb_sys_id", help="Existing KB article sys_id to update")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Publish the update. Without this flag a dry-run plan is returned.",
    )
    parser.add_argument(
        "--category",
        help="Override category for the KB article (optional)",
    )
    parser.add_argument(
        "--tag",
        action="append",
        dest="tags",
        default=[],
        help="Additional tag to include. May be provided multiple times.",
    )
    parser.add_argument(
        "--attach",
        action="append",
        dest="attachments",
        default=[],
        help="Attachment to upload with the KB article. Repeat for multiple attachments.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    sop_markdown = Path(args.sop).read_text(encoding="utf-8")

    agent = KBPublisherAgent(llm_chat_fn=chat)
    result = agent.run(
        sop_markdown=sop_markdown,
        kb_base_sys_id=args.kb_base_sys_id,
        category=args.category,
        tags=args.tags,
        attachments=args.attachments,
        publish_if_allowed=args.apply,
        existing_sys_id=args.kb_sys_id,
    )

    print(json.dumps(result, indent=2))
    if not args.apply:
        print("\nDry run complete. Re-run with --apply to push the update.")


if __name__ == "__main__":
    main()

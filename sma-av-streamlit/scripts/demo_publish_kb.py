"""Example script to publish a ServiceNow KB article from a SOP markdown file."""
import argparse
import json
from pathlib import Path

from core.agents.kb_publisher import KBPublisherAgent
from core.llm.client import chat


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sop_path", help="Path to the SOP markdown file")
    parser.add_argument("kb_base_sys_id", help="Target ServiceNow KB base sys_id")
    parser.add_argument(
        "--category",
        default="Operations > AV",
        help="Override category to use for the new article",
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
        help="Path to a file to attach (can be repeated)",
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
    agent = KBPublisherAgent(llm_chat_fn=chat)
    result = agent.run(
        sop_markdown=sop,
        kb_base_sys_id=args.kb_base_sys_id,
        category=args.category,
        tags=args.tags,
        attachments=args.attachments,
        publish_if_allowed=args.publish,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

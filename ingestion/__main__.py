"""Command line entry point for Plaid ingestion.

    python -m ingestion link-sandbox      create a sandbox Item
    python -m ingestion list-items        show linked Items (tokens redacted)
    python -m ingestion fetch             fetch changes and print a summary
    python -m ingestion sync              fetch changes and write to Snowflake
    python -m ingestion snapshot          land account and balance snapshots
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import plaid

from ingestion import plaid_client
from ingestion.config import ConfigError, load_settings
from ingestion.items import PlaidItem, items_for_environment, load_items, save_item

logger = logging.getLogger("ingestion")


def cmd_link_sandbox(args: argparse.Namespace) -> int:
    settings = load_settings()
    if settings.is_production:
        print(
            "Refusing to run: PLAID_ENV is production. Sandbox Items can only be "
            "created in the sandbox environment. Production accounts require the "
            "Link flow.",
            file=sys.stderr,
        )
        return 2

    client = plaid_client.build_client(settings)
    access_token = plaid_client.create_sandbox_item(client, args.institution)
    item_id = plaid_client.get_item_id(client, access_token)
    name = plaid_client.get_institution_name(client, args.institution)

    save_item(
        PlaidItem(
            item_id=item_id,
            access_token=access_token,
            institution_id=args.institution,
            institution_name=name,
            environment=settings.plaid_env,
        )
    )
    print(f"Linked sandbox Item {item_id} ({name or args.institution})")
    print("Access token stored in .plaid_items.json (gitignored, mode 600)")
    return 0


def cmd_list_items(args: argparse.Namespace) -> int:
    items = load_items()
    if not items:
        print("No linked Items. Run: python -m ingestion link-sandbox")
        return 0
    for item in items.values():
        print(json.dumps(item.redacted(), indent=2))
    return 0


def cmd_fetch(args: argparse.Namespace) -> int:
    settings = load_settings()
    items = items_for_environment(settings.plaid_env)
    if not items:
        print(
            f"No linked Items for environment {settings.plaid_env!r}.",
            file=sys.stderr,
        )
        return 1

    client = plaid_client.build_client(settings)
    for item in items:
        print(f"\nItem {item.item_id} ({item.institution_name or 'unknown'})")
        totals = {"added": 0, "modified": 0, "removed": 0}
        pages = 0
        final_cursor = ""

        for page in plaid_client.sync_transactions(client, item.access_token):
            pages += 1
            totals["added"] += len(page.added)
            totals["modified"] += len(page.modified)
            totals["removed"] += len(page.removed)
            final_cursor = page.next_cursor

            if args.save_fixture and pages == 1:
                path = Path(args.save_fixture)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(
                    json.dumps(
                        {
                            "added": page.added[:5],
                            "modified": page.modified[:5],
                            "removed": page.removed[:5],
                            "has_more": page.has_more,
                        },
                        indent=2,
                        default=str,
                    )
                    + "\n"
                )
                print(f"  wrote fixture to {path}")

        print(f"  {pages} page(s): {totals}")
        print(f"  cursor now ...{final_cursor[-12:] if final_cursor else '(none)'}")
        print("  (nothing written to Snowflake; this command is read only)")
    return 0



def cmd_sync(args: argparse.Namespace) -> int:
    from ingestion.loader import SnowflakeLoader
    from ingestion.sync import snapshot_item, sync_item

    settings = load_settings()
    items = items_for_environment(settings.plaid_env)
    if not items:
        print(
            f"No linked Items for environment {settings.plaid_env!r}.",
            file=sys.stderr,
        )
        return 1

    client = plaid_client.build_client(settings)
    with SnowflakeLoader(settings.snowflake_connection) as loader:
        for item in items:
            print(f"\nItem {item.item_id} ({item.institution_name or 'unknown'})")
            if args.command == "sync":
                result = sync_item(client, loader, item)
                print(
                    f"  {result.pages} page(s), {result.rows}, "
                    f"batch {result.batch_id}"
                )
                print(f"  cursor committed atomically with {result.total_rows} rows")
            else:
                wrote = snapshot_item(client, loader, item)
                print(f"  snapshot written: {wrote}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ingestion", description=__doc__)
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    link = sub.add_parser("link-sandbox", help="create a sandbox Item")
    link.add_argument(
        "--institution",
        default="ins_109508",
        help="sandbox institution id (default: First Platypus Bank)",
    )
    link.set_defaults(func=cmd_link_sandbox)

    listing = sub.add_parser("list-items", help="show linked Items")
    listing.set_defaults(func=cmd_list_items)

    fetch = sub.add_parser("fetch", help="fetch changes and print a summary")
    fetch.add_argument(
        "--save-fixture",
        metavar="PATH",
        help="write a truncated first page to PATH as a test fixture",
    )
    fetch.set_defaults(func=cmd_fetch)

    sync = sub.add_parser("sync", help="fetch changes and write to Snowflake")
    sync.set_defaults(func=cmd_sync)

    snapshot = sub.add_parser(
        "snapshot", help="land account and balance snapshots"
    )
    snapshot.set_defaults(func=cmd_sync)

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    try:
        return args.func(args)
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    except plaid.ApiException as exc:
        body = json.loads(exc.body) if exc.body else {}
        print(
            f"Plaid API error: {body.get('error_code')} - "
            f"{body.get('error_message')}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

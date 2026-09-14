import argparse
import sys

from app.config.logging import configure_logging
from app.config.settings import get_settings
from app.database.mongodb import get_client, initialize_database
from app.pipeline import run_pipeline
from app.providers.factory import ProviderFactory


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CoS Sales Agent")
    parser.add_argument("--healthcheck", action="store_true")
    parser.add_argument("--mode", choices=["demo"], default=None)
    parser.add_argument("--reset-demo", action="store_true")
    return parser


def run_healthcheck(settings) -> tuple[bool, list[str]]:
    lines = ["CoS Sales Agent Health Check", ""]
    ok = True
    lines.append("✓ Configuration loaded")

    try:
        client = get_client(settings.mongodb_uri)
        db = initialize_database(client, settings.mongodb_database)
        client.admin.command("ping") if hasattr(client, "admin") else None
        lines.append("✓ MongoDB connected")
        lines.append("✓ MongoDB indexes ready")
    except Exception as exc:  # pragma: no cover - exercised via integration only
        ok = False
        lines.append(f"✗ MongoDB connection failed: {exc}")

    lines.append(f"✓ Email provider: {settings.email_provider.upper()}")
    lines.append(f"✓ Calendar provider: {settings.calendar_provider.upper()}")
    lines.append(f"✓ LLM provider: {settings.llm_provider.upper()}")

    mcp_email_marker = "✓" if settings.mcp_email_enabled else "○"
    mcp_calendar_marker = "✓" if settings.mcp_calendar_enabled else "○"
    lines.append(f"{mcp_email_marker} MCP Email: {'enabled' if settings.mcp_email_enabled else 'disabled'}")
    lines.append(f"{mcp_calendar_marker} MCP Calendar: {'enabled' if settings.mcp_calendar_enabled else 'disabled'}")

    lines.append("")
    lines.append("System ready." if ok else "System not ready.")
    return ok, lines


def run_reset_demo(db, settings) -> None:
    if settings.app_env != "development" and not settings.simulation_mode:
        raise PermissionError("--reset-demo is only permitted when APP_ENV=development or SIMULATION_MODE=true")

    for collection_name in [
        "emails",
        "threads",
        "context_snapshots",
        "knowledge_items",
        "reply_drafts",
        "calendar_actions",
        "processing_runs",
        "entities",
        "opportunities",
        "activities",
    ]:
        db[collection_name].delete_many({})


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    settings = get_settings()
    configure_logging(settings.log_level)

    if args.healthcheck:
        ok, lines = run_healthcheck(settings)
        print("\n".join(lines))
        return 0 if ok else 1

    if args.reset_demo:
        try:
            client = get_client(settings.mongodb_uri)
            db = initialize_database(client, settings.mongodb_database)
            run_reset_demo(db, settings)
            print("Demo data reset.")
            return 0
        except PermissionError as exc:
            print(f"Refused: {exc}")
            return 1

    if args.mode == "demo":
        client = get_client(settings.mongodb_uri)
        db = initialize_database(client, settings.mongodb_database)

        email_provider = ProviderFactory.create_email_provider(settings)
        llm_provider = ProviderFactory.create_llm_provider(settings)
        calendar_provider = ProviderFactory.create_calendar_provider(settings)

        summary = run_pipeline(db, email_provider, llm_provider, calendar_provider, settings)
        print(
            f"Demo run complete: processed={summary.processed} completed={summary.completed} "
            f"failed={summary.failed} skipped={summary.skipped}"
        )
        return 0

    build_arg_parser().print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())

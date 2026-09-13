from pymongo.database import Database


def initialize_indexes(db: Database) -> None:
    db.emails.create_index("message_id", unique=True)
    db.emails.create_index("processing_status.stage")

    db.threads.create_index("thread_id", unique=True)

    db.context_snapshots.create_index(
        [("thread_id", 1), ("triggering_email_id", 1)], unique=True
    )
    db.context_snapshots.create_index([("thread_id", 1), ("context_version", 1)])

    db.knowledge_items.create_index(
        [("thread_id", 1), ("subject_key", 1), ("predicate", 1), ("fact_key", 1)],
        unique=True,
    )

    db.reply_drafts.create_index("source_email_id", unique=True)

    db.calendar_actions.create_index(
        [("thread_id", 1), ("meeting_fingerprint", 1)], unique=True
    )

    db.processing_runs.create_index("started_at")

"""Quick, ad-hoc utility to print how processed emails connect to canonical entities.

Not part of the tested pipeline -- a one-off inspection tool. Run with:
    python inspect_entities.py
"""

from pymongo import MongoClient

from app.config.settings import get_settings

_ENTITY_COLLECTIONS = {
    "people": "people",
    "projects": "projects",
    "commitments": "commitments",
    "follow_ups": "follow_ups",
    "meetings": "meetings",
    "personal": "personal_items",
}

_ENTITY_SUMMARY_FIELDS = {
    "people": lambda d: f"{d.get('name')} <{d.get('email') or 'no email'}> (review_flag={d.get('review_flag')})",
    "projects": lambda d: f"{d.get('project')} (entity={d.get('entity')}, goal_pillar={d.get('goal_pillar')})",
    "commitments": lambda d: f"{d.get('what')!r} [{d.get('class')}] due={d.get('committed_date')} ({d.get('date_type')})",
    "follow_ups": lambda d: f"commitment_id={d.get('commitment_id')} thread_id={d.get('thread_id')}",
    "meetings": lambda d: f"date={d.get('date')} actionable={d.get('actionable')}",
    "personal": lambda d: f"{d.get('type')}: {d.get('description')} (due={d.get('date_or_deadline')})",
}


def main() -> None:
    settings = get_settings()
    client = MongoClient(settings.mongodb_uri)
    db = client[settings.mongodb_database]

    entity_docs: dict[str, dict[str, dict]] = {
        key: {doc["id"]: doc for doc in db[collection].find({}, {"_id": 0})}
        for key, collection in _ENTITY_COLLECTIONS.items()
    }

    emails = list(db.emails.find({}, {"_id": 0}).sort("timestamp", 1))
    if not emails:
        print("No processed emails found. Run process_email on at least one email first.")
        return

    for email in emails:
        print("=" * 100)
        print(f"EMAIL  {email.get('subject')}")
        print(f"       from={email['from']['email']}  timestamp={email.get('timestamp')}")
        print(f"       status={email.get('processing_status', {}).get('stage')}"
              f"  goal_pillar={email.get('goal_pillar')}  label={email.get('label_applied')}")

        refs = email.get("entities_referenced")
        if not refs:
            print("       (not yet processed through ENTITIES_PROCESSED -- no entity links)")
            continue

        any_refs = False
        for key, ids in refs.items():
            for entity_id in ids:
                any_refs = True
                doc = entity_docs.get(key, {}).get(entity_id)
                summary = _ENTITY_SUMMARY_FIELDS[key](doc) if doc else "(not found)"
                print(f"       -> [{key}] {entity_id}: {summary}")

        if not any_refs:
            print("       (no entities referenced from this email)")

    print("=" * 100)
    print("\nTotals:")
    for key, collection in _ENTITY_COLLECTIONS.items():
        print(f"  {collection}: {db[collection].count_documents({})}")


if __name__ == "__main__":
    main()

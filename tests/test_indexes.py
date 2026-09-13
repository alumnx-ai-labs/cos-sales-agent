import mongomock

from app.database.indexes import initialize_indexes


def test_initialize_indexes_creates_expected_unique_indexes():
    client = mongomock.MongoClient()
    db = client["cos_sales_test"]

    initialize_indexes(db)
    initialize_indexes(db)  # must be safe to call twice

    def index_keys(collection_name):
        return {
            tuple(spec["key"]): spec.get("unique", False)
            for spec in db[collection_name].index_information().values()
            if spec["key"] != [("_id", 1)] and spec.get("unique", False)
        }

    assert index_keys("emails") == {(("message_id", 1),): True}
    assert index_keys("threads") == {(("thread_id", 1),): True}
    assert index_keys("context_snapshots") == {
        (("thread_id", 1), ("triggering_email_id", 1)): True
    }
    assert index_keys("knowledge_items") == {
        (("thread_id", 1), ("subject_key", 1), ("predicate", 1), ("fact_key", 1)): True
    }
    assert index_keys("reply_drafts") == {(("source_email_id", 1),): True}
    assert index_keys("calendar_actions") == {
        (("thread_id", 1), ("meeting_fingerprint", 1)): True
    }

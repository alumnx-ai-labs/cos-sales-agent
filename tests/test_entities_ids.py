import mongomock

from app.entities.ids import next_id


def test_next_id_is_sequential_and_zero_padded():
    client = mongomock.MongoClient()
    db = client["cos_sales_test"]

    assert next_id(db, "PER-") == "PER-001"
    assert next_id(db, "PER-") == "PER-002"


def test_next_id_is_independent_per_prefix():
    client = mongomock.MongoClient()
    db = client["cos_sales_test"]

    assert next_id(db, "PER-") == "PER-001"
    assert next_id(db, "PRJ-") == "PRJ-001"
    assert next_id(db, "PER-") == "PER-002"


def test_next_id_grows_past_three_digits_without_erroring():
    client = mongomock.MongoClient()
    db = client["cos_sales_test"]

    for _ in range(1000):
        result = next_id(db, "COM-")

    assert result == "COM-1000"

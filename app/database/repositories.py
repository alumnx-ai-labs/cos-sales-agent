from datetime import datetime, timezone
from typing import Any

from pymongo import ReturnDocument
from pymongo.collection import Collection
from pymongo.database import Database


class _BaseRepository:
    collection_name: str

    def __init__(self, db: Database) -> None:
        self._collection: Collection = db[self.collection_name]

    def upsert_by_key(self, key: dict[str, Any], document: dict[str, Any]) -> dict[str, Any]:
        self._collection.update_one(key, {"$set": document}, upsert=True)
        return self._collection.find_one(key, {"_id": 0})

    def find_one(self, key: dict[str, Any]) -> dict[str, Any] | None:
        return self._collection.find_one(key, {"_id": 0})

    def find_many(self, key: dict[str, Any]) -> list[dict[str, Any]]:
        return list(self._collection.find(key, {"_id": 0}))


class EmailRepository(_BaseRepository):
    collection_name = "emails"

    def set_stage(
        self,
        message_id: str,
        stage: str,
        error: str | None = None,
        failed_stage: str | None = None,
    ) -> None:
        self._collection.update_one(
            {"message_id": message_id},
            {
                "$set": {
                    "processing_status": {
                        "stage": stage,
                        "error": error,
                        "failed_stage": failed_stage,
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    }
                }
            },
            upsert=True,
        )


class ThreadRepository(_BaseRepository):
    collection_name = "threads"


class ContextSnapshotRepository(_BaseRepository):
    collection_name = "context_snapshots"

    def latest_for_thread(self, thread_id: str) -> dict[str, Any] | None:
        return self._collection.find_one(
            {"thread_id": thread_id}, {"_id": 0}, sort=[("context_version", -1)]
        )

    def all_for_thread(self, thread_id: str) -> list[dict[str, Any]]:
        return list(
            self._collection.find({"thread_id": thread_id}, {"_id": 0}).sort("context_version", 1)
        )


class KnowledgeRepository(_BaseRepository):
    collection_name = "knowledge_items"

    def all_for_thread(self, thread_id: str) -> list[dict[str, Any]]:
        return self.find_many({"thread_id": thread_id})


class ReplyDraftRepository(_BaseRepository):
    collection_name = "reply_drafts"


class CalendarActionRepository(_BaseRepository):
    collection_name = "calendar_actions"


class ProcessingRunRepository(_BaseRepository):
    collection_name = "processing_runs"


class EntityRepository(_BaseRepository):
    collection_name = "entities"


class OpportunityRepository(_BaseRepository):
    collection_name = "opportunities"


class ActivityRepository(_BaseRepository):
    collection_name = "activities"


class CounterRepository(_BaseRepository):
    collection_name = "counters"

    def increment_and_get(self, prefix: str) -> int:
        doc = self._collection.find_one_and_update(
            {"_id": prefix},
            {"$inc": {"seq": 1}},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return doc["seq"]


class PersonRepository(_BaseRepository):
    collection_name = "people"


class ProjectRepository(_BaseRepository):
    collection_name = "projects"


class CommitmentRepository(_BaseRepository):
    collection_name = "commitments"

    def all_for_thread(self, thread_id: str) -> list[dict]:
        return self.find_many({"thread_id": thread_id})


class FollowUpRepository(_BaseRepository):
    collection_name = "follow_ups"


class MeetingRepository(_BaseRepository):
    collection_name = "meetings"

    def all_for_thread(self, thread_id: str) -> list[dict]:
        return self.find_many({"thread_id": thread_id})


class PersonalItemRepository(_BaseRepository):
    collection_name = "personal_items"

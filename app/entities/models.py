from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Person(BaseModel):
    id: str
    name: str
    email: str | None = None
    aliases: list[str] = Field(default_factory=list)
    org: str | None = None
    type: str | None = None
    goal_pillar: str | None = None
    role_in_pillar: str | None = None
    tier: str | None = None
    voice_register: str | None = None
    last_inbound: datetime | None = None
    last_outbound: datetime | None = None
    reports_to: str | None = None
    open_threads: list[str] = Field(default_factory=list)
    note_link: str | None = None
    review_flag: bool = False
    source: str = "gmail"


class Project(BaseModel):
    id: str
    project: str
    cluster: str | None = None
    entity: str | None = None
    goal_pillar: str | None = None
    objective: str | None = None
    target: str | None = None
    status: str | None = None
    owner: str | None = None
    collaborators: list[str] = Field(default_factory=list)
    next_milestone: str | None = None
    due: datetime | None = None
    health: str | None = None
    last_movement: datetime | None = None
    note_link: str | None = None
    source: str = "gmail"


class Commitment(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    what: str
    commitment_class: Literal["mine", "owed_to_me", "theirs", "recap"] = Field(alias="class")
    importance: str | None = None
    owed_by: str | None = None
    owed_to: str | None = None
    source_record: str
    made_on: datetime
    committed_date: datetime | None = None
    date_type: Literal["stated", "inferred", "window"] | None = None
    status: str = "open"
    goal_pillar: str | None = None
    project_id: str | None = None


class FollowUp(BaseModel):
    id: str
    commitment_id: str | None = None
    thread_id: str | None = None

    @model_validator(mode="after")
    def _exactly_one_link(self) -> "FollowUp":
        if (self.commitment_id is None) == (self.thread_id is None):
            raise ValueError("exactly one of commitment_id or thread_id must be set")
        return self


class Meeting(BaseModel):
    id: str
    date: datetime | None = None
    attendees: list[str] = Field(default_factory=list)
    project_or_pillar: str | None = None
    minutes_record: str | None = None
    actions_raised: list[str] = Field(default_factory=list)
    next_meeting_date: datetime | None = None
    agenda_target: str | None = None
    actionable: bool = False
    agenda_written: bool = False


class PersonalItem(BaseModel):
    id: str
    type: str
    description: str
    date_or_deadline: datetime | None = None
    status: str = "open"

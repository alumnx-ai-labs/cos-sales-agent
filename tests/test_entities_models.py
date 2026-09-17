import pytest
from pydantic import ValidationError

from app.entities.models import Commitment, FollowUp, Meeting, Person, PersonalItem, Project


def test_person_defaults():
    person = Person(id="PER-001", name="Jane Doe", email="jane@example.com")
    assert person.aliases == []
    assert person.review_flag is False
    assert person.source == "gmail"


def test_project_has_no_review_flag_field():
    project = Project(id="PRJ-001", project="Renewal Q4")
    assert not hasattr(project, "review_flag")


def test_commitment_class_field_uses_class_alias():
    commitment = Commitment.model_validate(
        {
            "id": "COM-001",
            "what": "send updated case study",
            "class": "mine",
            "source_record": "msg_001",
            "made_on": "2026-09-13T10:30:00Z",
        }
    )
    assert commitment.commitment_class == "mine"
    dumped = commitment.model_dump(mode="json", by_alias=True)
    assert dumped["class"] == "mine"
    assert "commitment_class" not in dumped


def test_commitment_constructed_by_python_name_also_works():
    commitment = Commitment(
        id="COM-002",
        what="send pricing",
        commitment_class="theirs",
        source_record="msg_002",
        made_on="2026-09-13T10:30:00Z",
    )
    assert commitment.commitment_class == "theirs"


def test_commitment_rejects_invalid_class():
    with pytest.raises(ValidationError):
        Commitment(
            id="COM-003",
            what="x",
            commitment_class="not_a_real_class",
            source_record="msg_003",
            made_on="2026-09-13T10:30:00Z",
        )


def test_follow_up_requires_exactly_one_link():
    with pytest.raises(ValidationError):
        FollowUp(id="FU-001")  # neither set

    with pytest.raises(ValidationError):
        FollowUp(id="FU-002", commitment_id="COM-001", thread_id="thread_1")  # both set

    ok = FollowUp(id="FU-003", commitment_id="COM-001")
    assert ok.thread_id is None


def test_follow_up_has_no_extra_fields():
    follow_up = FollowUp(id="FU-004", thread_id="thread_1")
    assert follow_up.model_dump(mode="json").keys() == {"id", "commitment_id", "thread_id"}


def test_meeting_defaults():
    meeting = Meeting(id="MTG-001")
    assert meeting.attendees == []
    assert meeting.actions_raised == []
    assert meeting.agenda_written is False
    assert meeting.actionable is False


def test_meeting_actionable_can_be_set_true():
    meeting = Meeting(id="MTG-002", actionable=True)
    assert meeting.actionable is True


def test_personal_item_defaults():
    item = PersonalItem(id="PSN-001", type="reminder", description="renew passport")
    assert item.status == "open"

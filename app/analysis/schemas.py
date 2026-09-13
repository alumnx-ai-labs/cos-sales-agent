from pydantic import BaseModel, Field


class Fact(BaseModel):
    subject: str
    predicate: str
    object: str


class EmailAnalysis(BaseModel):
    email_id: str
    summary: str
    intent: str
    entities: list[str] = Field(default_factory=list)
    facts: list[Fact] = Field(default_factory=list)
    requirements: list[str] = Field(default_factory=list)
    pain_points: list[str] = Field(default_factory=list)
    buying_signals: list[str] = Field(default_factory=list)
    objections: list[str] = Field(default_factory=list)
    competitors: list[str] = Field(default_factory=list)
    pricing_mentions: list[str] = Field(default_factory=list)
    commitments: list[str] = Field(default_factory=list)
    action_items: list[str] = Field(default_factory=list)
    meetings: list[str] = Field(default_factory=list)
    people: list[str] = Field(default_factory=list)
    companies: list[str] = Field(default_factory=list)
    products: list[str] = Field(default_factory=list)

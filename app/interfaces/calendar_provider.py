from abc import ABC, abstractmethod

from app.calendar.models import CalendarEvent


class CalendarProvider(ABC):
    @abstractmethod
    def create_event(self, event: CalendarEvent) -> str:
        ...

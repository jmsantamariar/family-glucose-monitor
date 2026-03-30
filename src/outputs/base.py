"""Abstract base class for alert outputs."""
from abc import ABC, abstractmethod


class BaseOutput(ABC):
    @abstractmethod
    def send_alert(self, message: str, glucose_value: int, level: str) -> bool:
        """Send alert. Returns True if successful."""
        ...

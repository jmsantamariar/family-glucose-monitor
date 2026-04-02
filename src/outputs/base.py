"""Abstract base class for alert outputs and Notifier protocol."""
from abc import ABC, abstractmethod
from typing import Protocol, runtime_checkable


@runtime_checkable
class Notifier(Protocol):
    """Protocol for dispatching alert notifications.

    Any object implementing ``notify(message, glucose_value, level) -> bool``
    satisfies this protocol.  Using a :class:`~typing.Protocol` (rather than
    an ABC) keeps coupling minimal: concrete output adapters do **not** need
    to inherit from :class:`Notifier` — they only need to provide a matching
    ``notify`` method.

    :meth:`notify` should return ``True`` if at least one delivery channel
    succeeded, ``False`` otherwise.
    """

    def notify(self, message: str, glucose_value: int, level: str) -> bool:
        """Send an alert notification.

        :param message: Human-readable alert text.
        :param glucose_value: Current glucose value in mg/dL.
        :param level: Alert level (``"low"``, ``"high"``, or ``"normal"``).
        :returns: ``True`` if at least one channel delivered successfully.
        """
        ...


class BaseOutput(ABC):
    """Abstract base class for individual alert output channels.

    Concrete implementations (Telegram, Webhook, WhatsApp …) inherit from
    this class.  :class:`~src.outputs.multi_notifier.MultiNotifier` wraps a
    list of :class:`BaseOutput` instances to implement :class:`Notifier`.
    """

    @abstractmethod
    def send_alert(self, message: str, glucose_value: int, level: str) -> bool:
        """Send alert. Returns True if successful."""
        ...

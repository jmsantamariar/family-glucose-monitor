"""MultiNotifier: dispatches alerts to multiple BaseOutput channels.

:class:`MultiNotifier` is the default :class:`~src.outputs.base.Notifier`
implementation used by :func:`src.main.run_once`.  It wraps a list of
:class:`~src.outputs.base.BaseOutput` adapters and aggregates their results:
the notification is considered successful when *at least one* channel
delivers the alert.
"""
import logging

from src.outputs.base import BaseOutput, Notifier  # noqa: F401 – Notifier re-exported

logger = logging.getLogger(__name__)


class MultiNotifier:
    """Dispatch an alert to multiple :class:`~src.outputs.base.BaseOutput` channels.

    Satisfies the :class:`~src.outputs.base.Notifier` protocol via its
    :meth:`notify` method.

    Parameters
    ----------
    outputs:
        List of concrete output adapters (Telegram, Webhook, WhatsApp …).
    """

    def __init__(self, outputs: list[BaseOutput]) -> None:
        self._outputs = outputs

    # ------------------------------------------------------------------
    # Notifier protocol
    # ------------------------------------------------------------------

    def notify(self, message: str, glucose_value: int, level: str) -> bool:
        """Send *message* to all configured outputs.

        Catches and logs exceptions from individual outputs so that a single
        failing channel does not prevent delivery to the others.

        :returns: ``True`` if at least one output returned ``True`` from
            :meth:`~src.outputs.base.BaseOutput.send_alert`.
        """
        any_success = False
        for output in self._outputs:
            try:
                if output.send_alert(message, glucose_value, level):
                    any_success = True
            except Exception as exc:
                logger.error(
                    "Output %s failed: %s", type(output).__name__, exc
                )
        return any_success

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def __bool__(self) -> bool:
        """Return ``True`` when at least one output is configured."""
        return bool(self._outputs)

    def __len__(self) -> int:
        return len(self._outputs)

    def __repr__(self) -> str:
        names = [type(o).__name__ for o in self._outputs]
        return f"MultiNotifier({names!r})"

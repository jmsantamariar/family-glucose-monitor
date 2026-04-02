"""Tests for MultiNotifier and the Notifier protocol."""
from unittest.mock import MagicMock

import pytest

from src.outputs.base import BaseOutput, Notifier
from src.outputs.multi_notifier import MultiNotifier


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_output(success: bool = True) -> BaseOutput:
    """Return a mock BaseOutput whose send_alert returns *success*."""
    m = MagicMock(spec=BaseOutput)
    m.send_alert.return_value = success
    return m


# ---------------------------------------------------------------------------
# Notifier Protocol
# ---------------------------------------------------------------------------


class TestNotifierProtocol:
    def test_multi_notifier_satisfies_protocol(self):
        """MultiNotifier must be a runtime-checkable Notifier."""
        mn = MultiNotifier([])
        assert isinstance(mn, Notifier)

    def test_any_object_with_notify_satisfies_protocol(self):
        class MinimalNotifier:
            def notify(self, message: str, glucose_value: int, level: str) -> bool:
                return True

        assert isinstance(MinimalNotifier(), Notifier)

    def test_base_output_does_not_satisfy_notifier(self):
        """BaseOutput (send_alert) should NOT satisfy the Notifier (notify) protocol."""
        output = _mock_output()
        assert not isinstance(output, Notifier)


# ---------------------------------------------------------------------------
# MultiNotifier.__bool__ / __len__
# ---------------------------------------------------------------------------


class TestMultiNotifierBool:
    def test_empty_is_falsy(self):
        assert not MultiNotifier([])

    def test_non_empty_is_truthy(self):
        assert MultiNotifier([_mock_output()])

    def test_len_empty(self):
        assert len(MultiNotifier([])) == 0

    def test_len_two_outputs(self):
        assert len(MultiNotifier([_mock_output(), _mock_output()])) == 2


# ---------------------------------------------------------------------------
# MultiNotifier.notify — success / failure combinations
# ---------------------------------------------------------------------------


class TestMultiNotifierNotify:
    def test_single_success_returns_true(self):
        mn = MultiNotifier([_mock_output(success=True)])
        assert mn.notify("msg", 55, "low") is True

    def test_single_failure_returns_false(self):
        mn = MultiNotifier([_mock_output(success=False)])
        assert mn.notify("msg", 55, "low") is False

    def test_any_success_returns_true(self):
        """True when at least one output succeeds."""
        mn = MultiNotifier([_mock_output(False), _mock_output(True)])
        assert mn.notify("msg", 200, "high") is True

    def test_all_fail_returns_false(self):
        mn = MultiNotifier([_mock_output(False), _mock_output(False)])
        assert mn.notify("msg", 55, "low") is False

    def test_empty_returns_false(self):
        assert MultiNotifier([]).notify("msg", 100, "normal") is False

    def test_all_outputs_called(self):
        o1, o2 = _mock_output(), _mock_output()
        MultiNotifier([o1, o2]).notify("msg", 55, "low")
        o1.send_alert.assert_called_once_with("msg", 55, "low")
        o2.send_alert.assert_called_once_with("msg", 55, "low")

    def test_exception_in_one_output_does_not_stop_others(self):
        """An exception in one channel should not prevent delivery to others."""
        bad = _mock_output()
        bad.send_alert.side_effect = RuntimeError("network error")
        good = _mock_output(success=True)
        mn = MultiNotifier([bad, good])
        assert mn.notify("msg", 55, "low") is True
        good.send_alert.assert_called_once()

    def test_exception_in_only_output_returns_false(self):
        bad = _mock_output()
        bad.send_alert.side_effect = RuntimeError("boom")
        assert MultiNotifier([bad]).notify("msg", 55, "low") is False


# ---------------------------------------------------------------------------
# MultiNotifier.__repr__
# ---------------------------------------------------------------------------


class TestMultiNotifierRepr:
    def test_repr_includes_output_type_names(self):
        class TelegramOutput(BaseOutput):
            def send_alert(self, *a) -> bool:
                return True

        mn = MultiNotifier([TelegramOutput()])
        assert "TelegramOutput" in repr(mn)

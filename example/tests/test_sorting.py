"""Exercise uncertain and failed responses separately from the live Jev tests."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from typesafe_sdk import ChoiceAnswer, TypeSafeError

from sorting import sort_task

LABELS = [{"id": 7, "name": "Work", "description": "Professional tasks"}]


def test_missing_credentials_leave_task_unsorted():
    assert sort_task("Write a report", LABELS, None) == (None, {"status": "unavailable"})


def test_service_failure_leaves_task_unsorted():
    client = Mock()
    client.system_one.side_effect = TypeSafeError("connection failed")
    assert sort_task("Write a report", LABELS, client) == (None, {"status": "unavailable"})


@pytest.mark.parametrize("choice", ["unsorted", "invented_label"])
def test_no_match_and_invalid_choice_are_not_assigned(choice):
    client = Mock()
    client.system_one.return_value = SimpleNamespace(
        model="jev-test",
        choices={
            "bucket": ChoiceAnswer(choice=choice, confidence=0.4, probabilities={choice: 1.0})
        },
    )
    label_id, result = sort_task("Something vague", LABELS, client)
    assert label_id is None
    assert result["status"] == ("unsorted" if choice == "unsorted" else "unavailable")
    question = client.system_one.call_args.kwargs["questions"]["bucket"]
    assert question.criteria["label_7"] == {"name": "Work", "description": "Professional tasks"}
    assert "unsorted" in question.criteria

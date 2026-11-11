
import json
from types import SimpleNamespace

import pytest
import ask


class MockMessage:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls

    def model_dump(self, exclude_none=True):
        result = {
            "role": "assistant",
            "content": self.content,
        }

        if self.tool_calls:
            result["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.function.name,
                        "arguments": call.function.arguments,
                    },
                }
                for call in self.tool_calls
            ]

        return result


def make_response(content=None, tool_calls=None):
    message = MockMessage(content, tool_calls)
    choice = SimpleNamespace(message=message)
    return SimpleNamespace(choices=[choice])


def make_tool_call(name, arguments, call_id="call_123"):
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(
            name=name,
            arguments=json.dumps(arguments),
        ),
    )


@pytest.fixture(autouse=True)
def reset_conversation():
    ask.conversation_messages[:] = [
        {"role": "system", "content": ask.SYSTEM_PROMPT}
    ]
    yield
    ask.conversation_messages[:] = [
        {"role": "system", "content": ask.SYSTEM_PROMPT}
    ]


def test_ai_generates_response(mocker):
    mocker.patch.object(
        ask.client.chat.completions,
        "create",
        return_value=make_response(
            content="Hello! I am RailAssist."
        ),
    )

    result = ask.ask_question("Hello")

    assert result == "Hello! I am RailAssist."


def test_user_message_saved_in_history(mocker):
    mocker.patch.object(
        ask.client.chat.completions,
        "create",
        return_value=make_response(content="Hello!"),
    )

    ask.ask_question("Hello")

    assert ask.conversation_messages[-2]["content"] == "Hello"


def test_search_stations_tool_call(mocker):
    tool_call = make_tool_call(
        "search_stations",
        {"keyword": "ERS"},
    )

    mocker.patch.object(
        ask.client.chat.completions,
        "create",
        side_effect=[
            make_response(tool_calls=[tool_call]),
            make_response(content="Ernakulam Junction (ERS)"),
        ],
    )

    mock_search = mocker.patch(
        "ask.search_stations",
        return_value=[("ERS", "ERNAKULAM JN", "Kerala")],
    )

    result = ask.ask_question("Find Ernakulam station")

    mock_search.assert_called_once_with(keyword="ERS")
    assert "ERS" in result


def test_get_train_details_tool_call(mocker):
    tool_call = make_tool_call(
        "get_train_details",
        {"train_number": "16303"},
    )

    mocker.patch.object(
        ask.client.chat.completions,
        "create",
        side_effect=[
            make_response(tool_calls=[tool_call]),
            make_response(content="Vanchinad Express"),
        ],
    )

    mock_details = mocker.patch(
        "ask.get_train_details",
        return_value={
            "number": "16303",
            "name": "Vanchinad Express",
        },
    )

    result = ask.ask_question("Tell me about train 16303")

    mock_details.assert_called_once_with(train_number="16303")
    assert "Vanchinad Express" in result


def test_conversation_history_preserved(mocker):
    mocker.patch.object(
        ask.client.chat.completions,
        "create",
        return_value=make_response(
            content="The train is Vanchinad Express."
        ),
    )

    ask.ask_question("Tell me about train 16303")

    assert len(ask.conversation_messages) == 3
    assert ask.conversation_messages[-2]["role"] == "user"
    assert ask.conversation_messages[-1]["content"] == (
        "The train is Vanchinad Express."
    )


def test_api_failure_does_not_corrupt_history(mocker):
    mocker.patch.object(
        ask.client.chat.completions,
        "create",
        side_effect=RuntimeError("API unavailable"),
    )

    original_length = len(ask.conversation_messages)

    with pytest.raises(RuntimeError):
        ask.ask_question("Hello")

    assert len(ask.conversation_messages) == original_length


def test_multiple_tool_calls(mocker):
    station_call = make_tool_call(
        "search_stations",
        {"keyword": "ERS"},
        "call_1",
    )

    details_call = make_tool_call(
        "get_train_details",
        {"train_number": "16303"},
        "call_2",
    )

    mocker.patch.object(
        ask.client.chat.completions,
        "create",
        side_effect=[
            make_response(
                tool_calls=[station_call, details_call]
            ),
            make_response(content="Vanchinad Express"),
        ],
    )

    mock_station = mocker.patch(
        "ask.search_stations",
        return_value=[("ERS", "ERNAKULAM JN", "Kerala")],
    )

    mock_details = mocker.patch(
        "ask.get_train_details",
        return_value={
            "number": "16303",
            "name": "Vanchinad Express",
        },
    )

    result = ask.ask_question(
        "Find station ERS and details of train 16303"
    )

    mock_station.assert_called_once()
    mock_details.assert_called_once()
    assert "Vanchinad Express" in result


def test_tool_error_is_returned_to_ai(mocker):
    tool_call = make_tool_call(
        "get_train_details",
        {"train_number": "99999"},
    )

    mocker.patch.object(
        ask.client.chat.completions,
        "create",
        side_effect=[
            make_response(tool_calls=[tool_call]),
            make_response(
                content="Train 99999 was not found."
            ),
        ],
    )

    mocker.patch(
        "ask.get_train_details",
        return_value={
            "error": "Train 99999 was not found."
        },
    )

    result = ask.ask_question("Tell me about train 99999")

    assert "not found" in result.lower()

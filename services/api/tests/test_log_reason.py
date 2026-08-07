"""What a failed invocation says in the log.

`→ 400` on its own is the log line that sends you to the code to find out which
of twenty rejections it was. These pin down where the reason is dug out of,
because a handler that *returns* an error looks nothing like one that raised.
"""

from cubicle.runtime.invoker import InvokeResult, _reason


def _result(**kwargs) -> InvokeResult:
    base = {
        "status_code": 400,
        "body": None,
        "headers": {},
        "duration_ms": 1.0,
        "cold": False,
        "error": None,
        "logs": [],
        "context_read": [],
        "context_wrote": [],
        "request_id": "req_test",
    }
    return InvokeResult(**{**base, **kwargs})


def test_a_raised_handler_reports_the_exception():
    assert _reason(_result(error="ValueError: bad image")) == "ValueError: bad image"


def test_a_returned_error_is_read_from_the_body():
    """The ordinary way to reject input, and the case that used to say nothing."""
    assert _reason(_result(body={"error": "image data is missing"})) == "image data is missing"


def test_message_is_preferred_over_a_bare_code():
    assert _reason(_result(body={"message": "the file is not a JPEG"})) == "the file is not a JPEG"


def test_a_code_and_a_message_are_both_kept():
    """`not_found` is what to grep for; the sentence is what to read."""
    reason = _reason(_result(body={"error": "bad_request", "message": "no image in body"}))
    assert reason == "bad_request: no image in body"


def test_a_code_that_repeats_the_message_is_not_doubled():
    assert _reason(_result(body={"error": "nope", "message": "nope"})) == "nope"


def test_a_body_with_no_known_field_is_shown_as_json():
    reason = _reason(_result(body={"unexpected": 12}))
    assert "unexpected" in reason and "12" in reason


def test_a_plain_string_body_is_the_reason():
    assert _reason(_result(body="not an image")) == "not an image"


def test_a_raised_error_wins_over_the_body():
    """An exception is the more specific fact about what went wrong."""
    result = _result(error="KeyError: 'src'", body={"error": "internal"})
    assert _reason(result) == "KeyError: 'src'"


def test_nothing_to_say_stays_empty():
    """So the line reads `→ 400` rather than `→ 400 · `."""
    assert _reason(_result(body=None)) == ""
    assert _reason(_result(body={})) == "{}"
    assert _reason(_result(body="   ")) == ""


def test_a_long_reason_is_cut():
    """A log line is not a place to paste a stack trace or a whole payload."""
    assert len(_reason(_result(body={"error": "x" * 5000}))) <= 400

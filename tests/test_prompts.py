import pytest

from doc2sheet.loaders import LoadedDocument
from doc2sheet.prompts import EXTRACTION_SCHEMA, build_messages, parse_json_reply, repair_messages


def test_schema_is_strict_mode_compatible():
    props = EXTRACTION_SCHEMA["properties"]
    assert set(EXTRACTION_SCHEMA["required"]) == set(props)
    assert EXTRACTION_SCHEMA["additionalProperties"] is False
    item = props["line_items"]["items"]
    assert set(item["required"]) == set(item["properties"])


@pytest.mark.parametrize(
    "reply",
    [
        '{"total": 1}',
        '```json\n{"total": 1}\n```',
        'Sure! Here is the data:\n{"total": 1}\nLet me know if you need more.',
        '<think>The total is 1, so...</think>{"total": 1}',
        '[{"total": 1}]',
    ],
)
def test_parse_json_reply_tolerates_wrappers(reply):
    assert parse_json_reply(reply) == {"total": 1}


@pytest.mark.parametrize("reply", ["no json here", '{"total": 1', "[1, 2]"])
def test_parse_json_reply_rejects_garbage(reply):
    with pytest.raises(ValueError):
        parse_json_reply(reply)


def test_build_messages_includes_images_and_text_layer():
    doc = LoadedDocument(name="a.pdf", images=[b"\xff\xd8fake"], text="Total 12.00", page_count=4)
    messages = build_messages(doc)
    assert messages[0]["role"] == "system"
    content = messages[1]["content"]
    text = content[0]["text"]
    assert "Total 12.00" in text and "<text_layer>" in text
    assert "first 1 of 4 pages" in text
    assert content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_repair_messages_appends_feedback():
    base = [{"role": "user", "content": "x"}]
    repaired = repair_messages(base, "oops", "invalid JSON")
    assert repaired[-2] == {"role": "assistant", "content": "oops"}
    assert "invalid JSON" in repaired[-1]["content"]
    assert base == [{"role": "user", "content": "x"}]  # original list untouched

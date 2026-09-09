from src.pipeline.parse import heuristic_parse
from src.providers.llm import extract_json


def test_heuristic_parse_common_shapes():
    raw = """
    Targets:
    - Jane Doe - VP Engineering at Acme
    2. Bob Smith, Widgets Inc
    Carol White | CTO | Foo Labs | met at SaaStr
    """
    rows = heuristic_parse(raw)
    assert [r.name for r in rows] == ["Jane Doe", "Bob Smith", "Carol White"]
    assert rows[0].title == "VP Engineering" and rows[0].company == "Acme"
    assert rows[1].company == "Widgets Inc"
    assert rows[2].hints == "met at SaaStr"


def test_extract_json_array_in_fence():
    text = 'Sure:\n```json\n[{"name": "A"}]\n```'
    assert extract_json(text) == [{"name": "A"}]


def test_extract_json_object_with_prose():
    text = 'Result {"a": 1, "b": {"c": 2}} thanks'
    assert extract_json(text) == {"a": 1, "b": {"c": 2}}

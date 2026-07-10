import json
from pathlib import Path

from doc_splitter.ir.serialize import load_ir

GOLDEN = Path(__file__).parent / "golden"


def _corpus() -> dict:
    return json.loads((GOLDEN / "corpus.json").read_text(encoding="utf-8"))


def test_golden_corpus_contains_all_phase_zero_scenarios():
    ids = {case["id"] for case in _corpus()["cases"]}
    assert ids == {
        "topic-change-with-heading",
        "topic-change-without-heading",
        "subheading-same-topic",
        "early-topic-change-before-minimum",
        "continuous-topic-17-pages",
        "continuous-topic-25-pages",
        "table-on-topic-boundary",
        "image-on-topic-boundary",
        "pdf-blank-middle-page",
        "docx-list-and-standalone-image",
    }


def test_golden_sources_exist_and_ir_boundaries_reference_real_elements():
    for case in _corpus()["cases"]:
        source = GOLDEN / case["source"]
        assert source.is_file(), case["id"]
        if case["kind"] != "ir":
            continue
        ir = load_ir(source)
        element_ids = {element.id for element in ir.elements}
        expected = case["expected"]
        for element_id in expected.get("topic_boundaries_after", []):
            assert element_id in element_ids, (case["id"], element_id)
        for element_id in expected.get("must_not_split_after", []):
            assert element_id in element_ids, (case["id"], element_id)


def test_desired_page_policy_is_frozen():
    assert _corpus()["desired_page_policy"] == {
        "target_min_pages": 5,
        "preferred_max_pages": 12,
        "soft_max_pages": 13,
        "hard_max_pages": 20,
        "topic_change_overrides_minimum": True,
        "extension_after_soft_max_requires_semantic_evidence": True,
    }

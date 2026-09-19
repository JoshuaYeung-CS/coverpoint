"""Every number the documents quote must still be what results/ says.

docs/CITED.json lists each quoted value: where it lives in results/, how it is formatted,
and which documents quote it. `make reproduce` regenerates results/ and compares; this
test is the other half, and fails the moment a document and a result disagree.
"""
from harness import report


def test_every_cited_number_matches_the_results():
    problems = report.check_cited()
    assert not problems, "\n".join(problems)


def test_the_list_of_cited_numbers_is_not_empty():
    assert report.CITED.exists() and len(report.load(report.CITED)) >= 20

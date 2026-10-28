import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from range_access import capture, unchanged, after_selection_source_matches


class R:
    """A mutable provider document with independently stale range handles."""

    def __init__(self, doc, start, end):
        self.doc, self.start, self.end = doc, start, end
        self.stale = False

    def Clone(self):
        return R(self.doc, self.start, self.end)

    def GetText(self, count):
        if self.stale:
            raise RuntimeError('old live range is stale')
        text = self.doc[0][self.start:self.end]
        return text if count < 0 else text[:count]

    def ExpandToEnclosingUnit(self, unit):
        assert unit == 4
        text = self.doc[0]
        self.start = text.rfind('\n', 0, self.start) + 1
        self.end = text.find('\n', self.end)
        if self.end < 0:
            self.end = len(text)

    def MoveEndpointByRange(self, endpoint, other, other_endpoint):
        position = other.start if other_endpoint == 0 else other.end
        if endpoint == 0:
            self.start = position
            if self.start > self.end:
                self.end = self.start
        else:
            self.end = position
            if self.end < self.start:
                self.start = self.end

    def CompareEndpoints(self, endpoint, other, other_endpoint):
        if self.stale or other.stale:
            raise RuntimeError('old live range cannot compare endpoints')
        return ((self.start if endpoint == 0 else self.end)
                - (other.start if other_endpoint == 0 else other.end))


class Array:
    def __init__(self, item, count=1):
        self.item, self.Length = item, count

    def GetElement(self, index):
        assert index == 0 and self.Length == 1
        return self.item


class P:
    def __init__(self, doc, anchor):
        self.doc, self.anchor = doc, anchor
        self.selection_count = 1

    def GetSelection(self):
        return Array(self.anchor, self.selection_count)

    @property
    def DocumentRange(self):
        return R(self.doc, 0, len(self.doc[0]))


RID = (1, 2)


def stale_old_ranges(snapshot):
    snapshot.target.stale = True
    snapshot.caret_or_selection.stale = True


def test_immutable_preselection_check():
    doc = ['first\nsecond\nthird']
    pattern = P(doc, R(doc, 7, 7))
    snapshot = capture(RID, pattern, True)
    assert snapshot.text == 'second' and not snapshot.selected
    stale_old_ranges(snapshot)
    assert unchanged(snapshot, RID, pattern), 'fresh capture must survive stale old ranges'
    assert not unchanged(snapshot, (9,), pattern)
    pattern.anchor = R(doc, 8, 8)
    assert not unchanged(snapshot, RID, pattern), 'caret movement must cancel'
    pattern.anchor = R(doc, 7, 7)
    doc[0] = 'first\nseXond\nthird'
    assert not unchanged(snapshot, RID, pattern), 'real source edits must cancel'
    doc[0] = 'other\nsecond\nthird'
    assert not unchanged(snapshot, RID, pattern), 'changed prefix is a different anchor'


def test_fresh_field_after_deliberate_selection():
    doc = ['first\nsecond\nthird']
    pattern = P(doc, R(doc, 7, 7))
    snapshot = capture(RID, pattern, False)
    stale_old_ranges(snapshot)
    pattern.anchor = R(doc, 0, len(doc[0]))
    assert after_selection_source_matches(snapshot, RID, pattern), 'own Ctrl+A is not a source edit'
    assert not after_selection_source_matches(snapshot, (9,), pattern)
    doc[0] = 'actually changed'
    assert not after_selection_source_matches(snapshot, RID, pattern)


def test_fresh_document_after_deliberate_selection():
    doc = ['first\nsecond\nthird']
    pattern = P(doc, R(doc, 7, 7))
    snapshot = capture(RID, pattern, True)
    stale_old_ranges(snapshot)
    pattern.anchor = R(doc, 6, 12)
    assert after_selection_source_matches(snapshot, RID, pattern), 'fresh selection proves intended paragraph'
    pattern.anchor = R(doc, 7, 9)
    assert not after_selection_source_matches(snapshot, RID, pattern)
    pattern.anchor = R(doc, 6, 12)
    doc[0] = 'other\nsecond\nthird'
    assert not after_selection_source_matches(snapshot, RID, pattern)


def test_duplicate_occurrence_is_not_same_target():
    doc = ['same\nsame']
    pattern = P(doc, R(doc, 0, 4))
    snapshot = capture(RID, pattern, True)
    assert after_selection_source_matches(snapshot, RID, pattern)
    pattern.anchor = R(doc, 5, 9)
    assert not unchanged(snapshot, RID, pattern)
    assert not after_selection_source_matches(snapshot, RID, pattern), 'same words elsewhere must not be replaced'


def test_invalid_selection_and_empty_source():
    doc = ['text']
    pattern = P(doc, R(doc, 0, 0))
    snapshot = capture(RID, pattern, False)
    pattern.selection_count = 0
    assert not unchanged(snapshot, RID, pattern)
    # A field post-selection check compares fresh document text independently of selection metadata.
    assert after_selection_source_matches(snapshot, RID, pattern)
    for count in (0, 2):
        pattern.selection_count = count
        try:
            capture(RID, pattern, True)
        except ValueError:
            pass
        else:
            raise AssertionError('missing or ambiguous selection must fail')
    pattern.selection_count = 1
    doc[0] = '   '
    try:
        capture(RID, pattern, False)
    except ValueError:
        pass
    else:
        raise AssertionError('whitespace-only source must fail')


if __name__ == '__main__':
    test_immutable_preselection_check()
    test_fresh_field_after_deliberate_selection()
    test_fresh_document_after_deliberate_selection()
    test_duplicate_occurrence_is_not_same_target()
    test_invalid_selection_and_empty_source()
    print('fresh source, stale ranges, real edits and duplicate locations: PASS')

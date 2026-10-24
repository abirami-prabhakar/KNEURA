"""Deterministic fallback includes only supported class-level statements."""
import pytest
from backend.reporting import compose, TEMPLATE
from backend.inference import NAMES


def test_complete_template_preserves_order_and_sources():
    approved = [{'id': str(i), 'name': name} for i, name in enumerate(NAMES)]
    findings, impression, statements, provider = compose(list(reversed(approved)))
    assert provider == 'Evidence-bound template'
    assert len(statements) == 24
    for section, text in [('findings', findings), ('impression', impression)]:
        sources = [s for s in statements if s['section'] == section]
        assert text == '\n'.join(s['text'] for s in sources)
        assert [s['findingIds'] for s in sources] == [[f['id']] for f in approved]
    assert set(TEMPLATE) == set(NAMES)


def test_selected_abnormalities_do_not_invent_detail():
    findings, impression, statements, _ = compose([{'id':'acl', 'name':'ACL'}, {'id':'fluid', 'name':'Effusion'}])
    assert findings == 'Anterior cruciate ligament abnormality.\nKnee joint effusion.'
    assert impression == findings
    assert all(s['findingIds'] in [['acl'], ['fluid']] for s in statements)
    assert not any(word in findings.lower() for word in ['tear', 'grade', ' normal ', 'meniscus'])


def test_no_approved_findings_is_not_a_normal_report():
    findings, impression, statements, _ = compose([])
    assert 'does not establish a normal examination' in findings
    assert impression == findings
    assert all(s['findingIds'] == [] for s in statements)


@pytest.mark.parametrize('approved', [[{'id':'1','name':'Unknown'}], [{'id':'1','name':'ACL'},{'id':'2','name':'ACL'}]])
def test_unsupported_input_fails_closed(approved):
    with pytest.raises(ValueError):
        compose(approved)

"""Append-only events inside the persisted case aggregate."""
from datetime import datetime, timezone
from copy import deepcopy
import uuid
import hashlib
import json


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def verify(case):
    events = case['audit']
    chain = case.get('auditChain')
    if not chain:
        return dict(valid=False, events=len(events), tampered_events=[], legacy_events=len(events), reason='Legacy history has no hash chain.')
    count = chain['legacyCount']
    bad = []
    previous = digest(events[:count])
    if len(events) < count or previous != chain['legacyHash']:
        bad.append('legacy-prefix')
    for entry in events[count:]:
        content = {key: value for key, value in entry.items() if key != 'hash'}
        if entry.get('previous_hash') != previous or entry.get('hash') != digest(content):
            bad.append(entry.get('id', 'missing-id'))
        previous = entry.get('hash', '')
    if previous != chain['head']:
        bad.append('chain-head')
    return dict(valid=not bad, events=len(events), tampered_events=bad, legacy_events=count,
                head=chain['head'], reason='Hash consistency only; no externally anchored authenticity guarantee.')


def now():
    return datetime.now(timezone.utc).isoformat()


def event(case, action, actor, *, actor_id=None, object_id=None, previous=None, current=None):
    if 'auditChain' not in case:
        anchor = digest(case['audit'])
        case['auditChain'] = dict(legacyCount=len(case['audit']), legacyHash=anchor, head=anchor)
    elif not verify(case)['valid']:
        raise ValueError('Audit chain integrity failed. Preserve storage and investigate before further changes.')
    case['updatedAt'] = now()
    entry = dict(id=uuid.uuid4().hex, timestamp=case['updatedAt'],
        caseId=case['id'], action=action, actor=actor, actorId=actor_id,
        objectId=object_id or case['id'], previous=deepcopy(previous), current=deepcopy(current),
        previous_hash=case['auditChain']['head'])
    entry['hash'] = digest(entry)
    case['audit'].append(entry)
    case['auditChain']['head'] = entry['hash']

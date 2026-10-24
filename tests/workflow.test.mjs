import test from 'node:test'
import assert from 'node:assert/strict'
import { reviewComplete, approvedFindingIds, imagingWindows, finalApprovalBlocker, needsAttention } from '../src/workflow.ts'

const names = ['ACL', 'MCL', 'Medial Meniscus', 'Lateral Meniscus', 'Medial OA', 'Lateral OA', 'Patellofemoral OA', 'Effusion', 'Synovitis', "Baker's cyst", 'Contusion', 'Fracture']
const complete = () => names.map((name, index) => ({ id: String(index), name, probability: .5, status: index < 3 ? 'APPROVED' : 'REJECTED' }))
test('blocks empty, incomplete and pending reviews', () => {
  assert.equal(reviewComplete([]), false)
  assert.equal(reviewComplete(complete().slice(1)), false)
  const findings = complete(); findings[11].status = 'PENDING'
  assert.equal(reviewComplete(findings), false)
  assert.throws(() => approvedFindingIds(findings), /All 12/)
})
test('prevents duplicate IDs or duplicate canonical outputs from bypassing the gate', () => {
  const ids = complete(); ids[11].id = ids[0].id
  assert.equal(reviewComplete(ids), false)
  const names = complete(); names[11].name = names[0].name
  assert.equal(reviewComplete(names), false)
})
test('includes only explicit radiologist approvals in report input', () => {
  assert.equal(reviewComplete(complete()), true)
  assert.deepEqual(approvedFindingIds(complete()), ['0', '1', '2'])
})
test('supports a reviewed study with no approved abnormalities', () => {
  const findings = complete().map(f => ({ ...f, status: 'REJECTED' }))
  assert.equal(reviewComplete(findings), true)
  assert.deepEqual(approvedFindingIds(findings), [])
})
test('rejects unrecognized decision states', () => {
  const findings = complete(); findings[0].status = 'AUTO_APPROVED'
  assert.equal(reviewComplete(findings), false)
})


test('MRI windows preserve actual instance numbers and match five-slice inference', () => {
  const images = [21, 2, 13, 5, 8, 34].map(instanceNumber => ({ id: String(instanceNumber), instanceNumber, url: '' }))
  const windows = imagingWindows(images)
  assert.deepEqual(windows.map(window => window.map(image => image.instanceNumber)), [[2, 5, 8, 13, 21], [5, 8, 13, 21, 34]])
  assert.equal(images[0].instanceNumber, 21)
  assert.deepEqual(imagingWindows(images.slice(0, 4)), [])
  assert.equal(imagingWindows(images.slice(0, 5)).length, 1)
})


test('final approval explains placeholder and unsaved review blockers', () => {
  const report = {status:'DRAFT', findings:'Reviewed findings', impression:'Radiologist interpretation required before final approval.'}
  assert.match(finalApprovalBlocker(report, complete(), report), /clinical impression/)
  const draft = {...report, impression:'Clinician interpretation'}
  assert.match(finalApprovalBlocker(report, complete(), draft), /Save your changes/)
  assert.match(finalApprovalBlocker(draft, complete(), draft), /Save reviewed report/)
  const reviewed = {...draft, status:'UNDER_REVIEW', reviewedAt:'2026-09-29T00:00:00Z'}
  assert.equal(finalApprovalBlocker(reviewed, complete(), reviewed), null)
  assert.match(finalApprovalBlocker(reviewed, complete(), {...reviewed,impression:'Changed interpretation'}), /Save your changes/)
  assert.match(finalApprovalBlocker(reviewed, complete().slice(1), reviewed), /all 12/)
})


test('orthopedist attention queue includes final reports awaiting release', () => {
  const item = {status:'FINAL', report:{status:'FINAL'}}
  assert.equal(needsAttention(item, 'orthopedist'), true)
  assert.equal(needsAttention({...item, releasedToPatient:true}, 'orthopedist'), false)
  assert.equal(needsAttention({...item, report:{status:'DRAFT'}}, 'orthopedist'), false)
  assert.equal(needsAttention(item, 'radiologist'), false)
  assert.equal(needsAttention({status:'REVIEWING'}, 'radiologist'), true)
  assert.equal(needsAttention(item, 'patient'), false)
})

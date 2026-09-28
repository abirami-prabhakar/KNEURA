import { test, expect } from '@playwright/test'
import type { Page } from '@playwright/test'
import golden from '../../05_GOLDEN_CASE/KNEE_AI_GOLDEN_CASE.json' with { type: 'json' }
import cam from '../../07_GRADCAM/GRADCAM_ALL_12_RESULTS.json' with { type: 'json' }

const names = ['ACL', 'MCL', 'Medial Meniscus', 'Lateral Meniscus', 'Medial OA', 'Lateral OA', 'Patellofemoral OA', 'Effusion', 'Synovitis', "Baker's cyst", 'Contusion', 'Fracture']
const timestamp = '2026-09-23T08:00:00Z'
// Synthetic API fixtures only. These are never shipped or seeded in the application.
function study() {
  return {
    id: 'KN-TEST', status: 'AI_READY', updatedAt: timestamp,
    study: { id: 'study', patientName: 'Synthetic Test', patientId: 'TEST', description: 'Test knee MRI', date: '2026-09-23' },
    analysis: { modelVersion: 'KNEE-AI 3.3' },
    series: [{ id: '1.2.3', name: 'PD FS', sequence: 'PD', eligible: true, images: [34, 35, 37, 39, 40, 44].map(instanceNumber => ({ id: String(instanceNumber), instanceNumber, url: `/api/images/${instanceNumber}.png` })) }],
    findings: names.map((name, index) => ({ id: `F${index}`, name, probability: 0.90947, status: 'PENDING', patientExplanation: `Explanation supplied for ${name}.`, evidence: { seriesId: '1.2.3', seriesName: 'PD FS', windowNumber: 1, sliceStart: 34, sliceEnd: 40, instanceNumbers: [34, 35, 37, 39, 40], mriImageUrl: '/api/images/34.png', gradCamImageUrl: `/api/images/gradcam-${index}.png`, attribution: 'Window-level attribution, not a diagnosis.' }, decision: undefined as any })),
    audit: [{ id: 'a1', timestamp, action: 'MRI received', actor: 'Uploader' }, { id: 'a2', timestamp: '2026-09-23T08:01:00Z', action: 'AI findings generated', actor: 'AI service' }],
    report: undefined as any,
  }
}

async function workspace(page: Page, role = 'radiologist', setup: (item: ReturnType<typeof study>) => void = () => {}) {
  const item = study()
  setup(item)
  const requests: { path: string; body: any }[] = []
  let failCase = false
  await page.route('**/api/**', async route => {
    const req = route.request(), path = new URL(req.url()).pathname
    const json = (data: unknown, status = 200) => route.fulfill({ status, json: data })
    if (path.startsWith('/api/images/')) return route.fulfill({ contentType: 'image/png', body: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aWQAAAABJRU5ErkJggg==', 'base64') })
    if (path === '/api/auth/me') return json({ id: role, name: 'Reviewer Test', role })
    if (path === '/api/health') return json({ status: 'ok' })
    if (req.method() === 'POST' || req.method() === 'PATCH') {
      const body = req.postDataJSON()
      requests.push({ path, body })
      if (path.endsWith('/decision')) {
        const finding = item.findings.find(f => path.includes(`/${f.id}/`))!
        finding.status = body.status
        finding.decision = { status: body.status, userName: 'Reviewer Test', timestamp }
        item.status = 'REVIEWING'
      } else if (path.endsWith('/report') && req.method() === 'POST') {
        item.status = 'DRAFT'
        item.report = { id: 'R1', status: 'DRAFT', findings: item.findings.filter(f => f.status === 'APPROVED').map(f => `${f.name} approved.`).join('\n') || 'No AI-proposed abnormalities were approved. This does not establish a normal examination.', impression: '', updatedAt: timestamp, provider: 'Evidence-bound template', statements: item.findings.filter(f => f.status === 'APPROVED').map(f => ({ id: `S${f.id}`, text: `${f.name} approved.`, findingIds: [f.id], source: 'approved-finding' })) }
      } else if (path.endsWith('/report') && req.method() === 'PATCH') {
        Object.assign(item.report, body, { updatedAt: '2026-09-23T09:00:00Z' })
      } else if (path.endsWith('/finalize')) {
        item.status = 'FINAL'
        Object.assign(item.report, { status: 'FINAL', approvedBy: 'Reviewer Test', approvedAt: timestamp, updatedAt: '2026-09-23T10:00:00Z' })
      }
      return json(item)
    }
    // Deliberately return complete data to test frontend role filtering as defense in depth.
    if (path === '/api/cases') return json([item])
    if (path === '/api/cases/KN-TEST') return failCase ? json({ detail: 'Study request failed' }, 503) : json(item)
    if (path === '/api/model') return json({ version: 'KNEE-AI 3.3' })
    if (path === '/api/validation') return json({ studies: 9, windows: 844, series: 27, macroAuroc: 0.714, evaluatedAt: 'Unavailable' })
    return json({ detail: 'Case unavailable' }, 404)
  })
  return { item, requests, failCase: (value: boolean) => { failCase = value } }
}

function finalize(item: ReturnType<typeof study>) {
  item.status = 'FINAL'
  item.findings.forEach((f, i) => { f.status = i === 0 ? 'APPROVED' : 'REJECTED'; f.decision = { status: f.status, userName: 'Reviewer Test', timestamp } })
  item.report = { id: 'R1', status: 'FINAL', findings: 'ACL approved.', impression: 'Final radiologist assessment.', updatedAt: timestamp, approvedBy: 'Reviewer Test', approvedAt: timestamp, statements: [{ id: 'S1', text: 'ACL approved.', findingIds: ['F0'], source: 'approved-finding' }, { id: 'S2', text: 'Radiologist authored assessment.', findingIds: [], source: 'radiologist-authored' }] }
}

test('case navigation, canonical findings, MRI windows and unchanged backend evidence', async ({ page }) => {
  await workspace(page, 'radiologist', item => item.findings.reverse())
  await page.goto('/radiologist/cases')
  await page.getByRole('button', { name: 'KN-TEST', exact: true }).click()
  await expect(page.locator('.finding-row strong')).toHaveText(names)
  await expect(page.getByRole('region', { name: 'Evidence card for ACL' })).toContainText('34, 35, 37, 39, 40')
  await expect(page.getByRole('region', { name: 'Evidence card for ACL' })).toContainText('KNEE-AI 3.3')
  await expect(page.getByRole('img', { name: 'Grad-CAM for ACL', exact: true })).toHaveAttribute('src', '/api/images/gradcam-0.png')
  await expect(page.getByRole('button', {name:'Next window',exact:true})).toHaveCount(0)
  await expect(page.getByRole('button', {name:'Instance 39',exact:true})).toHaveCount(0)
  await expect(page.getByRole('button', {name:'Previous slice',exact:true})).toBeDisabled()
  await page.getByRole('button', {name:'Next slice',exact:true}).click()
  await expect(page.locator('.viewer-bottom-meta')).toContainText('INSTANCE 35')
  await page.getByLabel('MRI slice', {exact:true}).fill('5')
  await expect(page.getByRole('button', {name:'Next slice',exact:true})).toBeDisabled()
  await page.getByText('Image settings & evidence details', {exact:true}).click()
  await page.getByLabel('Five-slice window').selectOption('1')
  await expect(page.locator('.window-context')).toContainText('35, 37, 39, 40, 44')
  await page.getByLabel('MRI slice', {exact:true}).fill('3')
  await expect(page.locator('.window-context')).toContainText('Current window #2')
  await expect(page.locator('.viewer-bottom-meta')).toContainText('INSTANCE 39')
  await expect(page.getByRole('button', { name: 'Grad-CAM', exact: true })).toBeDisabled()
  await page.getByRole('button', { name: 'Selected finding evidence', exact: true }).click()
  await expect(page.locator('.viewer-canvas img')).toHaveAttribute('src', '/api/images/gradcam-0.png')
  await expect(page.locator('.window-context')).toContainText('Selected finding: ACL')
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.screenshot({ path: `test-results/workspace-${test.info().project.name}.png`, fullPage: true })
})

test('12 explicit decisions gate approved-only draft, edits and backend final approval', async ({ page }) => {
  const { requests } = await workspace(page)
  await page.goto('/radiologist/cases/KN-TEST/report')
  await expect(page.getByRole('button', { name: 'Generate draft report' })).toBeDisabled()
  await page.getByRole('button', { name: 'Images & findings' }).click()
  for (let i = 0; i < names.length; i++) {
    await page.locator('.finding-row').nth(i).click()
    await page.getByRole('button', { name: i === 0 ? 'Approve' : 'Reject', exact: true }).click()
    await expect(page.locator('.decision-panel .status')).toHaveText(i === 0 ? 'APPROVED' : 'REJECTED')
  }
  await expect(page.locator('.review-progress')).toContainText('12 / 12')
  await page.getByRole('button', { name: 'Continue to report' }).click()
  await page.getByText('Use a template instead (not LLM generated)', { exact: true }).click()
  await page.getByRole('button', { name: 'Generate template draft' }).click()
  await expect(page.getByLabel('Report findings')).toHaveValue('ACL approved.')
  expect(requests.find(r => r.path.endsWith('/report'))?.body).toEqual({ approvedFindingIds: ['F0'] })
  await page.getByLabel('Report impression').fill('Reviewed final impression.')
  await expect(page.getByRole('button', { name: 'Approve final', exact: true })).toBeDisabled()
  await expect(page.getByText('Save your edits to update statement traceability.', { exact: false })).toBeVisible()
  await page.getByRole('button', { name: 'Save draft', exact: true }).click()
  await page.getByRole('button', { name: 'Approve final', exact: true }).click()
  await page.getByRole('button', { name: 'Approve final report', exact: true }).click()
  await expect(page.getByRole('region', { name: 'Finalized case summary' })).toContainText('11')
  expect(requests.some(r => r.path.endsWith('/finalize'))).toBe(true)
  await expect(page.getByLabel('Report impression')).toHaveAttribute('readonly', '')
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.screenshot({ path: `test-results/report-${test.info().project.name}.png`, fullPage: true })
})

test('all rejected findings produce an explicit empty-input draft', async ({ page }) => {
  const { requests } = await workspace(page, 'radiologist', item => item.findings.forEach(f => { f.status = 'REJECTED' }))
  await page.goto('/radiologist/cases/KN-TEST/report')
  await expect(page.getByText('No AI finding has been approved.', { exact: true })).toBeVisible()
  await page.getByText('Use a template instead (not LLM generated)', { exact: true }).click()
  await page.getByRole('button', { name: 'Generate template draft' }).click()
  await expect(page.getByLabel('Report findings')).toHaveValue(/does not establish a normal examination/)
  expect(requests[0].body).toEqual({ approvedFindingIds: [] })
})

test('final report traces approved evidence and preserves authored provenance', async ({ page }) => {
  await workspace(page, 'radiologist', finalize)
  await page.goto('/radiologist/cases/KN-TEST/report')
  await page.getByRole('button', { name: 'ACL approved.', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toContainText('90.9%')
  await expect(dialog).toContainText('1.2.3')
  await expect(dialog).toContainText('34, 35, 37, 39, 40')
  await expect(dialog).toContainText('Reviewer Test')
  await dialog.getByRole('button', { name: 'Open finding in MRI workspace' }).click()
  await expect(page.locator('.finding-row.selected')).toContainText('ACL')
  await expect(page.getByRole('button', { name: 'Approve', exact: true })).toBeDisabled()
  await page.getByRole('button', { name: 'Report workspace' }).click()
  await page.getByRole('button', { name: 'Radiologist authored assessment.' }).click()
  await expect(dialog).toContainText('not attributed to AI imaging evidence')
})

test('orthopedist and patient routes expose only finalized approved information', async ({ page }) => {
  await workspace(page, 'orthopedist', finalize)
  await page.goto('/orthopedist/cases/KN-TEST')
  await expect(page.locator('.finding-row')).toHaveCount(1)
  await expect(page.locator('main')).not.toContainText('90.9%')
  await expect(page.locator('main')).not.toContainText('KNEE-AI 3.3')
  await page.getByRole('button', { name: 'Trace Evidence', exact: true }).click()
  await expect(page.getByRole('dialog')).toContainText('1.2.3')
  await page.unroute('**/api/**')
  await workspace(page, 'patient', finalize)
  await page.goto('/patient/mri/KN-TEST')
  await expect(page.locator('main')).toContainText('Explanation supplied for ACL.')
  await expect(page.locator('main')).toContainText('Final radiologist assessment.')
  await expect(page.locator('main')).not.toContainText('REJECTED')
  await expect(page.locator('main')).not.toContainText('90.9%')
  await expect(page.locator('main')).not.toContainText('KNEE-AI 3.3')
  await expect(page.locator('main img')).toHaveCount(0)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.screenshot({ path: `test-results/patient-${test.info().project.name}.png`, fullPage: true })
})

test('image failures, missing metadata, case retry, audit and missing case states', async ({ page }) => {
  const state = await workspace(page, 'radiologist', item => { delete (item.findings[0].evidence as any).instanceNumbers; delete (item as any).analysis })
  await page.route('**/api/images/gradcam-*', route => route.abort())
  state.failCase(true)
  await page.goto('/radiologist/cases/KN-TEST')
  await expect(page.getByRole('alert')).toContainText('Study request failed')
  state.failCase(false)
  await page.getByRole('button', { name: 'Try again', exact: true }).click()
  await expect(page.getByRole('region', { name: 'Evidence card for ACL' })).toContainText('Unavailable')
  await page.getByRole('button', { name: 'Grad-CAM', exact: true }).click()
  await expect(page.locator('.viewer-canvas [role=alert]')).toContainText('could not be loaded')
  await page.unroute('**/api/images/gradcam-*')
  await page.locator('.viewer-canvas').getByRole('button', { name: 'Retry image' }).click()
  await expect(page.locator('.viewer-canvas img')).toBeVisible()
  await page.getByRole('button', { name: 'Audit history' }).click()
  await expect(page.locator('.audit-event h3')).toHaveText(['MRI received', 'AI findings generated'])
  await page.goto('/radiologist/cases/missing')
  await expect(page.getByRole('alert')).toContainText('Case unavailable')
})

test('all navigation routes resolve; unfinished reports stay private', async ({ page }) => {
  await workspace(page)
  for (const route of ['overview', 'cases', 'review', 'reports', 'audit', 'model', 'validation']) {
    await page.goto(`/radiologist/${route}`)
    await expect(page.locator('main h1')).toBeVisible()
    await expect(page.locator('main')).not.toContainText('Page unavailable')
  }
  for (const role of ['orthopedist', 'patient']) {
    await page.unroute('**/api/**')
    await workspace(page, role)
    for (const route of role === 'patient' ? ['overview', 'findings', 'report'] : ['overview', 'cases', 'reports', 'evidence']) {
      await page.goto(`/${role}/${route}`)
      await expect(page.locator('main')).not.toContainText('KN-TEST')
      await expect(page.locator('main')).not.toContainText('Page unavailable')
    }
    await page.goto(`/${role}/cases/KN-TEST`)
    await expect(page.getByRole('heading', { name: 'Case unavailable' })).toBeVisible()
  }
})

test('MRI and Grad-CAM loading states and unavailable evidence are explicit', async ({ page }) => {
  await workspace(page, 'radiologist', item => { delete (item.findings[1] as any).evidence })
  let release!: () => void
  const ready = new Promise<void>(resolve => { release = resolve })
  await page.route('**/api/images/**', async route => { await ready; await route.fallback() })
  await page.goto('/radiologist/cases/KN-TEST', { waitUntil: 'domcontentloaded' })
  await expect(page.locator('.viewer-canvas [role=status]')).toContainText('Loading MRI')
  await expect(page.locator('.evidence-card [role=status]').last()).toContainText('Loading Grad-CAM')
  release()
  await expect(page.locator('.viewer-canvas img')).toBeVisible()
  await expect(page.locator('.evidence-card img')).toHaveCount(2)
  await page.locator('.finding-row').nth(1).click()
  await expect(page.getByRole('region', { name: 'Evidence card for MCL' })).toContainText('Evidence unavailable')
  await expect(page.getByRole('button', { name: 'Grad-CAM', exact: true })).toBeDisabled()
})

test('processing and finalized empty views do not fabricate findings', async ({ page }) => {
  await workspace(page, 'radiologist', item => { item.status = 'PROCESSING'; item.findings = [] })
  await page.goto('/radiologist/cases/KN-TEST')
  await expect(page.getByRole('heading', { name: 'Preparing findings and evidence' })).toBeVisible()
  await expect(page.locator('.finding-row')).toHaveCount(0)
  await page.unroute('**/api/**')
  await workspace(page, 'orthopedist', item => { finalize(item); item.findings.forEach(f => { f.status = 'REJECTED' }); item.report.findings = 'No AI-proposed abnormalities were approved.'; item.report.statements = [] })
  await page.goto('/orthopedist/cases/KN-TEST')
  await expect(page.getByRole('heading', { name: 'No approved findings' })).toBeVisible()
  await expect(page.locator('main')).not.toContainText('Preparing findings')
  await page.getByRole('button', { name: 'View final report' }).click()
  await expect(page.getByLabel('Report findings')).toHaveValue('No AI-proposed abnormalities were approved.')
})

test('reference case preserves probabilities and simulated status without distributing scans', async ({ page }) => {
  const { requests } = await workspace(page)
  await page.goto('/radiologist/cases/sample-case')
  await expect(page.getByRole('heading', { name: 'Radhika', exact: true }).first()).toBeVisible()
  await expect(page.locator('.handoff-findings strong')).toHaveText(Object.keys(golden.ai.probabilities))
  for (const result of cam.results) {
    await page.locator('.handoff-findings .finding-row').nth(result.class_index).click()
    const evidence = page.getByRole('region', { name: 'Golden case evidence' })
    await expect(evidence).toContainText(String(golden.ai.probabilities[result.abnormality as keyof typeof golden.ai.probabilities]))
    await expect(evidence).toContainText(String(result.probability))
    await expect(evidence).toContainText(result.instance_numbers.join(', '))
    await expect(evidence.getByRole('img')).toHaveCount(0)
    await expect(evidence).toContainText(`Supplied Grad-CAM overlay for ${result.abnormality} unavailable.`)
  }
  await expect(page.getByRole('region', { name: 'Supplied draft report' })).toContainText('Final approval: PENDING')
  await expect(page.getByRole('button', { name: 'Approve', exact: true })).toHaveCount(0)
  expect(requests).toHaveLength(0)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.screenshot({ path: `test-results/handoff-${test.info().project.name}.png`, fullPage: true })
  await page.goto('/radiologist/cases')
  await expect(page.locator('main')).not.toContainText('KNEE-DEMO-001')
  await page.goto('/radiologist/validation')
  await expect(page.getByRole('region', { name: 'AI team handoff metadata' })).toContainText('0.7136243386243387')
  await page.goto('/radiologist/model')
  await expect(page.getByRole('region', { name: 'AI team handoff metadata' })).toContainText('ac59d8ce17a0b35c15189d691f7c6aa828f31a3dfe14601a02036a6c3b892a82')
})

test('live case properties use API values and never borrow golden-case context', async ({ page }) => {
  await workspace(page, 'radiologist', item => {
    Object.assign(item, { patient: { display_id: 'LIVE-TEST', age: 51, sex: 'Male' }, clinical_context: { symptoms: 'Supplied live symptoms', medical_history: 'Supplied live history', clinical_notes: 'Supplied live notes' } })
    Object.assign(item.analysis, { seriesEvaluated: 2, windowsEvaluated: 19, aggregation: 'mean_probability_across_study_windows', checkpointSha256: 'live-checkpoint-hash' })
    Object.assign(item.findings[0].evidence, { windowProbability: 0.987654321, plane: 'Coronal' })
  })
  await page.goto('/radiologist/cases/KN-TEST')
  await page.getByText('Patient & study information', { exact: true }).click()
  const details = page.locator('.study-details')
  for (const value of ['LIVE-TEST', '51 years', 'Male', 'Supplied live symptoms', 'Supplied live history', 'Supplied live notes', 'live-checkpoint-hash', 'mean_probability_across_study_windows']) await expect(details).toContainText(value)
  await expect(page.getByRole('region', { name: 'Evidence card for ACL' })).toContainText('0.987654321')
  await expect(page.getByRole('region', { name: 'Evidence card for ACL' })).toContainText('Coronal')
  await expect(page.locator('main')).not.toContainText(golden.patient.clinical_context.symptoms)
  await page.unroute('**/api/**')
  await workspace(page)
  await page.reload()
  await page.getByText('Patient & study information', { exact: true }).click()
  await expect(details).toContainText('Not supplied')
  await expect(details).not.toContainText('51 years')
})

test('dashboard summaries and analysis cards use live status and decision API', async ({ page }) => {
  const { requests } = await workspace(page)
  await page.goto('/radiologist/overview')
  await expect(page.locator('.brand').first()).toContainText('KNEURA')
  await expect(page.getByRole('region', { name: 'Active study', exact: true })).toContainText('12 findings')
  await expect(page.getByRole('region', { name: 'System status' })).toContainText('Reachable')
  await expect(page.getByRole('region', { name: 'System status' })).toContainText('Readiness not reported')
  await page.getByRole('button', { name: 'Open study', exact: true }).click()
  await page.getByRole('button', { name: 'AI analysis', exact: true }).click()
  await expect(page.locator('.analysis-cards article')).toHaveCount(12)
  const card = page.getByRole('article', { name: 'Analysis ACL', exact: true })
  await expect(card.getByRole('progressbar')).toHaveAttribute('value', '0.90947')
  await card.getByRole('button', { name: 'Approve', exact: true }).click()
  await expect(card).toContainText('Approved for report')
  await card.getByRole('button', { name: 'Reject', exact: true }).click()
  await expect(card).toContainText('Rejected by radiologist')
  expect(requests.map(request=>request.body.status)).toEqual(['APPROVED','REJECTED'])
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.screenshot({ path: `test-results/analysis-${test.info().project.name}.png`, fullPage: true })
  await card.getByRole('button', { name: 'View explanation' }).click()
  await expect(page.locator('.finding-row.selected')).toContainText('ACL')
})

test('MRI pan and reset preserve the selected finding and slice', async ({ page }) => {
  await workspace(page)
  await page.goto('/radiologist/cases/KN-TEST')
  await page.getByText('Image settings & evidence details', {exact:true}).click()
  await page.getByRole('button', { name: 'Zoom in', exact: true }).click()
  await page.getByRole('button', { name: 'Pan', exact: true }).click()
  const canvas = page.locator('.viewer-canvas')
  await canvas.scrollIntoViewIfNeeded()
  const box = (await canvas.boundingBox())!
  await page.mouse.move(box.x+box.width/2,box.y+box.height/2)
  await page.mouse.down()
  await page.mouse.move(box.x+box.width/2+30,box.y+box.height/2+20)
  await page.mouse.up()
  await expect(canvas.locator('img')).toHaveAttribute('style', /translate\(30px, 20px\) scale\(1.25\)/)
  await page.getByRole('button', { name: 'Reset view', exact: true }).click()
  await expect(canvas.locator('img')).toHaveAttribute('style', /translate\(0px, 0px\) scale\(1\)/)
  await expect(page.locator('.viewer-bottom-meta')).toContainText('INSTANCE 34')
  await expect(page.locator('.finding-row.selected')).toContainText('ACL')
})

test('system connectivity failure can be retried without claiming engine readiness', async ({ page }) => {
  await workspace(page)
  await page.route('**/api/health', route=>route.fulfill({ status: 503, json: { detail: 'Unavailable' } }))
  await page.goto('/radiologist/overview')
  const status = page.getByRole('region', { name: 'System status' })
  await expect(status).toContainText('Unavailable')
  await page.unroute('**/api/health')
  await status.getByRole('button', { name: 'Refresh status' }).click()
  await expect(status).toContainText('Reachable')
  await expect(status).toContainText('Readiness not reported')
})


test('case milestones and next pending finding track review decisions', async ({ page }) => {
  await workspace(page)
  await page.goto('/radiologist/cases/KN-TEST')
  const milestones = page.getByRole('list', { name: 'Case workflow milestones' })
  await expect(milestones).toContainText('0/12 reviewed')
  await expect(milestones.locator('[aria-current="step"]')).toContainText('Radiologist review')
  await page.getByRole('button', { name: 'Approve', exact: true }).click()
  await expect(milestones).toContainText('1/12 reviewed')
  await page.getByRole('button', { name: 'Next pending finding' }).click()
  await expect(page.locator('.finding-row.selected')).toContainText('MCL')
  await expect(page.locator('.finding-row.selected')).toHaveAttribute('aria-pressed', 'true')
  await expect(page.locator('.decision-panel .status')).toHaveText('PENDING')
})


test('evidence card jumps back to its input and errors offer retry', async ({ page }) => {
  await workspace(page)
  await page.goto('/radiologist/cases/KN-TEST')
  await page.getByRole('button', { name: 'Next slice', exact: true }).click()
  await expect(page.locator('.viewer-bottom-meta')).toContainText('INSTANCE 35')
  await page.getByRole('button', { name: 'Open evidence in MRI viewer' }).click()
  await expect(page.locator('.viewer-bottom-meta')).toContainText('INSTANCE 34')
  await page.unroute('**/api/**')
  await workspace(page, 'radiologist', item => { item.status = 'ERROR'; item.findings = []; (item as any).analysisError = 'Checkpoint unavailable. Retry after configuration.' })
  await page.goto('/radiologist/cases/KN-TEST')
  await expect(page.getByRole('button', { name: 'Retry analysis', exact: true })).toBeVisible()
  await expect(page.getByRole('alert')).toContainText('Checkpoint unavailable')
})

test('expired case request clears clinical workspace and requires sign-in', async ({ page }) => {
  await workspace(page)
  await page.goto('/radiologist/cases')
  await page.route('**/api/cases/KN-TEST', route => route.fulfill({ status: 401, json: { detail: 'Session expired' } }))
  await page.getByRole('button', { name: 'KN-TEST', exact: true }).click()
  await expect(page).toHaveURL('/login')
  await expect(page.getByLabel('Password', { exact: true })).toBeVisible()
  await expect(page.locator('.finding-row')).toHaveCount(0)
})


test('narrative job UI polls persisted state using an explicit API fixture', async ({ page }) => {
  const state = await workspace(page, 'radiologist', item => item.findings.forEach((f,i) => { f.status=i<5?'APPROVED':'REJECTED' }))
  await page.route('**/api/system/llm/health', route => route.fulfill({json:{configured:true,reachable:true,provider:'EXPLICIT TEST FIXTURE',model:'fixture'}}))
  await page.route('**/api/cases/KN-TEST/report-jobs', async route => {
    expect(route.request().postDataJSON().approvedFindingIds).toEqual(['F0','F1','F2','F3','F4'])
    ;(state.item as any).reportJob={id:'JOB-TEST',status:'PROCESSING'}
    await route.fulfill({status:202,json:{job_id:'JOB-TEST',status:'QUEUED'}})
  })
  await page.goto('/radiologist/cases/KN-TEST/report')
  await page.getByLabel('Permitted clinical indication').fill('De-identified test context.')
  await page.getByRole('button',{name:'Generate draft report',exact:true}).click()
  await expect(page.getByRole('region',{name:'Live LLM narrative'})).toContainText('PROCESSING')
  ;(state.item as any).reportJob.status='FAILED'
  ;(state.item as any).reportJob.error='Explicit simulated provider failure.'
  await expect(page.getByRole('button',{name:'Retry LLM report',exact:true})).toBeVisible()
  await expect(page.getByLabel('Report findings')).toHaveCount(0)
  await page.reload()
  await expect(page.getByRole('region',{name:'Live LLM narrative'})).toContainText('FAILED')
})


test('orthopedist release stays available while reading and displays server failure', async ({page}) => {
  const state = await workspace(page, 'orthopedist', finalize)
  let calls = 0
  await page.route('**/api/cases/KN-TEST/release-to-patient', async route => {
    calls++
    if (calls === 1) return route.fulfill({status:503,json:{detail:'Release temporarily unavailable. Please retry.'}})
    ;(state.item as any).releasedToPatient = true
    return route.fulfill({json:state.item})
  })
  await page.goto('/orthopedist/cases/KN-TEST/report')
  await expect(page.getByText('Awaiting your approval', {exact:true})).toBeVisible()
  const approval = page.getByRole('region', {name:'Orthopedist approval'})
  await expect(approval).toBeInViewport()
  await page.evaluate(() => window.scrollTo(0,document.body.scrollHeight))
  await expect(approval).toBeInViewport()
  await approval.getByRole('button',{name:'Approve for Patient',exact:true}).click()
  await expect(approval).toContainText('Release temporarily unavailable. Please retry.')
  await approval.getByRole('button',{name:'Approve for Patient',exact:true}).click()
  await expect(approval).toHaveCount(0)
  await page.reload()
  await expect(page.getByText('RELEASED TO PATIENT',{exact:true})).toBeVisible()
  await expect(page.getByRole('button',{name:'Approve for Patient',exact:true})).toHaveCount(0)
  expect(calls).toBe(2)
})

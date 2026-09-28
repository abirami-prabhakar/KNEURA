import { chromium } from 'playwright'
import { expect } from '@playwright/test'
import { spawn } from 'node:child_process'
import { mkdtemp, mkdir } from 'node:fs/promises'
import path from 'node:path'
import assert from 'node:assert/strict'

await mkdir('test-results', { recursive: true })
const data = await mkdtemp(path.resolve('test-results/patient-e2e-'))
const processes = []
const start = (command, args, env) => {
  const child = spawn(command, args, { windowsHide: true, env: { ...process.env, ...env }, stdio: ['ignore', 'pipe', 'pipe'] })
  processes.push(child)
  child.stderr.on('data', chunk => process.stderr.write(chunk))
  return child
}
const base = 'http://127.0.0.1:5175'
async function ready(url) {
  for (let i = 0; i < 100; i++) {
    try { if ((await fetch(url)).ok) return } catch { /* starting */ }
    await new Promise(resolve => setTimeout(resolve, 300))
  }
  throw new Error(`Server did not start: ${url}`)
}
let browser
try {
  start('python', ['-B', 'tests/patient_test_server.py', data, '8001'], { PYTHONDONTWRITEBYTECODE: '1', KNEURA_ORIGINS: base })
  start(process.execPath, ['node_modules/vite/bin/vite.js', '--host', '127.0.0.1', '--port', '5175', '--strictPort'], { VITE_API_BASE_URL: '/api', KNEURA_API_TARGET: 'http://127.0.0.1:8001' })
  await Promise.all([ready(base), ready('http://127.0.0.1:8001/api/health')])
  browser = await chromium.launch({ headless: true, channel: process.env.PLAYWRIGHT_CHANNEL || 'chrome' })
  const page = await browser.newPage()
  await page.goto(base + '/login')
  await page.getByLabel('Email address').fill('radiologist@example.test')
  await page.getByLabel('Password', { exact: true }).fill('test-password')
  await page.getByRole('button', { name: 'Enter your workspace' }).click()
  await expect(page).toHaveURL(/radiologist\/overview/)
  await page.getByRole('button', { name: 'New case', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  await expect(page.getByLabel('Patient Name *')).toBeFocused()
  await dialog.getByRole('button', { name: 'Create Case', exact: true }).click()
  await expect(dialog.getByText("Please enter the patient's name.")).toBeVisible()
  await expect(dialog.getByText('Please enter a valid age between 0 and 120.')).toBeVisible()
  await expect(dialog.getByText('Please select a gender.')).toBeVisible()
  await page.getByLabel('Patient Name *').fill('Demo Patient')
  await page.getByLabel('Gender *').selectOption('Female')
  for (const age of ['-5', '12.5', '121']) {
    await page.getByLabel('Age *', { exact: true }).fill(age)
    await dialog.getByRole('button', { name: 'Create Case', exact: true }).click()
    await expect(dialog.getByText('Please enter a valid age between 0 and 120.')).toBeVisible()
  }
  await dialog.getByRole('button', { name: 'Cancel', exact: true }).click()
  await expect(dialog).not.toBeVisible()
  assert.equal((await page.request.get(base + '/api/cases')).status(), 200)
  assert.equal((await (await page.request.get(base + '/api/cases')).json()).length, 0)
  await page.getByRole('button', { name: 'New case', exact: true }).click()
  await page.keyboard.press('Escape')
  await expect(dialog).not.toBeVisible()
  await page.getByRole('button', { name: 'New case', exact: true }).click()
  await page.getByLabel('Patient Name *').fill('Demo Patient')
  await page.getByLabel('Age *', { exact: true }).fill('42')
  await page.getByLabel('Gender *').selectOption('Female')
  await page.route('**/api/cases', async route => {
    if (route.request().method() === 'POST') await route.fulfill({ status: 500, contentType: 'application/json', body: '{}' })
    else await route.continue()
  })
  await dialog.getByRole('button', { name: 'Create Case', exact: true }).click()
  await expect(dialog.getByText(/request could not be completed/)).toBeVisible()
  await expect(page.getByLabel('Patient Name *')).toHaveValue('Demo Patient')
  await page.unroute('**/api/cases')
  let release, postCount = 0
  const gate = new Promise(resolve => { release = resolve })
  await page.route('**/api/cases', async route => {
    if (route.request().method() === 'POST') { postCount++; await gate }
    await route.continue()
  })
  await dialog.getByRole('button', { name: 'Create Case', exact: true }).click()
  await expect(dialog.getByRole('button', { name: 'Creating Case…' })).toBeDisabled()
  await page.keyboard.press('Enter')
  await page.keyboard.press('Escape')
  await expect(dialog).toBeVisible()
  release()
  await expect(page).toHaveURL(/\/radiologist\/cases\/KN-/)
  assert.equal(postCount, 1)
  const caseUrl = page.url()
  await expect(page.locator('.case-heading')).toContainText('Demo Patient')
  await expect(page.locator('.case-heading')).toContainText('42 years · Female')
  await page.reload()
  await expect(page.locator('.case-heading')).toContainText('Demo Patient')
  await page.goto(base + '/radiologist/cases')
  await expect(page.locator('tbody')).toContainText('Demo Patient')
  await expect(page.locator('tbody')).toContainText('42 years · Female')
  await page.locator('.case-link').click()
  await expect(page).toHaveURL(caseUrl)
  await expect(page.getByRole('button', { name: 'Start analysis' })).toBeDisabled()
  await page.locator('input[type=file]').setInputFiles(path.join(data, 'synthetic.zip'))
  await page.getByRole('button', { name: 'Upload study', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Start analysis' })).toBeEnabled({ timeout: 60000 })
  await page.reload()
  await expect(page.locator('.case-heading')).toContainText('Demo Patient')
  await expect(page.locator('.case-heading')).toContainText('42 years · Female')
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto(base + '/radiologist/overview')
  await page.getByRole('button', { name: 'New case', exact: true }).click()
  const box = await dialog.boundingBox()
  assert.ok(box.x >= 0 && box.x + box.width <= 390)
  await page.screenshot({ path: path.join(data, 'patient-dialog-mobile.png') })
  console.log('PASS: real login, dialog validation, cancel/Escape, API error, duplicate prevention, persistence after reload/reopen, queue display, DICOM attachment and mobile dialog.')
} finally {
  await browser?.close()
  for (const child of processes) child.kill()
}

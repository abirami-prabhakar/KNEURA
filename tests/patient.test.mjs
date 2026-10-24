import test from 'node:test'
import assert from 'node:assert/strict'
import { validatePatient, patientName, patientDemographics, caseLabel } from '../src/patient.ts'

test('patient input validation rejects missing or invalid data', () => {
  assert.deepEqual(Object.keys(validatePatient('', '', '')), ['name', 'age', 'gender'])
  for (const age of ['-5', '12.5', 'abc', '121', '']) assert.ok(validatePatient('Patient', age, 'Female').age)
  assert.ok(validatePatient('   ', '42', 'Female').name)
  assert.ok(validatePatient('x'.repeat(101), '42', 'Female').name)
  assert.ok(validatePatient('Patient', '42', 'Unknown').gender)
})
test('valid boundaries and inclusive names are accepted', () => {
  for (const age of ['0', '42', '120']) assert.deepEqual(validatePatient("  O’Neil-Sánchez 李  ", age, 'Prefer not to say'), {})
})
test('saved demographics take precedence, with safe legacy fallbacks', () => {
  const item = {study:{patientName:'DICOM Name'},patient:{name:'Entered Name',age:0,gender:'Female'}}
  assert.equal(patientName(item), 'Entered Name')
  assert.equal(patientDemographics(item), '0 years · Female')
  assert.equal(patientName({study:{patientName:'Legacy'}}), 'Legacy')
  assert.equal(patientDemographics({study:{patientName:'Legacy'}}), '')
})

test('case labels use saved name and age with identical legacy fallbacks', () => {
  assert.equal(caseLabel({study:{patientName:'DICOM Name'},patient:{name:'Entered Name',age:42}}), 'Entered Name · 42 years')
  assert.equal(caseLabel({study:{patientName:'Infant'},patient:{age:0}}), 'Infant · 0 years')
  assert.equal(caseLabel({study:{patientName:'Legacy'}}), 'Legacy · Age not supplied')
  assert.equal(caseLabel({study:{patientName:''}}), 'Patient information unavailable · Age not supplied')
})

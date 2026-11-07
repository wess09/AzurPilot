import { describe, expect, it } from 'vitest'
import languageJson from '../../public/setup-illustrations/language.json'
import importJson from '../../public/setup-illustrations/import.json'
import regionJson from '../../public/setup-illustrations/region.json'
import emulatorJson from '../../public/setup-illustrations/emulator.json'
import reviewJson from '../../public/setup-illustrations/review.json'

describe('InstanceSetup Windows OOBE Artworks', () => {
  const steps = [
    { artwork: 'language', json: languageJson, expectedName: '01 - Language' },
    { artwork: 'import', json: importJson, expectedName: '13 - One Drive - Segments' },
    { artwork: 'region', json: regionJson, expectedName: '02 - Region' },
    { artwork: 'emulator', json: emulatorJson, expectedName: '16 - Services - MMX' },
    { artwork: 'review', json: reviewJson, expectedName: '07 - EULA' },
  ]

  it('provides all 5 Windows 11 Fluent 3D Lottie animation files with consistent dimensions and frame rates', () => {
    for (const step of steps) {
      expect(step.json.nm).toBe(step.expectedName)
      expect(step.json.w).toBe(552)
      expect(step.json.h).toBe(552)
      expect(step.json.fr).toBe(60)
      expect(step.json.op).toBe(210)
    }
  })
})

import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

// Vitest has no globals by default, so Testing Library can't auto-register this.
afterEach(cleanup)

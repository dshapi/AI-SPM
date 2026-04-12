// ui/src/admin/pages/__tests__/Inventory.test.jsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import Inventory from '../Inventory.jsx'

vi.mock('../../../hooks/useFilterParams.js', () => ({
  useFilterParams: (defaults) => ({
    values: defaults,
    setters: Object.fromEntries(
      Object.keys(defaults).map(k => [
        `set${k.charAt(0).toUpperCase()}${k.slice(1)}`, vi.fn()
      ])
    ),
  }),
}))

function renderInventory(route) {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <Routes>
        <Route path="/admin/inventory"          element={<Inventory />} />
        <Route path="/admin/inventory/:assetId" element={<Inventory />} />
      </Routes>
    </MemoryRouter>
  )
}

describe('Inventory query param', () => {
  it('auto-selects asset when ?asset=<name> is in the URL', async () => {
    renderInventory('/admin/inventory?asset=CustomerSupport-GPT')
    await waitFor(() => {
      expect(screen.getByTestId('asset-preview-panel')).toBeInTheDocument()
    })
  })

  it('does nothing when ?asset=<name> matches no asset', async () => {
    renderInventory('/admin/inventory?asset=DOES_NOT_EXIST')
    await waitFor(() => {
      expect(screen.queryByTestId('asset-preview-panel')).not.toBeInTheDocument()
    })
  })

  it('still works normally with path param /:assetId', async () => {
    renderInventory('/admin/inventory/ag-001')
    await waitFor(() => {
      expect(screen.getByTestId('asset-preview-panel')).toBeInTheDocument()
    })
  })
})

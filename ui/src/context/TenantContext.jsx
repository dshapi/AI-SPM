// src/context/TenantContext.jsx
import { createContext, useContext, useState, useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'

const TENANTS = [
  { id: 'prod',       label: 'Production'  },
  { id: 'staging',    label: 'Staging'     },
  { id: 'dev',        label: 'Development' },
  { id: 'customer-a', label: 'Customer A'  },
]

const TenantContext = createContext(null)

export function TenantProvider({ children }) {
  const [searchParams, setSearchParams] = useSearchParams()

  // Priority: URL param → localStorage → default 'prod'
  const [tenant, setTenantState] = useState(() => {
    const fromUrl = searchParams.get('tenant')
    if (fromUrl && TENANTS.some(t => t.id === fromUrl)) return fromUrl
    return localStorage.getItem('orbyx_tenant') ?? 'prod'
  })

  const setTenant = (id) => {
    setTenantState(id)
    localStorage.setItem('orbyx_tenant', id)
    setSearchParams(prev => {
      prev.set('tenant', id)
      return prev
    }, { replace: true })
  }

  // Sync URL on mount if not already present
  useEffect(() => {
    if (!searchParams.get('tenant')) {
      setSearchParams(prev => {
        prev.set('tenant', tenant)
        return prev
      }, { replace: true })
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <TenantContext.Provider value={{ tenant, setTenant, tenants: TENANTS }}>
      {children}
    </TenantContext.Provider>
  )
}

export function useTenant() {
  const ctx = useContext(TenantContext)
  if (!ctx) throw new Error('useTenant must be used within TenantProvider')
  return ctx
}

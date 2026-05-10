// src/LoginPage.jsx
// Triggers Keycloak's hosted login page via Authorization Code + PKCE.
// Keycloak's page renders username/password AND any configured Identity
// Providers (Google, etc.) — this React component just kicks off the redirect.
//
// Why no local form: ROPC (the previous grant_type=password approach) cannot
// support social IdPs because Google never hands its users' credentials to a
// third-party form. Auth Code + PKCE delegates auth to Keycloak's UI and
// works for both local and federated users uniformly.
import { useEffect, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { loginRedirect } from './api.js'

export default function LoginPage() {
  const location = useLocation()
  const returnTo = location.state?.from?.pathname || '/admin/overview'
  const [error, setError] = useState(null)

  // Auto-redirect on first paint. Wrapped in a tiny delay so React has a
  // chance to render the "Redirecting..." UI before the page navigates away —
  // makes failures (e.g. Keycloak unreachable) visibly debuggable.
  useEffect(() => {
    const t = setTimeout(() => {
      loginRedirect(returnTo).catch(e => setError(e.message || String(e)))
    }, 50)
    return () => clearTimeout(t)
  }, [returnTo])

  return (
    <div style={{
      minHeight: '100vh',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      background: '#f8fafc',
      fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
    }}>
      <div style={{
        width: '100%',
        maxWidth: 400,
        background: '#fff',
        border: '1px solid #e5e7eb',
        borderRadius: 16,
        padding: '40px 36px',
        textAlign: 'center',
        boxShadow: '0 10px 40px rgba(0,0,0,0.07)',
      }}>
        <img src="/logo.png" alt="Orbyx" style={{ width: 64, height: 64, objectFit: 'contain', marginBottom: 16 }} />
        <h1 style={{ margin: 0, fontSize: '1.5rem', fontWeight: 700, color: '#0f172a', letterSpacing: '-0.02em' }}>
          Orbyx AISPM
        </h1>

        {!error && (
          <p style={{ margin: '12px 0 0', fontSize: '0.875rem', color: '#64748b' }}>
            Redirecting to sign-in&hellip;
          </p>
        )}

        {error && (
          <>
            <p style={{
              marginTop: 20, padding: '10px 14px',
              background: '#fef2f2', border: '1px solid #fecaca',
              borderRadius: 8, fontSize: '0.875rem', color: '#dc2626',
              textAlign: 'left',
            }}>
              {error}
            </p>
            <button
              onClick={() => { setError(null); loginRedirect(returnTo).catch(e => setError(e.message)) }}
              style={{
                marginTop: 16, padding: '11px 24px',
                background: 'linear-gradient(135deg, #2563EB, #06B6D4)',
                color: '#fff', border: 'none', borderRadius: 8,
                fontSize: '0.9375rem', fontWeight: 600, cursor: 'pointer',
              }}
            >
              Try again
            </button>
          </>
        )}
      </div>
    </div>
  )
}

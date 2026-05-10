// src/AuthCallback.jsx
// Handles the OAuth Authorization Code redirect from Keycloak.
//
// Flow:
//   1. User clicked "Sign in" in LoginPage → redirected to Keycloak
//   2. User authenticated (local or via Google IdP)
//   3. Keycloak redirects to /auth/callback?code=...&state=...
//   4. This component runs on mount: exchanges the code for tokens
//      (PKCE-protected), then navigates the user to the page they originally
//      requested before being bounced to /login.
//
// Errors render in-place rather than redirecting back to /login, because a
// loop (login → callback fails → login → callback fails) is a worse user
// experience than a clear error message with a "Try again" button.
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { handleAuthCallback, loginRedirect } from './api.js'

export default function AuthCallback() {
  const navigate = useNavigate()
  const [error, setError] = useState(null)

  useEffect(() => {
    handleAuthCallback()
      .then(returnTo => {
        // Strip the code/state from URL history so a refresh doesn't re-attempt
        // the now-consumed authorization code (one-time use).
        navigate(returnTo, { replace: true })
      })
      .catch(e => setError(e.message || String(e)))
  }, [navigate])

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
        maxWidth: 480,
        background: '#fff',
        border: '1px solid #e5e7eb',
        borderRadius: 16,
        padding: '40px 36px',
        textAlign: 'center',
        boxShadow: '0 10px 40px rgba(0,0,0,0.07)',
      }}>
        {!error && (
          <>
            <h1 style={{ margin: 0, fontSize: '1.25rem', fontWeight: 600, color: '#0f172a' }}>
              Signing you in&hellip;
            </h1>
            <p style={{ margin: '12px 0 0', fontSize: '0.875rem', color: '#64748b' }}>
              Completing the sign-in handshake.
            </p>
          </>
        )}
        {error && (
          <>
            <h1 style={{ margin: 0, fontSize: '1.25rem', fontWeight: 600, color: '#dc2626' }}>
              Sign-in failed
            </h1>
            <p style={{
              marginTop: 16, padding: '10px 14px',
              background: '#fef2f2', border: '1px solid #fecaca',
              borderRadius: 8, fontSize: '0.875rem', color: '#dc2626',
              textAlign: 'left', wordBreak: 'break-word',
            }}>
              {error}
            </p>
            <button
              onClick={() => loginRedirect('/admin/overview').catch(e => setError(e.message))}
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

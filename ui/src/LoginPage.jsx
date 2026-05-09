// src/LoginPage.jsx
// Shown to any unauthenticated user. Calls api.login() then navigates to the
// originally-requested page (or /admin/overview as default).
import { useState } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { login } from './api.js'

export default function LoginPage() {
  const navigate  = useNavigate()
  const location  = useLocation()
  const from      = location.state?.from?.pathname || '/admin/overview'

  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error,    setError]    = useState(null)
  const [loading,  setLoading]  = useState(false)

  async function handleSubmit(e) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      await login(username, password)
      navigate(from, { replace: true })
    } catch {
      setError('Invalid username or password.')
    } finally {
      setLoading(false)
    }
  }

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
        boxShadow: '0 10px 40px rgba(0,0,0,0.07)',
      }}>

        {/* Logo + title */}
        <div style={{ textAlign: 'center', marginBottom: 32 }}>
          <img src="/logo.png" alt="Orbyx" style={{ width: 64, height: 64, objectFit: 'contain', marginBottom: 16 }} />
          <h1 style={{ margin: 0, fontSize: '1.5rem', fontWeight: 700, color: '#0f172a', letterSpacing: '-0.02em' }}>
            Orbyx AISPM
          </h1>
          <p style={{ margin: '6px 0 0', fontSize: '0.875rem', color: '#64748b' }}>
            Sign in to your account
          </p>
        </div>

        {/* Error banner */}
        {error && (
          <div style={{
            marginBottom: 20,
            padding: '10px 14px',
            background: '#fef2f2',
            border: '1px solid #fecaca',
            borderRadius: 8,
            fontSize: '0.875rem',
            color: '#dc2626',
          }}>
            {error}
          </div>
        )}

        {/* Form */}
        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div>
            <label style={{ display: 'block', fontSize: '0.8125rem', fontWeight: 500, color: '#374151', marginBottom: 6 }}>
              Username
            </label>
            <input
              type="text"
              value={username}
              onChange={e => setUsername(e.target.value)}
              autoComplete="username"
              required
              style={{
                width: '100%',
                boxSizing: 'border-box',
                padding: '10px 12px',
                border: '1.5px solid #e5e7eb',
                borderRadius: 8,
                fontSize: '0.9375rem',
                color: '#111827',
                outline: 'none',
                transition: 'border-color 0.15s',
              }}
              onFocus={e  => e.target.style.borderColor = '#2563eb'}
              onBlur={e   => e.target.style.borderColor = '#e5e7eb'}
            />
          </div>

          <div>
            <label style={{ display: 'block', fontSize: '0.8125rem', fontWeight: 500, color: '#374151', marginBottom: 6 }}>
              Password
            </label>
            <input
              type="password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              autoComplete="current-password"
              required
              style={{
                width: '100%',
                boxSizing: 'border-box',
                padding: '10px 12px',
                border: '1.5px solid #e5e7eb',
                borderRadius: 8,
                fontSize: '0.9375rem',
                color: '#111827',
                outline: 'none',
                transition: 'border-color 0.15s',
              }}
              onFocus={e  => e.target.style.borderColor = '#2563eb'}
              onBlur={e   => e.target.style.borderColor = '#e5e7eb'}
            />
          </div>

          <button
            type="submit"
            disabled={loading || !username || !password}
            style={{
              marginTop: 8,
              padding: '11px 0',
              background: loading || !username || !password
                ? '#e5e7eb'
                : 'linear-gradient(135deg, #2563EB, #06B6D4)',
              color: loading || !username || !password ? '#9ca3af' : '#fff',
              border: 'none',
              borderRadius: 8,
              fontSize: '0.9375rem',
              fontWeight: 600,
              cursor: loading || !username || !password ? 'not-allowed' : 'pointer',
              transition: 'opacity 0.15s',
            }}
          >
            {loading ? 'Signing in…' : 'Sign in'}
          </button>
        </form>

      </div>
    </div>
  )
}

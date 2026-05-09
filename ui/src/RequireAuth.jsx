// src/RequireAuth.jsx
// Wraps any route that needs a valid token. Unauthenticated users are
// redirected to /login and, after signing in, bounce back to where they came from.
import { useEffect, useState } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { getToken } from './api.js'

export default function RequireAuth({ children }) {
  const location = useLocation()
  const [checked, setChecked] = useState(false)
  const [authed,  setAuthed]  = useState(false)

  useEffect(() => {
    getToken().then(token => {
      setAuthed(!!token)
      setChecked(true)
    })
  }, [location.pathname])

  if (!checked) return null  // briefly blank while the async check resolves

  if (!authed) {
    return <Navigate to="/login" state={{ from: location }} replace />
  }

  return children
}

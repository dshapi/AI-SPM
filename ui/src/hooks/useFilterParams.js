// src/hooks/useFilterParams.js
import { useCallback, useRef } from 'react'
import { useSearchParams } from 'react-router-dom'

/**
 * useFilterParams — manage page filter state in the URL.
 *
 * @param {Object} defaults — { key: defaultValue } pairs.
 *   - String default: param is omitted from URL when value === default.
 *   - Boolean default (false): param is omitted when false, set to '1' when true.
 *
 * Returns an object with:
 *   - values: { key: currentValue }
 *   - setters: { setKey: fn }
 *   - reset: () => void — restore all params to defaults
 *
 * Usage:
 *   const { values, setters } = useFilterParams({
 *     severity: 'All Severity',
 *     highRiskOnly: false,
 *   })
 *   const { severity, highRiskOnly } = values
 *   const { setSeverity, setHighRiskOnly } = setters
 */
export function useFilterParams(defaults) {
  const [searchParams, setSearchParams] = useSearchParams()

  // Read current values from URL (or fall back to defaults)
  const values = {}
  for (const [key, def] of Object.entries(defaults)) {
    if (typeof def === 'boolean') {
      values[key] = searchParams.get(key) === '1'
    } else {
      values[key] = searchParams.get(key) ?? def
    }
  }

  // Each setter is recreated each render — fine because setSearchParams is stable
  // and these are not passed to memoized children in this codebase.
  const setters = {}
  for (const [key, def] of Object.entries(defaults)) {
    const Name = key.charAt(0).toUpperCase() + key.slice(1)
    setters[`set${Name}`] = (value) => {
      setSearchParams(prev => {
        const isDefault = typeof def === 'boolean' ? !value : value === def
        if (isDefault) {
          prev.delete(key)
        } else {
          prev.set(key, typeof def === 'boolean' ? '1' : value)
        }
        return prev
      }, { replace: true })
    }
  }

  // keysRef captures key names once on mount — they never change at runtime.
  // Using a ref avoids including `defaults` (new object each render) in a useCallback dep.
  const keysRef = useRef(Object.keys(defaults))

  const reset = useCallback(() => {
    setSearchParams(prev => {
      for (const key of keysRef.current) {
        prev.delete(key)
      }
      return prev
    }, { replace: true })
  }, [setSearchParams])

  return { values, setters, reset }
}

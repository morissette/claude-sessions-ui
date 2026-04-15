import { useState, useEffect } from 'react'

export function usePersistedState(key, defaultValue) {
  const [state, setState] = useState(() => {
    try {
      const raw = localStorage.getItem(key)
      if (!raw) return defaultValue
      const parsed = JSON.parse(raw)
      return parsed
    } catch {
      return defaultValue
    }
  })

  useEffect(() => {
    try {
      localStorage.setItem(key, JSON.stringify(state))
    } catch {
      // localStorage unavailable (private mode, quota exceeded) — silently ignore
    }
  }, [key, state])

  return [state, setState]
}

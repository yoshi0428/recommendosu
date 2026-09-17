const API_BASE = '/api/v1'

export async function getCurrentUser() {
  const response = await fetch(`${API_BASE}/auth/me`, {
    credentials: 'include',
  })

  if (!response.ok) {
    return null
  }

  return response.json()
}

export async function logout() {
  const response = await fetch(`${API_BASE}/auth/logout`, {
    method: 'POST',
    credentials: 'include',
  })

  if (!response.ok) {
    throw new Error('Failed to log out.')
  }
}

export function login() {
  window.location.href = `${API_BASE}/auth/osu`
}

export async function getRecommendations(body, options = {}) {
  const response = await fetch(`${API_BASE}/recommend`, {
    method: 'POST',
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(body),
    signal: options.signal, // <-- Pass the AbortController signal here
  })

  const data = await response.json()

  if (!response.ok) {
    const detail = Array.isArray(data.detail)
      ? data.detail
        .map((error) => {
          const location = error.loc?.join('.') ?? ''
          return `${location}: ${error.msg}`
        })
        .join('\n')
      : data.detail

    throw new Error(
      detail ||
      `Request failed with status ${response.status}`
    )
  }

  return data
}
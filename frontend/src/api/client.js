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
  const headers = {
    'Content-Type': 'application/json',
  }

  if (options.recommendationId) {
    headers['X-Recommendation-Id'] = options.recommendationId
  }

  const response = await fetch(`${API_BASE}/recommend`, {
    method: 'POST',
    credentials: 'include',
    headers,
    body: JSON.stringify(body),
    signal: options.signal,
  })

  const contentType = response.headers.get('content-type') || ''

  // Nginx can return an HTML 504 page when the recommendation backend takes too long to respond.
  // Do not try to parse that HTML response as JSON.
  if (response.status === 504) {
    throw new Error(
      'Recommendation generation took too long. ' +
      'The server timed out while waiting for the recommendations.'
    )
  }

  // Only parse the response as JSON when the server actually says that it returned JSON.
  if (contentType.includes('application/json')) {
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
        `Recommendation request failed with status ${response.status}`
      )
    }

    return data
  }

  // Any other non-JSON response is unexpected.
  // This handles HTML error pages and other proxy/server responses safely.
  throw new Error(
    `Recommendation request failed with status ${response.status}. ` +
    `Server returned ${contentType || 'an unknown response type'}.`
  )
}

export async function cancelRecommendation(recommendationId) {
  const response = await fetch(
    `${API_BASE}/recommend/${recommendationId}/cancel`,
    {
      method: 'POST',
      credentials: 'include',
    }
  )

  if (!response.ok) {
    const data = await response.json().catch(() => null)

    throw new Error(
      data?.detail ||
      `Cancellation request failed with status ${response.status}`
    )
  }

  return response.json()
}

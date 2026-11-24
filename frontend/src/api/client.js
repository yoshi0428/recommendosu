const API_BASE = "/api/v1";

// Make an Error from a failed response. Use the "detail" message of the
// backend if the body has one. If not, name the request and the status.
async function responseError(response, request) {
  const data = await response.json().catch(() => null);
  return new Error(
    data?.detail || `${request} failed with status ${response.status}`
  );
}

export async function getCurrentUser() {
  const response = await fetch(`${API_BASE}/auth/me`, {
    credentials: "include",
  });

  if (!response.ok) {
    return null;
  }

  return response.json();
}

export async function logout() {
  const response = await fetch(`${API_BASE}/auth/logout`, {
    method: "POST",
    credentials: "include",
  });

  if (!response.ok) {
    throw new Error("Failed to log out.");
  }
}

export async function getChangelog() {
  const response = await fetch(`${API_BASE}/changelog`);

  if (!response.ok) {
    throw new Error(`Failed to load the changelog (status ${response.status}).`);
  }

  return response.json();
}

export function login() {
  window.location.href = `${API_BASE}/auth/osu`;
}

export async function getRecommendations(body, options = {}) {
  const headers = {
    "Content-Type": "application/json",
  };

  if (options.recommendationId) {
    headers["X-Recommendation-Id"] = options.recommendationId;
  }

  const response = await fetch(`${API_BASE}/recommend`, {
    method: "POST",
    credentials: "include",
    headers,
    body: JSON.stringify(body),
    signal: options.signal,
  });

  // A recommendation that cancelRecommendation() cancelled ends with 204 and
  // no body.
  if (response.status === 204) {
    return null;
  }

  const contentType = response.headers.get("content-type") || "";

  // If the backend takes too long, Nginx can return an HTML 504 page. Do not
  // parse that HTML as JSON.
  if (response.status === 504) {
    throw new Error(
      "Recommendation generation took too long. " +
        "The server timed out while waiting for the recommendations."
    );
  }

  // Parse the response as JSON only if the server says that it is JSON.
  if (contentType.includes("application/json")) {
    const data = await response.json();

    if (!response.ok) {
      const detail = Array.isArray(data.detail)
        ? data.detail
            .map((error) => {
              const location = error.loc?.join(".") ?? "";
              return `${location}: ${error.msg}`;
            })
            .join("\n")
        : data.detail;

      throw new Error(
        detail || `Recommendation request failed with status ${response.status}`
      );
    }

    return data;
  }

  // Any other response that is not JSON is unexpected, for example an HTML
  // error page from the proxy. Report its status and type.
  throw new Error(
    `Recommendation request failed with status ${response.status}. ` +
      `Server returned ${contentType || "an unknown response type"}.`
  );
}

export async function getRecommendationPage(
  recommendationId,
  offset,
  limit,
  options = {}
) {
  const params = new URLSearchParams({
    offset: String(offset),
    limit: String(limit),
  });

  const response = await fetch(
    `${API_BASE}/recommend/${recommendationId}/page?${params}`,
    {
      credentials: "include",
      signal: options.signal,
    }
  );

  if (!response.ok) {
    throw await responseError(response, "Recommendation page request");
  }

  return response.json();
}

export async function cancelRecommendation(recommendationId) {
  const response = await fetch(
    `${API_BASE}/recommend/${recommendationId}/cancel`,
    {
      method: "POST",
      credentials: "include",
    }
  );

  if (!response.ok) {
    throw await responseError(response, "Cancellation request");
  }

  return response.json();
}

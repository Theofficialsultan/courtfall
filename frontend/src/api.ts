export async function apiGet<T>(path: string): Promise<T> {
  const response = await fetch(`/api${path}`)
  if (!response.ok) {
    throw new Error(`Request failed (${response.status})`)
  }
  return response.json() as Promise<T>
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`/api${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })
  if (!response.ok) {
    throw new Error(`Request failed (${response.status})`)
  }
  return response.json() as Promise<T>
}

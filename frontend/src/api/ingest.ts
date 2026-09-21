export interface IngestResult {
  repo: string
  pull_requests: number
  issues: number
}

export class IngestError extends Error {
  status: number
  retryAfter?: number

  constructor(message: string, status: number, retryAfter?: number) {
    super(message)
    this.status = status
    this.retryAfter = retryAfter
  }
}

const FALLBACK: Record<number, string> = {
  404: 'Repository not found or not accessible.',
  429: 'GitHub rate limit reached. Try again later.',
  502: 'GitHub returned an unexpected response.',
  503: 'Graph database is unavailable.',
}

/** POST /api/ingest/github (T-7.5). Throws IngestError with a user-facing message. */
export async function ingestRepo(repoUrl: string): Promise<IngestResult> {
  let res: Response
  try {
    res = await fetch('/api/ingest/github', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ repo_url: repoUrl }),
    })
  } catch {
    throw new IngestError('Could not reach the Cortex server.', 0)
  }

  if (res.ok) return (await res.json()) as IngestResult

  let detail: string | undefined
  try {
    const body = await res.json()
    // FastAPI sends a string for our errors, but a list for request-shape errors.
    if (typeof body.detail === 'string') detail = body.detail
  } catch {
    // non-JSON error body; use the fallback below
  }
  const retryAfter = Number(res.headers.get('Retry-After')) || undefined
  throw new IngestError(
    detail ?? FALLBACK[res.status] ?? `Request failed (${res.status}).`,
    res.status,
    retryAfter,
  )
}

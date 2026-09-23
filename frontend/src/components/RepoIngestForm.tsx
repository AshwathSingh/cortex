import { useState, type FormEvent } from 'react'
import { ingestRepo, IngestError, type IngestResult } from '../api/ingest'

type Status =
  | { kind: 'idle' }
  | { kind: 'loading' }
  | { kind: 'success'; result: IngestResult }
  | { kind: 'error'; message: string }

export default function RepoIngestForm() {
  const [repoUrl, setRepoUrl] = useState('')
  const [status, setStatus] = useState<Status>({ kind: 'idle' })

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    const url = repoUrl.trim()
    if (!url) {
      setStatus({ kind: 'error', message: 'Enter a GitHub repository URL.' })
      return
    }
    setStatus({ kind: 'loading' })
    try {
      setStatus({ kind: 'success', result: await ingestRepo(url) })
    } catch (err) {
      const message =
        err instanceof IngestError ? err.message : 'Something went wrong. Please try again.'
      setStatus({ kind: 'error', message })
    }
  }

  const loading = status.kind === 'loading'

  return (
    <form onSubmit={onSubmit} noValidate aria-label="Ingest a GitHub repository">
      <label htmlFor="repo-url">GitHub repository URL</label>
      <input
        id="repo-url"
        type="url"
        value={repoUrl}
        onChange={(e) => setRepoUrl(e.target.value)}
        placeholder="https://github.com/owner/repo"
        disabled={loading}
        autoComplete="off"
        spellCheck={false}
      />
      <button type="submit" disabled={loading}>
        {loading ? 'Ingesting…' : 'Ingest repository'}
      </button>

      <div aria-live="polite">
        {loading && <p className="hint">Fetching pull requests and issues. Large repos can take a while.</p>}
        {status.kind === 'error' && (
          <p role="alert" className="error">
            {status.message}
          </p>
        )}
        {status.kind === 'success' && (
          <p role="status" className="success">
            Ingested <strong>{status.result.repo}</strong>: {status.result.pull_requests} pull
            requests, {status.result.issues} issues.
          </p>
        )}
      </div>
    </form>
  )
}

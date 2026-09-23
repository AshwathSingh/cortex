import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import RepoIngestForm from './RepoIngestForm'

function mockFetch(status: number, body: unknown, headers: Record<string, string> = {}) {
  const fn = vi.fn().mockResolvedValue(
    new Response(JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json', ...headers },
    }),
  )
  vi.stubGlobal('fetch', fn)
  return fn
}

async function submit(url: string) {
  const user = userEvent.setup()
  render(<RepoIngestForm />)
  if (url) await user.type(screen.getByLabelText(/repository url/i), url)
  await user.click(screen.getByRole('button', { name: /ingest repository/i }))
}

afterEach(() => vi.unstubAllGlobals())

describe('RepoIngestForm', () => {
  it('posts the URL and shows the counts on success', async () => {
    const fetchFn = mockFetch(200, { repo: 'o/r', pull_requests: 3, issues: 2 })
    await submit('https://github.com/o/r')

    expect(await screen.findByRole('status')).toHaveTextContent('o/r: 3 pull requests, 2 issues')
    const [url, init] = fetchFn.mock.calls[0]
    expect(url).toBe('/api/ingest/github')
    expect(JSON.parse(init.body)).toEqual({ repo_url: 'https://github.com/o/r' })
  })

  it('shows the server message for an invalid URL (422)', async () => {
    mockFetch(422, { detail: "Not a GitHub repository URL: 'https://gitlab.com/a/b'" })
    await submit('https://gitlab.com/a/b')
    expect(await screen.findByRole('alert')).toHaveTextContent('Not a GitHub repository URL')
  })

  it('does not call the API for an empty input', async () => {
    const fetchFn = mockFetch(200, {})
    await submit('')
    expect(screen.getByRole('alert')).toHaveTextContent(/enter a github repository url/i)
    expect(fetchFn).not.toHaveBeenCalled()
  })

  it.each([
    [404, 'not found'],
    [429, 'rate limit'],
    [503, 'unavailable'],
  ])('shows a readable error for %i', async (status, text) => {
    mockFetch(status, {})
    await submit('https://github.com/o/r')
    expect(await screen.findByRole('alert')).toHaveTextContent(new RegExp(text, 'i'))
  })

  it('handles a list-shaped detail (request validation) without crashing', async () => {
    mockFetch(422, { detail: [{ msg: 'Field required' }] })
    await submit('https://github.com/o/r')
    expect(await screen.findByRole('alert')).toHaveTextContent(/request failed \(422\)/i)
  })

  it('shows an error when the server is unreachable', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('network')))
    await submit('https://github.com/o/r')
    expect(await screen.findByRole('alert')).toHaveTextContent(/could not reach/i)
  })

  it('disables the form while the request is in flight', async () => {
    let resolve!: (r: Response) => void
    vi.stubGlobal('fetch', vi.fn().mockReturnValue(new Promise<Response>((r) => (resolve = r))))
    await submit('https://github.com/o/r')

    expect(screen.getByRole('button', { name: /ingesting/i })).toBeDisabled()
    expect(screen.getByLabelText(/repository url/i)).toBeDisabled()

    resolve(new Response(JSON.stringify({ repo: 'o/r', pull_requests: 0, issues: 0 }), { status: 200 }))
    expect(await screen.findByRole('status')).toBeInTheDocument()
  })
})

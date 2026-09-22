import RepoIngestForm from './components/RepoIngestForm'

// Placeholder shell; app-wide routing/layout is owned by US-42.
export default function App() {
  return (
    <main>
      <h1>Cortex</h1>
      <p>Add a GitHub repository to build its knowledge graph.</p>
      <RepoIngestForm />
    </main>
  )
}

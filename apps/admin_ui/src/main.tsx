import React, {useEffect, useState} from 'react';
import {createRoot} from 'react-dom/client';
import {
  MissingAdminCredentialError,
  adminDevHeadersEnabled,
  decorateAdminRequest,
  getStoredAdminApiKey,
  storeAdminApiKey,
} from './auth';
import './styles.css';

type Modes = Record<string, any>;
type ApiResult = Record<string, any>;
const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8080';

async function api(path: string, init?: RequestInit, apiKey?: string | null) {
  const request = decorateAdminRequest(init, {apiKey});
  const requestHeaders = new Headers(request.headers);
  if (!requestHeaders.has('Content-Type')) requestHeaders.set('Content-Type', 'application/json');
  const res = await fetch(`${API_BASE}${path}`, {...request, headers: requestHeaders});
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json();
}

function errorResult(error: unknown): ApiResult {
  if (error instanceof MissingAdminCredentialError) {
    return {error: error.message, status: 'missing_credential'};
  }
  return {error: String(error)};
}

function JsonBlock({value}: {value: ApiResult | null}) {
  if (!value) return <pre className="muted">No response yet.</pre>;
  return <pre>{JSON.stringify(value, null, 2)}</pre>;
}

function App() {
  const [modes, setModes] = useState<Modes>({});
  const [session, setSession] = useState<ApiResult | null>(null);
  const [apiKey, setApiKey] = useState(getStoredAdminApiKey());
  const [mode, setMode] = useState('pdf_markdown_external_v1');
  const [title, setTitle] = useState('Expert AI Services knowledge document');
  const [filename, setFilename] = useState('expert-ai-services-knowledge.md');
  const [vectorStoreId, setVectorStoreId] = useState('vs_dev');
  const [knowledgeBaseId, setKnowledgeBaseId] = useState('kb_dev');
  const [content, setContent] = useState('# Expert AI Services\n\n<!-- page: 1 -->\nThis is an exai_vector_store production-candidate document for retrieval.');
  const [query, setQuery] = useState('What does the Expert AI Services document say?');
  const [result, setResult] = useState<ApiResult | null>(null);
  const [busy, setBusy] = useState(false);
  const devHeaders = adminDevHeadersEnabled();

  useEffect(() => { refreshSession(); }, []);

  function updateApiKey(value: string) {
    setApiKey(value);
    storeAdminApiKey(value);
  }

  async function refreshSession() {
    setBusy(true);
    try {
      const sessionRes = await api('/api/v1/admin/session', undefined, apiKey);
      setSession(sessionRes);
      const modesRes = await api('/api/v1/vectorization/modes', undefined, apiKey);
      setModes(modesRes.modes || {});
      setResult(sessionRes);
    } catch (e) {
      setSession(null);
      setResult(errorResult(e));
    } finally {
      setBusy(false);
    }
  }

  async function createVectorStore() {
    setBusy(true);
    try {
      const res = await api('/v1/vector_stores', {method: 'POST', body: JSON.stringify({name: 'Expert AI Services Vector Store', knowledge_base_id: knowledgeBaseId, attributes: {owner: 'mfrieson@expertaiservices.com', project: 'exai_vector_store'}})}, apiKey);
      setVectorStoreId(res.id);
      setResult(res);
    } catch (e) { setResult(errorResult(e)); } finally { setBusy(false); }
  }


  async function previewPlan() {
    setBusy(true);
    try {
      const res = await api('/api/v1/ingestion/preview', {method: 'POST', body: JSON.stringify({vector_store_id: vectorStoreId, knowledge_base_id: knowledgeBaseId, title, filename, mime_type: 'text/markdown', mode, content, security_level: 1, attributes: {source_pdf_id: mode === 'pdf_markdown_external_v1' ? 'external_pdf_markdown_bundle' : undefined}, persist: true})}, apiKey);
      setResult(res);
    } catch (e) { setResult(errorResult(e)); } finally { setBusy(false); }
  }

  async function ingest() {
    setBusy(true);
    try {
      const res = await api('/api/v1/documents/ingest', {method: 'POST', body: JSON.stringify({vector_store_id: vectorStoreId, knowledge_base_id: knowledgeBaseId, title, filename, mime_type: 'text/markdown', mode, content, security_level: 1, attributes: {source_pdf_id: mode === 'pdf_markdown_external_v1' ? 'external_pdf_markdown_bundle' : undefined}})}, apiKey);
      setResult(res);
    } catch (e) { setResult(errorResult(e)); } finally { setBusy(false); }
  }

  async function search() {
    setBusy(true);
    try {
      const res = await api('/api/v1/retrieval/search', {method: 'POST', body: JSON.stringify({query, vector_store_id: vectorStoreId, mode, top_k: 5})}, apiKey);
      setResult(res);
    } catch (e) { setResult(errorResult(e)); } finally { setBusy(false); }
  }

  return <main>
    <header>
      <h1>exai_vector_store</h1>
      <p>Expert AI Services vector retrieval platform for expertaiservices.com.</p>
    </header>

    <section className="grid">
      <div className="card">
        <h2>Admin session</h2>
        <label>Bearer API key <input type="password" value={apiKey} onChange={e => updateApiKey(e.currentTarget.value)} placeholder="svs_live_..." /></label>
        <div className="row"><button disabled={busy} onClick={refreshSession}>Connect</button><span className="muted">{devHeaders ? 'Dev headers enabled' : 'Production bearer required'}</span></div>
        <JsonBlock value={session} />
      </div>
      <div className="card">
        <h2>Vectorization mode</h2>
        <select value={mode} onChange={e => setMode(e.target.value)}>{Object.keys(modes).map(m => <option key={m} value={m}>{m}</option>)}</select>
        <p className="muted">Mode controls parser/chunker/tokenizer/embedding/rerank/retrieval defaults.</p>
        <JsonBlock value={modes[mode] || null} />
      </div>
    </section>

    <section className="card">
      <h2>OpenAI-compatible vector store</h2>
      <div className="row"><input value={knowledgeBaseId} onChange={e => setKnowledgeBaseId(e.target.value)} /><input value={vectorStoreId} onChange={e => setVectorStoreId(e.target.value)} /><button disabled={busy} onClick={createVectorStore}>Create store</button></div>
    </section>

    <section className="card">
      <h2>Ingest</h2>
      <div className="row"><input value={title} onChange={e => setTitle(e.target.value)} /><input value={filename} onChange={e => setFilename(e.target.value)} /></div>
      <textarea value={content} onChange={e => setContent(e.target.value)} rows={12} />
      <div className="row"><button disabled={busy} onClick={previewPlan}>Preview plan</button><button disabled={busy} onClick={ingest}>Ingest document</button></div>
    </section>

    <section className="card">
      <h2>Retrieve</h2>
      <div className="row"><input value={query} onChange={e => setQuery(e.target.value)} /><button disabled={busy} onClick={search}>Search</button></div>
    </section>

    <section className="card">
      <h2>Response</h2>
      <JsonBlock value={result} />
    </section>
  </main>;
}

createRoot(document.getElementById('root')!).render(<App />);

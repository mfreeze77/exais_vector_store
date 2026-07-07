import React, {useEffect, useState} from 'react';
import {createRoot} from 'react-dom/client';
import './styles.css';

type Modes = Record<string, any>;
type ApiResult = Record<string, any>;
const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8080';

function headers() {
  return {
    'Content-Type': 'application/json',
    'x-svs-tenant-id': localStorage.getItem('svs_tenant') || 'ten_dev',
    'x-svs-business-instance-id': localStorage.getItem('svs_biz') || 'biz_dev',
    'x-svs-user-id': localStorage.getItem('svs_user') || 'usr_dev',
    'x-svs-groups': localStorage.getItem('svs_groups') || 'grp_admin,grp_eng,admins,engineering',
    'x-svs-roles': localStorage.getItem('svs_roles') || 'owner,admin',
    'x-svs-max-security-level': localStorage.getItem('svs_level') || '5'
  };
}

async function api(path: string, init?: RequestInit) {
  const res = await fetch(`${API_BASE}${path}`, {...init, headers: {...headers(), ...(init?.headers || {})}});
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json();
}

function JsonBlock({value}: {value: ApiResult | null}) {
  if (!value) return <pre className="muted">No response yet.</pre>;
  return <pre>{JSON.stringify(value, null, 2)}</pre>;
}

function App() {
  const [modes, setModes] = useState<Modes>({});
  const [mode, setMode] = useState('pdf_markdown_external_v1');
  const [title, setTitle] = useState('Expert AI Services knowledge document');
  const [filename, setFilename] = useState('expert-ai-services-knowledge.md');
  const [vectorStoreId, setVectorStoreId] = useState('vs_dev');
  const [knowledgeBaseId, setKnowledgeBaseId] = useState('kb_dev');
  const [content, setContent] = useState('# Expert AI Services\n\n<!-- page: 1 -->\nThis is an exai_vector_store production-candidate document for retrieval.');
  const [query, setQuery] = useState('What does the Expert AI Services document say?');
  const [result, setResult] = useState<ApiResult | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => { api('/api/v1/vectorization/modes').then(r => { setModes(r.modes || {}); }).catch(err => setResult({error: String(err)})); }, []);

  async function createVectorStore() {
    setBusy(true);
    try {
      const res = await api('/v1/vector_stores', {method: 'POST', body: JSON.stringify({name: 'Expert AI Services Vector Store', knowledge_base_id: knowledgeBaseId, attributes: {owner: 'mfrieson@expertaiservices.com', project: 'exai_vector_store'}})});
      setVectorStoreId(res.id);
      setResult(res);
    } catch (e) { setResult({error: String(e)}); } finally { setBusy(false); }
  }


  async function previewPlan() {
    setBusy(true);
    try {
      const res = await api('/api/v1/ingestion/preview', {method: 'POST', body: JSON.stringify({vector_store_id: vectorStoreId, knowledge_base_id: knowledgeBaseId, title, filename, mime_type: 'text/markdown', mode, content, security_level: 1, attributes: {source_pdf_id: mode === 'pdf_markdown_external_v1' ? 'external_pdf_markdown_bundle' : undefined}, persist: true})});
      setResult(res);
    } catch (e) { setResult({error: String(e)}); } finally { setBusy(false); }
  }

  async function ingest() {
    setBusy(true);
    try {
      const res = await api('/api/v1/documents/ingest', {method: 'POST', body: JSON.stringify({vector_store_id: vectorStoreId, knowledge_base_id: knowledgeBaseId, title, filename, mime_type: 'text/markdown', mode, content, security_level: 1, attributes: {source_pdf_id: mode === 'pdf_markdown_external_v1' ? 'external_pdf_markdown_bundle' : undefined}})});
      setResult(res);
    } catch (e) { setResult({error: String(e)}); } finally { setBusy(false); }
  }

  async function search() {
    setBusy(true);
    try {
      const res = await api('/api/v1/retrieval/search', {method: 'POST', body: JSON.stringify({query, vector_store_id: vectorStoreId, mode, top_k: 5})});
      setResult(res);
    } catch (e) { setResult({error: String(e)}); } finally { setBusy(false); }
  }

  return <main>
    <header>
      <h1>exai_vector_store</h1>
      <p>Expert AI Services vector retrieval platform for expertaiservices.com.</p>
    </header>

    <section className="grid">
      <div className="card">
        <h2>Instance context</h2>
        <label>Tenant <input defaultValue={localStorage.getItem('svs_tenant') || 'ten_dev'} onBlur={e => localStorage.setItem('svs_tenant', e.currentTarget.value)} /></label>
        <label>Business instance <input defaultValue={localStorage.getItem('svs_biz') || 'biz_dev'} onBlur={e => localStorage.setItem('svs_biz', e.currentTarget.value)} /></label>
        <label>User <input defaultValue={localStorage.getItem('svs_user') || 'usr_dev'} onBlur={e => localStorage.setItem('svs_user', e.currentTarget.value)} /></label>
        <label>Security level <input defaultValue={localStorage.getItem('svs_level') || '5'} onBlur={e => localStorage.setItem('svs_level', e.currentTarget.value)} /></label>
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

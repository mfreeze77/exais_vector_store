import React, {useEffect, useMemo, useState} from 'react';
import {createRoot} from 'react-dom/client';
import {
  MissingAdminCredentialError,
  adminDevHeadersEnabled,
  decorateAdminRequest,
  getStoredAdminApiKey,
  storeAdminApiKey,
} from './auth';
import type {FleetBusinessInstance, FleetComponentVersion, FleetVersionReport} from './fleet';
import {displayValue, fleetIssueCount, selectedFleetInstance} from './fleet';
import './styles.css';

type ApiPayload = Record<string, any>;
type Modes = Record<string, ApiPayload>;
type TabId = 'overview' | 'onboarding' | 'stores' | 'ingest' | 'keys' | 'retrieve' | 'fleet' | 'backups';
type ListResponse<T> = {object?: string; data: T[]; has_more?: boolean; first_id?: string | null; last_id?: string | null};

type AdminSession = {
  object: 'admin.session';
  authenticated: boolean;
  tenant_id: string;
  business_instance_id: string;
  user_id?: string | null;
  api_key_id?: string | null;
  scopes: string[];
  roles: string[];
  groups: string[];
  max_security_level: number;
};

type VectorStore = {
  id: string;
  name?: string | null;
  description?: string | null;
  status: string;
  bytes: number;
  usage_bytes: number;
  file_counts: Record<string, number>;
  metadata?: Record<string, unknown>;
  attributes?: Record<string, unknown>;
  created_at?: number | null;
  expires_at?: number | null;
  last_active_at?: number | null;
};

type VectorStoreFile = {
  id: string;
  vector_store_id: string;
  status?: string | null;
  usage_bytes?: number;
  created_at?: number | null;
  last_error?: {code?: string | null; message?: string | null} | null;
  attributes?: Record<string, unknown>;
};

type ApiKeyRecord = {
  id: string;
  label: string;
  scopes: string[];
  max_security_level: number;
  api_key?: string | null;
  status?: string | null;
  created_at?: number | null;
  last_used_at?: number | null;
  expires_at?: number | null;
};

type IngestionJob = {
  id: string;
  job_type?: string | null;
  status: string;
  attempts?: number;
  max_attempts?: number;
  last_error?: string | null;
  created_at?: number | null;
  updated_at?: number | null;
  completed_at?: number | null;
  payload?: ApiPayload;
};

type SearchResult = {
  file_id?: string | null;
  filename?: string | null;
  score?: number | null;
  content?: Array<{type?: string; text?: string; annotations?: ApiPayload[]}>;
  annotations?: ApiPayload[];
  citation?: ApiPayload | null;
  citations?: ApiPayload[];
  attributes?: Record<string, unknown>;
};

type SearchResultsPage = {
  object?: string;
  search_query?: string | string[] | null;
  data?: SearchResult[];
  citations?: ApiPayload[];
  has_more?: boolean;
  next_page?: string | null;
};

type BackupMetrics = {
  successTotal: number;
  failedTotal: number;
  lastSuccessTimestamp: number;
  freshnessAgeSeconds: number;
  manifestAvailableTotal: number;
  manifestArtifactsTotal: number;
  buildVersion?: string;
};

type CustomerDraft = {
  customerName: string;
  customerSlug: string;
  apiHostname: string;
  adminHostname: string;
  initialStoreName: string;
  ingestionMode: string;
  deploymentNotes: string;
  adminKeyHandedOff: boolean;
};

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8080';
const tabs: Array<{id: TabId; label: string; hint: string}> = [
  {id: 'overview', label: 'Instance', hint: 'Customer cell status'},
  {id: 'onboarding', label: 'Onboarding', hint: 'Private VPS workflow'},
  {id: 'stores', label: 'Vector Stores', hint: 'Stores and files'},
  {id: 'ingest', label: 'Ingestion', hint: 'Upload and paste'},
  {id: 'keys', label: 'Agent Keys', hint: 'Scoped handoff'},
  {id: 'retrieve', label: 'Test Bench', hint: 'Cited evidence'},
  {id: 'fleet', label: 'Fleet', hint: 'Release drift'},
  {id: 'backups', label: 'Backups', hint: 'Restore proof'},
];

function apiError(error: unknown): ApiPayload {
  if (error instanceof MissingAdminCredentialError) {
    return {error: error.message, status: 'missing_credential'};
  }
  return {error: error instanceof Error ? error.message : String(error)};
}

async function apiJson<T>(path: string, init?: RequestInit, apiKey?: string | null): Promise<T> {
  const request = decorateAdminRequest(init, {apiKey});
  const requestHeaders = new Headers(request.headers);
  if (!requestHeaders.has('Content-Type')) requestHeaders.set('Content-Type', 'application/json');
  const res = await fetch(`${API_BASE}${path}`, {...request, headers: requestHeaders});
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json();
}

async function apiForm<T>(path: string, form: FormData, apiKey?: string | null): Promise<T> {
  const request = decorateAdminRequest({method: 'POST', body: form}, {apiKey});
  const res = await fetch(`${API_BASE}${path}`, request);
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json();
}

async function fetchMetrics(): Promise<BackupMetrics> {
  const res = await fetch(`${API_BASE}/metrics`);
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return parseBackupMetrics(await res.text());
}

function parseBackupMetrics(raw: string): BackupMetrics {
  const metric = (name: string): number => {
    const line = raw.split('\n').find(entry => entry.startsWith(`${name} `) || entry.startsWith(`${name}{`));
    if (!line) return 0;
    const value = Number(line.trim().split(/\s+/).pop());
    return Number.isFinite(value) ? value : 0;
  };
  const buildLine = raw.split('\n').find(entry => entry.startsWith('svs_api_build_info{'));
  const buildVersion = buildLine?.match(/version="([^"]+)"/)?.[1];
  return {
    successTotal: metric('svs_backup_bundle_success_total'),
    failedTotal: metric('svs_backup_bundle_failed_total'),
    lastSuccessTimestamp: metric('svs_backup_bundle_last_success_timestamp_seconds'),
    freshnessAgeSeconds: metric('svs_backup_freshness_age_seconds'),
    manifestAvailableTotal: metric('svs_backup_manifest_available_total'),
    manifestArtifactsTotal: metric('svs_backup_manifest_artifacts_total'),
    buildVersion,
  };
}

function formatBytes(value?: number | null): string {
  const bytes = Number(value || 0);
  if (bytes < 1024) return `${bytes} B`;
  const units = ['KB', 'MB', 'GB', 'TB'];
  let size = bytes / 1024;
  let unit = units[0];
  for (let index = 1; size >= 1024 && index < units.length; index += 1) {
    size /= 1024;
    unit = units[index];
  }
  return `${size.toFixed(size >= 10 ? 1 : 2)} ${unit}`;
}

function formatDate(seconds?: number | null): string {
  if (!seconds) return 'not recorded';
  return new Date(seconds * 1000).toLocaleString();
}

function statusTone(status?: string | null): string {
  const normalized = (status || 'unknown').toLowerCase();
  if (['healthy', 'current', 'completed', 'active', 'ready', 'succeeded', 'success'].includes(normalized)) return 'good';
  if (['in_progress', 'queued', 'pending', 'stale', 'warning'].includes(normalized)) return 'warn';
  if (['failed', 'error', 'revoked', 'cancelled', 'unverifiable', 'missing'].includes(normalized)) return 'bad';
  return 'neutral';
}

function jsonString(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

function redactedKey(value?: string | null): string {
  if (!value) return 'svs_live_...redacted';
  if (value.length <= 18) return 'svs_live_...redacted';
  return `${value.slice(0, 9)}...${value.slice(-6)}`;
}

function selectedStoreFromList(stores: VectorStore[], vectorStoreId: string): VectorStore | null {
  return stores.find(store => store.id === vectorStoreId) || stores[0] || null;
}

function searchResultsFromResponse(response: ApiPayload | null): SearchResult[] {
  if (!response) return [];
  if (Array.isArray(response.data)) return response.data as SearchResult[];
  if (Array.isArray(response.output)) {
    return response.output
      .flatMap((item: ApiPayload) => item?.results || item?.search_results || [])
      .map((item: ApiPayload) => ({
        file_id: item.file_id,
        filename: item.filename,
        score: item.score,
        attributes: item.attributes || {},
        content: item.text ? [{type: 'text', text: item.text, annotations: []}] : [],
        annotations: [],
      }));
  }
  return [];
}

function textFromResult(result: SearchResult): string {
  const first = result.content?.find(item => typeof item.text === 'string');
  return first?.text || '';
}

function copyToClipboard(value: string): void {
  navigator.clipboard?.writeText(value).catch(() => undefined);
}

function JsonInspector({title, value}: {title: string; value: unknown}) {
  return <details className="json-inspector">
    <summary>{title}</summary>
    <pre>{value ? jsonString(value) : 'No payload loaded.'}</pre>
  </details>;
}

function StatusBadge({status}: {status?: string | null}) {
  const value = status || 'unknown';
  return <span className={`status-badge ${statusTone(value)}`}>{value}</span>;
}

function MetricTile({label, value, detail, tone = 'neutral'}: {label: string; value: string; detail?: string; tone?: string}) {
  return <div className={`metric-tile ${tone}`}>
    <span>{label}</span>
    <strong>{value}</strong>
    {detail && <small>{detail}</small>}
  </div>;
}

function AppShell({
  activeTab,
  setActiveTab,
  children,
}: {
  activeTab: TabId;
  setActiveTab: (tab: TabId) => void;
  children: React.ReactNode;
}) {
  return <div className="app-shell">
    <aside className="side-nav">
      <div className="brand-block">
        <strong>ExAIS</strong>
        <span>Private Vector Store Ops</span>
      </div>
      <nav aria-label="Operator console">
        {tabs.map(tab => <button
          key={tab.id}
          className={activeTab === tab.id ? 'nav-item active' : 'nav-item'}
          onClick={() => setActiveTab(tab.id)}
          type="button"
        >
          <span>{tab.label}</span>
          <small>{tab.hint}</small>
        </button>)}
      </nav>
    </aside>
    <main className="workspace">{children}</main>
  </div>;
}

function TopBar({
  session,
  apiKey,
  busy,
  error,
  onApiKeyChange,
  onRefresh,
}: {
  session: AdminSession | null;
  apiKey: string;
  busy: string;
  error: ApiPayload | null;
  onApiKeyChange: (value: string) => void;
  onRefresh: () => void;
}) {
  const devHeaders = adminDevHeadersEnabled();
  return <header className="top-bar">
    <div>
      <h1>Customer Private VPS Operator Console</h1>
      <p>Manage one isolated ExAIS Docker Compose cell and its OpenAI-compatible vector-store endpoints.</p>
    </div>
    <div className="auth-panel">
      <label>
        Operator bearer key
        <input
          type="password"
          value={apiKey}
          onChange={event => onApiKeyChange(event.currentTarget.value)}
          placeholder="svs_live_..."
          autoComplete="off"
        />
      </label>
      <button disabled={Boolean(busy)} onClick={onRefresh} type="button">{busy || 'Refresh cell'}</button>
      <div className="auth-status">
        <StatusBadge status={session?.authenticated ? 'active' : 'missing'} />
        <span>{session ? `business ${session.business_instance_id}` : 'production bearer required'}</span>
      </div>
      {devHeaders && <small className="internal-note">Local Vite dev identity headers are active; production builds require bearer auth.</small>}
      {error && <small className="error-text">{String(error.error || jsonString(error))}</small>}
    </div>
  </header>;
}

function InstanceOverview({
  customer,
  session,
  fleet,
  selectedFleet,
  stores,
  files,
  apiKeys,
  backups,
  apiBase,
}: {
  customer: CustomerDraft;
  session: AdminSession | null;
  fleet: FleetVersionReport | null;
  selectedFleet: FleetBusinessInstance | null;
  stores: VectorStore[];
  files: VectorStoreFile[];
  apiKeys: ApiKeyRecord[];
  backups: BackupMetrics | null;
  apiBase: string;
}) {
  const flagged = fleetIssueCount(selectedFleet);
  const totalFiles = stores.reduce((sum, store) => sum + Number(store.file_counts?.total || 0), 0);
  const backupTone = backups?.lastSuccessTimestamp ? 'good' : 'bad';
  return <section className="panel">
    <div className="section-heading">
      <div>
        <p className="eyebrow">Private customer cell</p>
        <h2>{customer.customerName || selectedFleet?.name || 'Customer instance'}</h2>
        <p>One VPS, one Docker Compose stack, one customer data plane.</p>
      </div>
      <StatusBadge status={selectedFleet?.verification_status || (session ? 'active' : 'missing')} />
    </div>
    <div className="metrics-grid">
      <MetricTile label="API base" value={customer.apiHostname || apiBase} detail="Expose through HTTPS reverse proxy" tone="good" />
      <MetricTile label="Business instance" value={session?.business_instance_id || selectedFleet?.id || 'not connected'} detail={session?.tenant_id ? `tenant ${session.tenant_id}` : 'connect with operator key'} />
      <MetricTile label="Release" value={fleet?.product_version || backups?.buildVersion || 'not recorded'} detail={`${flagged} flagged component${flagged === 1 ? '' : 's'}`} tone={flagged ? 'warn' : 'good'} />
      <MetricTile label="Stores" value={String(stores.length)} detail={`${totalFiles} attached file${totalFiles === 1 ? '' : 's'}`} tone={stores.length ? 'good' : 'warn'} />
      <MetricTile label="Agent keys" value={String(apiKeys.filter(key => key.scopes.includes('retrieval:read')).length)} detail="retrieval:read scoped keys" />
      <MetricTile label="Backup proof" value={backups?.lastSuccessTimestamp ? formatDate(backups.lastSuccessTimestamp) : 'missing'} detail="from /metrics backup counters" tone={backupTone} />
    </div>
    <div className="summary-strip">
      <div><strong>Agent endpoint</strong><span>{customer.apiHostname || apiBase}/v1/responses</span></div>
      <div><strong>Admin surface</strong><span>{customer.adminHostname || 'private admin hostname not set'}</span></div>
      <div><strong>Isolation boundary</strong><span>separate VPS, compose project, volumes, secrets, keys, backups</span></div>
    </div>
    <JsonInspector title="Raw admin session" value={session} />
  </section>;
}

function OnboardingWorkflow({
  customer,
  modes,
  onCustomerChange,
  onCreateStore,
  onCreateAgentKey,
}: {
  customer: CustomerDraft;
  modes: Modes;
  onCustomerChange: (patch: Partial<CustomerDraft>) => void;
  onCreateStore: () => void;
  onCreateAgentKey: () => void;
}) {
  const steps = [
    {label: 'Customer profile', done: Boolean(customer.customerName && customer.customerSlug)},
    {label: 'HTTPS endpoints', done: Boolean(customer.apiHostname && customer.adminHostname)},
    {label: 'Initial vector store', done: Boolean(customer.initialStoreName)},
    {label: 'Agent retrieval key', done: customer.adminKeyHandedOff},
    {label: 'Deployment notes', done: Boolean(customer.deploymentNotes.trim())},
  ];
  return <section className="panel">
    <div className="section-heading">
      <div>
        <p className="eyebrow">Onboarding runbook</p>
        <h2>Private VPS cell setup</h2>
        <p>Capture the handoff state before the customer's agent starts using the endpoint.</p>
      </div>
      <StatusBadge status={steps.every(step => step.done) ? 'ready' : 'pending'} />
    </div>
    <div className="split-layout">
      <form className="form-grid" onSubmit={event => event.preventDefault()}>
        <label>Customer name<input value={customer.customerName} onChange={event => onCustomerChange({customerName: event.currentTarget.value})} /></label>
        <label>Customer slug<input value={customer.customerSlug} onChange={event => onCustomerChange({customerSlug: event.currentTarget.value})} /></label>
        <label>API hostname<input value={customer.apiHostname} onChange={event => onCustomerChange({apiHostname: event.currentTarget.value})} /></label>
        <label>Admin hostname<input value={customer.adminHostname} onChange={event => onCustomerChange({adminHostname: event.currentTarget.value})} /></label>
        <label>Initial vector store<input value={customer.initialStoreName} onChange={event => onCustomerChange({initialStoreName: event.currentTarget.value})} /></label>
        <label>Ingestion mode
          <select value={customer.ingestionMode} onChange={event => onCustomerChange({ingestionMode: event.currentTarget.value})}>
            {Object.keys(modes).map(mode => <option key={mode} value={mode}>{mode}</option>)}
            {!Object.keys(modes).length && <option value={customer.ingestionMode}>{customer.ingestionMode}</option>}
          </select>
        </label>
        <label className="wide">Deployment notes<textarea rows={5} value={customer.deploymentNotes} onChange={event => onCustomerChange({deploymentNotes: event.currentTarget.value})} /></label>
        <label className="check-row wide">
          <input type="checkbox" checked={customer.adminKeyHandedOff} onChange={event => onCustomerChange({adminKeyHandedOff: event.currentTarget.checked})} />
          Admin key handoff is recorded outside the UI
        </label>
        <div className="button-row wide">
          <button type="button" onClick={onCreateStore}>Create initial store</button>
          <button type="button" className="secondary" onClick={onCreateAgentKey}>Create retrieval key</button>
        </div>
      </form>
      <div className="checklist">
        {steps.map(step => <div key={step.label} className={step.done ? 'check-item done' : 'check-item'}>
          <span>{step.done ? 'done' : 'open'}</span>
          <strong>{step.label}</strong>
        </div>)}
      </div>
    </div>
  </section>;
}

function VectorStoreManagement({
  stores,
  selectedStore,
  selectedVectorStoreId,
  files,
  storeName,
  storeDescription,
  busy,
  onSelectStore,
  onStoreNameChange,
  onStoreDescriptionChange,
  onCreateStore,
  onDeleteStore,
  onRefreshStores,
  onRefreshFiles,
}: {
  stores: VectorStore[];
  selectedStore: VectorStore | null;
  selectedVectorStoreId: string;
  files: VectorStoreFile[];
  storeName: string;
  storeDescription: string;
  busy: string;
  onSelectStore: (id: string) => void;
  onStoreNameChange: (value: string) => void;
  onStoreDescriptionChange: (value: string) => void;
  onCreateStore: () => void;
  onDeleteStore: (id: string) => void;
  onRefreshStores: () => void;
  onRefreshFiles: () => void;
}) {
  return <section className="panel">
    <div className="section-heading">
      <div>
        <p className="eyebrow">OpenAI-compatible stores</p>
        <h2>Vector-store management</h2>
        <p>Create, select, inspect file counts, and review attached-file status.</p>
      </div>
      <button className="secondary" type="button" onClick={onRefreshStores} disabled={Boolean(busy)}>Refresh stores</button>
    </div>
    <div className="toolbar">
      <label>New store name<input value={storeName} onChange={event => onStoreNameChange(event.currentTarget.value)} /></label>
      <label>Description<input value={storeDescription} onChange={event => onStoreDescriptionChange(event.currentTarget.value)} /></label>
      <button type="button" onClick={onCreateStore} disabled={Boolean(busy)}>Create store</button>
    </div>
    <div className="table-shell">
      <table>
        <thead><tr><th>Name</th><th>Status</th><th>Files</th><th>Bytes</th><th>Last active</th><th>Action</th></tr></thead>
        <tbody>
          {stores.map(store => <tr key={store.id} className={store.id === selectedVectorStoreId ? 'selected-row' : ''}>
            <td><strong>{store.name || store.id}</strong><span className="mono-block">{store.id}</span></td>
            <td><StatusBadge status={store.status} /></td>
            <td>{store.file_counts?.total || 0} total / {store.file_counts?.completed || 0} complete</td>
            <td>{formatBytes(store.bytes || store.usage_bytes)}</td>
            <td>{formatDate(store.last_active_at || store.created_at)}</td>
            <td>
              <div className="row-actions">
                <button className="secondary small" type="button" onClick={() => onSelectStore(store.id)}>Select</button>
                <button className="danger small" type="button" onClick={() => onDeleteStore(store.id)}>Retire</button>
              </div>
            </td>
          </tr>)}
          {!stores.length && <tr><td colSpan={6} className="empty-cell">No vector stores visible for this operator key.</td></tr>}
        </tbody>
      </table>
    </div>
    <div className="section-heading compact">
      <div>
        <h3>Attached files</h3>
        <p>{selectedStore ? selectedStore.id : 'Select a vector store to load files.'}</p>
      </div>
      <button className="secondary" type="button" onClick={onRefreshFiles} disabled={Boolean(busy || !selectedStore)}>Refresh files</button>
    </div>
    <div className="table-shell">
      <table>
        <thead><tr><th>File</th><th>Status</th><th>Usage</th><th>Created</th><th>Error</th></tr></thead>
        <tbody>
          {files.map(file => <tr key={file.id}>
            <td className="mono">{file.id}</td>
            <td><StatusBadge status={file.status || 'unknown'} /></td>
            <td>{formatBytes(file.usage_bytes)}</td>
            <td>{formatDate(file.created_at)}</td>
            <td>{file.last_error?.message || 'none'}</td>
          </tr>)}
          {!files.length && <tr><td colSpan={5} className="empty-cell">No attached files loaded for the selected store.</td></tr>}
        </tbody>
      </table>
    </div>
    <JsonInspector title="Selected store JSON" value={selectedStore} />
  </section>;
}

function IngestionWorkspace({
  modes,
  selectedStore,
  mode,
  title,
  filename,
  content,
  selectedFile,
  busy,
  onModeChange,
  onTitleChange,
  onFilenameChange,
  onContentChange,
  onFileChange,
  onPreview,
  onPasteIngest,
  onUploadAndAttach,
  jobs,
  onRefreshJobs,
  onRetryJob,
  lastIngestPayload,
}: {
  modes: Modes;
  selectedStore: VectorStore | null;
  mode: string;
  title: string;
  filename: string;
  content: string;
  selectedFile: File | null;
  busy: string;
  onModeChange: (value: string) => void;
  onTitleChange: (value: string) => void;
  onFilenameChange: (value: string) => void;
  onContentChange: (value: string) => void;
  onFileChange: (file: File | null) => void;
  onPreview: () => void;
  onPasteIngest: () => void;
  onUploadAndAttach: () => void;
  jobs: IngestionJob[];
  onRefreshJobs: () => void;
  onRetryJob: (id: string) => void;
  lastIngestPayload: ApiPayload | null;
}) {
  return <section className="panel">
    <div className="section-heading">
      <div>
        <p className="eyebrow">Document workspace</p>
        <h2>Ingest customer source material</h2>
        <p>Preview the mode plan, ingest pasted Markdown/text, or upload an OpenAI-compatible file and attach it to the selected store.</p>
      </div>
      <StatusBadge status={selectedStore ? 'ready' : 'missing'} />
    </div>
    <div className="summary-strip">
      <div><strong>Selected store</strong><span>{selectedStore?.id || 'none'}</span></div>
      <div><strong>Mode</strong><span>{mode}</span></div>
      <div><strong>Selected upload</strong><span>{selectedFile ? `${selectedFile.name} (${formatBytes(selectedFile.size)})` : 'no file selected'}</span></div>
    </div>
    <form className="form-grid" onSubmit={event => event.preventDefault()}>
      <label>Title<input value={title} onChange={event => onTitleChange(event.currentTarget.value)} /></label>
      <label>Filename<input value={filename} onChange={event => onFilenameChange(event.currentTarget.value)} /></label>
      <label>Mode
        <select value={mode} onChange={event => onModeChange(event.currentTarget.value)}>
          {Object.keys(modes).map(candidate => <option key={candidate} value={candidate}>{candidate}</option>)}
          {!Object.keys(modes).length && <option value={mode}>{mode}</option>}
        </select>
      </label>
      <label>Upload file<input type="file" onChange={event => onFileChange(event.currentTarget.files?.[0] || null)} /></label>
      <label className="wide">Paste content<textarea rows={12} value={content} onChange={event => onContentChange(event.currentTarget.value)} /></label>
      <div className="button-row wide">
        <button type="button" onClick={onPreview} disabled={Boolean(busy || !selectedStore)}>Preview mode plan</button>
        <button type="button" onClick={onPasteIngest} disabled={Boolean(busy || !selectedStore)}>Ingest pasted content</button>
        <button type="button" className="secondary" onClick={onUploadAndAttach} disabled={Boolean(busy || !selectedStore || !selectedFile)}>Upload and attach file</button>
      </div>
    </form>
    <div className="section-heading compact">
      <div>
        <h3>Recent ingestion jobs</h3>
        <p>Queued, failed, and completed jobs visible to this operator key.</p>
      </div>
      <button className="secondary" type="button" onClick={onRefreshJobs} disabled={Boolean(busy)}>Refresh jobs</button>
    </div>
    <div className="table-shell">
      <table>
        <thead><tr><th>Job</th><th>Status</th><th>Type</th><th>Attempts</th><th>Updated</th><th>Error / Action</th></tr></thead>
        <tbody>
          {jobs.map(job => <tr key={job.id}>
            <td className="mono">{job.id}</td>
            <td><StatusBadge status={job.status} /></td>
            <td>{job.job_type || 'not recorded'}</td>
            <td>{job.attempts ?? 0} / {job.max_attempts ?? 'n/a'}</td>
            <td>{formatDate(job.completed_at || job.updated_at || job.created_at)}</td>
            <td>
              <span>{job.last_error || 'none'}</span>
              {['failed', 'cancelled'].includes(job.status) && <button className="secondary small" type="button" onClick={() => onRetryJob(job.id)}>Retry</button>}
            </td>
          </tr>)}
          {!jobs.length && <tr><td colSpan={6} className="empty-cell">No recent ingestion jobs visible.</td></tr>}
        </tbody>
      </table>
    </div>
    <JsonInspector title="Mode configuration" value={modes[mode]} />
    <JsonInspector title="Last ingestion payload" value={lastIngestPayload} />
  </section>;
}

function AgentKeyHandoff({
  customer,
  selectedStore,
  apiKeys,
  keyLabel,
  createdKey,
  busy,
  onKeyLabelChange,
  onCreateAgentKey,
  onRefreshKeys,
  onRevokeKey,
}: {
  customer: CustomerDraft;
  selectedStore: VectorStore | null;
  apiKeys: ApiKeyRecord[];
  keyLabel: string;
  createdKey: ApiKeyRecord | null;
  busy: string;
  onKeyLabelChange: (value: string) => void;
  onCreateAgentKey: () => void;
  onRefreshKeys: () => void;
  onRevokeKey: (id: string) => void;
}) {
  const endpointBase = customer.apiHostname || API_BASE;
  const responseExample = jsonString({
    model: 'gpt-5.4-mini',
    input: [{role: 'user', content: [{type: 'input_text', text: 'What does the source say?'}]}],
    tools: [{type: 'file_search', vector_store_ids: [selectedStore?.id || 'vs_...']}],
  });
  const searchExample = jsonString({query: 'What does the source say?', max_num_results: 5, include_content: true, include_metadata: true});
  return <section className="panel">
    <div className="section-heading">
      <div>
        <p className="eyebrow">Agent handoff</p>
        <h2>Scoped retrieval keys and endpoint examples</h2>
        <p>Create read-only keys for customer agents. Raw values are shown only on the create response.</p>
      </div>
      <button className="secondary" type="button" onClick={onRefreshKeys} disabled={Boolean(busy)}>Refresh keys</button>
    </div>
    <div className="toolbar">
      <label>Agent key label<input value={keyLabel} onChange={event => onKeyLabelChange(event.currentTarget.value)} /></label>
      <button type="button" onClick={onCreateAgentKey} disabled={Boolean(busy)}>Create retrieval:read key</button>
    </div>
    {createdKey?.api_key && <div className="secret-once">
      <div>
        <strong>Raw key returned once</strong>
        <span>{createdKey.label} / {createdKey.scopes.join(', ')}</span>
      </div>
      <code>{createdKey.api_key}</code>
      <button className="secondary" type="button" onClick={() => copyToClipboard(createdKey.api_key || '')}>Copy once</button>
    </div>}
    <div className="code-grid">
      <div className="code-panel">
        <div className="code-heading"><strong>Responses file_search</strong><button className="secondary small" type="button" onClick={() => copyToClipboard(responseExample)}>Copy body</button></div>
        <p className="mono">POST {endpointBase}/v1/responses</p>
        <p className="mono">Authorization: Bearer {createdKey?.api_key ? redactedKey(createdKey.api_key) : 'svs_live_...redacted'}</p>
        <pre>{responseExample}</pre>
      </div>
      <div className="code-panel">
        <div className="code-heading"><strong>Direct vector-store search</strong><button className="secondary small" type="button" onClick={() => copyToClipboard(searchExample)}>Copy body</button></div>
        <p className="mono">POST {endpointBase}/v1/vector_stores/{selectedStore?.id || 'vs_...'}/search</p>
        <p className="mono">Authorization: Bearer svs_live_...redacted</p>
        <pre>{searchExample}</pre>
      </div>
    </div>
    <div className="table-shell">
      <table>
        <thead><tr><th>Label</th><th>Status</th><th>Scopes</th><th>Max level</th><th>Last used</th><th>Action</th></tr></thead>
        <tbody>
          {apiKeys.map(key => <tr key={key.id}>
            <td><strong>{key.label}</strong><span className="mono-block">{key.id}</span></td>
            <td><StatusBadge status={key.status || 'active'} /></td>
            <td>{key.scopes.join(', ')}</td>
            <td>{key.max_security_level}</td>
            <td>{formatDate(key.last_used_at)}</td>
            <td><button className="danger small" type="button" onClick={() => onRevokeKey(key.id)}>Revoke</button></td>
          </tr>)}
          {!apiKeys.length && <tr><td colSpan={6} className="empty-cell">No API keys visible for this business instance.</td></tr>}
        </tbody>
      </table>
    </div>
  </section>;
}

function RetrievalBench({
  selectedStore,
  query,
  busy,
  result,
  onQueryChange,
  onDirectSearch,
  onResponsesSearch,
}: {
  selectedStore: VectorStore | null;
  query: string;
  busy: string;
  result: ApiPayload | null;
  onQueryChange: (value: string) => void;
  onDirectSearch: () => void;
  onResponsesSearch: () => void;
}) {
  const results = searchResultsFromResponse(result);
  return <section className="panel">
    <div className="section-heading">
      <div>
        <p className="eyebrow">Retrieval proof</p>
        <h2>Test bench with evidence cards</h2>
        <p>Run direct OpenAI-compatible search or Responses file_search against the selected customer store.</p>
      </div>
      <StatusBadge status={selectedStore ? 'ready' : 'missing'} />
    </div>
    <div className="toolbar">
      <label>Query<input value={query} onChange={event => onQueryChange(event.currentTarget.value)} /></label>
      <button type="button" onClick={onDirectSearch} disabled={Boolean(busy || !selectedStore)}>Direct search</button>
      <button type="button" className="secondary" onClick={onResponsesSearch} disabled={Boolean(busy || !selectedStore)}>Responses file_search</button>
    </div>
    <div className="evidence-grid">
      {results.map((item, index) => {
        const citation = item.citation || item.citations?.[0] || item.annotations?.[0] || {};
        return <article className="evidence-card" key={`${item.file_id || index}-${index}`}>
          <div className="evidence-top">
            <strong>{item.filename || citation.filename || 'source file'}</strong>
            <span>{typeof item.score === 'number' ? item.score.toFixed(3) : 'score n/a'}</span>
          </div>
          <p>{textFromResult(item) || 'Content was not included in this response.'}</p>
          <dl>
            <div><dt>Rank</dt><dd>{index + 1}</dd></div>
            <div><dt>File ID</dt><dd>{item.file_id || citation.file_id || 'not recorded'}</dd></div>
            <div><dt>Citation</dt><dd>{citation.marker || citation.model_marker || citation.type || 'not recorded'}</dd></div>
          </dl>
        </article>;
      })}
      {!results.length && <div className="empty-state">Run a search to render cited evidence cards before inspecting raw JSON.</div>}
    </div>
    <JsonInspector title="Raw retrieval response" value={result} />
  </section>;
}

function FleetStatus({
  fleet,
  selectedFleet,
  selectedBusinessInstanceId,
  busy,
  onSelectBusiness,
  onRefreshFleet,
}: {
  fleet: FleetVersionReport | null;
  selectedFleet: FleetBusinessInstance | null;
  selectedBusinessInstanceId: string;
  busy: string;
  onSelectBusiness: (id: string) => void;
  onRefreshFleet: () => void;
}) {
  return <section className="panel">
    <div className="section-heading">
      <div>
        <p className="eyebrow">Release and fleet evidence</p>
        <h2>Compose service health and version drift</h2>
        <p>{fleet?.evidence_note || 'Recorded control-plane state only; live agent polling is not available in this UI.'}</p>
      </div>
      <button className="secondary" type="button" onClick={onRefreshFleet} disabled={Boolean(busy)}>Refresh fleet</button>
    </div>
    <div className="toolbar">
      <label>Business instance
        <select value={selectedBusinessInstanceId} onChange={event => onSelectBusiness(event.currentTarget.value)}>
          {(fleet?.business_instances || []).map(instance => <option key={instance.id} value={instance.id}>{instance.name} ({instance.slug})</option>)}
          {!fleet?.business_instances.length && <option value="">No instances loaded</option>}
        </select>
      </label>
      <MetricTile label="Product version" value={fleet?.product_version || 'not recorded'} detail="from /api/v1/admin/fleet/versions" />
      <MetricTile label="Flagged components" value={String(fleetIssueCount(selectedFleet))} detail="current vs declared evidence" tone={fleetIssueCount(selectedFleet) ? 'warn' : 'good'} />
    </div>
    <ComponentRows components={selectedFleet?.components || []} />
    <DeploymentRows deployments={fleet?.deployments || []} />
    <JsonInspector title="Raw fleet report" value={fleet} />
  </section>;
}

function ComponentRows({components}: {components: FleetComponentVersion[]}) {
  return <div className="table-shell">
    <table>
      <thead><tr><th>Service</th><th>Status</th><th>Declared</th><th>Running</th><th>Image</th><th>Digest</th></tr></thead>
      <tbody>
        {components.map(component => <tr key={component.service}>
          <td><strong>{component.service}</strong><span>{component.reasons?.[0] || component.source}</span></td>
          <td><StatusBadge status={component.status} /></td>
          <td>{displayValue(component.declared_version)}</td>
          <td>{displayValue(component.running_version)}</td>
          <td className="mono">{displayValue(component.image || component.expected_image)}</td>
          <td className="mono">{displayValue(component.digest)}</td>
        </tr>)}
        {!components.length && <tr><td colSpan={6} className="empty-cell">No component version evidence loaded.</td></tr>}
      </tbody>
    </table>
  </div>;
}

function DeploymentRows({deployments}: {deployments: FleetVersionReport['deployments']}) {
  return <div className="table-shell">
    <table>
      <thead><tr><th>Deployment</th><th>Business</th><th>Status</th><th>From</th><th>To</th><th>Completed</th></tr></thead>
      <tbody>
        {deployments.map(deployment => <tr key={deployment.id}>
          <td className="mono">{deployment.id}</td>
          <td className="mono">{displayValue(deployment.business_instance_id)}</td>
          <td><StatusBadge status={deployment.status} /></td>
          <td>{displayValue(deployment.from_version)}</td>
          <td>{displayValue(deployment.to_version)}</td>
          <td>{formatDate(deployment.completed_at || deployment.started_at || deployment.created_at)}</td>
        </tr>)}
        {!deployments.length && <tr><td colSpan={6} className="empty-cell">No deployment records visible under this operator key.</td></tr>}
      </tbody>
    </table>
  </div>;
}

function BackupReadiness({backups, onRefresh}: {backups: BackupMetrics | null; onRefresh: () => void}) {
  const hasBackup = Boolean(backups?.lastSuccessTimestamp);
  const hasManifest = Number(backups?.manifestAvailableTotal || 0) > 0;
  const hasArtifacts = Number(backups?.manifestArtifactsTotal || 0) > 0;
  return <section className="panel">
    <div className="section-heading">
      <div>
        <p className="eyebrow">Backup boundary</p>
        <h2>Restore readiness</h2>
        <p>Shows current API metrics only. External offsite restore drills still need operator proof.</p>
      </div>
      <button className="secondary" type="button" onClick={onRefresh}>Refresh metrics</button>
    </div>
    <div className="metrics-grid">
      <MetricTile label="Last successful backup" value={hasBackup ? formatDate(backups?.lastSuccessTimestamp) : 'missing'} detail="svs_backup_bundle_last_success_timestamp_seconds" tone={hasBackup ? 'good' : 'bad'} />
      <MetricTile label="Successful bundles" value={String(backups?.successTotal || 0)} detail={`${backups?.failedTotal || 0} failed`} tone={(backups?.failedTotal || 0) ? 'warn' : 'neutral'} />
      <MetricTile label="Manifests" value={String(backups?.manifestAvailableTotal || 0)} detail={`${backups?.manifestArtifactsTotal || 0} artifacts recorded`} tone={hasManifest && hasArtifacts ? 'good' : 'bad'} />
      <MetricTile label="Restore preflight" value="not API-backed" detail="use scripts/restore-instance.sh --preflight-only" tone="warn" />
    </div>
    <div className="warning-list">
      <div className={hasBackup ? 'check-item done' : 'check-item'}><span>{hasBackup ? 'done' : 'open'}</span><strong>Database/object/vector backup record exists</strong></div>
      <div className={hasManifest ? 'check-item done' : 'check-item'}><span>{hasManifest ? 'done' : 'open'}</span><strong>Artifact manifest present</strong></div>
      <div className="check-item"><span>open</span><strong>Offsite restore drill proof is not exposed by a backend endpoint yet</strong></div>
      <div className="check-item"><span>open</span><strong>Target VPS restore preflight must be run by operator script</strong></div>
    </div>
    <JsonInspector title="Backup metrics" value={backups} />
  </section>;
}

function App() {
  const [activeTab, setActiveTab] = useState<TabId>('overview');
  const [apiKey, setApiKey] = useState(getStoredAdminApiKey());
  const [session, setSession] = useState<AdminSession | null>(null);
  const [modes, setModes] = useState<Modes>({});
  const [fleet, setFleet] = useState<FleetVersionReport | null>(null);
  const [metrics, setMetrics] = useState<BackupMetrics | null>(null);
  const [stores, setStores] = useState<VectorStore[]>([]);
  const [storeFiles, setStoreFiles] = useState<VectorStoreFile[]>([]);
  const [apiKeys, setApiKeys] = useState<ApiKeyRecord[]>([]);
  const [jobs, setJobs] = useState<IngestionJob[]>([]);
  const [selectedBusinessInstanceId, setSelectedBusinessInstanceId] = useState('');
  const [selectedVectorStoreId, setSelectedVectorStoreId] = useState('');
  const [busy, setBusy] = useState('');
  const [lastError, setLastError] = useState<ApiPayload | null>(null);
  const [lastPayload, setLastPayload] = useState<ApiPayload | null>(null);
  const [lastIngestPayload, setLastIngestPayload] = useState<ApiPayload | null>(null);
  const [createdKey, setCreatedKey] = useState<ApiKeyRecord | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [customer, setCustomer] = useState<CustomerDraft>({
    customerName: 'Expert AI Services customer',
    customerSlug: 'customer-private-cell',
    apiHostname: API_BASE,
    adminHostname: 'https://admin.customer.example.com',
    initialStoreName: 'Customer Knowledge Base',
    ingestionMode: 'pdf_markdown_external_v1',
    deploymentNotes: 'Hetzner VPS, Docker Compose, HTTPS reverse proxy, private volumes, offsite backups pending proof.',
    adminKeyHandedOff: false,
  });
  const [storeName, setStoreName] = useState('Customer Knowledge Base');
  const [storeDescription, setStoreDescription] = useState('Private customer vector store for agent retrieval.');
  const [documentTitle, setDocumentTitle] = useState('Customer knowledge document');
  const [filename, setFilename] = useState('customer-knowledge.md');
  const [content, setContent] = useState('# Customer Knowledge\n\nPaste customer-approved source content here before ingestion.');
  const [query, setQuery] = useState('What does the customer knowledge base say?');
  const [agentKeyLabel, setAgentKeyLabel] = useState('customer-agent-retrieval-read');

  const selectedFleet = selectedFleetInstance(fleet);
  const selectedStore = useMemo(() => selectedStoreFromList(stores, selectedVectorStoreId), [stores, selectedVectorStoreId]);
  const activeMode = customer.ingestionMode || Object.keys(modes)[0] || 'pdf_markdown_external_v1';

  useEffect(() => {
    refreshAll();
  }, []);

  useEffect(() => {
    if (selectedStore && selectedStore.id !== selectedVectorStoreId) {
      setSelectedVectorStoreId(selectedStore.id);
    }
  }, [selectedStore, selectedVectorStoreId]);

  function setError(error: unknown) {
    const payload = apiError(error);
    setLastError(payload);
    setLastPayload(payload);
  }

  function updateApiKey(value: string) {
    setApiKey(value);
    storeAdminApiKey(value);
  }

  function updateCustomer(patch: Partial<CustomerDraft>) {
    setCustomer(current => ({...current, ...patch}));
  }

  async function withBusy(label: string, work: () => Promise<void>) {
    setBusy(label);
    setLastError(null);
    try {
      await work();
    } catch (error) {
      setError(error);
    } finally {
      setBusy('');
    }
  }

  async function refreshAll() {
    await withBusy('Refreshing', async () => {
      const results = await Promise.allSettled([refreshSessionOnly(), refreshModesOnly(), refreshFleetOnly(), refreshMetricsOnly(), refreshStoresOnly(), refreshApiKeysOnly(), refreshJobsOnly()]);
      const failures = results.filter(result => result.status === 'rejected') as PromiseRejectedResult[];
      if (failures.length) {
        throw new Error(failures.map(failure => failure.reason instanceof Error ? failure.reason.message : String(failure.reason)).join(' | '));
      }
    });
  }

  async function refreshSessionOnly() {
    const response = await apiJson<AdminSession>('/api/v1/admin/session', undefined, apiKey);
    setSession(response);
    setLastPayload(response);
  }

  async function refreshModesOnly() {
    const response = await apiJson<{modes?: Modes}>('/api/v1/vectorization/modes', undefined, apiKey);
    setModes(response.modes || {});
    if (!customer.ingestionMode && response.modes && Object.keys(response.modes)[0]) {
      updateCustomer({ingestionMode: Object.keys(response.modes)[0]});
    }
  }

  async function refreshFleetOnly(selection = selectedBusinessInstanceId) {
    const queryString = selection ? `?business_instance_id=${encodeURIComponent(selection)}` : '';
    const response = await apiJson<FleetVersionReport>(`/api/v1/admin/fleet/versions${queryString}`, undefined, apiKey);
    setFleet(response);
    setSelectedBusinessInstanceId(response.selected_business_instance_id || selection || response.business_instances[0]?.id || '');
  }

  async function refreshMetricsOnly() {
    setMetrics(await fetchMetrics());
  }

  async function refreshStoresOnly(preferredStoreId?: string | null) {
    const response = await apiJson<ListResponse<VectorStore>>('/v1/vector_stores?limit=50', undefined, apiKey);
    const nextStores = response.data || [];
    setStores(nextStores);
    const candidate = preferredStoreId === null ? '' : preferredStoreId ?? selectedVectorStoreId;
    const nextSelected = nextStores.find(store => store.id === candidate)?.id || nextStores[0]?.id || '';
    setSelectedVectorStoreId(nextSelected);
    if (nextSelected) await refreshStoreFilesOnly(nextSelected);
    else setStoreFiles([]);
  }

  async function refreshStoreFilesOnly(storeId = selectedVectorStoreId) {
    if (!storeId) {
      setStoreFiles([]);
      return;
    }
    const response = await apiJson<ListResponse<VectorStoreFile>>(`/v1/vector_stores/${encodeURIComponent(storeId)}/files?limit=50`, undefined, apiKey);
    setStoreFiles(response.data || []);
  }

  async function refreshApiKeysOnly() {
    const response = await apiJson<ListResponse<ApiKeyRecord>>('/api/v1/admin/api-keys?limit=50', undefined, apiKey);
    setApiKeys(response.data || []);
  }

  async function refreshJobsOnly() {
    const response = await apiJson<ListResponse<IngestionJob>>('/api/v1/jobs?limit=20', undefined, apiKey);
    setJobs(response.data || []);
  }

  function selectBusinessInstance(id: string) {
    setSelectedBusinessInstanceId(id);
    withBusy('Loading fleet', () => refreshFleetOnly(id));
  }

  function selectVectorStore(id: string) {
    setSelectedVectorStoreId(id);
    withBusy('Loading files', () => refreshStoreFilesOnly(id));
  }

  async function createVectorStore() {
    await withBusy('Creating store', async () => {
      const response = await apiJson<VectorStore>('/v1/vector_stores', {
        method: 'POST',
        body: jsonString({
          name: storeName || customer.initialStoreName,
          description: storeDescription,
          metadata: {customer_slug: customer.customerSlug, deployment_model: 'one_vps_compose_stack_per_customer'},
          attributes: {operator: 'expertaiservices', isolation: 'private_vps_compose_cell'},
        }),
      }, apiKey);
      setSelectedVectorStoreId(response.id);
      setLastPayload(response);
      await refreshStoresOnly(response.id);
    });
  }

  async function deleteVectorStore(id: string) {
    if (!window.confirm(`Retire vector store ${id}? This removes it from normal search and cannot be undone from the UI.`)) return;
    await withBusy('Retiring store', async () => {
      const response = await apiJson<ApiPayload>(`/v1/vector_stores/${encodeURIComponent(id)}`, {method: 'DELETE'}, apiKey);
      setLastPayload(response);
      if (selectedVectorStoreId === id) {
        setSelectedVectorStoreId('');
        setStoreFiles([]);
      }
      await refreshStoresOnly(null);
    });
  }

  async function previewPlan() {
    if (!selectedStore) return;
    await withBusy('Previewing', async () => {
      const response = await apiJson<ApiPayload>('/api/v1/ingestion/preview', {
        method: 'POST',
        body: jsonString({
          vector_store_id: selectedStore.id,
          knowledge_base_id: customer.customerSlug || 'customer_private_cell',
          title: documentTitle,
          filename,
          mime_type: 'text/markdown',
          mode: activeMode,
          content,
          security_level: 1,
          attributes: {customer_slug: customer.customerSlug, source: 'operator_console_paste_preview'},
          persist: true,
        }),
      }, apiKey);
      setLastIngestPayload(response);
      setLastPayload(response);
    });
  }

  async function ingestPastedContent() {
    if (!selectedStore) return;
    await withBusy('Ingesting', async () => {
      const response = await apiJson<ApiPayload>(`/v1/vector_stores/${encodeURIComponent(selectedStore.id)}/files`, {
        method: 'POST',
        body: jsonString({
          title: documentTitle,
          filename,
          mime_type: 'text/markdown',
          mode: activeMode,
          content,
          knowledge_base_id: customer.customerSlug || 'customer_private_cell',
          security_level: 1,
          attributes: {customer_slug: customer.customerSlug, source: 'operator_console_paste'},
        }),
      }, apiKey);
      setLastIngestPayload(response);
      setLastPayload(response);
      await refreshStoresOnly();
      await refreshJobsOnly();
    });
  }

  async function uploadAndAttachFile() {
    if (!selectedStore || !selectedFile) return;
    await withBusy('Uploading', async () => {
      const form = new FormData();
      form.append('purpose', 'assistants');
      form.append('file', selectedFile);
      const uploaded = await apiForm<ApiPayload>('/v1/files', form, apiKey);
      const attached = await apiJson<ApiPayload>(`/v1/vector_stores/${encodeURIComponent(selectedStore.id)}/files`, {
        method: 'POST',
        body: jsonString({file_id: uploaded.id, attributes: {customer_slug: customer.customerSlug, source: 'operator_console_upload'}}),
      }, apiKey);
      const response = {uploaded, attached};
      setLastIngestPayload(response);
      setLastPayload(response);
      await refreshStoresOnly();
      await refreshJobsOnly();
    });
  }

  async function retryJob(id: string) {
    await withBusy('Retrying job', async () => {
      const response = await apiJson<ApiPayload>(`/api/v1/jobs/${encodeURIComponent(id)}/retry`, {method: 'POST'}, apiKey);
      setLastPayload(response);
      await refreshJobsOnly();
    });
  }

  async function createAgentKey() {
    await withBusy('Creating key', async () => {
      const params = new URLSearchParams({
        label: agentKeyLabel || `${customer.customerSlug}-agent-retrieval-read`,
        scopes: 'retrieval:read,vector_stores:read,documents:read',
        max_security_level: '1',
      });
      const response = await apiJson<ApiKeyRecord>(`/api/v1/admin/api-keys?${params.toString()}`, {method: 'POST'}, apiKey);
      setCreatedKey(response);
      setLastPayload({...response, api_key: response.api_key ? redactedKey(response.api_key) : null});
      updateCustomer({adminKeyHandedOff: false});
      await refreshApiKeysOnly();
    });
  }

  async function revokeApiKey(id: string) {
    if (!window.confirm(`Revoke API key ${id}? This is immediate.`)) return;
    await withBusy('Revoking key', async () => {
      const response = await apiJson<ApiPayload>(`/api/v1/admin/api-keys/${encodeURIComponent(id)}`, {method: 'DELETE'}, apiKey);
      setLastPayload(response);
      await refreshApiKeysOnly();
    });
  }

  async function directSearch() {
    if (!selectedStore) return;
    await withBusy('Searching', async () => {
      const response = await apiJson<SearchResultsPage>(`/v1/vector_stores/${encodeURIComponent(selectedStore.id)}/search`, {
        method: 'POST',
        body: jsonString({query, max_num_results: 5, include_content: true, include_metadata: true, rewrite_query: true}),
      }, apiKey);
      setLastPayload(response as ApiPayload);
    });
  }

  async function responsesFileSearch() {
    if (!selectedStore) return;
    await withBusy('Searching', async () => {
      const response = await apiJson<ApiPayload>('/v1/responses', {
        method: 'POST',
        body: jsonString({
          model: 'gpt-5.4-mini',
          input: [{role: 'user', content: [{type: 'input_text', text: query}]}],
          tools: [{type: 'file_search', vector_store_ids: [selectedStore.id], max_num_results: 5}],
          include: ['file_search_call.results'],
        }),
      }, apiKey);
      setLastPayload(response);
    });
  }

  function renderActiveTab() {
    if (activeTab === 'overview') {
      return <InstanceOverview customer={customer} session={session} fleet={fleet} selectedFleet={selectedFleet} stores={stores} files={storeFiles} apiKeys={apiKeys} backups={metrics} apiBase={API_BASE} />;
    }
    if (activeTab === 'onboarding') {
      return <OnboardingWorkflow customer={customer} modes={modes} onCustomerChange={updateCustomer} onCreateStore={createVectorStore} onCreateAgentKey={createAgentKey} />;
    }
    if (activeTab === 'stores') {
      return <VectorStoreManagement
        stores={stores}
        selectedStore={selectedStore}
        selectedVectorStoreId={selectedVectorStoreId}
        files={storeFiles}
        storeName={storeName}
        storeDescription={storeDescription}
        busy={busy}
        onSelectStore={selectVectorStore}
        onStoreNameChange={setStoreName}
        onStoreDescriptionChange={setStoreDescription}
        onCreateStore={createVectorStore}
        onDeleteStore={deleteVectorStore}
        onRefreshStores={() => withBusy('Refreshing stores', refreshStoresOnly)}
        onRefreshFiles={() => withBusy('Refreshing files', () => refreshStoreFilesOnly())}
      />;
    }
    if (activeTab === 'ingest') {
      return <IngestionWorkspace
        modes={modes}
        selectedStore={selectedStore}
        mode={activeMode}
        title={documentTitle}
        filename={filename}
        content={content}
        selectedFile={selectedFile}
        busy={busy}
        onModeChange={value => updateCustomer({ingestionMode: value})}
        onTitleChange={setDocumentTitle}
        onFilenameChange={setFilename}
        onContentChange={setContent}
        onFileChange={setSelectedFile}
        onPreview={previewPlan}
        onPasteIngest={ingestPastedContent}
        onUploadAndAttach={uploadAndAttachFile}
        jobs={jobs}
        onRefreshJobs={() => withBusy('Refreshing jobs', refreshJobsOnly)}
        onRetryJob={retryJob}
        lastIngestPayload={lastIngestPayload}
      />;
    }
    if (activeTab === 'keys') {
      return <AgentKeyHandoff
        customer={customer}
        selectedStore={selectedStore}
        apiKeys={apiKeys}
        keyLabel={agentKeyLabel}
        createdKey={createdKey}
        busy={busy}
        onKeyLabelChange={setAgentKeyLabel}
        onCreateAgentKey={createAgentKey}
        onRefreshKeys={() => withBusy('Refreshing keys', refreshApiKeysOnly)}
        onRevokeKey={revokeApiKey}
      />;
    }
    if (activeTab === 'retrieve') {
      return <RetrievalBench selectedStore={selectedStore} query={query} busy={busy} result={lastPayload} onQueryChange={setQuery} onDirectSearch={directSearch} onResponsesSearch={responsesFileSearch} />;
    }
    if (activeTab === 'fleet') {
      return <FleetStatus fleet={fleet} selectedFleet={selectedFleet} selectedBusinessInstanceId={selectedBusinessInstanceId} busy={busy} onSelectBusiness={selectBusinessInstance} onRefreshFleet={() => withBusy('Refreshing fleet', () => refreshFleetOnly())} />;
    }
    return <BackupReadiness backups={metrics} onRefresh={() => withBusy('Refreshing metrics', refreshMetricsOnly)} />;
  }

  return <AppShell activeTab={activeTab} setActiveTab={setActiveTab}>
    <TopBar session={session} apiKey={apiKey} busy={busy} error={lastError} onApiKeyChange={updateApiKey} onRefresh={refreshAll} />
    {renderActiveTab()}
    <JsonInspector title="Last API payload" value={lastPayload} />
  </AppShell>;
}

createRoot(document.getElementById('root')!).render(<App />);

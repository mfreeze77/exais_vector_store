export const ADMIN_API_KEY_STORAGE_KEY = 'svs_admin_api_key';

export const DEV_IDENTITY_HEADER_NAMES = [
  'x-svs-tenant-id',
  'x-svs-business-instance-id',
  'x-svs-user-id',
  'x-svs-groups',
  'x-svs-roles',
  'x-svs-max-security-level',
] as const;

type HeaderMap = Record<string, string>;
type EnvMap = Record<string, unknown>;
type StorageLike = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;

export class MissingAdminCredentialError extends Error {
  constructor() {
    super('Missing bearer API key');
    this.name = 'MissingAdminCredentialError';
  }
}

export type AdminAuthOptions = {
  apiKey?: string | null;
  storage?: StorageLike | null;
  devStorage?: StorageLike | null;
  devHeaders?: boolean;
  env?: EnvMap;
};

function browserSessionStorage(): StorageLike | null {
  if (typeof window === 'undefined') return null;
  return window.sessionStorage;
}

function browserLocalStorage(): StorageLike | null {
  if (typeof window === 'undefined') return null;
  return window.localStorage;
}

function envFlag(value: unknown): boolean {
  if (typeof value !== 'string') return value === true;
  return ['1', 'true', 'yes', 'on'].includes(value.trim().toLowerCase());
}

export function adminDevHeadersEnabled(env: EnvMap = import.meta.env): boolean {
  if (envFlag(env.PROD)) return false;
  return envFlag(env.DEV) && (envFlag(env.VITE_SVS_DEV_MODE) || envFlag(env.VITE_ADMIN_DEV_HEADERS));
}

export function getStoredAdminApiKey(storage: StorageLike | null = browserSessionStorage()): string {
  return (storage?.getItem(ADMIN_API_KEY_STORAGE_KEY) || '').trim();
}

export function storeAdminApiKey(value: string, storage: StorageLike | null = browserSessionStorage()): void {
  if (!storage) return;
  const trimmed = value.trim();
  if (trimmed) {
    storage.setItem(ADMIN_API_KEY_STORAGE_KEY, trimmed);
  } else {
    storage.removeItem(ADMIN_API_KEY_STORAGE_KEY);
  }
}

function storageValue(storage: StorageLike | null, key: string, fallback: string): string {
  return storage?.getItem(key)?.trim() || fallback;
}

export function normalizeBearerCredential(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) throw new MissingAdminCredentialError();
  return trimmed.toLowerCase().startsWith('bearer ') ? trimmed : `Bearer ${trimmed}`;
}

export function buildDevIdentityHeaders(storage: StorageLike | null = browserLocalStorage()): HeaderMap {
  return {
    'x-svs-tenant-id': storageValue(storage, 'svs_tenant', 'ten_dev'),
    'x-svs-business-instance-id': storageValue(storage, 'svs_biz', 'biz_dev'),
    'x-svs-user-id': storageValue(storage, 'svs_user', 'usr_dev'),
    'x-svs-groups': storageValue(storage, 'svs_groups', 'grp_admin,grp_eng,admins,engineering'),
    'x-svs-roles': storageValue(storage, 'svs_roles', 'owner,admin'),
    'x-svs-max-security-level': storageValue(storage, 'svs_level', '5'),
  };
}

export function buildAdminAuthHeaders(options: AdminAuthOptions = {}): HeaderMap {
  const apiKey = (options.apiKey ?? getStoredAdminApiKey(options.storage)).trim();
  if (apiKey) {
    return {Authorization: normalizeBearerCredential(apiKey)};
  }
  if (options.devHeaders ?? adminDevHeadersEnabled(options.env)) {
    return buildDevIdentityHeaders(options.devStorage ?? browserLocalStorage());
  }
  throw new MissingAdminCredentialError();
}

function headersToRecord(headers?: HeadersInit): HeaderMap {
  const record: HeaderMap = {};
  new Headers(headers || {}).forEach((value, key) => {
    record[key] = value;
  });
  return record;
}

function deleteHeader(headers: HeaderMap, headerName: string): void {
  const normalized = headerName.toLowerCase();
  for (const key of Object.keys(headers)) {
    if (key.toLowerCase() === normalized) {
      delete headers[key];
    }
  }
}

export function removeDevIdentityHeaders(headers: HeaderMap): HeaderMap {
  for (const headerName of DEV_IDENTITY_HEADER_NAMES) {
    deleteHeader(headers, headerName);
  }
  return headers;
}

export function decorateAdminRequest(init: RequestInit = {}, options: AdminAuthOptions = {}): RequestInit {
  const headers = removeDevIdentityHeaders(headersToRecord(init.headers));
  deleteHeader(headers, 'authorization');
  return {
    ...init,
    credentials: init.credentials ?? 'include',
    headers: {
      ...headers,
      ...buildAdminAuthHeaders(options),
    },
  };
}

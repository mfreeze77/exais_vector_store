export type FleetComponentStatus = 'current' | 'stale' | 'unverifiable';

export type FleetComponentVersion = {
  service: string;
  status: FleetComponentStatus;
  declared_version?: string | null;
  running_version?: string | null;
  image?: string | null;
  expected_image?: string | null;
  digest?: string | null;
  image_id?: string | null;
  source: string;
  reasons: string[];
};

export type FleetDeploymentRecord = {
  id: string;
  instance_id?: string | null;
  business_instance_id?: string | null;
  from_version?: string | null;
  to_version?: string | null;
  status: string;
  image_digests: Record<string, unknown>;
  manifest: Record<string, unknown>;
  started_at?: number | null;
  completed_at?: number | null;
  created_at?: number | null;
};

export type FleetBusinessInstance = {
  id: string;
  name: string;
  slug: string;
  deployment_mode?: string | null;
  isolation_level?: string | null;
  status?: string | null;
  created_at?: number | null;
  vault: Record<string, unknown>;
  declared_product_version?: string | null;
  latest_deployment?: FleetDeploymentRecord | null;
  components: FleetComponentVersion[];
  verification_status: FleetComponentStatus;
  issues: string[];
};

export type FleetVersionReport = {
  object: 'fleet.version_report';
  tenant_id: string;
  selected_business_instance_id?: string | null;
  product_version?: string | null;
  generated_at: number;
  expected_services: string[];
  business_instances: FleetBusinessInstance[];
  deployments: FleetDeploymentRecord[];
  evidence_note: string;
};

export function selectedFleetInstance(report: FleetVersionReport | null): FleetBusinessInstance | null {
  if (!report) return null;
  const selected = report.selected_business_instance_id;
  return report.business_instances.find(instance => instance.id === selected) || report.business_instances[0] || null;
}

export function fleetIssueCount(instance: FleetBusinessInstance | null): number {
  if (!instance) return 0;
  return instance.components.filter(component => component.status !== 'current').length;
}

export function displayValue(value?: string | number | null): string {
  if (value === undefined || value === null || value === '') return 'not recorded';
  return String(value);
}

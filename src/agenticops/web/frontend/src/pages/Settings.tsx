import { useEffect, useState, useRef, useCallback, useId } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import * as Tabs from "@radix-ui/react-tabs";
import { Card, CardHeader, CardBody } from "@/components/ui/Card";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { Badge } from "@/components/ui/Badge";
import { Switch } from "@/components/ui/Switch";
import { formatShortDate } from "@/lib/formatDate";
import { buildAccountCredentials, hasStoredSecrets } from "@/lib/accountForm";
import { useLocale } from "@/i18n/LocaleContext";
import { useCloseOnEscape } from "@/hooks/useCloseOnEscape";
import { itemViews, settingsTab } from "@/lib/setup";
import { SECTIONS, modelAvailability, modelListOrFallback, sectionAnchor, sectionOfHash, shownTab, type SectionId } from "@/lib/settingsPage";
import { auditTabVisible } from "@/lib/plans";
import { AutomationCard } from "@/components/settings/AutomationCard";
import { StatusText } from "@/components/ui/StatusText";
import { useReadiness } from "@/hooks/useSetup";
import { formatFullDate } from "@/lib/formatDate";
import { useScanFocus } from "@/hooks/useScanFocus";
import { useSettings, useUpdateSettings, type AppSettings } from "@/hooks/useSettings";
import { useExcludePatterns, useUpdateExcludePatterns } from "@/hooks/useExcludePatterns";
import { MessagingTab } from "@/components/settings/MessagingTab";
import { AuditTab } from "@/components/settings/AuditTab";
import { KBTab } from "@/components/settings/KBTab";
import { ModelProvidersTab } from "@/components/settings/ModelProvidersTab";
import { OtherModelsCard } from "@/components/settings/OtherModelsCard";
import { ModelPicker } from "@/components/models/ModelPicker";
import { canChangeModels } from "@/lib/permissions";
import { SkillsTab } from "@/components/settings/SkillsTab";
import { ConnectorsCard } from "@/components/settings/ConnectorsCard";
import { ChatUploadCard } from "@/components/settings/ChatUploadCard";
import { ModelRuntimeCard } from "@/components/settings/ModelRuntimeCard";
import {
  useAccounts,
  useCreateAccount,
  useUpdateAccount,
  useDeleteAccount,
  useEnvironmentInfo,
  useTestConnection,
} from "@/hooks/useAccounts";
import {
  useMcpServers,
  useUpsertMcpServer,
  useDeleteMcpServer,
  useReloadMcpServers,
  useImportMcpServers,
} from "@/hooks/useMcpServers";
import {
  useAgentMemories,
  useUpdateAgentMemory,
  useDeleteAgentMemory,
  type AgentMemory,
} from "@/hooks/useAgentMemory";
import type { ScanFocus, AgentModelConfig } from "@/api/types";
import type { Account, AccountCreate, AccountUpdate, CloudProvider, McpServerConfig, CredentialSourceType } from "@/api/types";
import { useBootstrap, useReadOnly } from "@/hooks/useBootstrap";

import { fillPlaceholders } from "@/lib/placeholders";
/* ── Scan Focus section ─────────────────────────────────────────── */

const FOCUS_META: Record<ScanFocus, { services: string; icon: JSX.Element }> = {
  all:        { services: "",                                         icon: <IconAll /> },
  computing:  { services: "EC2, Lambda, ECS, EKS, AutoScaling",       icon: <IconCompute /> },
  networking: { services: "VPC, SG, ELB, Subnet, NAT GW, Route53",    icon: <IconNetwork /> },
  databases:  { services: "RDS, DynamoDB, ElastiCache, OpenSearch",   icon: <IconDatabase /> },
  storage:    { services: "S3, EBS, EFS",                             icon: <IconStorage /> },
  security:   { services: "IAM Roles, KMS",                           icon: <IconSecurity /> },
  billing:    { services: "Cost Explorer, Budgets, Quotas",           icon: <IconBilling /> },
};

type T = (key: string) => string;

/** One of the General tab's three sections (MVP-2.9.0 N25): its name, and what it applies to. */
function SectionHead({ id, t }: { id: SectionId; t: T }) {
  return (
    <div id={sectionAnchor(id)} className="scroll-mt-[calc(var(--topbar-h)+1rem)] border-b border-border pb-2 pt-2">
      <h2 className="text-xl font-semibold text-foreground">{t(`settings.section.${id}`)}</h2>
      <p className="mt-0.5 text-xs text-muted-foreground">{t(`settings.section.${id}.scope`)}</p>
    </div>
  );
}

/** The settings, once they are read: loading and «could not be read» (with a retry) are said, never an empty card. */
function Loaded({ q, t, children }: { q: ReturnType<typeof useSettings>; t: T; children: (s: AppSettings) => React.ReactNode }) {
  if (q.isLoading) return <Spinner label={t("common.loading")} />;
  if (q.error || !q.data) {
    return <ErrorBanner message={`${t("settings.loadFailed")}${q.error ? ` · ${q.error.message}` : ""}`}
                        onRetry={() => void q.refetch()} actionLabel={t("common.retry")} />;
  }
  return <>{children(q.data)}</>;
}

/** Where the models are called, and when Main's was last verified (MVP-2.9.0 N25; the record is N23's). */
function ModelFactsCard() {
  const { t } = useLocale();
  const readiness = useReadiness(true);
  const model = readiness.data?.model;
  const view = readiness.data ? itemViews(readiness.data)[1] : null;
  const check = model?.check ?? null;
  return (
    <Card>
      <CardBody>
        {readiness.isLoading ? <Spinner label={t("common.loading")} />
          : !model || !view ? <ErrorBanner message={t("settings.loadFailed")} onRetry={() => void readiness.refetch()} actionLabel={t("common.retry")} />
          : (
            <dl className="grid gap-x-6 gap-y-1.5 text-sm sm:grid-cols-[auto_minmax(0,1fr)]">
              {model.provider && model.provider !== "bedrock" ? (<>
                <dt className="text-muted-foreground">{t("settings.models.provider")}</dt>
                <dd className="[overflow-wrap:anywhere]"><span className="text-foreground">{model.provider}</span> <span className="font-mono text-xs text-muted-foreground">{model.endpoint}</span></dd>
              </>) : (<>
                <dt className="text-muted-foreground">{t("settings.models.region")}</dt>
                <dd><span className="font-mono text-foreground">{model.region}</span> <span className="text-xs text-muted-foreground">· {t("settings.models.regionNote")}</span></dd>
              </>)}
              <dt className="text-muted-foreground">{t("settings.models.main")}</dt>
              <dd className="font-mono text-foreground [overflow-wrap:anywhere]">{model.model_id}</dd>
              <dt className="text-muted-foreground">{t("settings.models.verified")}</dt>
              <dd className="flex flex-wrap items-center gap-x-2">
                <StatusText tone={view.tone} className="whitespace-normal">{t(view.stateKey)}</StatusText>
                {check && (
                  <span className="text-xs text-muted-foreground">
                    {fillPlaceholders(t(check.ok ? "setup.check.ok" : "setup.check.failed"), { time: formatFullDate(check.checked_at), by: check.checked_by.replace(/^user:/, "") })}
                    {!check.ok && check.detail ? ` · ${check.detail}` : ""}
                  </span>
                )}
                <Link to="/app/setup" className="text-xs font-medium text-primary hover:underline">{t("settings.models.setup")}</Link>
              </dd>
            </dl>
          )}
      </CardBody>
    </Card>
  );
}

function FocusToggle({
  label, description, icon, active, onClick,
}: {
  label: string; description: string; icon: JSX.Element; active: boolean; onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`group flex items-start gap-3 p-3 rounded-lg border transition-all text-left ${
        active
          ? "bg-primary-50 border-primary-300 shadow-sm"
          : "bg-background border-border hover:border-border hover:bg-secondary"
      }`}
    >
      <div className={`mt-0.5 flex-shrink-0 w-8 h-8 rounded-lg flex items-center justify-center ${
        active ? "bg-primary-100 text-primary-600" : "bg-secondary text-muted-foreground group-hover:text-muted-foreground"
      }`}>
        {icon}
      </div>
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span className={`text-sm font-medium ${active ? "text-primary-700" : "text-foreground"}`}>
            {label}
          </span>
          <div aria-hidden className={`w-7 h-4 rounded-full transition-colors flex items-center ${
            active ? "bg-primary-500 justify-end" : "bg-muted-foreground/30 justify-start"
          }`}>
            <div className="w-3 h-3 mx-0.5 rounded-full bg-background shadow-sm" />
          </div>
        </div>
        <p className="text-xs text-muted-foreground mt-0.5 leading-tight">{description}</p>
      </div>
    </button>
  );
}

/* ── Pipeline toggle ────────────────────────────────────────────── */

function SettingToggle({
  label, description, enabled, onChange, saving,
}: {
  label: string; description: string; enabled: boolean; onChange: (v: boolean) => void; saving?: boolean;
}) {
  const id = useId();
  return (
    <div className="flex items-center justify-between gap-4 py-3 border-b border-border/50 last:border-b-0">
      <div>
        <span id={`${id}-name`} className="text-sm font-medium text-foreground">{label}</span>
        <p id={`${id}-desc`} className="text-xs text-muted-foreground mt-0.5">{description}</p>
      </div>
      <Switch checked={enabled} onCheckedChange={onChange} disabled={saving}
              labelledBy={`${id}-name`} describedBy={`${id}-desc`} />
    </div>
  );
}

/* ── Account form modal ────────────────────────────────────────── */

const PROVIDER_OPTIONS: { value: CloudProvider; label: string }[] = [
  { value: "aws", label: "AWS" },
  { value: "azure", label: "Azure" },
  { value: "gcp", label: "GCP" },
  { value: "alicloud", label: "Alicloud" },
];

/** A provider's static-credential fields. `words` = the field's name in the locale files (`settings.cred.<words>`);
 *  `sample` = an example value shown as the placeholder as it is, `hint` = a placeholder said in words
 *  (`settings.cred.ph.<hint>`). */
const PROVIDER_FIELDS: Record<CloudProvider, { key: string; words: string; type?: string; sample?: string; hint?: string }[]> = {
  aws: [
    { key: "access_key_id", words: "accessKeyId", sample: "AKIA..." },
    { key: "secret_access_key", words: "secretAccessKey", type: "password", hint: "secretAccessKey" },
    { key: "account_id", words: "accountId", sample: "123456789012" },
  ],
  azure: [
    { key: "subscription_id", words: "subscriptionId", sample: "00000000-0000-0000-0000-000000000000" },
    { key: "tenant_id", words: "tenantId", sample: "00000000-0000-0000-0000-000000000000" },
    { key: "client_id", words: "clientId", hint: "spAppId" },
    { key: "client_secret", words: "clientSecret", type: "password", hint: "spSecret" },
  ],
  gcp: [
    { key: "project_id", words: "projectId", sample: "my-gcp-project" },
    { key: "service_account_key", words: "serviceAccountKey", type: "textarea", sample: '{"type": "service_account", ...}' },
  ],
  alicloud: [
    { key: "access_key_id", words: "accessKeyId", sample: "LTAI..." },
    { key: "access_key_secret", words: "accessKeySecret", type: "password", hint: "secret" },
    { key: "account_id", words: "accountId", sample: "1234567890" },
  ],
};

function AccountFormModal({
  initial, onClose, onSave, saving, error,
}: {
  initial?: Account | null; onClose: () => void;
  onSave: (data: AccountCreate | AccountUpdate) => void; saving: boolean;
  error?: string | null;
}) {
  const isEdit = !!initial;
  const { t } = useLocale();
  useCloseOnEscape(onClose);        // the house rule: a dialog closes on Escape
  const [provider, setProvider] = useState<CloudProvider>(initial?.provider ?? "aws");
  const [name, setName] = useState(initial?.name ?? "");
  const [regions, setRegions] = useState(initial?.regions?.join(", ") ?? "");
  const [isEnabled, setIsEnabled] = useState(initial?.is_enabled ?? true);
  // Infer source type from credentials — only two user-facing options: assume_role | static_keys
  function inferSourceType(): CredentialSourceType {
    const dbType = initial?.credential_source_type;
    const c = initial?.credentials;
    // If DB already says assume_role or static_keys, trust it
    if (dbType === "assume_role" || dbType === "static_keys") return dbType;
    // Infer from credentials content
    if (c?.role_arn) return "assume_role";
    if (c?.access_key_id || c?.secret_access_key || c?._encrypted) return "static_keys";
    // Default to assume_role (the standard enterprise pattern)
    return "assume_role";
  }
  const [sourceType, setSourceType] = useState<CredentialSourceType>(inferSourceType());
  // Seed credential fields from existing account (edit mode)
  const initialCreds: Record<string, string> = {};
  if (initial?.credentials) {
    for (const [k, v] of Object.entries(initial.credentials)) {
      if (typeof v === "string" && v !== "***REDACTED***") {
        initialCreds[k] = v;
      } else if (typeof v === "object" && v !== null) {
        initialCreds[k] = JSON.stringify(v, null, 2);
      }
    }
  }
  const [creds, setCreds] = useState<Record<string, string>>(initialCreds);
  // The API never returns a stored secret (it shows it redacted) and keeps one an edit leaves empty
  const storedSecrets = isEdit && hasStoredSecrets(initial?.credentials);
  const [clearSecrets, setClearSecrets] = useState(false);

  const envQ = useEnvironmentInfo();

  const fields = PROVIDER_FIELDS[provider];

  // Only two user-facing options:
  // - assume_role: AK/SK (optional) → AssumeRole (standard enterprise pattern)
  // - static_keys: Direct AK/SK when AssumeRole is unavailable
  const SOURCE_TYPE_OPTIONS: { value: CredentialSourceType; label: string; description: string }[] = [
    { value: "assume_role", label: t("settings.account.method.assumeRole"), description: t("settings.account.method.assumeRoleDesc") },
    { value: "static_keys", label: t("settings.account.method.keys"), description: t("settings.account.method.keysDesc") },
  ];

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const regionList = regions.split(",").map((r) => r.trim()).filter(Boolean);
    const credentials = buildAccountCredentials({ method: sourceType as "assume_role" | "static_keys", fields, values: creds, isEdit });

    if (isEdit) {
      onSave({
        name, credential_source_type: sourceType, credentials, regions: regionList, is_enabled: isEnabled,
        ...(clearSecrets ? { clear_secrets: true } : {}),
      } as AccountUpdate);
    } else {
      onSave({ name, provider, credential_source_type: sourceType, credentials, regions: regionList, is_enabled: isEnabled } as AccountCreate);
    }
  }

  const inputClass = "w-full px-3 py-2 border border-border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary-500";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-background rounded-lg shadow-lg w-full max-w-lg p-6 max-h-[90vh] overflow-y-auto">
        <h3 className="text-lg font-semibold text-foreground mb-4">
          {isEdit ? t("settings.account.edit") : t("settings.account.new")}
        </h3>
        {envQ.data && (
          <div className="mb-3 p-2 rounded-lg bg-secondary text-xs text-muted-foreground flex items-center gap-2">
            <span>{t("settings.account.env")}<strong>{envQ.data.environment}</strong></span>
            <span>|</span>
            <span>{t("settings.account.encryption")}<strong>{envQ.data.credential_backend}</strong></span>
          </div>
        )}
        <form onSubmit={handleSubmit} className="space-y-3">
          <div>
            <label className="block text-sm font-medium text-foreground mb-1">{t("settings.account.provider")}</label>
            <select
              value={provider}
              onChange={(e) => { setProvider(e.target.value as CloudProvider); setCreds({}); }}
              disabled={isEdit}
              className={`${inputClass} disabled:bg-secondary`}
            >
              {PROVIDER_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-foreground mb-1">{t("settings.account.name")}</label>
            <input required value={name} onChange={(e) => setName(e.target.value)} placeholder={t("settings.account.namePh")} className={inputClass} />
          </div>
          <div>
            <label className="block text-sm font-medium text-foreground mb-1">{t("settings.account.regions")}</label>
            <input value={regions} onChange={(e) => setRegions(e.target.value)} placeholder="us-east-1, us-west-2" className={inputClass} />
          </div>

          {/* Credential Source Type */}
          <div>
            <label className="block text-sm font-medium text-foreground mb-1">{t("settings.account.method")}</label>
            <div className="space-y-1">
              {SOURCE_TYPE_OPTIONS.map((opt) => (
                <label key={opt.value} className={`flex items-start gap-2 p-2 rounded-lg border cursor-pointer transition-colors ${sourceType === opt.value ? "border-primary-500 bg-primary-50" : "border-border hover:bg-secondary"}`}>
                  <input
                    type="radio"
                    name="sourceType"
                    value={opt.value}
                    checked={sourceType === opt.value}
                    onChange={() => setSourceType(opt.value)}
                    className="mt-0.5"
                  />
                  <div>
                    <span className="text-sm font-medium text-foreground">{opt.label}</span>
                    <p className="text-xs text-muted-foreground">{opt.description}</p>
                  </div>
                </label>
              ))}
            </div>
          </div>

          {/* Dynamic fields based on source type */}
          {sourceType === "assume_role" && (
            <div className="space-y-3 border-t border-border pt-3">
              <div>
                <label className="block text-sm font-medium text-foreground mb-1">{t("settings.account.roleArn")} <span className="text-red-500">*</span></label>
                <input required value={creds.role_arn ?? ""} onChange={(e) => setCreds({ ...creds, role_arn: e.target.value })} placeholder="arn:aws:iam::123456789012:role/AgenticOpsRole" className={inputClass} />
              </div>
              <div>
                <label className="block text-sm font-medium text-foreground mb-1">{t("settings.account.externalId")}</label>
                <input value={creds.external_id ?? ""} onChange={(e) => setCreds({ ...creds, external_id: e.target.value })} placeholder="aiops-prod-xxx" className={inputClass} />
              </div>
              <div className="pt-2 border-t border-dashed border-border">
                <p className="text-xs text-muted-foreground mb-2">
                  {storedSecrets
                    ? t("settings.account.base")
                    : t("settings.account.baseDefault")}
                </p>
                <div className="space-y-2">
                  <div>
                    <label className="block text-sm font-medium text-foreground mb-1">{t("settings.account.akOptional")}</label>
                    <input value={creds.access_key_id ?? ""} onChange={(e) => setCreds({ ...creds, access_key_id: e.target.value })} placeholder={t("settings.account.akPh")} className={inputClass} />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-foreground mb-1">{t("settings.account.skOptional")}</label>
                    <input type="password" value={creds.secret_access_key ?? ""} onChange={(e) => setCreds({ ...creds, secret_access_key: e.target.value })} placeholder={t("settings.account.encrypted")} className={inputClass} />
                  </div>
                  {storedSecrets && (
                    <StoredKeys remove={clearSecrets} onRemove={setClearSecrets}
                      removeHint={t("settings.account.removeHintRole")} />
                  )}
                </div>
              </div>
            </div>
          )}

          {sourceType === "static_keys" && (
            <div className="space-y-3 border-t border-border pt-3">
              <div className="p-2 rounded-lg bg-yellow-50 border border-yellow-200 text-xs text-yellow-700">
                {t("settings.account.staticNote")}
              </div>
              {fields.map((f) => (
                <div key={f.key}>
                  <label className="block text-sm font-medium text-foreground mb-1">{t("settings.cred." + f.words)}</label>
                  {f.type === "textarea" ? (
                    <textarea
                      value={creds[f.key] ?? ""}
                      onChange={(e) => setCreds({ ...creds, [f.key]: e.target.value })}
                      placeholder={f.hint ? t("settings.cred.ph." + f.hint) : f.sample}
                      rows={4}
                      className={inputClass}
                    />
                  ) : (
                    <input
                      type={f.type ?? "text"}
                      value={creds[f.key] ?? ""}
                      onChange={(e) => setCreds({ ...creds, [f.key]: e.target.value })}
                      placeholder={f.hint ? t("settings.cred.ph." + f.hint) : f.sample}
                      className={inputClass}
                    />
                  )}
                </div>
              ))}
              {storedSecrets && (
                <StoredKeys remove={clearSecrets} onRemove={setClearSecrets}
                  removeHint={t("settings.account.removeHintKeys")} />
              )}
            </div>
          )}

          <div className="flex items-center gap-2">
            <input id="is-enabled-settings" type="checkbox" checked={isEnabled} onChange={(e) => setIsEnabled(e.target.checked)} className="rounded border-border" />
            <label htmlFor="is-enabled-settings" className="text-sm text-foreground">{t("common.enabled")}</label>
          </div>
          {error && (
            <div className="p-3 rounded-lg border bg-red-50 border-red-200 text-sm text-red-700">{error}</div>
          )}
          <div className="flex justify-end gap-2 pt-2">
            <button type="button" onClick={onClose} className="px-4 py-2 text-sm text-foreground border border-border rounded-lg hover:bg-secondary">{t("common.cancel")}</button>
            <button type="submit" disabled={saving} className="px-4 py-2 text-sm text-white bg-primary-600 rounded-lg hover:bg-primary-500 disabled:opacity-50">{saving ? t("common.saving") : t("common.save")}</button>
          </div>
        </form>
      </div>
    </div>
  );
}

/** An edited account that stores secrets: they are kept unless retyped, or removed on purpose. */
function StoredKeys({ remove, onRemove, removeHint }: {
  remove: boolean; onRemove: (remove: boolean) => void; removeHint: string;
}) {
  const { t } = useLocale();
  return (
    <div className="p-2 rounded-lg bg-secondary text-xs text-muted-foreground space-y-1.5">
      <p>{remove ? t("settings.account.keysRemoved") : t("settings.account.keysKept")}</p>
      <label className="flex items-start gap-2 cursor-pointer">
        <input type="checkbox" checked={remove} onChange={(e) => onRemove(e.target.checked)} className="mt-0.5 rounded border-border" />
        <span>
          <span className="text-foreground">{t("settings.account.removeKeys")}</span>
          <span className="block">{removeHint}</span>
        </span>
      </label>
    </div>
  );
}

function DeleteModal({
  account, onClose, onConfirm, deleting,
}: {
  account: Account; onClose: () => void; onConfirm: () => void; deleting: boolean;
}) {
  const { t } = useLocale();
  useCloseOnEscape(onClose);        // the house rule: a dialog closes on Escape
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-background rounded-lg shadow-lg w-full max-w-sm p-6">
        <h3 className="text-lg font-semibold text-foreground mb-2">{t("settings.account.delete")}</h3>
        <p className="text-sm text-muted-foreground mb-4">
          {t("settings.account.deleteAsk")} <strong>{account.name}</strong> ({account.provider.toUpperCase()}){t("settings.account.deleteWarn")}
        </p>
        <div className="flex justify-end gap-2">
          <button onClick={onClose} className="px-4 py-2 text-sm text-foreground border border-border rounded-lg hover:bg-secondary">{t("common.cancel")}</button>
          <button onClick={onConfirm} disabled={deleting} className="px-4 py-2 text-sm text-white bg-red-600 rounded-lg hover:bg-red-500 disabled:opacity-50">{deleting ? t("common.deleting") : t("common.delete")}</button>
        </div>
      </div>
    </div>
  );
}

/* ── Accounts columns ───────────────────────────────────────────── */

const SETTINGS_PROVIDER_BADGE: Record<CloudProvider, string> = {
  aws: "bg-orange-100 text-orange-700",
  azure: "bg-blue-100 text-blue-700",
  gcp: "bg-green-100 text-green-700",
  alicloud: "bg-purple-100 text-purple-700",
};

const SOURCE_TYPE_BADGE: Record<string, string> = {
  assume_role: "bg-blue-100 text-blue-700",
  static_keys: "bg-amber-100 text-amber-700",
};

const SOURCE_TYPE_LABEL: Record<string, string> = {
  assume_role: "AssumeRole",
  static_keys: "AK/SK",
};

const accountColumns = (t: T): Column<Account>[] => [
  { key: "name", header: t("settings.account.name"), sortable: true, sortValue: (r) => r.name, render: (r) => <span className="font-medium text-foreground">{r.name}</span> },
  { key: "provider", header: t("settings.account.provider"), render: (r) => <Badge className={SETTINGS_PROVIDER_BADGE[r.provider]}>{r.provider.toUpperCase()}</Badge> },
  { key: "credential_source_type", header: t("settings.account.col.auth"), render: (r) => <Badge className={SOURCE_TYPE_BADGE[r.credential_source_type] ?? "bg-secondary text-muted-foreground"}>{SOURCE_TYPE_LABEL[r.credential_source_type] ?? r.credential_source_type}</Badge> },
  { key: "regions", header: t("settings.account.col.regions"), render: (r) => <div className="flex flex-wrap gap-1">{r.regions.map((reg) => <Badge key={reg} className="bg-secondary text-muted-foreground">{reg}</Badge>)}</div> },
  { key: "is_enabled", header: t("settings.account.col.status"), render: (r) => r.is_enabled ? <Badge className="bg-green-100 text-green-700">{t("common.enabled")}</Badge> : <Badge className="bg-secondary text-muted-foreground">{t("common.disabled")}</Badge> },
  { key: "last_scanned_at", header: t("settings.account.col.scanned"), sortable: true, sortValue: (r) => r.last_scanned_at ?? "", render: (r) => <span className="text-sm text-muted-foreground">{r.last_scanned_at ? formatShortDate(r.last_scanned_at) : t("common.never")}</span> },
];

/* ── MCP Server form modal ────────────────────────────────────────── */

function McpServerFormModal({
  initial, onClose, onSave, saving,
}: {
  initial: { name: string; config: McpServerConfig } | null;
  onClose: () => void;
  onSave: (name: string, config: McpServerConfig) => void;
  saving: boolean;
}) {
  const isEdit = !!initial;
  const { t } = useLocale();
  useCloseOnEscape(onClose);        // the house rule: a dialog closes on Escape
  const [name, setName] = useState(initial?.name ?? "");
  const [command, setCommand] = useState(initial?.config.command ?? "");
  const [args, setArgs] = useState((initial?.config.args ?? []).join(" "));
  const [envText, setEnvText] = useState(
    Object.entries(initial?.config.env ?? {}).map(([k, v]) => `${k}=${v}`).join("\n"),
  );
  const [disabled, setDisabled] = useState(initial?.config.disabled ?? false);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const argList = args.trim() ? args.trim().split(/\s+/) : [];
    const env: Record<string, string> = {};
    envText.split("\n").filter(Boolean).forEach((line) => {
      const eq = line.indexOf("=");
      if (eq > 0) env[line.slice(0, eq).trim()] = line.slice(eq + 1).trim();
    });
    onSave(name, {
      command: command || undefined,
      args: argList.length ? argList : undefined,
      env: Object.keys(env).length ? env : undefined,
      disabled,
    });
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-background rounded-lg shadow-lg w-full max-w-md p-6">
        <h3 className="text-lg font-semibold text-foreground mb-4">
          {isEdit ? t("settings.mcp.edit") : t("settings.mcp.new")}
        </h3>
        <form onSubmit={handleSubmit} className="space-y-3">
          <div>
            <label className="block text-sm font-medium text-foreground mb-1">{t("settings.mcp.name")}</label>
            <input required disabled={isEdit} value={name} onChange={(e) => setName(e.target.value)} placeholder="awslabs.aws-documentation-mcp-server" className="w-full px-3 py-2 border border-border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary-500 disabled:bg-secondary font-mono" />
          </div>
          <div>
            <label className="block text-sm font-medium text-foreground mb-1">{t("settings.mcp.command")}</label>
            <input required value={command} onChange={(e) => setCommand(e.target.value)} placeholder="uvx" className="w-full px-3 py-2 border border-border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary-500 font-mono" />
          </div>
          <div>
            <label className="block text-sm font-medium text-foreground mb-1">{t("settings.mcp.args")}</label>
            <input value={args} onChange={(e) => setArgs(e.target.value)} placeholder="awslabs.aws-documentation-mcp-server@latest" className="w-full px-3 py-2 border border-border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary-500 font-mono" />
          </div>
          <div>
            <label className="block text-sm font-medium text-foreground mb-1">{t("settings.mcp.env")}</label>
            <textarea rows={3} value={envText} onChange={(e) => setEnvText(e.target.value)} placeholder={"FASTMCP_LOG_LEVEL=ERROR\nAWS_DOCUMENTATION_PARTITION=aws"} className="w-full px-3 py-2 border border-border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary-500 font-mono" />
          </div>
          <div className="flex items-center gap-2">
            <input id="mcp-disabled" type="checkbox" checked={disabled} onChange={(e) => setDisabled(e.target.checked)} className="rounded border-border" />
            <label htmlFor="mcp-disabled" className="text-sm text-foreground">{t("common.disabled")}</label>
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <button type="button" onClick={onClose} className="px-4 py-2 text-sm text-foreground border border-border rounded-lg hover:bg-secondary">{t("common.cancel")}</button>
            <button type="submit" disabled={saving} className="px-4 py-2 text-sm text-white bg-primary-600 rounded-lg hover:bg-primary-500 disabled:opacity-50">{saving ? t("common.saving") : t("common.save")}</button>
          </div>
        </form>
      </div>
    </div>
  );
}

/* ── MCP Import Dialog ──────────────────────────────────────────── */

interface McpValidationResult {
  valid: boolean;
  servers: string[];
  /** Why it is not valid — `settings.mcp.err.<error>` in the locale files; `names` fills «missing». */
  error?: "syntax" | "notObject" | "noKey" | "empty" | "missing";
  names?: string;
  /** What the server said when the import itself was refused — its own words, shown as they are. */
  detail?: string;
}

function validateMcpJson(text: string): McpValidationResult {
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch {
    return { valid: false, servers: [], error: "syntax" };
  }
  if (!data || typeof data !== "object") {
    return { valid: false, servers: [], error: "notObject" };
  }
  const obj = data as Record<string, unknown>;
  if (!obj.mcpServers || typeof obj.mcpServers !== "object" || Array.isArray(obj.mcpServers)) {
    return { valid: false, servers: [], error: "noKey" };
  }
  const entries = Object.entries(obj.mcpServers as Record<string, unknown>);
  if (entries.length === 0) {
    return { valid: false, servers: [], error: "empty" };
  }
  const invalid: string[] = [];
  for (const [name, cfg] of entries) {
    if (!cfg || typeof cfg !== "object") {
      invalid.push(name);
      continue;
    }
    const c = cfg as Record<string, unknown>;
    if (!c.command && !c.url) {
      invalid.push(name);
    }
  }
  if (invalid.length > 0) {
    return { valid: false, servers: [], error: "missing", names: invalid.join(", ") };
  }
  return { valid: true, servers: entries.map(([n]) => n) };
}

function McpImportDialog({
  onClose,
  onImport,
  importing,
}: {
  onClose: () => void;
  onImport: (data: unknown) => Promise<void>;
  importing: boolean;
}) {
  const { t } = useLocale();
  useCloseOnEscape(onClose);        // the house rule: a dialog closes on Escape
  const [mode, setMode] = useState<"file" | "paste">("file");
  const [jsonText, setJsonText] = useState("");
  const [validation, setValidation] = useState<McpValidationResult | null>(null);
  const [importResult, setImportResult] = useState<{ success: boolean; servers: string[] } | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const validate = useCallback((text: string) => {
    setJsonText(text);
    setImportResult(null);
    if (!text.trim()) {
      setValidation(null);
      return;
    }
    setValidation(validateMcpJson(text));
  }, []);

  function handleFileLoad(file: File) {
    const reader = new FileReader();
    reader.onload = (ev) => {
      const text = ev.target?.result as string;
      validate(text);
    };
    reader.readAsText(file);
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files[0];
    if (file && file.name.endsWith(".json")) handleFileLoad(file);
  }

  async function handleImport() {
    if (!validation?.valid) return;
    try {
      const data = JSON.parse(jsonText);
      await onImport(data);
      setImportResult({ success: true, servers: validation.servers });
      setTimeout(onClose, 2000);
    } catch (err) {
      setImportResult({ success: false, servers: [] });
      setValidation({ valid: false, servers: [], detail: String(err) });
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-background rounded-lg shadow-lg w-full max-w-lg p-6">
        <h3 className="text-lg font-semibold text-foreground mb-4">{t("settings.mcp.importTitle")}</h3>

        {/* Mode tabs */}
        <div className="flex gap-1 mb-4 bg-secondary rounded-lg p-1">
          <button
            onClick={() => { setMode("file"); setJsonText(""); setValidation(null); setImportResult(null); }}
            className={`flex-1 px-3 py-1.5 text-sm rounded-md transition-colors ${mode === "file" ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"}`}
          >{t("settings.mcp.upload")}</button>
          <button
            onClick={() => { setMode("paste"); setJsonText(""); setValidation(null); setImportResult(null); }}
            className={`flex-1 px-3 py-1.5 text-sm rounded-md transition-colors ${mode === "paste" ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"}`}
          >{t("settings.mcp.paste")}</button>
        </div>

        {/* File upload zone */}
        {mode === "file" && (
          <div
            onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
            onDragLeave={() => setDragOver(false)}
            onDrop={handleDrop}
            onClick={() => fileRef.current?.click()}
            className={`border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-colors ${
              dragOver ? "border-primary-400 bg-primary-50" : "border-border hover:border-border hover:bg-secondary"
            }`}
          >
            <input
              ref={fileRef}
              type="file"
              accept=".json"
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) handleFileLoad(file);
                e.target.value = "";
              }}
            />
            <p className="text-sm text-muted-foreground">{t("settings.mcp.drop")}</p>
            <p className="text-xs text-muted-foreground mt-1">{t("settings.mcp.format")} <code>{'{"mcpServers": {...}}'}</code></p>
          </div>
        )}

        {/* Paste textarea */}
        {mode === "paste" && (
          <textarea
            rows={8}
            value={jsonText}
            onChange={(e) => validate(e.target.value)}
            placeholder={'{\n  "mcpServers": {\n    "my-server": {\n      "command": "uvx",\n      "args": ["my-mcp-server"]\n    }\n  }\n}'}
            className="w-full px-3 py-2 border border-border rounded-lg text-sm font-mono focus:outline-none focus:ring-2 focus:ring-primary-500"
          />
        )}

        {/* Validation result */}
        {validation && (
          <div className={`mt-3 p-3 rounded-lg border text-sm ${
            validation.valid
              ? "bg-green-50 border-green-200 text-green-700"
              : "bg-red-50 border-red-200 text-red-700"
          }`}>
            {validation.valid ? (
              <div>
                <span className="font-medium">{fillPlaceholders(t(validation.servers.length === 1 ? "settings.mcp.foundOne" : "settings.mcp.foundMany"), { n: String(validation.servers.length) })}</span>
                <ul className="mt-1 ml-4 list-disc text-xs">
                  {validation.servers.map((s) => <li key={s} className="font-mono">{s}</li>)}
                </ul>
              </div>
            ) : (
              <span>{validation.error ? fillPlaceholders(t("settings.mcp.err." + validation.error), { names: validation.names ?? "" }) : validation.detail}</span>
            )}
          </div>
        )}

        {/* Import success feedback */}
        {importResult?.success && (
          <div className="mt-3 p-3 rounded-lg border bg-green-50 border-green-200 text-sm text-green-700">
            {fillPlaceholders(t("settings.mcp.imported"), { n: String(importResult.servers.length) })}
          </div>
        )}

        {/* Actions */}
        <div className="flex justify-end gap-2 mt-4">
          <button onClick={onClose} className="px-4 py-2 text-sm text-foreground border border-border rounded-lg hover:bg-secondary">{t("common.cancel")}</button>
          <button
            onClick={handleImport}
            disabled={!validation?.valid || importing || !!importResult?.success}
            className="px-4 py-2 text-sm text-white bg-primary-600 rounded-lg hover:bg-primary-500 disabled:opacity-50"
          >{importing ? t("settings.mcp.importing") : t("settings.importMcp")}</button>
        </div>
      </div>
    </div>
  );
}

/* ── Exclude Patterns Card ──────────────────────────────────────── */

function ExcludePatternsCard() {
  const { t } = useLocale();
  const patternsQ = useExcludePatterns();
  const updateMut = useUpdateExcludePatterns();
  const [newPattern, setNewPattern] = useState("");
  const [localPatterns, setLocalPatterns] = useState<string[] | null>(null);
  const [dirty, setDirty] = useState(false);

  const patterns = localPatterns ?? patternsQ.data?.patterns ?? [];

  function handleAdd() {
    const trimmed = newPattern.trim();
    if (!trimmed || patterns.includes(trimmed)) return;
    const updated = [...patterns, trimmed];
    setLocalPatterns(updated);
    setNewPattern("");
    setDirty(true);
  }

  function handleRemove(idx: number) {
    const updated = patterns.filter((_, i) => i !== idx);
    setLocalPatterns(updated);
    setDirty(true);
  }

  function handleSave() {
    updateMut.mutate(patterns, {
      onSuccess: () => {
        setDirty(false);
        setLocalPatterns(null);
      },
    });
  }

  return (
    <Card>
      <CardHeader>
        <div>
          <h3 className="text-lg font-semibold text-foreground">{t("settings.excludePatterns")}</h3>
          <span className="text-xs text-muted-foreground">{t("settings.excludePatternsDesc")}</span>
        </div>
      </CardHeader>
      <CardBody>
        {patternsQ.isLoading ? (
          <Spinner />
        ) : patternsQ.error ? (
          <ErrorBanner message={(patternsQ.error as Error).message} onRetry={() => patternsQ.refetch()} />
        ) : (
          <>
            <div className="space-y-2 mb-4">
              {patterns.length === 0 ? (
                <p className="text-sm text-muted-foreground">{t("settings.excludePatterns.none")}</p>
              ) : (
                patterns.map((p, i) => (
                  <div key={i} className="flex items-center justify-between p-2 rounded-lg border border-border bg-background">
                    <span className="text-sm font-mono text-foreground">{p}</span>
                    <button
                      onClick={() => handleRemove(i)}
                      className="text-xs text-red-600 hover:underline"
                    >
                      Remove
                    </button>
                  </div>
                ))
              )}
            </div>
            <div className="flex items-center gap-2">
              <input
                type="text"
                value={newPattern}
                onChange={(e) => setNewPattern(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") handleAdd(); }}
                placeholder={t("settings.excludePatterns.ph")}
                className="flex-1 px-3 py-2 border border-border rounded-lg text-sm font-mono focus:outline-none focus:ring-2 focus:ring-primary-500"
              />
              <button
                onClick={handleAdd}
                disabled={!newPattern.trim()}
                className="px-4 py-2 text-sm text-white bg-primary-600 rounded-lg hover:bg-primary-500 disabled:opacity-50"
              >
                Add
              </button>
            </div>
            {dirty && (
              <div className="flex justify-end mt-3">
                <button
                  onClick={handleSave}
                  disabled={updateMut.isPending}
                  className="px-4 py-2 text-sm text-white bg-primary-600 rounded-lg hover:bg-primary-500 disabled:opacity-50"
                >
                  {updateMut.isPending ? t("common.saving") : t("common.save")}
                </button>
              </div>
            )}
          </>
        )}
      </CardBody>
    </Card>
  );
}

/* ── Agent Models Card ──────────────────────────────────────────── */

// MODEL_PRESETS loaded from GET /api/settings → s.model_presets (single source: config.py)
// Shown only when the API returns no presets — the current generation, matching config/settings.yaml's bare aliases
const MODEL_PRESETS_FALLBACK = [
  { label: "Opus 5.5", value: "global.anthropic.claude-opus-5-5" },
  { label: "Sonnet 5.5", value: "global.anthropic.claude-sonnet-5-5" },
  { label: "Haiku 4.5", value: "global.anthropic.claude-haiku-4-5-20251001-v1:0" },
];

const AGENT_LABELS: Record<string, { label: string; tier: string }> = {
  main:     { label: "Main (Router)",  tier: "default" },
  scan:     { label: "Scan",           tier: "cheap" },
  detect:   { label: "Detect",         tier: "cheap" },
  rca:      { label: "RCA",            tier: "strong" },
  sre:      { label: "SRE",            tier: "strong" },
  executor: { label: "Executor",       tier: "default" },
  reporter: { label: "Reporter",       tier: "cheap" },
};

const TIER_COLORS: Record<string, string> = {
  default: "bg-blue-100 text-blue-700",
  cheap:   "bg-green-100 text-green-700",
  strong:  "bg-purple-100 text-purple-700",
};

function AgentModelsCard() {
  const { t } = useLocale();
  const boot = useBootstrap();
  const settingsQ = useSettings();
  const updateMut = useUpdateSettings();
  const s = settingsQ.data;

  function handleModelChange(agentName: string, modelId: string) {
    updateMut.mutate({ agent_models: { [agentName]: { model_id: modelId } } });
  }

  function handleMaxTokensChange(agentName: string, maxTokens: number) {
    updateMut.mutate({ agent_models: { [agentName]: { max_tokens: maxTokens } } });
  }

  function handleWindowSizeChange(agentName: string, windowSize: number) {
    updateMut.mutate({ agent_models: { [agentName]: { window_size: windowSize } } });
  }

  function handleReset(agentName: string) {
    updateMut.mutate({ agent_models: { [agentName]: { model_id: "", max_tokens: 0, window_size: 0 } } });
  }

  if (settingsQ.isLoading) return <Card><CardBody><Spinner /></CardBody></Card>;
  if (settingsQ.error) return <Card><CardBody><ErrorBanner message={settingsQ.error.message} onRetry={() => settingsQ.refetch()} /></CardBody></Card>;
  if (!s) return null;

  const agents = s.agent_models ?? {};
  const presets = modelListOrFallback(s.model_presets, MODEL_PRESETS_FALLBACK);   // N35: an empty list is believed
  const canChange = canChangeModels(boot.data);   // an administrator's with sign-in on (N35)

  return (
    <Card>
      <CardHeader>
        <h3 className="text-lg font-semibold text-foreground">{t("settings.agentModels.title")}</h3>
        <span className="text-xs text-muted-foreground">{t("settings.agentModels.subtitle")}</span>
      </CardHeader>
      <CardBody>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-xs text-muted-foreground uppercase">
                <th className="pb-2 pr-4">{t("settings.agentModels.agent")}</th>
                <th className="pb-2 pr-4">{t("settings.agentModels.tier")}</th>
                <th className="pb-2 pr-4">{t("settings.agentModels.model")}</th>
                <th className="pb-2 pr-4">{t("settings.agentModels.maxTokens")}</th>
                <th className="pb-2 pr-4">{t("settings.agentModels.window")}</th>
                <th className="pb-2"></th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(agents).map(([name, cfg]: [string, AgentModelConfig]) => {
                const meta = AGENT_LABELS[name] ?? { label: name, tier: "default" };
                // availability is read from the list of available models — no model is called (MVP-2.9.0 N25)
                const availability = modelAvailability(cfg.model_id, s.model_presets);
                return (
                  <tr key={name} className="border-b border-border align-top">
                    <td className="py-2.5 pr-4 font-medium text-foreground">{meta.label}</td>
                    <td className="py-2.5 pr-4">
                      <Badge className={TIER_COLORS[meta.tier] ?? "bg-secondary text-muted-foreground"}>
                        {meta.tier}
                      </Badge>
                    </td>
                    <td className="py-2.5 pr-4">
                      {/* MVP-2.9.0 N35: the one model picker — grouped by provider, with what each model can do; it
                          says under itself when the model is not available, calls no tools, or is not on the list */}
                      <ModelPicker value={cfg.model_id} presets={presets} onChange={(v) => handleModelChange(name, v)}
                                   ariaLabel={meta.label} setting={`agent_${name}_model_id`} modelIssues={s.model_issues}
                                   requireTools disabled={updateMut.isPending || !canChange} />
                      {availability === "listed" && (
                        <StatusText tone="ok" className="whitespace-normal text-[11px]">{t("settings.models.availability.listed")}</StatusText>
                      )}
                    </td>
                    <td className="py-2.5 pr-4">
                      <input
                        type="number"
                        value={cfg.max_tokens}
                        onChange={(e) => handleMaxTokensChange(name, parseInt(e.target.value) || 0)}
                        disabled={updateMut.isPending || !canChange}
                        className="w-24 px-2 py-1 border border-border rounded text-xs font-mono focus:outline-none focus:ring-2 focus:ring-primary-500 disabled:opacity-50"
                      />
                    </td>
                    <td className="py-2.5 pr-4">
                      <div className="flex items-center gap-2">
                        <select
                          value={cfg.window_size === -1 ? "-1" : cfg.window_size === 0 ? "0" : "custom"}
                          onChange={(e) => {
                            const v = e.target.value;
                            if (v === "-1" || v === "0") handleWindowSizeChange(name, parseInt(v));
                            else if (v === "custom") handleWindowSizeChange(name, 20);
                          }}
                          disabled={updateMut.isPending || !canChange}
                          className="px-2 py-1 border border-border rounded text-xs focus:outline-none focus:ring-2 focus:ring-primary-500 disabled:opacity-50"
                        >
                          <option value="0">{t("settings.agentModels.auto")}</option>
                          <option value="-1">{t("settings.agentModels.full")}</option>
                          <option value="custom">{t("settings.agentModels.custom")}</option>
                        </select>
                        {cfg.window_size > 0 && (
                          <input
                            type="number"
                            value={cfg.window_size}
                            onChange={(e) => handleWindowSizeChange(name, Math.max(1, parseInt(e.target.value) || 1))}
                            disabled={updateMut.isPending || !canChange}
                            className="w-20 px-2 py-1 border border-border rounded text-xs font-mono focus:outline-none focus:ring-2 focus:ring-primary-500 disabled:opacity-50"
                          />
                        )}
                        <Badge className={cfg.window_mode === "full" ? "bg-green-100 text-green-700" : "bg-amber-100 text-amber-700"}>
                          {cfg.window_mode === "full" ? t("settings.agentModels.modeFull") : t("settings.agentModels.modeSliding")}
                        </Badge>
                      </div>
                    </td>
                    <td className="py-2.5">
                      <button
                        onClick={() => handleReset(name)}
                        disabled={updateMut.isPending || !canChange}
                        className="text-xs text-muted-foreground hover:text-red-600 disabled:opacity-50"
                        title={t("settings.agentModels.resetHint")}
                      >{t("settings.agentModels.reset")}</button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <p className="mt-3 text-xs text-muted-foreground">{t("settings.models.availabilityNote")}</p>
      </CardBody>
    </Card>
  );
}

/* ── Galaxy Build Model Card ────────────────────────────────────── */

function GalaxyModelCard() {
  const { t } = useLocale();
  const boot = useBootstrap();
  const settingsQ = useSettings();
  const updateMut = useUpdateSettings();
  const s = settingsQ.data;

  if (settingsQ.isLoading) return <Card><CardBody><Spinner /></CardBody></Card>;
  if (settingsQ.error) return <Card><CardBody><ErrorBanner message={settingsQ.error.message} onRetry={() => settingsQ.refetch()} /></CardBody></Card>;
  if (!s) return null;

  const presets = modelListOrFallback(s.model_presets, MODEL_PRESETS_FALLBACK);   // N35: an empty list is believed
  const current = s.galaxy_model_id ?? "";

  return (
    <Card>
      <CardHeader>
        <h3 className="text-lg font-semibold text-foreground">{t("settings.galaxyModel.title")}</h3>
        <span className="text-xs text-muted-foreground">{t("settings.galaxyModel.subtitle")}</span>
      </CardHeader>
      <CardBody>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="max-w-md">
            <p className="text-sm text-foreground">{t("settings.galaxyModel.id")}</p>
            <p className="text-xs text-muted-foreground mt-0.5">{t("settings.galaxyModel.note")}</p>
          </div>
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <ModelPicker value={current} presets={presets} onChange={(v) => updateMut.mutate({ galaxy_model_id: v })}
                         ariaLabel={t("settings.galaxyModel.title")} setting="galaxy_model_id" modelIssues={s.model_issues}
                         emptyOption={{ label: t("settings.galaxyModel.default") }}
                         disabled={updateMut.isPending || !canChangeModels(boot.data)} />
            <Badge className="bg-violet-100 text-violet-700">{t("settings.galaxyModel.experimental")}</Badge>
          </div>
        </div>
      </CardBody>
    </Card>
  );
}

/* ── IM Connections (read-only) ─────────────────────────────────── */

function IMConnectionsCard({ feishuActive, slackActive }: { feishuActive: boolean; slackActive: boolean }) {
  const { t } = useLocale();
  return (
    <Card>
      <CardHeader>
        <h3 className="text-lg font-semibold text-foreground">{t("settings.im.title")}</h3>
        <span className="text-xs text-muted-foreground">{t("settings.im.subtitle")}</span>
      </CardHeader>
      <CardBody>
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium text-foreground">{t("settings.im.feishu")}</span>
            </div>
            <Badge className={feishuActive ? "bg-green-100 text-green-700" : "bg-secondary text-muted-foreground"}>
              {feishuActive ? t("settings.im.active") : t("settings.im.inactive")}
            </Badge>
          </div>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium text-foreground">{t("settings.im.slack")}</span>
            </div>
            <Badge className={slackActive ? "bg-green-100 text-green-700" : "bg-secondary text-muted-foreground"}>
              {slackActive ? t("settings.im.active") : t("settings.im.inactive")}
            </Badge>
          </div>
        </div>
        <p className="text-xs text-muted-foreground mt-3">
          {t("settings.im.note")}
        </p>
      </CardBody>
    </Card>
  );
}

/* ── Report Storage ────────────────────────────────────────────── */

function ReportStorageCard({
  settings: s,
  onSave,
  saving,
}: {
  settings: import("@/hooks/useSettings").AppSettings;
  onSave: (patch: Record<string, unknown>) => void;
  saving: boolean;
}) {
  const { t } = useLocale();
  const [storage, setStorage] = useState(s.report_storage);
  const [bucket, setBucket] = useState(s.report_s3_bucket);
  const [prefix, setPrefix] = useState(s.report_s3_prefix);
  const [region, setRegion] = useState(s.report_s3_region);
  const [expiry, setExpiry] = useState(s.report_presigned_url_expiry);

  const dirty =
    storage !== s.report_storage ||
    bucket !== s.report_s3_bucket ||
    prefix !== s.report_s3_prefix ||
    region !== s.report_s3_region ||
    expiry !== s.report_presigned_url_expiry;

  const handleSave = () => {
    onSave({
      report_storage: storage,
      report_s3_bucket: bucket,
      report_s3_prefix: prefix,
      report_s3_region: region,
      report_presigned_url_expiry: expiry,
    });
  };

  const inputClass = "w-full px-3 py-2 border border-border rounded-lg text-sm bg-background text-foreground focus:outline-none focus:ring-2 focus:ring-primary-500";

  return (
    <Card>
      <CardHeader>
        <h3 className="text-lg font-semibold text-foreground">{t("settings.reportStore.title")}</h3>
        <span className="text-xs text-muted-foreground">{t("settings.reportStore.subtitle")}</span>
      </CardHeader>
      <CardBody>
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-foreground mb-1">{t("settings.reportStore.backend")}</label>
            <select value={storage} onChange={(e) => setStorage(e.target.value)} className={inputClass}>
              <option value="local">{t("settings.reportStore.local")}</option>
              <option value="s3">Amazon S3</option>
            </select>
          </div>

          {storage === "s3" && (
            <>
              <div>
                <label className="block text-sm font-medium text-foreground mb-1">{t("settings.reportStore.bucket")}</label>
                <input value={bucket} onChange={(e) => setBucket(e.target.value)} placeholder="my-reports-bucket" className={inputClass} />
              </div>
              <div>
                <label className="block text-sm font-medium text-foreground mb-1">{t("settings.reportStore.prefix")}</label>
                <input value={prefix} onChange={(e) => setPrefix(e.target.value)} placeholder="reports/" className={inputClass} />
              </div>
              <div>
                <label className="block text-sm font-medium text-foreground mb-1">{t("settings.reportStore.region")}</label>
                <input value={region} onChange={(e) => setRegion(e.target.value)} placeholder="us-east-1" className={inputClass} />
              </div>
              <div>
                <label className="block text-sm font-medium text-foreground mb-1">{t("settings.reportStore.expiry")}</label>
                <input type="number" value={expiry} onChange={(e) => setExpiry(Number(e.target.value))} min={60} className={inputClass} />
                <p className="text-xs text-muted-foreground mt-1">{t("settings.reportStore.expiryNote")}</p>
              </div>
            </>
          )}

          <button
            onClick={handleSave}
            disabled={!dirty || saving}
            className="px-4 py-2 text-sm font-medium text-white bg-primary-600 rounded-lg hover:bg-primary-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {saving ? t("common.saving") : t("common.save")}
          </button>
        </div>
      </CardBody>
    </Card>
  );
}

/* ── Main Settings page ─────────────────────────────────────────── */

export default function Settings() {
  const readOnly = useReadOnly();  // a viewer allowed to view Settings: everything shown, nothing changeable
  const { selected: focusSelected, toggle: toggleFocus, focusValue, ALL_CATEGORIES } = useScanFocus();
  const settingsQ = useSettings();
  const updateMut = useUpdateSettings();

  // Accounts
  const [filterProvider, setFilterProvider] = useState<string>("");
  const { data: accounts, isLoading: acctLoading, error: acctError } = useAccounts(filterProvider || undefined);
  const createMut = useCreateAccount();
  const updateAcctMut = useUpdateAccount();
  const deleteMut = useDeleteAccount();
  const testConnMut = useTestConnection();
  const [testingId, setTestingId] = useState<number | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<Account | null>(null);
  const [deleting, setDeleting] = useState<Account | null>(null);
  const [acctFormError, setAcctFormError] = useState<string | null>(null);

  // MCP Servers
  const mcpQ = useMcpServers();
  const upsertMcp = useUpsertMcpServer();
  const deleteMcp = useDeleteMcpServer();
  const reloadMcp = useReloadMcpServers();
  const importMcp = useImportMcpServers();
  const [mcpFormOpen, setMcpFormOpen] = useState(false);
  const [mcpEditing, setMcpEditing] = useState<{ name: string; config: McpServerConfig } | null>(null);
  const [mcpDeleting, setMcpDeleting] = useState<string | null>(null);
  useCloseOnEscape(() => setMcpDeleting(null), mcpDeleting !== null);   // its confirmation is drawn by this page
  const [mcpImportOpen, setMcpImportOpen] = useState(false);

  // Agent Memory
  const [memAgent, setMemAgent] = useState("");
  const [memStatus, setMemStatus] = useState("active");
  const memQ = useAgentMemories(memAgent, memStatus);
  const updateMemMut = useUpdateAgentMemory();
  const deleteMemMut = useDeleteAgentMemory();
  const [memEditing, setMemEditing] = useState<AgentMemory | null>(null);
  const [memEditConf, setMemEditConf] = useState(3);

  const s = settingsQ.data;

  function patchSetting(key: string, value: boolean) {
    updateMut.mutate({ [key]: value });
  }

  const { t } = useLocale();
  // the open tab is in the address (`?tab=accounts`): the setup overview links to the tab an item is changed on
  const [params, setParams] = useSearchParams();
  // the audit log is an administrator's when sign-in is on (/api/audit refuses anyone else): not offered otherwise
  const auditOn = auditTabVisible(useBootstrap().data);
  const tab = shownTab(settingsTab(params.get("tab")), auditOn);
  const location = useLocation();
  const navigate = useNavigate();
  const goToSection = (id: SectionId) => {
    document.getElementById(sectionAnchor(id))?.scrollIntoView({ block: "start" });
    navigate({ search: location.search, hash: `#${sectionAnchor(id)}` }, { replace: true });
  };
  // An address that names a section opens on it. The cards above it load one by one and push it down, so it is
  // put back at the top each time the tab grows — until the page has settled (4 s) or the person takes over.
  useEffect(() => {
    const id = sectionOfHash(location.hash);
    const head = id && tab === "general" ? document.getElementById(sectionAnchor(id)) : null;
    if (!head) return;
    const align = () => head.scrollIntoView({ block: "start" });
    align();
    const panel = head.closest('[role="tabpanel"]');
    const observer = panel && typeof ResizeObserver !== "undefined" ? new ResizeObserver(align) : null;
    if (panel && observer) observer.observe(panel);
    const takeover = ["wheel", "touchmove", "keydown", "pointerdown"] as const;
    const stop = () => observer?.disconnect();
    const timer = window.setTimeout(stop, 4000);
    takeover.forEach((name) => window.addEventListener(name, stop, { once: true, passive: true }));
    return () => { stop(); window.clearTimeout(timer); takeover.forEach((name) => window.removeEventListener(name, stop)); };
  }, [location.hash, tab]);
  const openTab = (value: string) => {
    const next = new URLSearchParams(params);
    if (value === "general") next.delete("tab"); else next.set("tab", value);
    setParams(next, { replace: true });
  };
  const tabTriggerClass = "shrink-0 whitespace-nowrap px-4 py-2 text-sm font-medium border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:text-primary text-muted-foreground hover:text-foreground transition-colors";

  return (
    <div className="max-w-5xl">
      <div className="mb-4 flex flex-wrap items-baseline justify-between gap-3">
        <h1 className="text-2xl font-semibold text-foreground">{t("settings.title")}</h1>
        <Link to="/app/setup" className="text-sm font-medium text-primary hover:underline">{t("setup.entry")}</Link>
      </div>
      {readOnly && (
        <p role="status" className="mb-4 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-800 dark:border-amber-700 dark:bg-amber-950/40 dark:text-amber-300">
          {t("settings.readOnlyNotice")}
        </p>
      )}

      <Tabs.Root value={tab} onValueChange={openTab}>
        <Tabs.List className="flex border-b border-border mb-6 gap-0 overflow-x-auto">
          <Tabs.Trigger value="general" className={tabTriggerClass}>{t("settings.general")}</Tabs.Trigger>
          <Tabs.Trigger value="accounts" className={tabTriggerClass}>{t("settings.accounts")}</Tabs.Trigger>
          <Tabs.Trigger value="providers" className={tabTriggerClass}>{t("settings.providers")}</Tabs.Trigger>
          <Tabs.Trigger value="messaging" className={tabTriggerClass}>{t("settings.messaging")}</Tabs.Trigger>
          {auditOn && <Tabs.Trigger value="audit" className={tabTriggerClass}>{t("settings.audit")}</Tabs.Trigger>}
          <Tabs.Trigger value="kb" className={tabTriggerClass}>{t("settings.kb")}</Tabs.Trigger>
          <Tabs.Trigger value="skills" className={tabTriggerClass}>{t("settings.skills")}</Tabs.Trigger>
          <Tabs.Trigger value="mcp" className={tabTriggerClass}>{t("settings.mcp")}</Tabs.Trigger>
          <Tabs.Trigger value="memory" className={tabTriggerClass}>{t("settings.memory")}</Tabs.Trigger>
        </Tabs.List>

        {/* ── General Tab ──────────────────────────────────────── */}
        <Tabs.Content value="general" className="space-y-6">
          {/* MVP-2.9.0 N25 (the 2.8.0 spec's S8): three sections with anchors, each saying what it applies to */}
          <div className="flex flex-wrap items-center justify-between gap-3">
            <nav aria-label={t("settings.section.nav")} className="flex flex-wrap gap-1 rounded-lg bg-secondary p-1">
              {SECTIONS.map((id) => (
                <a key={id} href={`#${sectionAnchor(id)}`} onClick={(e) => { e.preventDefault(); goToSection(id); }}
                   className="inline-flex items-center rounded-md px-3 py-1 text-sm text-muted-foreground hover:bg-background hover:text-foreground max-[767px]:min-h-[44px]">
                  {t(`settings.section.${id}`)}
                </a>
              ))}
            </nav>
            {auditOn && <Link to="/app/settings?tab=audit&entity=system&hours=720" className="text-sm font-medium text-primary hover:underline">{t("settings.auditLink")}</Link>}
          </div>
          <fieldset disabled={readOnly} className="m-0 min-w-0 space-y-6 border-0 p-0">
      {updateMut.error && <ErrorBanner message={updateMut.error.message} onRetry={() => updateMut.reset()} actionLabel={t("common.close")} />}

      {/* ── 1 · Basics ───────────────────────────────────────── */}
      <SectionHead id="basics" t={t} />
      <Card>
        <CardHeader>
          <h3 className="text-lg font-semibold text-foreground">{t("settings.scanFocus")}</h3>
          <span className="text-xs text-muted-foreground">
            {focusValue === "all" ? t("settings.scanFocus.all") : focusValue.split(",").map((cat) => t(`settings.focus.${cat}`)).join(", ")}
          </span>
        </CardHeader>
        <CardBody>
          <p className="text-sm text-muted-foreground mb-4">{t("settings.scanFocusDesc")} {t("settings.scanFocus.applies")}</p>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
            <FocusToggle
              label={t("settings.scanFocus.allLabel")}
              description={t("settings.scanFocus.all")}
              icon={<IconAll />}
              active={focusSelected.has("all")}
              onClick={() => toggleFocus("all")}
            />
            {ALL_CATEGORIES.map((cat) => (
              <FocusToggle
                key={cat}
                label={t(`settings.focus.${cat}`)}
                description={FOCUS_META[cat].services}
                icon={FOCUS_META[cat].icon}
                active={focusSelected.has("all") || focusSelected.has(cat)}
                onClick={() => toggleFocus(cat)}
              />
            ))}
          </div>
        </CardBody>
      </Card>

      <ExcludePatternsCard />

      {/* low-impact switches: saved at a click, each audited */}
      <Card>
        <CardHeader>
          <h3 className="text-lg font-semibold text-foreground">{t("settings.low.title")}</h3>
        </CardHeader>
        <CardBody>
          <Loaded q={settingsQ} t={t}>
            {(s) => (
              <div>
                <SettingToggle label={t("settings.notificationsEnabled")} description={t("settings.notificationsDesc")}
                               enabled={s.notifications_enabled} onChange={(v) => patchSetting("notifications_enabled", v)} saving={updateMut.isPending} />
                <SettingToggle label={t("settings.consolidated")} description={t("settings.consolidatedDesc")}
                               enabled={s.notifications_consolidated} onChange={(v) => patchSetting("notifications_consolidated", v)} saving={updateMut.isPending} />
                <SettingToggle label={t("settings.promptCache")} description={t("settings.promptCacheDesc")}
                               enabled={s.bedrock_cache_enabled} onChange={(v) => patchSetting("bedrock_cache_enabled", v)} saving={updateMut.isPending} />
                <SettingToggle label={t("settings.skillAutoImprove")} description={t("settings.skillAutoImproveDesc")}
                               enabled={s.skills_auto_improve_enabled} onChange={(v) => patchSetting("skills_auto_improve_enabled", v)} saving={updateMut.isPending} />
                <SettingToggle label={t("settings.skillReview")} description={t("settings.skillReviewDesc")}
                               enabled={s.skills_post_resolution_review} onChange={(v) => patchSetting("skills_post_resolution_review", v)} saving={updateMut.isPending} />
                <SettingToggle label={t("settings.skillNotify")} description={t("settings.skillNotifyDesc")}
                               enabled={s.skills_improvement_notify} onChange={(v) => patchSetting("skills_improvement_notify", v)} saving={updateMut.isPending} />
              </div>
            )}
          </Loaded>
        </CardBody>
      </Card>

      {/* ── Enhanced Backend (ACP) ───────────────────────────── */}
      {s && (
        <Card>
          <CardHeader>
            <h3 className="text-lg font-semibold text-foreground">{t("settings.acp.title")}</h3>
            <span className="text-xs text-muted-foreground">{t("settings.acp.subtitle")}</span>
          </CardHeader>
          <CardBody>
            <SettingToggle
              label={t("settings.acp.toggle")}
              description={t("settings.acp.toggleDesc")}
              enabled={s.acp_enhanced_enabled}
              onChange={(v) => updateMut.mutate({ acp_enhanced_enabled: v })}
              saving={updateMut.isPending}
            />
            <div className="pt-4">
              <label htmlFor="acp-backend" className="block text-sm font-medium text-foreground mb-1">{t("settings.acp.provider")}</label>
              <select
                id="acp-backend"
                value={s.acp_enhanced_backend}
                disabled={!s.acp_enhanced_enabled || updateMut.isPending}
                onChange={(e) => updateMut.mutate({ acp_enhanced_backend: e.target.value })}
                className="w-full px-3 py-2 border border-border rounded-lg text-[16px] sm:text-sm bg-background text-foreground focus:outline-none focus:ring-2 focus:ring-primary-500 disabled:opacity-50"
              >
                {s.acp_available_backends.map((b) => (
                  <option key={b} value={b}>{b}</option>
                ))}
              </select>
              <p className="text-xs text-muted-foreground mt-2">{t("settings.acp.note")}</p>
              {s.acp_enhanced_blocked === "bedrock_off" && (
                <p role="status" className="text-xs text-amber-700 dark:text-amber-300 mt-2">{t("settings.acp.blockedBedrockOff")}</p>
              )}
            </div>
          </CardBody>
        </Card>
      )}

      {/* ── Chat attachments (2026-11-07) ────────────────────── */}
      <ChatUploadCard />

      {/* ── Pull connectors (k8s discovery) ──────────────────── */}
      <ConnectorsCard />

      {/* ── IM Connections (read-only status) ────────────────── */}
      {s && <IMConnectionsCard feishuActive={s.feishu_ws_active} slackActive={s.slack_ws_active} />}

      {/* ── Report Storage ───────────────────────────────────── */}
      {s && <ReportStorageCard settings={s} onSave={(patch) => updateMut.mutate(patch)} saving={updateMut.isPending} />}

      {/* ── 2 · Automation and execution ─────────────────────── */}
      <SectionHead id="automation" t={t} />
      <Card>
        <CardHeader>
          <h3 className="text-lg font-semibold text-foreground">{t("settings.autoRca.title")}</h3>
        </CardHeader>
        <CardBody>
          <Loaded q={settingsQ} t={t}>
            {(s) => (
              <SettingToggle label={t("settings.autoRca")} description={t("settings.autoRcaDesc")}
                             enabled={s.auto_rca_enabled} onChange={(v) => patchSetting("auto_rca_enabled", v)} saving={updateMut.isPending} />
            )}
          </Loaded>
        </CardBody>
      </Card>
      {/* the six high-impact switches: staged, previewed, then saved — never by one click */}
      {s && <AutomationCard s={s} />}

      {/* ── 3 · Models ───────────────────────────────────────── */}
      <SectionHead id="models" t={t} />
      <ModelFactsCard />
      <AgentModelsCard />
      <OtherModelsCard />
      <GalaxyModelCard />
      <ModelRuntimeCard />
          </fieldset>
        </Tabs.Content>

        {/* ── Accounts Tab ─────────────────────────────────────── */}
        <Tabs.Content value="accounts" className="space-y-6">
          <fieldset disabled={readOnly} className="m-0 min-w-0 space-y-6 border-0 p-0">
      <Card>
        <CardHeader>
          <h2 className="text-lg font-semibold text-foreground">{t("settings.account.title")}</h2>
          <div className="flex items-center gap-3">
            <select
              value={filterProvider}
              onChange={(e) => setFilterProvider(e.target.value)}
              className="px-3 py-2 text-sm border border-border rounded-lg bg-background text-foreground"
            >
              <option value="">{t("settings.account.allProviders")}</option>
              {PROVIDER_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
            <button
              onClick={() => { setEditing(null); setFormOpen(true); }}
              className="px-4 py-2 text-sm text-white bg-primary-600 rounded-lg hover:bg-primary-500"
            >
              {t("settings.account.new")}
            </button>
          </div>
        </CardHeader>
        {acctLoading ? (
          <div className="p-6"><Spinner /></div>
        ) : acctError ? (
          <div className="p-6"><ErrorBanner message={(acctError as Error).message} /></div>
        ) : (
          <DataTable
            columns={[
              ...accountColumns(t),
              {
                key: "actions",
                header: "",
                render: (r) => (
                  <div className="flex gap-2 items-center">
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        setTestingId(r.id);
                        testConnMut.mutate(r.id, {
                          onSettled: () => setTimeout(() => setTestingId(null), 3000),
                        });
                      }}
                      disabled={testingId === r.id}
                      className="text-xs text-green-600 hover:underline disabled:opacity-50"
                    >
                      {testingId === r.id
                        ? testConnMut.isPending ? t("settings.account.testing") : testConnMut.isSuccess && testConnMut.data?.success ? t("settings.account.testOk") : t("settings.account.testFailed")
                        : t("settings.account.test")}
                    </button>
                    <button onClick={(e) => { e.stopPropagation(); setEditing(r); setFormOpen(true); }} className="text-xs text-primary-600 hover:underline">{t("common.edit")}</button>
                    <button onClick={(e) => { e.stopPropagation(); setDeleting(r); }} className="text-xs text-red-600 hover:underline">{t("common.delete")}</button>
                  </div>
                ),
              },
            ]}
            data={accounts ?? []}
            rowKey={(r) => r.id}
            emptyMessage={t("settings.account.none")}
          />
        )}
      </Card>

          </fieldset>
        </Tabs.Content>

        {/* ── Model providers Tab (MVP-2.9.0 N35) ─────────────── */}
        <Tabs.Content value="providers">
          <ModelProvidersTab />
        </Tabs.Content>

        {/* ── Messaging Tab ────────────────────────────────────── */}
        <Tabs.Content value="messaging" className="space-y-6">
          <fieldset disabled={readOnly} className="m-0 min-w-0 space-y-6 border-0 p-0">
          <MessagingTab />
          </fieldset>
        </Tabs.Content>

        {/* ── Audit Tab ────────────────────────────────────────── */}
        <Tabs.Content value="audit">
          <AuditTab />
        </Tabs.Content>

        {/* ── Knowledge Base Tab ───────────────────────────────── */}
        <Tabs.Content value="kb">
          <KBTab />
        </Tabs.Content>

        {/* ── Skills Tab ───────────────────────────────────────── */}
        <Tabs.Content value="skills">
          <SkillsTab />
        </Tabs.Content>

        {/* ── MCP Servers Tab ──────────────────────────────────── */}
        <Tabs.Content value="mcp" className="space-y-6">
          <fieldset disabled={readOnly} className="m-0 min-w-0 space-y-6 border-0 p-0">
      <Card>
        <CardHeader>
          <h2 className="text-lg font-semibold text-foreground">{t("settings.mcp")}</h2>
          <div className="flex gap-2">
            <button
              onClick={() => setMcpImportOpen(true)}
              className="px-3 py-1.5 text-sm text-foreground border border-border rounded-lg hover:bg-secondary"
            >
              {t("settings.mcp.importJson")}
            </button>
            <button
              onClick={() => reloadMcp.mutate()}
              disabled={reloadMcp.isPending}
              className="px-3 py-1.5 text-sm text-foreground border border-border rounded-lg hover:bg-secondary disabled:opacity-50"
            >
              {reloadMcp.isPending ? t("settings.mcp.reloading") : t("settings.reloadMcp")}
            </button>
            <button
              onClick={() => { setMcpEditing(null); setMcpFormOpen(true); }}
              className="px-4 py-2 text-sm text-white bg-primary-600 rounded-lg hover:bg-primary-500"
            >
              {t("settings.addMcp")}
            </button>
          </div>
        </CardHeader>
        <CardBody>
          {mcpQ.isLoading ? (
            <Spinner />
          ) : mcpQ.error ? (
            <ErrorBanner message={(mcpQ.error as Error).message} onRetry={() => mcpQ.refetch()} />
          ) : (
            <div className="space-y-2">
              {Object.keys(mcpQ.data ?? {}).length === 0 ? (
                <p className="text-sm text-muted-foreground py-4 text-center">{t("settings.mcp.none")}</p>
              ) : (
                Object.entries(mcpQ.data ?? {}).map(([name, cfg]) => (
                  <div key={name} className="flex items-center justify-between p-3 rounded-lg border border-border bg-background">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium text-foreground">{name}</span>
                        {cfg.disabled ? (
                          <Badge className="bg-secondary text-muted-foreground">{t("common.disabled")}</Badge>
                        ) : (
                          <Badge className="bg-green-100 text-green-700">{t("common.active")}</Badge>
                        )}
                        <Badge className="bg-blue-50 text-blue-600">
                          {cfg.url ? "SSE" : "stdio"}
                        </Badge>
                      </div>
                      <p className="text-xs text-muted-foreground mt-0.5 font-mono break-all">
                        {cfg.url ?? `${cfg.command ?? ""} ${(cfg.args ?? []).join(" ")}`}
                      </p>
                    </div>
                    <div className="flex gap-2 flex-shrink-0">
                      <button
                        onClick={() => { setMcpEditing({ name, config: cfg }); setMcpFormOpen(true); }}
                        className="text-xs text-primary-600 hover:underline"
                      >{t("common.edit")}</button>
                      <button
                        onClick={() => setMcpDeleting(name)}
                        className="text-xs text-red-600 hover:underline"
                      >{t("common.delete")}</button>
                    </div>
                  </div>
                ))
              )}
            </div>
          )}
        </CardBody>
      </Card>
          </fieldset>
        </Tabs.Content>

        {/* ── Agent Memory Tab ──────────────────────────────────── */}
        <Tabs.Content value="memory" className="space-y-6">
      <Card>
        <CardHeader>
          <h2 className="text-lg font-semibold text-foreground">{t("settings.memory")}</h2>
          <div className="flex items-center gap-2">
            <select
              value={memAgent}
              onChange={(e) => setMemAgent(e.target.value)}
              className="px-3 py-1.5 text-sm border border-border rounded-lg bg-background text-foreground"
            >
              <option value="">{t("settings.memory.allAgents")}</option>
              {["detect", "rca", "sre", "executor", "reporter", "scan", "shared"].map((a) => (
                <option key={a} value={a}>{a}</option>
              ))}
            </select>
            <select
              value={memStatus}
              onChange={(e) => setMemStatus(e.target.value)}
              className="px-3 py-1.5 text-sm border border-border rounded-lg bg-background text-foreground"
            >
              <option value="active">{t("settings.memory.active")}</option>
              <option value="archived">{t("settings.memory.archived")}</option>
              <option value="all">{t("settings.memory.all")}</option>
            </select>
          </div>
        </CardHeader>
        <CardBody>
          {memQ.isLoading ? (
            <Spinner />
          ) : memQ.error ? (
            <ErrorBanner message={(memQ.error as Error).message} onRetry={() => memQ.refetch()} />
          ) : !memQ.data?.length ? (
            <p className="text-sm text-muted-foreground py-4 text-center">{t("settings.memory.none")}</p>
          ) : (
            <div className="space-y-2">
              {memQ.data.map((m) => (
                <div key={`${m.agent}-${m.filename}`} className="flex items-center justify-between p-3 rounded-lg border border-border bg-background">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 flex-wrap">
                      <Badge className="bg-blue-50 text-blue-600 dark:bg-blue-950 dark:text-blue-400">{m.agent}</Badge>
                      <span className="text-sm font-medium text-foreground truncate">{m.filename}</span>
                      {m.status === "archived" && (
                        <Badge className="bg-secondary text-muted-foreground">{t("settings.memory.archived")}</Badge>
                      )}
                    </div>
                    <p className="text-xs text-muted-foreground mt-1 line-clamp-1">{m.summary}</p>
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 mt-1">
                      <span className="text-xs text-muted-foreground">
                        {t("settings.memory.confidence")}<strong>{m.confidence}</strong>/5
                      </span>
                      <span className="text-xs text-muted-foreground">{t("settings.memory.source")}{m.source}</span>
                      {m.resource_pattern && (
                        <span className="min-w-0 break-all text-xs text-muted-foreground font-mono">{m.resource_pattern}</span>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center gap-2 flex-shrink-0 ml-3">
                    {/* Confidence editor */}
                    {memEditing?.filename === m.filename && memEditing?.agent === m.agent ? (
                      <div className="flex items-center gap-1">
                        {[1, 2, 3, 4, 5].map((n) => (
                          <button
                            key={n}
                            onClick={() => setMemEditConf(n)}
                            className={`w-6 h-6 rounded text-xs font-bold ${
                              n <= memEditConf
                                ? "bg-primary text-primary-foreground"
                                : "bg-secondary text-muted-foreground"
                            }`}
                          >
                            {n}
                          </button>
                        ))}
                        <button
                          onClick={() => {
                            updateMemMut.mutate(
                              { agent: m.agent, filename: m.filename, data: { confidence: memEditConf } },
                              { onSuccess: () => setMemEditing(null) },
                            );
                          }}
                          disabled={updateMemMut.isPending}
                          className="text-xs text-primary-600 hover:underline ml-1"
                        >
                          Save
                        </button>
                        <button
                          onClick={() => setMemEditing(null)}
                          className="text-xs text-muted-foreground hover:underline"
                        >
                          Cancel
                        </button>
                      </div>
                    ) : readOnly ? null : (
                      <button
                        onClick={() => { setMemEditing(m); setMemEditConf(m.confidence); }}
                        className="text-xs text-primary-600 hover:underline"
                      >
                        Edit
                      </button>
                    )}
                    {m.status === "active" && !readOnly && (
                      <button
                        onClick={() => deleteMemMut.mutate({ agent: m.agent, filename: m.filename })}
                        disabled={deleteMemMut.isPending}
                        className="text-xs text-red-600 hover:underline"
                      >
                        Archive
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardBody>
      </Card>
        </Tabs.Content>
      </Tabs.Root>

      {/* MCP Modals */}
      {mcpImportOpen && (
        <McpImportDialog
          importing={importMcp.isPending}
          onClose={() => setMcpImportOpen(false)}
          onImport={async (data) => { await importMcp.mutateAsync(data as { mcpServers: Record<string, McpServerConfig> }); }}
        />
      )}
      {mcpFormOpen && (
        <McpServerFormModal
          initial={mcpEditing}
          saving={upsertMcp.isPending}
          onClose={() => { setMcpFormOpen(false); setMcpEditing(null); }}
          onSave={async (name, config) => {
            await upsertMcp.mutateAsync({ name, config });
            setMcpFormOpen(false);
            setMcpEditing(null);
          }}
        />
      )}
      {mcpDeleting && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="bg-background rounded-lg shadow-lg w-full max-w-sm p-6">
            <h3 className="text-lg font-semibold text-foreground mb-2">{t("settings.mcp.delete")}</h3>
            <p className="text-sm text-muted-foreground mb-4">
              {t("settings.mcp.deleteAsk")} <strong>{mcpDeleting}</strong>{t("settings.mcp.deleteEnd")}
            </p>
            <div className="flex justify-end gap-2">
              <button onClick={() => setMcpDeleting(null)} className="px-4 py-2 text-sm text-foreground border border-border rounded-lg hover:bg-secondary">{t("common.cancel")}</button>
              <button
                onClick={async () => { await deleteMcp.mutateAsync(mcpDeleting); setMcpDeleting(null); }}
                disabled={deleteMcp.isPending}
                className="px-4 py-2 text-sm text-white bg-red-600 rounded-lg hover:bg-red-500 disabled:opacity-50"
              >{deleteMcp.isPending ? t("common.deleting") : t("common.delete")}</button>
            </div>
          </div>
        </div>
      )}

      {/* Modals */}
      {formOpen && (
        <AccountFormModal
          initial={editing}
          saving={createMut.isPending || updateAcctMut.isPending}
          error={acctFormError}
          onClose={() => { setFormOpen(false); setEditing(null); setAcctFormError(null); }}
          onSave={async (data) => {
            setAcctFormError(null);
            try {
              if (editing) {
                await updateAcctMut.mutateAsync({ id: editing.id, data: data as AccountUpdate });
              } else {
                await createMut.mutateAsync(data as AccountCreate);
              }
              setFormOpen(false);
              setEditing(null);
            } catch (err) {
              setAcctFormError(err instanceof Error ? err.message : String(err));
            }
          }}
        />
      )}
      {deleting && (
        <DeleteModal
          account={deleting}
          deleting={deleteMut.isPending}
          onClose={() => setDeleting(null)}
          onConfirm={async () => {
            await deleteMut.mutateAsync(deleting.id);
            setDeleting(null);
          }}
        />
      )}
    </div>
  );
}

/* ── SVG Icons (16x16) ────────────────────────────────────────────── */

function IconAll() {
  return (
    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M4 6h16M4 12h16M4 18h16" />
    </svg>
  );
}
function IconCompute() {
  return (
    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
    </svg>
  );
}
function IconNetwork() {
  return (
    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M21 12a9 9 0 01-9 9m9-9a9 9 0 00-9-9m9 9H3m9 9a9 9 0 01-9-9m9 9c1.657 0 3-4.03 3-9s-1.343-9-3-9m0 18c-1.657 0-3-4.03-3-9s1.343-9 3-9" />
    </svg>
  );
}
function IconDatabase() {
  return (
    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4m0 5c0 2.21-3.582 4-8 4s-8-1.79-8-4" />
    </svg>
  );
}
function IconStorage() {
  return (
    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M5 8h14M5 8a2 2 0 110-4h14a2 2 0 110 4M5 8v10a2 2 0 002 2h10a2 2 0 002-2V8m-9 4h4" />
    </svg>
  );
}
function IconSecurity() {
  return (
    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
    </svg>
  );
}
function IconBilling() {
  return (
    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
    </svg>
  );
}

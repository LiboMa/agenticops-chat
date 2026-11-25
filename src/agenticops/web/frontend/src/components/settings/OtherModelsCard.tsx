import { useState } from "react";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { ModelPicker } from "@/components/models/ModelPicker";
import { useLocale } from "@/i18n/LocaleContext";
import { useBootstrap } from "@/hooks/useBootstrap";
import { useSettings, useUpdateSettings } from "@/hooks/useSettings";
import { canChangeModels } from "@/lib/permissions";
import { settingName } from "@/lib/modelRefs";

/** The nine model settings beside the agents' own (`model_settings` of GET /api/settings) and the settings field each
 *  writes — the server's llm/model_settings.SETTINGS. */
export const MODEL_SETTING_FIELDS: Record<string, string> = {
  tier_default: "bedrock_model_id",
  tier_cheap: "bedrock_model_id_cheap",
  tier_strong: "bedrock_model_id_strong",
  executor_simple: "executor_simple_model_id",
  security: "security_model_id",
  report_translation: "report_translation_model_id",
  signal_gate: "signal_gate_llm_model",
  rca_critic: "rca_critic_model_id",
  galaxy: "galaxy_model_id",
};

/** Settings → General → «Other places that use a model» (MVP-2.9.0 N35): the three tiers (what an agent without its
 *  own model runs on), the executor's model for simple plans and the five direct callers — each with the one model
 *  picker, «default» where an empty value has a meaning, and the model in force. An administrator's to change. */
export function OtherModelsCard() {
  const { t } = useLocale();
  const settingsQ = useSettings();
  const updateMut = useUpdateSettings();
  const boot = useBootstrap();
  const [error, setError] = useState<string | null>(null);
  const s = settingsQ.data;
  if (settingsQ.isLoading) return <Card><CardBody><Spinner /></CardBody></Card>;
  if (settingsQ.error) return <Card><CardBody><ErrorBanner message={settingsQ.error.message} onRetry={() => settingsQ.refetch()} /></CardBody></Card>;
  if (!s?.model_settings) return null;
  const editable = canChangeModels(boot.data);
  const views = s.model_settings;
  const presets = s.model_presets ?? [];
  const labelOf = (v: string) => presets.find((p) => p.value === v)?.label ?? v;

  function change(key: string, value: string) {
    setError(null);
    updateMut.mutate({ model_settings: { [key]: value } }, { onError: (e) => setError((e as Error).message) });
  }

  return (
    <Card>
      <CardHeader>
        <h3 className="text-lg font-semibold text-foreground">{t("settings.models.other.title")}</h3>
        <span className="text-xs text-muted-foreground">{t("settings.models.other.subtitle")}</span>
      </CardHeader>
      <CardBody className="space-y-3">
        {!editable && <p className="text-xs text-muted-foreground">{t("settings.providers.adminOnly")}</p>}
        {error && <p role="alert" className="text-sm text-destructive [overflow-wrap:anywhere]">{error}</p>}
        <ul className="divide-y divide-border">
          {Object.entries(MODEL_SETTING_FIELDS).map(([key, field]) => {
            const v = views[key];
            if (!v) return null;
            return (
              <li key={key} className="grid grid-cols-1 gap-2 py-3 md:grid-cols-[minmax(0,1fr)_320px]">
                <div className="min-w-0">
                  <p className="text-sm font-medium text-foreground">{settingName(t, field)}</p>
                  <p className="text-xs text-muted-foreground">{t(`settings.models.other.${key}`)}</p>
                  {!v.value && v.effective && (
                    <p className="mt-0.5 text-xs text-muted-foreground [overflow-wrap:anywhere]">
                      {t("settings.models.inForce").replace("{model}", labelOf(v.effective))}
                    </p>
                  )}
                </div>
                <ModelPicker value={v.value} presets={presets} onChange={(value) => change(key, value)}
                             ariaLabel={settingName(t, field)} setting={field} modelIssues={s.model_issues}
                             requireTools={key === "tier_default" || key === "tier_strong" || key === "tier_cheap" || key === "executor_simple"}
                             disabled={!editable || updateMut.isPending}
                             emptyOption={v.default === null ? undefined
                               : { label: t("settings.models.default"), hint: v.default ? labelOf(v.default) : "" }} />
              </li>
            );
          })}
        </ul>
      </CardBody>
    </Card>
  );
}

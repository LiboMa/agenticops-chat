import { useId, useMemo, useRef, useState, type KeyboardEvent } from "react";
import * as Popover from "@radix-ui/react-popover";
import { useLocale } from "@/i18n/LocaleContext";
import { nextMenuIndex, type MenuKey } from "@/lib/menuNav";
import { badges, groupPresets, issueOf, type ModelIssue, type ModelPreset, type Purpose } from "@/lib/modelRefs";

const MENU_KEYS = new Set<string>(["ArrowDown", "ArrowUp", "Home", "End"]);

/** The one model picker (MVP-2.9.0 N35) — every place a model is chosen: the agents' models, the other model
 *  settings, Galaxy, the knowledge base's vectors. A search box over a list grouped by provider (Bedrock first), each
 *  model with what it can do; the arrow keys, Home / End and Enter work in the box. Under the button it says what is
 *  wrong with the value: not available (the server's reason when it gave one), an agent that would have no tools, or
 *  a Bedrock id that is not on the list. */
export function ModelPicker({ value, presets, onChange, purpose = "chat", emptyOption, requireTools = false, disabled = false,
                              ariaLabel, setting, modelIssues }: {
  value: string;
  presets: ModelPreset[];
  onChange: (value: string) => void;
  purpose?: Purpose;
  /** an entry for "" (the setting's default), with what that default is */
  emptyOption?: { label: string; hint?: string };
  /** the setting is an agent's: a model that calls no tools leaves it without them */
  requireTools?: boolean;
  disabled?: boolean;
  ariaLabel: string;
  /** the settings field this picker writes, to find it among the server's model issues */
  setting?: string;
  modelIssues?: ModelIssue[];
}) {
  const { t } = useLocale();
  const uid = useId();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(-1);
  const listRef = useRef<HTMLDivElement>(null);
  const groups = useMemo(() => groupPresets(presets, { query, purpose }), [presets, query, purpose]);
  const options = useMemo(() => [
    ...(emptyOption && !query.trim() ? [{ value: "", label: emptyOption.label, hint: emptyOption.hint ?? "" }] : []),
    ...groups.flatMap((g) => g.items.map((p) => ({ value: p.value, label: p.label, hint: g.label }))),
  ], [groups, emptyOption, query]);

  const current = presets.find((p) => p.value === value);
  const issue = setting ? issueOf(value, presets, modelIssues, setting) : null;
  const reason = (modelIssues ?? []).find((i) => i.setting === setting && i.value === value)?.reason;
  const unlisted = !!value && !current && issue !== "unavailable";
  const buttonText = !value ? emptyOption?.label ?? "" : current?.label ?? value;

  function pick(v: string) {
    setOpen(false);
    setQuery("");
    if (v !== value) onChange(v);
  }

  function onKey(e: KeyboardEvent<HTMLInputElement>) {
    if (MENU_KEYS.has(e.key)) {
      e.preventDefault();
      const next = nextMenuIndex(active, e.key as MenuKey, options.map(() => false));
      setActive(next);
      listRef.current?.querySelector(`#${CSS.escape(`${uid}-o${next}`)}`)?.scrollIntoView({ block: "nearest" });
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (active >= 0 && options[active]) pick(options[active].value);
    }
  }

  let index = -1;
  const option = (v: string, label: string, sub: string, mono: string | null, extra?: ModelPreset) => {
    index += 1;
    const i = index;
    const selected = v === value;
    return (
      <div key={`${v}-${i}`} id={`${uid}-o${i}`} role="option" aria-selected={selected}
           onMouseDown={(e) => e.preventDefault()} onClick={() => pick(v)} onMouseEnter={() => setActive(i)}
           className={`flex cursor-pointer items-start gap-2 rounded-lg px-2.5 py-1.5 ${i === active ? "bg-muted" : ""}`}>
        <span aria-hidden className={`mt-0.5 w-3.5 shrink-0 text-xs text-primary ${selected ? "" : "invisible"}`}>✓</span>
        <span className="min-w-0 flex-1">
          <span className={`block break-words text-xs text-foreground ${selected ? "font-medium" : ""}`}>{label}</span>
          {mono && <span className="block break-all font-mono text-[10px] text-muted-foreground">{mono}</span>}
          {sub && <span className="block break-words text-[10px] text-muted-foreground">{sub}</span>}
          {extra && <Badges p={extra} />}
        </span>
      </div>
    );
  };

  return (
    <div className="min-w-0">
      <Popover.Root open={open} onOpenChange={(o) => { setOpen(o); if (!o) setQuery(""); setActive(-1); }}>
        <Popover.Trigger asChild>
          <button type="button" disabled={disabled} aria-label={`${ariaLabel}: ${buttonText}`}
                  className={`flex w-full min-w-0 max-w-[320px] items-center gap-2 rounded-md border px-2 py-1.5 text-left text-xs focus:outline-none focus-visible:ring-2 focus-visible:ring-primary disabled:cursor-not-allowed disabled:opacity-50 ${issue === "unavailable" ? "border-destructive" : "border-border"} bg-background`}>
            <span className="min-w-0 flex-1">
              <span className="block break-words text-foreground">{buttonText}</span>
              {value && <span className="block break-all font-mono text-[10px] text-muted-foreground">{value}</span>}
            </span>
            <svg aria-hidden className={`h-3 w-3 shrink-0 transition-transform ${open ? "rotate-180" : ""}`} fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
            </svg>
          </button>
        </Popover.Trigger>
        <Popover.Portal>
          <Popover.Content align="start" sideOffset={6} collisionPadding={12}
                           onOpenAutoFocus={(e) => { e.preventDefault(); (e.currentTarget as HTMLElement).querySelector("input")?.focus(); }}
                           className="z-50 flex w-80 max-w-[calc(100vw-1.5rem)] max-h-[min(26rem,var(--radix-popover-content-available-height))] flex-col rounded-xl border border-border bg-card p-1 shadow-lg animate-[slideInRight_0.2s_ease-out]">
            <input value={query} onChange={(e) => { setQuery(e.target.value); setActive(-1); }} onKeyDown={onKey}
                   role="combobox" aria-expanded aria-controls={`${uid}-list`} aria-autocomplete="list"
                   aria-activedescendant={active >= 0 ? `${uid}-o${active}` : undefined} aria-label={t("settings.models.search")}
                   placeholder={t("settings.models.search")}
                   className="m-1 rounded-md border border-border bg-background px-2 py-1.5 text-xs text-foreground focus:outline-none focus:ring-2 focus:ring-primary" />
            <div ref={listRef} id={`${uid}-list`} role="listbox" aria-label={ariaLabel} className="min-h-0 overflow-y-auto">
              {emptyOption && !query.trim() && option("", emptyOption.label, emptyOption.hint ?? "", null)}
              {groups.map((g) => (
                <div key={g.provider} role="group" aria-labelledby={`${uid}-g-${g.provider}`}>
                  <div id={`${uid}-g-${g.provider}`} className="px-2.5 pb-0.5 pt-2 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">{g.label}</div>
                  {g.items.map((p) => option(p.value, p.label, "", p.value, p))}
                </div>
              ))}
              {options.length === 0 && <p className="px-3 py-4 text-center text-xs text-muted-foreground">{t("settings.models.noMatch")}</p>}
            </div>
          </Popover.Content>
        </Popover.Portal>
      </Popover.Root>
      {issue === "unavailable" && (
        <p className="mt-1 max-w-[320px] text-[11px] text-destructive">
          {t("settings.models.unavailable")}{reason ? ` — ${t(`settings.models.issue.${reason}`)}` : ""}
        </p>
      )}
      {issue === "noTools" && requireTools && <p className="mt-1 max-w-[320px] text-[11px] text-amber-700 dark:text-amber-300">{t("settings.models.noToolsAgent")}</p>}
      {unlisted && <p className="mt-1 max-w-[320px] text-[11px] text-amber-700 dark:text-amber-300">{t("settings.models.unlisted")}</p>}
    </div>
  );
}

/** A model's capabilities as small chips — the same words in the picker, the chat's selector and the models dialog. */
export function Badges({ p }: { p: ModelPreset }) {
  const { t } = useLocale();
  const list = badges(p);
  if (!list.length) return null;
  return (
    <span className="mt-0.5 flex flex-wrap gap-1">
      {list.map((b) => (
        <span key={b} className={`rounded px-1 py-px text-[10px] ${b === "noTools" ? "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300"
          : b === "unpriced" || b === "toolsUnknown" ? "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300"
          : "bg-muted text-muted-foreground"}`}>{t(`settings.models.badge.${b}`)}</span>
      ))}
    </span>
  );
}

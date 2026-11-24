import { useState, FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useAuth } from "@/hooks/useAuth";
import { useLocale } from "@/i18n/LocaleContext";
import { safeNext } from "@/lib/home";
import { loginError } from "@/lib/setup";

const EXAMPLE_STEPS = [1, 2, 3, 4] as const;

/** Signing in (MVP-2.9.0 N23 — the 2.8.0 spec's S6). Beside the form, on a desktop: one sentence on what this is
 *  for and a STATIC example of how a change goes, marked as an example — nothing of any workspace is shown before
 *  signing in. A wrong name or password and a server that cannot be reached are two different sentences, and what
 *  was typed stays. No self-service recovery or SSO is offered: neither exists. */
export default function Login() {
  const { t, locale, setLocale } = useLocale();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [shown, setShown] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const { login } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await login(email, password);
      // back to where the user was, if that is an in-app page; else /app decides (home preference)
      navigate(safeNext(params.get("next"), window.location.origin) ?? "/app", { replace: true });
    } catch (err: unknown) {
      const said = loginError(err);
      setError(said.key ? t(said.key) : said.message ?? t("login.failed"));
    } finally {
      setLoading(false);
    }
  }

  const field = "w-full rounded-md border border-border bg-background px-3 py-2 text-[16px] text-foreground sm:text-sm";

  return (
    <div className="min-h-screen bg-canvas lg:grid lg:grid-cols-2">
      {/* a desktop's left half: what it is for, and an example that is no workspace's data */}
      <aside className="hidden flex-col justify-center gap-6 border-r border-border bg-card px-12 py-10 lg:flex">
        <div>
          <div className="flex items-center gap-3">
            <img src={`${import.meta.env.BASE_URL}logo-icon.svg`} alt="" className="h-9 w-9" />
            <span className="text-2xl font-bold text-primary">AgenticOps</span>
          </div>
          <p className="mt-4 max-w-md text-lg leading-relaxed text-foreground">{t("login.pitch")}</p>
        </div>
        <section aria-labelledby="login-example" className="max-w-md rounded-lg border border-border bg-background p-5">
          <div className="flex items-center justify-between gap-3">
            <h2 id="login-example" className="text-sm font-semibold text-foreground">{t("login.example.title")}</h2>
            <span className="rounded border border-border px-1.5 py-0.5 text-[11px] text-muted-foreground">{t("login.example.label")}</span>
          </div>
          <ol className="mt-3 space-y-3">
            {EXAMPLE_STEPS.map((n) => (
              <li key={n} className="flex gap-3">
                <span aria-hidden="true" className="mt-0.5 flex h-5 w-5 flex-none items-center justify-center rounded-full bg-selected text-[11px] font-semibold text-primary">{n}</span>
                <span className="text-sm">
                  <span className="font-medium text-foreground">{t(`login.example.step${n}`)}</span>
                  <span className="block text-muted-foreground">{t(`login.example.step${n}.body`)}</span>
                </span>
              </li>
            ))}
          </ol>
          <p className="mt-3 text-xs text-muted-foreground">{t("login.example.note")}</p>
        </section>
      </aside>

      <main className="flex min-h-screen items-center justify-center px-4 py-8">
        <div className="w-full max-w-sm">
          <div className="mb-3 flex justify-end">
            <div role="group" aria-label="Language / 语言" className="flex rounded-[5px] border border-border bg-card p-0.5">
              {(["zh", "en"] as const).map((l) => (
                <button key={l} type="button" onClick={() => setLocale(l)} aria-pressed={locale === l}
                        className={`rounded-[3px] px-2 py-1 text-[11px] ${locale === l ? "bg-selected font-semibold text-primary" : "text-muted-foreground"}`}>
                  {l === "zh" ? "中文" : "English"}
                </button>
              ))}
            </div>
          </div>
          <div className="rounded-lg border border-border bg-card p-8 shadow-sm">
            <div className="mb-8 text-center">
              <img src={`${import.meta.env.BASE_URL}logo-icon.svg`} alt="" className="mx-auto mb-3 h-9 w-9" />
              <h1 className="text-2xl font-bold text-primary">AgenticOps</h1>
              <p className="mt-1 text-sm text-muted-foreground">{t("login.tagline")}</p>
              {/* a phone has no left half: the one sentence stands here */}
              <p className="mt-2 text-sm text-muted-foreground lg:hidden">{t("login.pitch")}</p>
            </div>

            {error && (
              <div role="alert" className="mb-4 rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700 dark:border-red-800 dark:bg-red-900/20 dark:text-red-400">
                {error}
              </div>
            )}

            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <label htmlFor="email" className="mb-1 block text-sm font-medium text-foreground">{t("login.username")}</label>
                <input id="email" type="text" autoComplete="username" autoCapitalize="none" spellCheck={false} required value={email}
                       onChange={(e) => setEmail(e.target.value)} className={field} />
              </div>
              <div>
                <label htmlFor="password" className="mb-1 block text-sm font-medium text-foreground">{t("login.password")}</label>
                <div className="relative">
                  <input id="password" type={shown ? "text" : "password"} autoComplete="current-password" required value={password}
                         onChange={(e) => setPassword(e.target.value)} className={`${field} pr-24`} />
                  <button type="button" aria-pressed={shown} aria-controls="password" onClick={() => setShown((v) => !v)}
                          className={`absolute inset-y-0 right-0 rounded-r-md px-3 text-xs hover:text-foreground ${shown ? "font-semibold text-primary" : "text-muted-foreground"}`}>
                    {t("login.showPassword")}
                  </button>
                </div>
              </div>
              <button type="submit" disabled={loading}
                      className="min-h-[44px] w-full rounded-md bg-primary px-4 py-2 font-medium text-primary-foreground transition-colors hover:bg-primary-hover disabled:opacity-60 sm:min-h-0">
                {loading ? t("login.signingIn") : t("login.signIn")}
              </button>
            </form>
          </div>
          <p className="mt-4 text-center text-xs text-muted-foreground">{t("login.cantSignIn")}</p>
          <p className="mt-1 text-center text-xs text-muted-foreground">
            {t("login.firstTime")}{" "}
            <Link to="/app/setup" className="font-medium text-primary hover:underline">{t("login.seeSetup")}</Link>
          </p>
        </div>
      </main>
    </div>
  );
}

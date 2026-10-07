import { useState, FormEvent } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useAuth } from "@/hooks/useAuth";
import { useLocale } from "@/i18n/LocaleContext";
import { ApiError } from "@/api/client";
import { safeNext } from "@/lib/home";

export default function Login() {
  const { t, locale, setLocale } = useLocale();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
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
      // a wrong password in the reader's language; anything else as the server said it
      setError(err instanceof ApiError && err.status === 401 ? t("login.invalid")
        : err instanceof Error ? err.message : t("login.failed"));
    } finally {
      setLoading(false);
    }
  }

  const field = "w-full rounded-md border border-border bg-background px-3 py-2 text-foreground";

  return (
    <div className="flex min-h-screen items-center justify-center bg-canvas px-4">
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
          </div>

          {error && (
            <div role="alert" className="mb-4 rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700 dark:border-red-800 dark:bg-red-900/20 dark:text-red-400">
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label htmlFor="email" className="mb-1 block text-sm font-medium text-foreground">{t("login.email")}</label>
              <input id="email" type="text" autoComplete="username" required value={email}
                     onChange={(e) => setEmail(e.target.value)} className={field} placeholder="admin" />
            </div>
            <div>
              <label htmlFor="password" className="mb-1 block text-sm font-medium text-foreground">{t("login.password")}</label>
              <input id="password" type="password" autoComplete="current-password" required value={password}
                     onChange={(e) => setPassword(e.target.value)} className={field} placeholder="********" />
            </div>
            <button type="submit" disabled={loading}
                    className="w-full rounded-md bg-primary px-4 py-2 font-medium text-primary-foreground transition-colors hover:bg-primary-hover disabled:opacity-60">
              {loading ? t("login.signingIn") : t("login.signIn")}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}

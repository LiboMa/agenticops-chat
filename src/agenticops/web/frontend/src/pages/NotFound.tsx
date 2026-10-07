import { Link } from "react-router-dom";
import { useLocale } from "@/i18n/LocaleContext";

/** Any /app path no route knows: say so (no blank page) and offer the way back. */
export default function NotFound() {
  const { t } = useLocale();
  return (
    <div className="mx-auto max-w-xl py-24 text-center">
      <h1 className="text-2xl font-semibold text-foreground">{t("notFound.title")}</h1>
      <p className="mt-3 text-sm text-muted-foreground">{t("notFound.body")}</p>
      <Link to="/app/chat" className="mt-6 inline-flex rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary-hover">
        {t("notFound.back")}
      </Link>
    </div>
  );
}

import { Link, Navigate, Route, Routes } from "react-router-dom";
import { AccountScopeProvider } from "@/components/layout/AccountScope";
import { ShellEffects } from "@/components/layout/ShellEffects";
import { DecideLens } from "./decide/DecideLens";
import { useNfT } from "./i18n";
import { LiveLens } from "./live/LiveLens";
import { NewShell } from "./shell/NewShell";
import { Message } from "./shell/StateBlock";
import { StoryLens } from "./story/StoryLens";
import "./newui.css";

/** NewUI (MVP-2.9.0): the new interface, at /app/new, beside the classic one. It sits outside the classic shell, so it
 *  brings its own account scope and the shell's background duties (language ↔ preference). */
export default function NewApp() {
  return (
    <AccountScopeProvider>
      <NewShell>
        <Routes>
          <Route index element={<Navigate to="decide" replace />} />
          <Route path="decide" element={<DecideLens />} />
          <Route path="decide/:item" element={<DecideLens />} />
          <Route path="story/:item" element={<StoryLens />} />
          <Route path="live" element={<LiveLens />} />
          <Route path="live/:lane" element={<LiveLens />} />
          <Route path="world/*" element={<Soon />} />
          <Route path="*" element={<Lost />} />
        </Routes>
      </NewShell>
      <ShellEffects />
    </AccountScopeProvider>
  );
}

function Soon() {
  const t = useNfT();
  return <section className="view"><div className="card pane"><Message big={t("shell.soon.big")}><p>{t("shell.soon.p")}</p></Message></div></section>;
}

function Lost() {
  const t = useNfT();
  return (
    <section className="view"><div className="card pane">
      <Message big={t("shell.notFound.big")}>
        <p>{t("shell.notFound.p")}</p>
        <p><Link className="btn" to="/app/new/decide"><span className="t">{t("shell.notFound.home")}</span></Link></p>
      </Message>
    </div></section>
  );
}

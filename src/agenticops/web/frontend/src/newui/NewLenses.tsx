import { Link, Navigate, Route, Routes } from "react-router-dom";
import { DecideLens } from "./decide/DecideLens";
import { useNfT } from "./i18n";
import { LiveLens } from "./live/LiveLens";
import { Message } from "./shell/StateBlock";
import { StoryLens } from "./story/StoryLens";
import { WorldLens } from "./world/WorldLens";

/** NewUI's own pages (/app/new/…), drawn inside its shell (components/layout/NewFrame mounts the shell, the account
 *  scope and the background duties; this is the lenses' chunk). */
export default function NewLenses() {
  return (
    <Routes>
      <Route index element={<Navigate to="decide" replace />} />
      <Route path="decide" element={<DecideLens />} />
      <Route path="decide/:item" element={<DecideLens />} />
      <Route path="story/:item" element={<StoryLens />} />
      <Route path="live" element={<LiveLens />} />
      <Route path="live/:lane" element={<LiveLens />} />
      <Route path="world" element={<WorldLens />} />
      <Route path="*" element={<Lost />} />
    </Routes>
  );
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

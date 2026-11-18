import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { useAccountScope } from "@/components/layout/AccountScope";
import { useAccounts } from "@/hooks/useAccounts";
import { useReadOnly } from "@/hooks/useBootstrap";
import { parseItem } from "@/lib/inbox";
import { DecideContext, type BriefKeys, type DecideApi } from "../decide/briefs/briefContext";
import { usePeek } from "../decide/widgets/usePeek";
import { useMyItem } from "../hooks/useMyItem";
import { useNfT } from "../i18n";
import { storyOrigin } from "../lib/story";
import { Message } from "../shell/StateBlock";
import { useLensKeys, useShell } from "../shell/shellContext";
import { ChangeStory } from "./ChangeStory";
import { IssueStory } from "./IssueStory";
import { BackOnly, type StoryFrame } from "./StoryBits";

/** «经过»: one item's whole record, at its own address (`/app/new/story/I12`). The brief asks for one decision; this
 *  page is everything behind it. It goes back to where it was opened from — a direct link goes to «待决». */
export function StoryLens() {
  const t = useNfT();
  const navigate = useNavigate();
  const location = useLocation();
  const { item: param = "" } = useParams();
  const target = parseItem(param);
  const item = target ? param : null;
  const origin = storyOrigin(location.state);
  const { notify } = useShell();
  const readOnly = useReadOnly();
  const { accountId, setAccountId } = useAccountScope();
  const accounts = useAccounts();
  const mine = useMyItem(item).data ?? null;
  const peek = usePeek(item);

  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 30_000);
    return () => window.clearInterval(id);
  }, []);

  const back = useCallback(() => {
    if (origin) navigate(-1);                                   // the browser's Back and this button are the same step
    else navigate("/app/new/decide", { replace: true });
  }, [origin, navigate]);

  // «去决定»: the decide lens lists one account scope; an item of another account would read «not waiting on you»
  // there, so the scope follows the item — and says so
  const decide = useCallback(() => {
    if (!mine) return;
    if (accountId != null && mine.account_id != null && mine.account_id !== accountId) {
      setAccountId(mine.account_id);
      notify(t("story.scopeMoved", { name: accounts.data?.find((a) => a.id === mine.account_id)?.name ?? `#${mine.account_id}` }));
    }
    if (origin?.from === "decide" && origin.back.split("?")[0] === `/app/new/decide/${mine.id}`) navigate(-1);
    else navigate(`/app/new/decide/${mine.id}`);
  }, [mine, accountId, setAccountId, notify, t, accounts.data, origin, navigate]);

  const pageKeys = useRef<BriefKeys | null>(null);
  const api = useMemo<DecideApi>(() => ({
    setBriefKeys: (keys) => { pageKeys.current = keys; }, done: (_item, message) => notify(message),
    failed: (item, message) => notify(`${item.ref}　${message}`), openPeek: peek.show,
    hide: () => () => {},            // no queue here: nothing to take off a list
  }), [notify, peek.show]);

  useLensKeys({
    onKey: (key, e, repeat) => {
      if (peek.onKey(key)) return true;
      if (key === "enter" && mine) { if (!repeat) decide(); return true; }
      return pageKeys.current?.onKey?.(key, e, repeat);
    },
    onEscape: () => {
      if (peek.open) { peek.close(); return true; }
      back();
      return true;
    },
  });

  const frame: StoryFrame = { item: item ?? "", mine, now, readOnly, from: origin?.from ?? "decide", onBack: back, onDecide: decide };
  return (
    <DecideContext.Provider value={api}>
      <section className="view" id="story">
        {!target ? (
          <article className="story card">
            <BackOnly frame={frame} />
            <Message big={t("story.none.big")}><p>{t("story.none.p")}</p></Message>
          </article>
        ) : target.kind === "issue" ? <IssueStory key={param} id={target.id} frame={frame} />
          : <ChangeStory key={param} id={target.id} frame={frame} />}
      </section>
      {peek.node}
    </DecideContext.Provider>
  );
}

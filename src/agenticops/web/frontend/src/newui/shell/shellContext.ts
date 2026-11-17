import { createContext, useContext, useEffect, useRef } from "react";

/** What the open lens does with the keyboard. The shell decides first whether a key press counts at all
 *  (lib/keys.keyIntent); what is left comes here. */
export interface LensKeys {
  /** a key the shell did not use itself; true = used (the shell then stops the browser's default) */
  onKey?: (key: string, e: KeyboardEvent, repeat: boolean) => boolean | void;
  onKeyUp?: (key: string, e: KeyboardEvent) => void;
  /** Escape: true when something of the lens closed (a panel, a form); false lets the shell go on */
  onEscape?: () => boolean;
}

export interface ShellApi {
  setLensKeys: (keys: LensKeys | null) => void;
  /** one plain line where the command bar sits, gone after a moment */
  notify: (text: string) => void;
  /** single-key shortcuts are on (the account menu switches them off) */
  singleKeys: boolean;
  /** a state class on NewUI's root, for layout that depends on what a lens has open (`peeking`, `lane-open`, `view3d`) */
  setRootFlag: (flag: string, on: boolean) => void;
}

export const ShellContext = createContext<ShellApi>({ setLensKeys: () => {}, notify: () => {}, singleKeys: true, setRootFlag: () => {} });
export const useShell = () => useContext(ShellContext);

/** The lens's keys, registered while it is on the page. The handlers may be new functions on every render. */
export function useLensKeys(keys: LensKeys): void {
  const { setLensKeys } = useShell();
  const latest = useRef(keys);
  latest.current = keys;
  useEffect(() => {
    setLensKeys({
      onKey: (key, e, repeat) => latest.current.onKey?.(key, e, repeat),
      onKeyUp: (key, e) => latest.current.onKeyUp?.(key, e),
      onEscape: () => latest.current.onEscape?.() ?? false,
    });
    return () => setLensKeys(null);
  }, [setLensKeys]);
}

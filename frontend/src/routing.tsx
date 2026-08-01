import {
  createContext,
  type PropsWithChildren,
  useContext,
  useMemo,
} from "react";
import { Router } from "wouter";
import { memoryLocation } from "wouter/memory-location";
import { useHistoryState } from "wouter/use-browser-location";

type MemoryEntry = string | { pathname: string; state?: unknown };

const MemoryRouteState = createContext<
  { active: false } | { active: true; state: unknown }
>({ active: false });

export function MemoryRouter({
  children,
  initialEntries = ["/"],
}: PropsWithChildren<{ initialEntries?: MemoryEntry[] }>) {
  const entry = initialEntries[0] ?? "/";
  const pathname = typeof entry === "string" ? entry : entry.pathname;
  const state = typeof entry === "string" ? undefined : entry.state;
  const location = useMemo(() => memoryLocation({ path: pathname, state }), [pathname, state]);

  return (
    <MemoryRouteState.Provider value={{ active: true, state }}>
      <Router hook={location.hook}>{children}</Router>
    </MemoryRouteState.Provider>
  );
}

export function useRouteState<T>(): T | null {
  const memory = useContext(MemoryRouteState);
  const browser = useHistoryState<T>();
  if (memory.active) return (memory.state as T | undefined) ?? null;
  return browser ?? null;
}

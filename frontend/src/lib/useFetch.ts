import { useEffect, useState } from "react";

interface State<T> {
  data?: T;
  error?: Error;
  loading: boolean;
}

/** Run `load` when `deps` change; `reload()` runs it again. Ignores stale responses. */
export function useFetch<T>(load: () => Promise<T>, deps: unknown[]) {
  const [state, setState] = useState<State<T>>({ loading: true });
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let current = true;
    setState((s) => ({ ...s, loading: true }));
    load().then(
      (data) => current && setState({ data, loading: false }),
      (error: Error) => current && setState({ error, loading: false }),
    );
    return () => {
      current = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);

  return { ...state, reload: () => setTick((t) => t + 1) };
}

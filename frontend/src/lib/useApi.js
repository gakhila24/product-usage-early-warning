import { useCallback, useEffect, useRef, useState } from "react";

/**
 * useApi(fetcher, deps) -> { data, error, loading, reload, setData }
 * Re-runs whenever `deps` change; ignores responses from stale requests.
 */
export function useApi(fetcher, deps = []) {
  const [state, setState] = useState({ data: null, error: null, loading: true });
  const [tick, setTick] = useState(0);
  const seq = useRef(0);
  useEffect(() => {
    const id = ++seq.current;
    setState((s) => ({ ...s, loading: true, error: null }));
    Promise.resolve().then(fetcher)
      .then((data) => { if (id === seq.current) setState({ data, error: null, loading: false }); })
      .catch((err) => { if (id === seq.current) setState((s) => ({ data: s.data, error: err.message || "Request failed", loading: false })); });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);
  const reload = useCallback(() => setTick((t) => t + 1), []);
  const setData = useCallback((updater) => setState((s) => ({ ...s, data: typeof updater === "function" ? updater(s.data) : updater })), []);
  return { ...state, reload, setData };
}

export function useDebounced(value, ms = 300) {
  const [v, setV] = useState(value);
  useEffect(() => { const t = setTimeout(() => setV(value), ms); return () => clearTimeout(t); }, [value, ms]);
  return v;
}

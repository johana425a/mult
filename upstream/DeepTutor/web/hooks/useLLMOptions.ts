"use client";

import { useCallback, useEffect, useReducer, useRef, useState } from "react";

import { listLLMOptions, LLM_OPTIONS_UPDATED_EVENT } from "@/lib/llm-options";
import {
  INITIAL_LLM_OPTIONS_STATE,
  reduceLLMOptionsState,
} from "@/lib/llm-options-state";
import { createSingleFlight } from "@/lib/single-flight";

interface RefreshOptions {
  force?: boolean;
  /** Keep the last usable catalog visible while synchronizing in the background. */
  background?: boolean;
}

/** Owns model-catalog loading independently from the chat page lifecycle. */
export function useLLMOptions(loader = listLLMOptions) {
  const [state, dispatch] = useReducer(
    reduceLLMOptionsState,
    INITIAL_LLM_OPTIONS_STATE,
  );
  const latestRequestRef = useRef(0);
  const [loadOptions] = useState(() => ({ current: createSingleFlight(loader) }));
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const refresh = useCallback(
    async (options?: RefreshOptions) => {
      const requestId = ++latestRequestRef.current;
      dispatch({
        type: "refresh-started",
        background: options?.background ?? false,
      });

      // Browser lifecycle events commonly arrive as a focus/pageshow/visibility
      // cluster. Coalesce that cluster here, without changing the global cache's
      // force semantics for mutation-sensitive resources such as knowledge bases.
      try {
        const payload = await loadOptions.current({ force: options?.force });
        if (!mountedRef.current || requestId !== latestRequestRef.current)
          return;
        dispatch({ type: "refresh-succeeded", payload });
      } catch {
        if (!mountedRef.current || requestId !== latestRequestRef.current)
          return;
        dispatch({ type: "refresh-failed" });
      }
    },
    [loadOptions],
  );

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    const changed = () => {
      // A mutation supersedes a pre-mutation in-flight fetch. A new local
      // flight lets the invalidated shared cache synchronize all consumers.
      latestRequestRef.current++;
      loadOptions.current = createSingleFlight(loader);
      void refresh({ background: true });
    };
    window.addEventListener(LLM_OPTIONS_UPDATED_EVENT, changed);
    return () => window.removeEventListener(LLM_OPTIONS_UPDATED_EVENT, changed);
  }, [loader, loadOptions, refresh]);

  return {
    options: state.options,
    activeDefault: state.activeDefault,
    loading: state.status === "loading",
    error: state.status === "error",
    refresh,
  };
}

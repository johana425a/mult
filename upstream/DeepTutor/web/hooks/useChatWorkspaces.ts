"use client";
import * as React from 'react';
import { useRetained } from '@/lib/sidebar-view-state.cjs';

import { useEffect, useState } from "react";

import { subscribeSessionChanges } from "@/lib/session-events";
import {
  listWorkspaces,
  type ChatWorkspaceRegistration,
} from "@/lib/workspaces-api";

/**
 * The workspaces a conversation can be filed under.
 *
 * Only the user-created ones: ``system`` is a read-only configuration snapshot
 * and ``general`` is the absence of a binding, so neither is a destination. A
 * workspace is managed from settings and the sidebar, and a conversation is moved
 * from three different surfaces (composer pill, sidebar row menu, chat header),
 * so every surface reloads on the same signal the session list uses instead of
 * each keeping its own idea of what exists.
 */
export function useChatWorkspaces() {
  const [workspaces, setWorkspaces] = useRetained<ChatWorkspaceRegistration[]>(React, 'workspaces', []);
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    let refreshVersion = 0;
    const refresh = () => {
      const version = ++refreshVersion;
      void listWorkspaces(true)
        .then((rows) => {
          if (!alive || version !== refreshVersion) return;
          setWorkspaces(rows.filter((row) => row.kind === "workspace"));
          setError("");
        })
        .catch((err) => {
          if (alive && version === refreshVersion) setError(err instanceof Error ? err.message : String(err));
        });
    };
    refresh();
    const unsubscribe = subscribeSessionChanges(refresh);
    return () => {
      alive = false;
      unsubscribe();
    };
  }, []);

  return { workspaces, error };
}

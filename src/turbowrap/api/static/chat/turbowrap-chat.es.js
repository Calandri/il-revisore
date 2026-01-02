var je = Object.defineProperty;
var Pe = (e, r, t) => r in e ? je(e, r, { enumerable: !0, configurable: !0, writable: !0, value: t }) : e[r] = t;
var ce = (e, r, t) => Pe(e, typeof r != "symbol" ? r + "" : r, t);
import l, { createContext as pe, useContext as fe, useMemo as W, useState as $, useCallback as k, useEffect as L, useRef as P } from "react";
function U(e) {
  return {
    id: e.id,
    cliType: e.cli_type,
    repositoryId: e.repository_id,
    currentBranch: e.current_branch,
    status: e.status,
    mockupProjectId: e.mockup_project_id,
    mockupId: e.mockup_id,
    model: e.model,
    agentName: e.agent_name,
    thinkingEnabled: e.thinking_enabled,
    thinkingBudget: e.thinking_budget,
    reasoningEnabled: e.reasoning_enabled,
    mcpServers: e.mcp_servers,
    claudeSessionId: e.claude_session_id,
    icon: e.icon,
    color: e.color,
    displayName: e.display_name,
    position: e.position,
    totalMessages: e.total_messages,
    totalTokensIn: e.total_tokens_in,
    totalTokensOut: e.total_tokens_out,
    createdAt: new Date(e.created_at),
    updatedAt: new Date(e.updated_at),
    lastMessageAt: e.last_message_at ? new Date(e.last_message_at) : null
  };
}
function Oe(e) {
  return {
    id: e.id,
    sessionId: e.session_id,
    role: e.role,
    content: e.content,
    segments: e.segments ?? void 0,
    isThinking: e.is_thinking,
    tokensIn: e.tokens_in ?? void 0,
    tokensOut: e.tokens_out ?? void 0,
    modelUsed: e.model_used ?? void 0,
    agentUsed: e.agent_used ?? void 0,
    durationMs: e.duration_ms ?? void 0,
    createdAt: new Date(e.created_at)
  };
}
function V() {
  return {
    isStreaming: !1,
    content: "",
    segments: [{ type: "text", content: "" }],
    activeTools: [],
    activeAgents: [],
    pendingMessage: null,
    error: null
  };
}
class ie extends Error {
  constructor(r, t, a) {
    super(r), this.status = t, this.code = a, this.name = "ChatAPIError";
  }
}
async function ze(e, r, t) {
  var d, u;
  const a = (d = e.body) == null ? void 0 : d.getReader();
  if (!a) {
    (u = r.onError) == null || u.call(r, new Error("Response body is not readable"));
    return;
  }
  const n = new TextDecoder();
  let s = "", o = "", c = "chunk";
  try {
    for (; ; ) {
      if (t != null && t.aborted)
        throw new DOMException("Aborted", "AbortError");
      const { done: i, value: g } = await a.read();
      if (i) break;
      s += n.decode(g, { stream: !0 });
      const p = s.split(`
`);
      s = p.pop() || "";
      for (const m of p)
        if (m.trim()) {
          if (m.startsWith("event: "))
            c = m.slice(7).trim(), o = "";
          else if (m.startsWith("data: ")) {
            o += m.slice(6);
            try {
              const b = JSON.parse(o);
              We(c, b, r), c = "chunk", o = "";
            } catch {
            }
          }
        }
    }
  } finally {
    a.releaseLock();
  }
}
function We(e, r, t) {
  var a, n, s, o, c, d, u, i, g, p, m;
  switch (e) {
    case "start":
      typeof r.session_id == "string" && ((a = t.onStart) == null || a.call(t, r.session_id));
      break;
    case "chunk":
      typeof r.content == "string" && ((n = t.onChunk) == null || n.call(
        t,
        r.content,
        typeof r.fullContent == "string" ? r.fullContent : void 0
      ));
      break;
    case "thinking":
      typeof r.content == "string" && ((s = t.onThinking) == null || s.call(t, r.content));
      break;
    case "tool_start": {
      if (typeof r.tool_name != "string" || typeof r.tool_id != "string")
        break;
      const b = {
        name: r.tool_name,
        id: r.tool_id,
        startedAt: Date.now()
      };
      (o = t.onToolStart) == null || o.call(t, b);
      break;
    }
    case "tool_end":
      typeof r.tool_name == "string" && ((c = t.onToolEnd) == null || c.call(
        t,
        r.tool_name,
        typeof r.tool_input == "object" && r.tool_input !== null ? r.tool_input : void 0
      ));
      break;
    case "agent_start": {
      if (typeof r.agent_type != "string" || typeof r.agent_model != "string" || typeof r.description != "string")
        break;
      const b = {
        type: r.agent_type,
        model: r.agent_model,
        description: r.description,
        startedAt: Date.now()
      };
      (d = t.onAgentStart) == null || d.call(t, b);
      break;
    }
    case "done":
      typeof r.message_id == "string" && typeof r.total_length == "number" && ((u = t.onDone) == null || u.call(t, r.message_id, r.total_length));
      break;
    case "title_updated":
      typeof r.title == "string" && ((i = t.onTitleUpdate) == null || i.call(t, r.title));
      break;
    case "action":
      (r.type === "navigate" || r.type === "highlight") && typeof r.target == "string" && ((g = t.onAction) == null || g.call(t, {
        type: r.type,
        target: r.target
      }));
      break;
    case "usage":
      typeof r.input_tokens == "number" && typeof r.output_tokens == "number" && ((p = t.onUsage) == null || p.call(t, {
        inputTokens: r.input_tokens,
        outputTokens: r.output_tokens,
        cacheReadInputTokens: typeof r.cache_read_input_tokens == "number" ? r.cache_read_input_tokens : void 0,
        cacheCreationInputTokens: typeof r.cache_creation_input_tokens == "number" ? r.cache_creation_input_tokens : void 0
      }));
      break;
    case "error":
      typeof r.error == "string" && ((m = t.onError) == null || m.call(t, new Error(r.error)));
      break;
  }
}
class Ue {
  constructor(r) {
    ce(this, "config");
    this.config = {
      timeout: 12e4,
      ...r,
      baseUrl: r.baseUrl.replace(/\/$/, "")
    };
  }
  // ============================================================================
  // Private helpers
  // ============================================================================
  async getHeaders() {
    var t, a;
    const r = {
      "Content-Type": "application/json",
      ...this.config.headers
    };
    if (this.config.getAuthToken)
      try {
        const n = await this.config.getAuthToken();
        n && (r.Authorization = `Bearer ${n}`);
      } catch (n) {
        console.error("Failed to get auth token:", n), (a = (t = this.config).onError) == null || a.call(
          t,
          n instanceof Error ? n : new Error("Failed to get auth token")
        );
      }
    return r;
  }
  async handleError(r) {
    var t, a, n, s, o, c;
    r.status === 401 && ((a = (t = this.config).onUnauthorized) == null || a.call(t));
    try {
      const d = await r.json(), u = new ie(
        d.detail || d.message || `HTTP ${r.status}`,
        r.status,
        d.error_type
      );
      return (s = (n = this.config).onError) == null || s.call(n, u), u;
    } catch {
      const d = new ie(
        `HTTP ${r.status}: ${r.statusText}`,
        r.status
      );
      return (c = (o = this.config).onError) == null || c.call(o, d), d;
    }
  }
  async fetch(r, t = {}) {
    const a = `${this.config.baseUrl}${r}`, n = await this.getHeaders(), s = new AbortController(), o = setTimeout(() => s.abort(), this.config.timeout);
    try {
      const c = await fetch(a, {
        ...t,
        headers: { ...n, ...t.headers },
        signal: t.signal || s.signal
      });
      if (!c.ok)
        throw await this.handleError(c);
      return c.json();
    } finally {
      clearTimeout(o);
    }
  }
  // ============================================================================
  // Session Management
  // ============================================================================
  /**
   * Get all chat sessions
   */
  async getSessions(r) {
    const t = new URLSearchParams();
    r != null && r.repositoryId && t.set("repository_id", r.repositoryId), r != null && r.cliType && t.set("cli_type", r.cliType), r != null && r.limit && t.set("limit", r.limit.toString());
    const a = t.toString(), n = `/api/cli-chat/sessions${a ? `?${a}` : ""}`;
    return (await this.fetch(n)).map(U);
  }
  /**
   * Create a new chat session
   */
  async createSession(r) {
    const t = await this.fetch("/api/cli-chat/sessions", {
      method: "POST",
      body: JSON.stringify({
        cli_type: r.cliType,
        repository_id: r.repositoryId,
        display_name: r.displayName,
        icon: r.icon,
        color: r.color,
        mockup_project_id: r.mockupProjectId,
        mockup_id: r.mockupId
      })
    });
    return U(t);
  }
  /**
   * Get a single session by ID
   */
  async getSession(r) {
    const t = await this.fetch(
      `/api/cli-chat/sessions/${r}`
    );
    return U(t);
  }
  /**
   * Update session settings
   */
  async updateSession(r, t) {
    const a = await this.fetch(
      `/api/cli-chat/sessions/${r}`,
      {
        method: "PUT",
        body: JSON.stringify({
          display_name: t.displayName,
          icon: t.icon,
          color: t.color,
          position: t.position,
          model: t.model,
          agent_name: t.agentName,
          thinking_enabled: t.thinkingEnabled,
          thinking_budget: t.thinkingBudget,
          reasoning_enabled: t.reasoningEnabled,
          mcp_servers: t.mcpServers,
          mockup_project_id: t.mockupProjectId,
          mockup_id: t.mockupId
        })
      }
    );
    return U(a);
  }
  /**
   * Delete a session (soft delete)
   */
  async deleteSession(r) {
    await this.fetch(`/api/cli-chat/sessions/${r}`, {
      method: "DELETE"
    });
  }
  /**
   * Start the CLI process for a session
   */
  async startSession(r) {
    return this.fetch(`/api/cli-chat/sessions/${r}/start`, {
      method: "POST"
    });
  }
  /**
   * Stop the CLI process for a session
   */
  async stopSession(r) {
    return this.fetch(`/api/cli-chat/sessions/${r}/stop`, {
      method: "POST"
    });
  }
  /**
   * Fork a session (duplicate with messages)
   */
  async forkSession(r) {
    const t = await this.fetch(
      `/api/cli-chat/sessions/${r}/fork`,
      { method: "POST" }
    );
    return U(t);
  }
  /**
   * Get available branches for session's repository
   */
  async getBranches(r) {
    return this.fetch(`/api/cli-chat/sessions/${r}/branches`);
  }
  /**
   * Change the active branch for a session
   */
  async changeBranch(r, t) {
    const a = await this.fetch(
      `/api/cli-chat/sessions/${r}/branch`,
      {
        method: "POST",
        body: JSON.stringify({ branch: t })
      }
    );
    return U(a);
  }
  // ============================================================================
  // Messages
  // ============================================================================
  /**
   * Get messages for a session
   */
  async getMessages(r, t) {
    const a = new URLSearchParams();
    t != null && t.limit && a.set("limit", t.limit.toString()), t != null && t.includeThinking && a.set("include_thinking", "true");
    const n = a.toString(), s = `/api/cli-chat/sessions/${r}/messages${n ? `?${n}` : ""}`;
    return (await this.fetch(s)).map(Oe);
  }
  /**
   * Send a message and stream the response via SSE
   */
  async streamMessage(r, t, a = {}) {
    var o;
    const n = await this.getHeaders(), s = await fetch(
      `${this.config.baseUrl}/api/cli-chat/sessions/${r}/message`,
      {
        method: "POST",
        headers: n,
        body: JSON.stringify({
          content: t,
          model_override: a.modelOverride
        }),
        signal: a.signal
      }
    );
    if (!s.ok) {
      const c = await this.handleError(s);
      (o = a.onError) == null || o.call(a, c);
      return;
    }
    await ze(s, a, a.signal);
  }
  // ============================================================================
  // Context & Usage
  // ============================================================================
  /**
   * Get context info for a session (tokens, categories, etc.)
   */
  async getContextInfo(r) {
    const t = await this.fetch(
      `/api/cli-chat/sessions/${r}/context`
    );
    return {
      model: t.model,
      tokens: {
        used: t.tokens_in || 0,
        limit: 2e5,
        // Default for Claude
        percentage: (t.tokens_in || 0) / 2e5 * 100
      },
      categories: t.categories || [],
      mcpTools: t.mcpTools || [],
      agents: t.agents || []
    };
  }
  /**
   * Get usage info for a session (version, MCP servers, etc.)
   */
  async getUsageInfo(r) {
    const t = await this.fetch(
      `/api/cli-chat/sessions/${r}/usage`
    );
    return {
      version: t.version,
      sessionId: t.session_id,
      cwd: t.cwd,
      loginMethod: t.login_method,
      organization: t.organization,
      email: t.email,
      model: t.model,
      modelId: t.model_id,
      ide: t.ide,
      ideVersion: t.ide_version,
      mcpServers: t.mcp_servers || [],
      memory: t.memory,
      settingSources: t.setting_sources
    };
  }
  // ============================================================================
  // Agents
  // ============================================================================
  /**
   * Get list of available agents
   */
  async getAgents() {
    return (await this.fetch(
      "/api/cli-chat/agents"
    )).agents;
  }
  /**
   * Get a single agent by name
   */
  async getAgent(r) {
    return this.fetch(`/api/cli-chat/agents/${r}`);
  }
  // ============================================================================
  // Slash Commands
  // ============================================================================
  /**
   * Get slash command prompt by name
   */
  async getSlashCommand(r) {
    return this.fetch(`/api/cli-chat/commands/${r}`);
  }
  /**
   * List available slash commands
   */
  async getSlashCommands() {
    return this.fetch("/api/cli-chat/commands");
  }
  // ============================================================================
  // Repositories
  // ============================================================================
  /**
   * Get list of repositories
   */
  async getRepositories() {
    return this.fetch("/api/git/repositories");
  }
}
const he = pe(null);
function te() {
  const e = fe(he);
  if (!e)
    throw new Error("useChatClient must be used within a ChatProvider");
  return e;
}
const Be = {}, le = (e) => {
  let r;
  const t = /* @__PURE__ */ new Set(), a = (i, g) => {
    const p = typeof i == "function" ? i(r) : i;
    if (!Object.is(p, r)) {
      const m = r;
      r = g ?? (typeof p != "object" || p === null) ? p : Object.assign({}, r, p), t.forEach((b) => b(r, m));
    }
  }, n = () => r, d = { setState: a, getState: n, getInitialState: () => u, subscribe: (i) => (t.add(i), () => t.delete(i)), destroy: () => {
    (Be ? "production" : void 0) !== "production" && console.warn(
      "[DEPRECATED] The `destroy` method will be unsupported in a future version. Instead use unsubscribe function returned by subscribe. Everything will be garbage-collected if store is garbage-collected."
    ), t.clear();
  } }, u = r = e(a, n, d);
  return d;
}, He = (e) => e ? le(e) : le;
function Fe(e) {
  return e && e.__esModule && Object.prototype.hasOwnProperty.call(e, "default") ? e.default : e;
}
var ye = { exports: {} }, ve = {}, be = { exports: {} }, Ee = {};
/**
 * @license React
 * use-sync-external-store-shim.production.js
 *
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */
var B = l;
function Ve(e, r) {
  return e === r && (e !== 0 || 1 / e === 1 / r) || e !== e && r !== r;
}
var Ge = typeof Object.is == "function" ? Object.is : Ve, Je = B.useState, qe = B.useEffect, Ke = B.useLayoutEffect, Qe = B.useDebugValue;
function Ye(e, r) {
  var t = r(), a = Je({ inst: { value: t, getSnapshot: r } }), n = a[0].inst, s = a[1];
  return Ke(
    function() {
      n.value = t, n.getSnapshot = r, Q(n) && s({ inst: n });
    },
    [e, t, r]
  ), qe(
    function() {
      return Q(n) && s({ inst: n }), e(function() {
        Q(n) && s({ inst: n });
      });
    },
    [e]
  ), Qe(t), t;
}
function Q(e) {
  var r = e.getSnapshot;
  e = e.value;
  try {
    var t = r();
    return !Ge(e, t);
  } catch {
    return !0;
  }
}
function Xe(e, r) {
  return r();
}
var Ze = typeof window > "u" || typeof window.document > "u" || typeof window.document.createElement > "u" ? Xe : Ye;
Ee.useSyncExternalStore = B.useSyncExternalStore !== void 0 ? B.useSyncExternalStore : Ze;
be.exports = Ee;
var et = be.exports;
/**
 * @license React
 * use-sync-external-store-shim/with-selector.production.js
 *
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */
var J = l, tt = et;
function rt(e, r) {
  return e === r && (e !== 0 || 1 / e === 1 / r) || e !== e && r !== r;
}
var at = typeof Object.is == "function" ? Object.is : rt, nt = tt.useSyncExternalStore, st = J.useRef, ot = J.useEffect, ct = J.useMemo, it = J.useDebugValue;
ve.useSyncExternalStoreWithSelector = function(e, r, t, a, n) {
  var s = st(null);
  if (s.current === null) {
    var o = { hasValue: !1, value: null };
    s.current = o;
  } else o = s.current;
  s = ct(
    function() {
      function d(m) {
        if (!u) {
          if (u = !0, i = m, m = a(m), n !== void 0 && o.hasValue) {
            var b = o.value;
            if (n(b, m))
              return g = b;
          }
          return g = m;
        }
        if (b = g, at(i, m)) return b;
        var y = a(m);
        return n !== void 0 && n(b, y) ? (i = m, b) : (i = m, g = y);
      }
      var u = !1, i, g, p = t === void 0 ? null : t;
      return [
        function() {
          return d(r());
        },
        p === null ? void 0 : function() {
          return d(p());
        }
      ];
    },
    [r, t, a, n]
  );
  var c = nt(e, s[0], s[1]);
  return ot(
    function() {
      o.hasValue = !0, o.value = c;
    },
    [c]
  ), it(c), c;
};
ye.exports = ve;
var lt = ye.exports;
const dt = /* @__PURE__ */ Fe(lt), Se = {}, { useDebugValue: ut } = l, { useSyncExternalStoreWithSelector: mt } = dt;
let de = !1;
const gt = (e) => e;
function pt(e, r = gt, t) {
  (Se ? "production" : void 0) !== "production" && t && !de && (console.warn(
    "[DEPRECATED] Use `createWithEqualityFn` instead of `create` or use `useStoreWithEqualityFn` instead of `useStore`. They can be imported from 'zustand/traditional'. https://github.com/pmndrs/zustand/discussions/1937"
  ), de = !0);
  const a = mt(
    e.subscribe,
    e.getState,
    e.getServerState || e.getInitialState,
    r,
    t
  );
  return ut(a), a;
}
const ft = (e) => {
  (Se ? "production" : void 0) !== "production" && typeof e != "function" && console.warn(
    "[DEPRECATED] Passing a vanilla store will be unsupported in a future version. Instead use `import { useStore } from 'zustand'`."
  );
  const r = typeof e == "function" ? He(e) : e, t = (a, n) => pt(r, a, n);
  return Object.assign(t, r), t;
}, ht = (e) => ft, Y = { BASE_URL: "/", DEV: !1, MODE: "production", PROD: !0, SSR: !1 }, ee = /* @__PURE__ */ new Map(), G = (e) => {
  const r = ee.get(e);
  return r ? Object.fromEntries(
    Object.entries(r.stores).map(([t, a]) => [t, a.getState()])
  ) : {};
}, yt = (e, r, t) => {
  if (e === void 0)
    return {
      type: "untracked",
      connection: r.connect(t)
    };
  const a = ee.get(t.name);
  if (a)
    return { type: "tracked", store: e, ...a };
  const n = {
    connection: r.connect(t),
    stores: {}
  };
  return ee.set(t.name, n), { type: "tracked", store: e, ...n };
}, vt = (e, r = {}) => (t, a, n) => {
  const { enabled: s, anonymousActionType: o, store: c, ...d } = r;
  let u;
  try {
    u = (s ?? (Y ? "production" : void 0) !== "production") && window.__REDUX_DEVTOOLS_EXTENSION__;
  } catch {
  }
  if (!u)
    return (Y ? "production" : void 0) !== "production" && s && console.warn(
      "[zustand devtools middleware] Please install/enable Redux devtools extension"
    ), e(t, a, n);
  const { connection: i, ...g } = yt(c, u, d);
  let p = !0;
  n.setState = (y, S, f) => {
    const h = t(y, S);
    if (!p) return h;
    const E = f === void 0 ? { type: o || "anonymous" } : typeof f == "string" ? { type: f } : f;
    return c === void 0 ? (i == null || i.send(E, a()), h) : (i == null || i.send(
      {
        ...E,
        type: `${c}/${E.type}`
      },
      {
        ...G(d.name),
        [c]: n.getState()
      }
    ), h);
  };
  const m = (...y) => {
    const S = p;
    p = !1, t(...y), p = S;
  }, b = e(n.setState, a, n);
  if (g.type === "untracked" ? i == null || i.init(b) : (g.stores[g.store] = n, i == null || i.init(
    Object.fromEntries(
      Object.entries(g.stores).map(([y, S]) => [
        y,
        y === g.store ? b : S.getState()
      ])
    )
  )), n.dispatchFromDevtools && typeof n.dispatch == "function") {
    let y = !1;
    const S = n.dispatch;
    n.dispatch = (...f) => {
      (Y ? "production" : void 0) !== "production" && f[0].type === "__setState" && !y && (console.warn(
        '[zustand devtools middleware] "__setState" action type is reserved to set state from the devtools. Avoid using it.'
      ), y = !0), S(...f);
    };
  }
  return i.subscribe((y) => {
    var S;
    switch (y.type) {
      case "ACTION":
        if (typeof y.payload != "string") {
          console.error(
            "[zustand devtools middleware] Unsupported action format"
          );
          return;
        }
        return X(
          y.payload,
          (f) => {
            if (f.type === "__setState") {
              if (c === void 0) {
                m(f.state);
                return;
              }
              Object.keys(f.state).length !== 1 && console.error(
                `
                    [zustand devtools middleware] Unsupported __setState action format.
                    When using 'store' option in devtools(), the 'state' should have only one key, which is a value of 'store' that was passed in devtools(),
                    and value of this only key should be a state object. Example: { "type": "__setState", "state": { "abc123Store": { "foo": "bar" } } }
                    `
              );
              const h = f.state[c];
              if (h == null)
                return;
              JSON.stringify(n.getState()) !== JSON.stringify(h) && m(h);
              return;
            }
            n.dispatchFromDevtools && typeof n.dispatch == "function" && n.dispatch(f);
          }
        );
      case "DISPATCH":
        switch (y.payload.type) {
          case "RESET":
            return m(b), c === void 0 ? i == null ? void 0 : i.init(n.getState()) : i == null ? void 0 : i.init(G(d.name));
          case "COMMIT":
            if (c === void 0) {
              i == null || i.init(n.getState());
              return;
            }
            return i == null ? void 0 : i.init(G(d.name));
          case "ROLLBACK":
            return X(y.state, (f) => {
              if (c === void 0) {
                m(f), i == null || i.init(n.getState());
                return;
              }
              m(f[c]), i == null || i.init(G(d.name));
            });
          case "JUMP_TO_STATE":
          case "JUMP_TO_ACTION":
            return X(y.state, (f) => {
              if (c === void 0) {
                m(f);
                return;
              }
              JSON.stringify(n.getState()) !== JSON.stringify(f[c]) && m(f[c]);
            });
          case "IMPORT_STATE": {
            const { nextLiftedState: f } = y.payload, h = (S = f.computedStates.slice(-1)[0]) == null ? void 0 : S.state;
            if (!h) return;
            m(c === void 0 ? h : h[c]), i == null || i.send(
              null,
              // FIXME no-any
              f
            );
            return;
          }
          case "PAUSE_RECORDING":
            return p = !p;
        }
        return;
    }
  }), b;
}, bt = vt, X = (e, r) => {
  let t;
  try {
    t = JSON.parse(e);
  } catch (a) {
    console.error(
      "[zustand devtools middleware] Could not parse the received json",
      a
    );
  }
  t !== void 0 && r(t);
}, Et = (e) => (r, t, a) => {
  const n = a.subscribe;
  return a.subscribe = (o, c, d) => {
    let u = o;
    if (c) {
      const i = (d == null ? void 0 : d.equalityFn) || Object.is;
      let g = o(a.getState());
      u = (p) => {
        const m = o(p);
        if (!i(g, m)) {
          const b = g;
          c(g = m, b);
        }
      }, d != null && d.fireImmediately && c(g, g);
    }
    return n(u);
  }, e(r, t, a);
}, St = Et, ue = {
  sessions: /* @__PURE__ */ new Map(),
  activeSessionId: null,
  secondarySessionId: null,
  messages: /* @__PURE__ */ new Map(),
  streamState: /* @__PURE__ */ new Map(),
  agents: [],
  isInitialized: !1,
  chatMode: "third",
  dualChatEnabled: !1,
  showHistory: !1,
  showSettings: !1,
  activePane: "left"
}, _ = ht()(
  bt(
    St((e, r) => ({
      ...ue,
      actions: {
        // ======================================================================
        // Session management
        // ======================================================================
        setActiveSession: (t) => {
          e({ activeSessionId: t }, !1, "setActiveSession");
        },
        setSecondarySession: (t) => {
          e({ secondarySessionId: t }, !1, "setSecondarySession");
        },
        addSession: (t) => {
          e((a) => {
            const n = new Map(a.sessions);
            n.set(t.id, t);
            const s = new Map(a.messages);
            s.set(t.id, []);
            const o = new Map(a.streamState);
            return o.set(t.id, V()), { sessions: n, messages: s, streamState: o };
          }, !1, "addSession");
        },
        updateSession: (t, a) => {
          e((n) => {
            const s = new Map(n.sessions), o = s.get(t);
            return o && s.set(t, { ...o, ...a }), { sessions: s };
          }, !1, "updateSession");
        },
        removeSession: (t) => {
          e((a) => {
            const n = new Map(a.sessions);
            n.delete(t);
            const s = new Map(a.messages);
            s.delete(t);
            const o = new Map(a.streamState);
            o.delete(t);
            const c = a.activeSessionId === t ? null : a.activeSessionId, d = a.secondarySessionId === t ? null : a.secondarySessionId;
            return { sessions: n, messages: s, streamState: o, activeSessionId: c, secondarySessionId: d };
          }, !1, "removeSession");
        },
        setSessions: (t) => {
          e((a) => {
            const n = /* @__PURE__ */ new Map(), s = new Map(a.messages), o = new Map(a.streamState);
            for (const c of t)
              n.set(c.id, c), s.has(c.id) || s.set(c.id, []), o.has(c.id) || o.set(c.id, V());
            return {
              sessions: n,
              messages: s,
              streamState: o
            };
          }, !1, "setSessions");
        },
        // ======================================================================
        // Message management
        // ======================================================================
        addMessage: (t, a) => {
          e((n) => {
            const s = new Map(n.messages), o = [...s.get(t) || [], a];
            return s.set(t, o), { messages: s };
          }, !1, "addMessage");
        },
        updateMessage: (t, a, n) => {
          e((s) => {
            const o = new Map(s.messages), d = (o.get(t) || []).map(
              (u) => u.id === a ? { ...u, ...n } : u
            );
            return o.set(t, d), { messages: o };
          }, !1, "updateMessage");
        },
        setMessages: (t, a) => {
          e((n) => {
            const s = new Map(n.messages);
            return s.set(t, a), { messages: s };
          }, !1, "setMessages");
        },
        clearMessages: (t) => {
          e((a) => {
            const n = new Map(a.messages);
            return n.set(t, []), { messages: n };
          }, !1, "clearMessages");
        },
        // ======================================================================
        // Streaming
        // ======================================================================
        startStream: (t) => {
          e((a) => {
            const n = new Map(a.streamState);
            return n.set(t, {
              ...V(),
              isStreaming: !0
            }), { streamState: n };
          }, !1, "startStream");
        },
        appendStreamContent: (t, a, n) => {
          e((s) => {
            var g;
            const o = new Map(s.streamState), c = o.get(t);
            if (!c) return s;
            const d = n !== void 0 ? n : c.content + a, u = [...c.segments], i = u[u.length - 1];
            if ((i == null ? void 0 : i.type) === "text") {
              const p = n !== void 0 ? n.slice(((g = i.content) == null ? void 0 : g.length) || 0) : a;
              u[u.length - 1] = {
                ...i,
                content: (i.content || "") + p
              };
            }
            return o.set(t, {
              ...c,
              content: d,
              segments: u
            }), { streamState: o };
          }, !1, "appendStreamContent");
        },
        addStreamSegment: (t, a) => {
          e((n) => {
            const s = new Map(n.streamState), o = s.get(t);
            if (!o) return n;
            const c = [...o.segments, a];
            return a.type !== "text" && c.push({ type: "text", content: "" }), s.set(t, {
              ...o,
              segments: c
            }), { streamState: s };
          }, !1, "addStreamSegment");
        },
        endStream: (t, a) => {
          e((n) => {
            const s = new Map(n.streamState), o = s.get(t);
            if (s.set(t, {
              ...V(),
              pendingMessage: (o == null ? void 0 : o.pendingMessage) || null
            }), a) {
              const c = new Map(n.messages), d = [...c.get(t) || [], a];
              return c.set(t, d), { streamState: s, messages: c };
            }
            return { streamState: s };
          }, !1, "endStream");
        },
        abortStream: (t) => {
          e((a) => {
            const n = new Map(a.streamState);
            return n.set(t, V()), { streamState: n };
          }, !1, "abortStream");
        },
        setStreamError: (t, a) => {
          e((n) => {
            const s = new Map(n.streamState), o = s.get(t);
            return o && s.set(t, {
              ...o,
              isStreaming: !1,
              error: a
            }), { streamState: s };
          }, !1, "setStreamError");
        },
        // ======================================================================
        // Tool/Agent tracking
        // ======================================================================
        addActiveTool: (t, a) => {
          e((n) => {
            const s = new Map(n.streamState), o = s.get(t);
            return o && s.set(t, {
              ...o,
              activeTools: [...o.activeTools, a]
            }), { streamState: s };
          }, !1, "addActiveTool");
        },
        removeActiveTool: (t, a, n) => {
          e((s) => {
            const o = new Map(s.streamState), c = o.get(t);
            if (c) {
              const d = c.activeTools.filter((i) => i.name !== a), u = c.segments.map((i) => i.type === "tool" && i.name === a && !i.input ? { ...i, input: n, completedAt: Date.now() } : i);
              o.set(t, {
                ...c,
                activeTools: d,
                segments: u
              });
            }
            return { streamState: o };
          }, !1, "removeActiveTool");
        },
        addActiveAgent: (t, a) => {
          e((n) => {
            const s = new Map(n.streamState), o = s.get(t);
            return o && s.set(t, {
              ...o,
              activeAgents: [...o.activeAgents, a]
            }), { streamState: s };
          }, !1, "addActiveAgent");
        },
        // ======================================================================
        // Pending messages
        // ======================================================================
        setPendingMessage: (t, a) => {
          e((n) => {
            const s = new Map(n.streamState), o = s.get(t);
            return o && s.set(t, {
              ...o,
              pendingMessage: a
            }), { streamState: s };
          }, !1, "setPendingMessage");
        },
        // ======================================================================
        // Agents
        // ======================================================================
        setAgents: (t) => {
          e({ agents: t }, !1, "setAgents");
        },
        // ======================================================================
        // UI State
        // ======================================================================
        setChatMode: (t) => {
          e({ chatMode: t }, !1, "setChatMode");
        },
        toggleDualChat: () => {
          e((t) => ({
            dualChatEnabled: !t.dualChatEnabled
          }), !1, "toggleDualChat");
        },
        toggleHistory: () => {
          e((t) => ({
            showHistory: !t.showHistory
          }), !1, "toggleHistory");
        },
        toggleSettings: () => {
          e((t) => ({
            showSettings: !t.showSettings
          }), !1, "toggleSettings");
        },
        setActivePane: (t) => {
          e({ activePane: t }, !1, "setActivePane");
        },
        // ======================================================================
        // Initialization
        // ======================================================================
        initialize: (t, a) => {
          const { actions: n } = r();
          n.setSessions(t), n.setAgents(a), e({ isInitialized: !0 }, !1, "initialize");
        },
        reset: () => {
          e(ue, !1, "reset");
        }
      }
    })),
    { name: "turbowrap-chat" }
  )
), re = (e) => e.activeSessionId ? e.sessions.get(e.activeSessionId) ?? null : null, ke = (e) => e.secondarySessionId ? e.sessions.get(e.secondarySessionId) ?? null : null, kt = (e) => Array.from(e.sessions.values()), we = (e) => e.activeSessionId ? e.sessions.has(e.activeSessionId) ? e.messages.get(e.activeSessionId) ?? [] : [] : [], wt = (e) => e.secondarySessionId ? e.messages.get(e.secondarySessionId) ?? [] : [], xe = (e) => e.activeSessionId ? e.streamState.get(e.activeSessionId) ?? null : null, xt = (e) => e.secondarySessionId ? e.streamState.get(e.secondarySessionId) ?? null : null, Sr = (e) => (r) => {
  var t;
  return ((t = r.streamState.get(e)) == null ? void 0 : t.isStreaming) ?? !1;
}, Rt = (e) => e.dualChatEnabled && e.secondarySessionId !== null, Nt = (e) => e.activePane, Mt = (e) => e.agents, Re = pe(null);
function _t() {
  const e = fe(Re);
  if (!e)
    throw new Error("useChatContext must be used within a ChatProvider");
  return e;
}
function Tt({
  config: e,
  children: r,
  autoLoadSessions: t = !1,
  // Changed to false - ChatWidget handles initialization
  autoLoadAgents: a = !1
  // Changed to false - ChatWidget handles initialization
}) {
  const n = W(() => new Ue(e), [e]), s = _(), [o, c] = $(s.isInitialized), d = k(() => {
    c(!0);
  }, []);
  L(() => {
    async function i() {
      var g;
      try {
        const [p, m] = await Promise.all([
          t ? n.getSessions() : Promise.resolve([]),
          a ? n.getAgents() : Promise.resolve([])
        ]);
        s.actions.initialize(p, m), c(!0);
      } catch (p) {
        console.error("[ChatProvider] Failed to initialize:", p), (g = e.onError) == null || g.call(e, p instanceof Error ? p : new Error(String(p)));
      }
    }
    (t || a) && !s.isInitialized && i();
  }, [n, s, t, a, e]);
  const u = W(() => ({
    apiClient: n,
    store: s,
    isInitialized: o,
    initialize: d
  }), [n, s, o, d]);
  return /* @__PURE__ */ l.createElement(Re.Provider, { value: u }, /* @__PURE__ */ l.createElement(he.Provider, { value: n }, r));
}
function Ct(e) {
  const { apiUrl: r, onAction: t, onTitleUpdate: a, onError: n } = e, s = P(null), o = P(null), c = P(null), d = _(), u = k((m) => {
    const b = m.data, { type: y, sessionId: S, data: f } = b;
    if (!S && y !== "STATE_SYNC") return;
    const h = d.actions;
    switch (y) {
      case "STREAM_START":
        S && h.startStream(S);
        break;
      case "CHUNK": {
        const E = f;
        S && (E != null && E.content) && h.appendStreamContent(S, E.content);
        break;
      }
      case "SYSTEM":
        break;
      case "TOOL_START": {
        const E = f;
        S && E && h.addActiveTool(S, {
          id: E.tool_id,
          name: E.tool_name,
          startedAt: Date.now()
        });
        break;
      }
      case "TOOL_END": {
        const E = f;
        S && E && h.removeActiveTool(S, E.tool_id || E.tool_name);
        break;
      }
      case "AGENT_START": {
        const E = f;
        S && E && h.addActiveAgent(S, {
          type: E.agent_type,
          model: E.agent_model,
          description: E.description,
          startedAt: Date.now()
        });
        break;
      }
      case "AGENT_END":
        break;
      case "ACTION": {
        const E = f;
        E && (t == null || t(E.type, E.target));
        break;
      }
      case "DONE":
      case "STREAM_END": {
        S && h.endStream(S);
        break;
      }
      case "STREAM_ABORTED": {
        S && h.abortStream(S);
        break;
      }
      case "ERROR": {
        const E = f;
        S && h.endStream(S), n == null || n(new Error((E == null ? void 0 : E.message) || "Stream error"));
        break;
      }
      case "TITLE_UPDATE": {
        const E = f;
        S && (E != null && E.title) && (a == null || a(S, E.title), h.updateSession(S, { displayName: E.title }));
        break;
      }
      case "STATE_SYNC": {
        const E = f;
        E && Object.entries(E).forEach(([N, C]) => {
          C.streaming && (h.startStream(N), C.streamContent && h.appendStreamContent(N, C.streamContent));
        });
        break;
      }
    }
  }, [d, t, a, n]);
  L(() => {
    if (typeof SharedWorker > "u") {
      console.warn("SharedWorker not supported, falling back to direct fetch");
      return;
    }
    try {
      const m = e.workerUrl || "/static/js/chat-worker.js";
      s.current = new SharedWorker(m, { name: "turbowrap-chat" }), o.current = s.current.port, o.current.onmessage = u, o.current.start(), o.current.postMessage({ type: "GET_STATE" }), c.current = setInterval(() => {
        var b;
        (b = o.current) == null || b.postMessage({ type: "PONG" });
      }, 3e4);
    } catch (m) {
      console.error("Failed to connect to SharedWorker:", m), n == null || n(m instanceof Error ? m : new Error("Worker connection failed"));
    }
    return () => {
      var m;
      c.current && clearInterval(c.current), (m = o.current) == null || m.close();
    };
  }, [e.workerUrl, u, n]);
  const i = k((m, b) => {
    if (!o.current) {
      n == null || n(new Error("Worker not connected"));
      return;
    }
    const y = {
      sessionId: m,
      content: b,
      apiUrl: r
    };
    o.current.postMessage({
      type: "SEND_MESSAGE",
      ...y
    });
  }, [r, n]), g = k((m) => {
    o.current && (o.current.postMessage({
      type: "STOP_STREAM",
      sessionId: m
    }), d.actions.abortStream(m));
  }, [d]), p = k((m) => {
    o.current && o.current.postMessage({
      type: "CLEAR_STATE",
      sessionId: m
    });
  }, []);
  return {
    sendMessage: i,
    stopStream: g,
    clearState: p,
    isConnected: !!o.current
  };
}
function $t() {
  return /* @__PURE__ */ l.createElement("svg", { className: "w-5 h-5", fill: "none", viewBox: "0 0 24 24", stroke: "currentColor" }, /* @__PURE__ */ l.createElement("path", { strokeLinecap: "round", strokeLinejoin: "round", strokeWidth: 2, d: "M4 6h16M4 12h16M4 18h16" }));
}
function At() {
  return /* @__PURE__ */ l.createElement("svg", { className: "w-5 h-5", fill: "none", viewBox: "0 0 24 24", stroke: "currentColor" }, /* @__PURE__ */ l.createElement("path", { strokeLinecap: "round", strokeLinejoin: "round", strokeWidth: 2, d: "M12 4v16m8-8H4" }));
}
function Dt() {
  return /* @__PURE__ */ l.createElement("svg", { className: "w-5 h-5", fill: "none", viewBox: "0 0 24 24", stroke: "currentColor" }, /* @__PURE__ */ l.createElement(
    "path",
    {
      strokeLinecap: "round",
      strokeLinejoin: "round",
      strokeWidth: 2,
      d: "M9 17V7m0 10a2 2 0 01-2 2H5a2 2 0 01-2-2V7a2 2 0 012-2h2a2 2 0 012 2m0 10a2 2 0 002 2h2a2 2 0 002-2M9 7a2 2 0 012-2h2a2 2 0 012 2m0 10V7m0 10a2 2 0 002 2h2a2 2 0 002-2V7a2 2 0 00-2-2h-2a2 2 0 00-2 2"
    }
  ));
}
function It() {
  return /* @__PURE__ */ l.createElement("svg", { className: "w-5 h-5", fill: "none", viewBox: "0 0 24 24", stroke: "currentColor" }, /* @__PURE__ */ l.createElement(
    "path",
    {
      strokeLinecap: "round",
      strokeLinejoin: "round",
      strokeWidth: 2,
      d: "M4 8V4m0 0h4M4 4l5 5m11-1V4m0 0h-4m4 0l-5 5M4 16v4m0 0h4m-4 0l5-5m11 5l-5-5m5 5v-4m0 4h-4"
    }
  ));
}
function Lt() {
  return /* @__PURE__ */ l.createElement("svg", { className: "w-5 h-5", fill: "none", viewBox: "0 0 24 24", stroke: "currentColor" }, /* @__PURE__ */ l.createElement("path", { strokeLinecap: "round", strokeLinejoin: "round", strokeWidth: 2, d: "M6 18L18 6M6 6l12 12" }));
}
function jt({
  onToggleHistory: e,
  onToggleDualChat: r,
  onNewChat: t,
  onExpand: a,
  onClose: n,
  chatMode: s,
  dualChatEnabled: o = !1,
  showHistory: c = !1,
  streamingCount: d = 0,
  className: u = "",
  children: i
}) {
  const [g, p] = l.useState(!1);
  return /* @__PURE__ */ l.createElement("div", { className: `flex items-center gap-1 px-2 py-1.5 border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 ${u}` }, /* @__PURE__ */ l.createElement(
    "button",
    {
      onClick: e,
      className: `p-1.5 rounded hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors ${c ? "bg-gray-200 dark:bg-gray-700" : ""}`,
      title: "Toggle history"
    },
    /* @__PURE__ */ l.createElement($t, null)
  ), /* @__PURE__ */ l.createElement("div", { className: "flex-1 flex items-center gap-1 overflow-x-auto" }, i), (s === "full" || s === "page") && /* @__PURE__ */ l.createElement(
    "button",
    {
      onClick: r,
      className: `p-1.5 rounded hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors ${o ? "bg-indigo-100 dark:bg-indigo-900 text-indigo-600" : ""}`,
      title: "Toggle dual chat"
    },
    /* @__PURE__ */ l.createElement(Dt, null)
  ), /* @__PURE__ */ l.createElement("div", { className: "relative" }, /* @__PURE__ */ l.createElement(
    "button",
    {
      onClick: () => p(!g),
      disabled: d >= 10,
      className: "p-1.5 rounded hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors disabled:opacity-50",
      title: "New chat"
    },
    /* @__PURE__ */ l.createElement(At, null),
    d > 0 && /* @__PURE__ */ l.createElement("span", { className: "absolute -top-1 -right-1 w-4 h-4 bg-amber-500 text-white text-[10px] rounded-full flex items-center justify-center" }, d)
  ), g && /* @__PURE__ */ l.createElement("div", { className: "absolute right-0 top-full mt-1 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg shadow-lg z-50 py-1 min-w-[140px]" }, /* @__PURE__ */ l.createElement(
    "button",
    {
      onClick: () => {
        t == null || t("claude"), p(!1);
      },
      className: "w-full px-3 py-2 text-left hover:bg-gray-100 dark:hover:bg-gray-700 flex items-center gap-2"
    },
    /* @__PURE__ */ l.createElement("span", { className: "w-5 h-5 rounded-full bg-orange-100 text-orange-600 flex items-center justify-center text-xs font-bold" }, "C"),
    "Claude Chat"
  ), /* @__PURE__ */ l.createElement(
    "button",
    {
      onClick: () => {
        t == null || t("gemini"), p(!1);
      },
      className: "w-full px-3 py-2 text-left hover:bg-gray-100 dark:hover:bg-gray-700 flex items-center gap-2"
    },
    /* @__PURE__ */ l.createElement("span", { className: "w-5 h-5 rounded-full bg-blue-100 text-blue-600 flex items-center justify-center text-xs font-bold" }, "G"),
    "Gemini Chat"
  ))), /* @__PURE__ */ l.createElement(
    "button",
    {
      onClick: a,
      className: "p-1.5 rounded hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors",
      title: "Expand"
    },
    /* @__PURE__ */ l.createElement(It, null)
  ), /* @__PURE__ */ l.createElement(
    "button",
    {
      onClick: n,
      className: "p-1.5 rounded hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors",
      title: "Close"
    },
    /* @__PURE__ */ l.createElement(Lt, null)
  ));
}
function Pt(e) {
  const t = (/* @__PURE__ */ new Date()).getTime() - e.getTime(), a = Math.floor(t / 6e4);
  if (a < 1) return "now";
  if (a < 60) return `${a}m`;
  const n = Math.floor(a / 60);
  return n < 24 ? `${n}h` : `${Math.floor(n / 24)}d`;
}
function Ot({
  session: e,
  isActive: r,
  isSecondary: t,
  onSelect: a,
  onContextMenu: n
}) {
  const s = e.lastMessageAt || e.updatedAt;
  return /* @__PURE__ */ l.createElement(
    "button",
    {
      onClick: a,
      onContextMenu: n,
      className: `flex items-center gap-1.5 px-2 py-1 rounded text-sm whitespace-nowrap transition-colors ${r ? "bg-white dark:bg-gray-700 shadow-sm" : t ? "bg-indigo-50 dark:bg-indigo-900/30 ring-1 ring-indigo-300" : "hover:bg-gray-200 dark:hover:bg-gray-700"}`
    },
    /* @__PURE__ */ l.createElement(
      "span",
      {
        className: `w-4 h-4 rounded-full flex items-center justify-center text-[10px] font-bold ${e.cliType === "gemini" ? "bg-blue-100 text-blue-600 dark:bg-blue-900 dark:text-blue-400" : "bg-orange-100 text-orange-600 dark:bg-orange-900 dark:text-orange-400"}`
      },
      e.cliType === "gemini" ? "G" : "C"
    ),
    /* @__PURE__ */ l.createElement("span", { className: "truncate max-w-[100px]" }, e.displayName || "Untitled"),
    /* @__PURE__ */ l.createElement("span", { className: "text-xs text-gray-400" }, Pt(s))
  );
}
function zt({
  sessions: e,
  activeSessionId: r,
  secondarySessionId: t,
  onSelect: a,
  onContextMenu: n,
  className: s = ""
}) {
  return e.length === 0 ? null : /* @__PURE__ */ l.createElement("div", { className: `flex items-center gap-1 overflow-x-auto ${s}` }, e.map((o) => /* @__PURE__ */ l.createElement(
    Ot,
    {
      key: o.id,
      session: o,
      isActive: o.id === r,
      isSecondary: o.id === t,
      onSelect: () => a(o.id),
      onContextMenu: (c) => {
        c.preventDefault(), n == null || n(o.id, c);
      }
    }
  )));
}
function Wt(e) {
  const r = /* @__PURE__ */ new Date(), t = new Date(r.getFullYear(), r.getMonth(), r.getDate()), a = new Date(e.getFullYear(), e.getMonth(), e.getDate()), n = Math.floor((t.getTime() - a.getTime()) / 864e5);
  return n === 0 ? "Today" : n === 1 ? "Yesterday" : n < 7 ? e.toLocaleDateString("en-US", { weekday: "long" }) : e.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}
function Ut(e) {
  return e ? e.includes("opus") ? "Opus" : e.includes("sonnet") ? "Sonnet" : e.includes("haiku") ? "Haiku" : e.includes("pro") ? "Pro" : e.includes("flash") ? "Flash" : "" : "";
}
function Bt({
  session: e,
  isActive: r,
  onSelect: t,
  onDelete: a
}) {
  const [n, s] = l.useState(!1);
  return /* @__PURE__ */ l.createElement(
    "div",
    {
      onMouseEnter: () => s(!0),
      onMouseLeave: () => s(!1),
      className: `group flex items-center gap-2 px-3 py-2 rounded-lg cursor-pointer transition-colors ${r ? "bg-indigo-50 dark:bg-indigo-900/30" : "hover:bg-gray-100 dark:hover:bg-gray-800"}`,
      onClick: t
    },
    /* @__PURE__ */ l.createElement(
      "span",
      {
        className: `w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold flex-shrink-0 ${e.cliType === "gemini" ? "bg-blue-100 text-blue-600 dark:bg-blue-900 dark:text-blue-400" : "bg-orange-100 text-orange-600 dark:bg-orange-900 dark:text-orange-400"}`
      },
      e.cliType === "gemini" ? "G" : "C"
    ),
    /* @__PURE__ */ l.createElement("div", { className: "flex-1 min-w-0" }, /* @__PURE__ */ l.createElement("div", { className: "flex items-center gap-2" }, /* @__PURE__ */ l.createElement("span", { className: "font-medium truncate" }, e.displayName || "Untitled Chat"), e.model && /* @__PURE__ */ l.createElement("span", { className: "text-xs text-gray-400" }, Ut(e.model))), /* @__PURE__ */ l.createElement("div", { className: "flex items-center gap-2 text-xs text-gray-400" }, /* @__PURE__ */ l.createElement("span", null, e.totalMessages, " messages"))),
    n && /* @__PURE__ */ l.createElement(
      "button",
      {
        onClick: (o) => {
          o.stopPropagation(), a();
        },
        className: "p-1 rounded hover:bg-red-100 dark:hover:bg-red-900/30 text-gray-400 hover:text-red-500"
      },
      /* @__PURE__ */ l.createElement("svg", { className: "w-4 h-4", fill: "none", viewBox: "0 0 24 24", stroke: "currentColor" }, /* @__PURE__ */ l.createElement(
        "path",
        {
          strokeLinecap: "round",
          strokeLinejoin: "round",
          strokeWidth: 2,
          d: "M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"
        }
      ))
    )
  );
}
function Ht({
  isOpen: e,
  sessions: r,
  activeSessionId: t,
  onClose: a,
  onSelect: n,
  onDelete: s,
  onNewChat: o,
  className: c = ""
}) {
  if (!e) return null;
  const d = r.reduce((u, i) => {
    const g = Wt(i.lastMessageAt || i.updatedAt);
    return u[g] || (u[g] = []), u[g].push(i), u;
  }, {});
  return /* @__PURE__ */ l.createElement(l.Fragment, null, /* @__PURE__ */ l.createElement(
    "div",
    {
      className: "absolute inset-0 bg-black/20 z-40",
      onClick: a
    }
  ), /* @__PURE__ */ l.createElement("div", { className: `absolute left-0 top-0 bottom-0 w-72 bg-white dark:bg-gray-900 border-r border-gray-200 dark:border-gray-700 z-50 flex flex-col animate-slide-in ${c}` }, /* @__PURE__ */ l.createElement("div", { className: "flex items-center justify-between px-4 py-3 border-b border-gray-200 dark:border-gray-700" }, /* @__PURE__ */ l.createElement("h3", { className: "font-semibold" }, "Chat History"), /* @__PURE__ */ l.createElement(
    "button",
    {
      onClick: a,
      className: "p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-800"
    },
    /* @__PURE__ */ l.createElement("svg", { className: "w-5 h-5", fill: "none", viewBox: "0 0 24 24", stroke: "currentColor" }, /* @__PURE__ */ l.createElement("path", { strokeLinecap: "round", strokeLinejoin: "round", strokeWidth: 2, d: "M6 18L18 6M6 6l12 12" }))
  )), /* @__PURE__ */ l.createElement("div", { className: "flex gap-2 px-4 py-3 border-b border-gray-200 dark:border-gray-700" }, /* @__PURE__ */ l.createElement(
    "button",
    {
      onClick: () => o("claude"),
      className: "flex-1 flex items-center justify-center gap-2 px-3 py-2 rounded-lg bg-orange-50 dark:bg-orange-900/20 text-orange-600 hover:bg-orange-100 dark:hover:bg-orange-900/30 transition-colors"
    },
    /* @__PURE__ */ l.createElement("span", { className: "w-5 h-5 rounded-full bg-orange-100 text-orange-600 flex items-center justify-center text-xs font-bold" }, "C"),
    "Claude"
  ), /* @__PURE__ */ l.createElement(
    "button",
    {
      onClick: () => o("gemini"),
      className: "flex-1 flex items-center justify-center gap-2 px-3 py-2 rounded-lg bg-blue-50 dark:bg-blue-900/20 text-blue-600 hover:bg-blue-100 dark:hover:bg-blue-900/30 transition-colors"
    },
    /* @__PURE__ */ l.createElement("span", { className: "w-5 h-5 rounded-full bg-blue-100 text-blue-600 flex items-center justify-center text-xs font-bold" }, "G"),
    "Gemini"
  )), /* @__PURE__ */ l.createElement("div", { className: "flex-1 overflow-y-auto chat-scrollbar" }, r.length === 0 ? /* @__PURE__ */ l.createElement("div", { className: "px-4 py-8 text-center text-gray-400" }, /* @__PURE__ */ l.createElement("p", null, "No chat history yet"), /* @__PURE__ */ l.createElement("p", { className: "text-sm mt-1" }, "Start a new chat to begin")) : Object.entries(d).map(([u, i]) => /* @__PURE__ */ l.createElement("div", { key: u, className: "px-2 py-2" }, /* @__PURE__ */ l.createElement("div", { className: "px-2 py-1 text-xs text-gray-400 font-medium" }, u), /* @__PURE__ */ l.createElement("div", { className: "space-y-1" }, i.map((g) => /* @__PURE__ */ l.createElement(
    Bt,
    {
      key: g.id,
      session: g,
      isActive: g.id === t,
      onSelect: () => n(g.id),
      onDelete: () => s(g.id)
    }
  ))))))));
}
function Ft(e) {
  return e === "gemini" ? [
    { value: "gemini-2.0-flash-exp", label: "Flash" },
    { value: "gemini-exp-1206", label: "Pro" }
  ] : [
    { value: "opus", label: "Opus" },
    { value: "sonnet", label: "Sonnet" },
    { value: "haiku", label: "Haiku" }
  ];
}
function Vt(e) {
  return e ? e.includes("opus") ? "Opus" : e.includes("sonnet") ? "Sonnet" : e.includes("haiku") ? "Haiku" : e.includes("flash") ? "Flash" : e.includes("pro") ? "Pro" : e.split("-")[0] : "Select";
}
function Z() {
  return /* @__PURE__ */ React.createElement("svg", { className: "w-3 h-3", fill: "none", viewBox: "0 0 24 24", stroke: "currentColor" }, /* @__PURE__ */ React.createElement("path", { strokeLinecap: "round", strokeLinejoin: "round", strokeWidth: 2, d: "M19 9l-7 7-7-7" }));
}
function Gt() {
  return /* @__PURE__ */ React.createElement("svg", { className: "w-4 h-4", fill: "none", viewBox: "0 0 24 24", stroke: "currentColor" }, /* @__PURE__ */ React.createElement(
    "path",
    {
      strokeLinecap: "round",
      strokeLinejoin: "round",
      strokeWidth: 2,
      d: "M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
    }
  ));
}
function Jt({
  session: e,
  repository: r,
  branches: t = [],
  currentBranch: a,
  onModelChange: n,
  onRepoClick: s,
  onBranchChange: o,
  onInfoClick: c,
  className: d = ""
}) {
  const [u, i] = $(!1), [g, p] = $(!1), m = Ft(e.cliType);
  return /* @__PURE__ */ React.createElement("div", { className: `flex items-center gap-2 px-3 py-2 bg-gray-50 dark:bg-gray-800/50 border-b border-gray-200 dark:border-gray-700 text-sm ${d}` }, /* @__PURE__ */ React.createElement(
    "span",
    {
      className: `w-5 h-5 rounded-full flex items-center justify-center text-xs font-bold ${e.cliType === "gemini" ? "bg-blue-100 text-blue-600 dark:bg-blue-900 dark:text-blue-400" : "bg-orange-100 text-orange-600 dark:bg-orange-900 dark:text-orange-400"}`
    },
    e.cliType === "gemini" ? "G" : "C"
  ), /* @__PURE__ */ React.createElement("div", { className: "relative" }, /* @__PURE__ */ React.createElement(
    "button",
    {
      onClick: () => i(!u),
      className: "flex items-center gap-1 px-2 py-1 rounded hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors"
    },
    /* @__PURE__ */ React.createElement("span", null, Vt(e.model)),
    /* @__PURE__ */ React.createElement(Z, null)
  ), u && /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement(
    "div",
    {
      className: "fixed inset-0 z-40",
      onClick: () => i(!1)
    }
  ), /* @__PURE__ */ React.createElement("div", { className: "absolute left-0 top-full mt-1 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg shadow-lg z-50 py-1 min-w-[100px]" }, m.map((b) => {
    var y;
    return /* @__PURE__ */ React.createElement(
      "button",
      {
        key: b.value,
        onClick: () => {
          n(b.value), i(!1);
        },
        className: `w-full px-3 py-1.5 text-left hover:bg-gray-100 dark:hover:bg-gray-700 ${(y = e.model) != null && y.includes(b.value.toLowerCase()) ? "bg-indigo-50 dark:bg-indigo-900/30 text-indigo-600" : ""}`
      },
      b.label
    );
  })))), /* @__PURE__ */ React.createElement("span", { className: "text-gray-300 dark:text-gray-600" }, "|"), /* @__PURE__ */ React.createElement(
    "button",
    {
      onClick: s,
      className: "flex items-center gap-1 px-2 py-1 rounded hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors truncate max-w-[150px]"
    },
    /* @__PURE__ */ React.createElement("span", { className: "truncate" }, (r == null ? void 0 : r.name) || "Select repo"),
    /* @__PURE__ */ React.createElement(Z, null)
  ), r && t.length > 0 && o && /* @__PURE__ */ React.createElement("div", { className: "relative" }, /* @__PURE__ */ React.createElement(
    "button",
    {
      onClick: () => p(!g),
      className: "flex items-center gap-1 px-2 py-1 rounded hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors text-gray-500"
    },
    /* @__PURE__ */ React.createElement("span", { className: "truncate max-w-[100px]" }, a || "main"),
    /* @__PURE__ */ React.createElement(Z, null)
  ), g && /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement(
    "div",
    {
      className: "fixed inset-0 z-40",
      onClick: () => p(!1)
    }
  ), /* @__PURE__ */ React.createElement("div", { className: "absolute left-0 top-full mt-1 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg shadow-lg z-50 py-1 min-w-[120px] max-h-48 overflow-y-auto" }, t.map((b) => /* @__PURE__ */ React.createElement(
    "button",
    {
      key: b,
      onClick: () => {
        o(b), p(!1);
      },
      className: `w-full px-3 py-1.5 text-left hover:bg-gray-100 dark:hover:bg-gray-700 truncate ${b === a ? "bg-indigo-50 dark:bg-indigo-900/30 text-indigo-600" : ""}`
    },
    b
  ))))), /* @__PURE__ */ React.createElement("div", { className: "flex-1" }), /* @__PURE__ */ React.createElement(
    "button",
    {
      onClick: c,
      className: "p-1 rounded hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors text-gray-500",
      title: "Session info"
    },
    /* @__PURE__ */ React.createElement(Gt, null)
  ));
}
function ae({
  content: e,
  role: r = "assistant",
  className: t = ""
}) {
  const a = W(() => qt(e), [e, r]);
  return /* @__PURE__ */ React.createElement(
    "div",
    {
      className: `message-content prose prose-sm dark:prose-invert max-w-none ${t}`,
      dangerouslySetInnerHTML: { __html: a }
    }
  );
}
function qt(e, r) {
  if (!e) return "";
  let t = e;
  return t = Qt(t), t = t.replace(
    /```(\w+)?\n([\s\S]*?)```/g,
    (a, n, s) => {
      const o = n || "text", c = s.trim();
      return `<div class="chat-code-block">
        <div class="chat-code-header">
          <span>${o}</span>
          <button class="copy-btn text-xs hover:text-white" onclick="navigator.clipboard.writeText(this.closest('.chat-code-block').querySelector('code').textContent)">Copy</button>
        </div>
        <pre class="chat-code-content"><code class="language-${o}">${c}</code></pre>
      </div>`;
    }
  ), t = t.replace(/`([^`]+)`/g, '<code class="bg-gray-100 dark:bg-gray-800 px-1.5 py-0.5 rounded text-sm font-mono">$1</code>'), t = t.replace(
    /\[!(INFO|WARNING|ERROR|SUCCESS|TIP)\]\s*\n?([\s\S]*?)(?=\n\n|\n\[!|$)/gi,
    (a, n, s) => {
      const o = n.toLowerCase();
      return `<div class="chat-callout chat-callout-${o}">
        <span class="mr-2">${{
        info: "💡",
        warning: "⚠️",
        error: "❌",
        success: "✅",
        tip: "💡"
      }[o] || "📌"}</span>
        <span>${s.trim()}</span>
      </div>`;
    }
  ), t = t.replace(/^######\s+(.+)$/gm, '<h6 class="text-xs font-semibold mt-3 mb-1">$1</h6>'), t = t.replace(/^#####\s+(.+)$/gm, '<h5 class="text-sm font-semibold mt-3 mb-1">$1</h5>'), t = t.replace(/^####\s+(.+)$/gm, '<h4 class="text-base font-semibold mt-4 mb-2">$1</h4>'), t = t.replace(/^###\s+(.+)$/gm, '<h3 class="text-lg font-bold mt-4 mb-2">$1</h3>'), t = t.replace(/^##\s+(.+)$/gm, '<h2 class="text-xl font-bold mt-5 mb-2 text-indigo-600 dark:text-indigo-400">$1</h2>'), t = t.replace(/^#\s+(.+)$/gm, '<h1 class="text-2xl font-bold mt-6 mb-3 bg-gradient-to-r from-indigo-600 to-purple-600 bg-clip-text text-transparent">$1</h1>'), t = t.replace(/\*\*\*(.+?)\*\*\*/g, "<strong><em>$1</em></strong>"), t = t.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>"), t = t.replace(/\*(.+?)\*/g, "<em>$1</em>"), t = t.replace(/__(.+?)__/g, "<strong>$1</strong>"), t = t.replace(/_(.+?)_/g, "<em>$1</em>"), t = t.replace(/~~(.+?)~~/g, '<del class="text-gray-500">$1</del>'), t = t.replace(/==(.+?)==/g, '<mark class="bg-yellow-200 dark:bg-yellow-800 px-0.5 rounded">$1</mark>'), t = t.replace(/^---$/gm, '<hr class="my-4 border-gray-300 dark:border-gray-600">'), t = t.replace(
    /^>\s+(.+)$/gm,
    '<blockquote class="border-l-4 border-gray-300 dark:border-gray-600 pl-4 italic text-gray-600 dark:text-gray-400">$1</blockquote>'
  ), t = t.replace(/^[-*]\s+(.+)$/gm, '<li class="ml-4">$1</li>'), t = t.replace(/(<li.*<\/li>\n?)+/g, '<ul class="list-disc list-inside my-2">$&</ul>'), t = t.replace(/^\d+\.\s+(.+)$/gm, '<li class="ml-4">$1</li>'), t = t.replace(
    /^- \[x\]\s+(.+)$/gm,
    '<li class="ml-4 flex items-center gap-2"><input type="checkbox" checked disabled class="rounded text-indigo-500"><span class="line-through text-gray-500">$1</span></li>'
  ), t = t.replace(
    /^- \[ \]\s+(.+)$/gm,
    '<li class="ml-4 flex items-center gap-2"><input type="checkbox" disabled class="rounded"><span>$1</span></li>'
  ), t = t.replace(
    /\[([^\]]+)\]\(([^)]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener noreferrer" class="text-indigo-600 dark:text-indigo-400 hover:underline">$1</a>'
  ), t = t.replace(
    new RegExp('(?<!href="|src=")(https?:\\/\\/[^\\s<]+)', "g"),
    '<a href="$1" target="_blank" rel="noopener noreferrer" class="text-indigo-600 dark:text-indigo-400 hover:underline">$1</a>'
  ), t = Kt(t), t = t.replace(
    /<details>\s*<summary>([^<]+)<\/summary>([\s\S]*?)<\/details>/g,
    `<details class="my-2 border border-gray-200 dark:border-gray-700 rounded-lg">
      <summary class="px-3 py-2 cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-800 font-medium">$1</summary>
      <div class="px-3 py-2 border-t border-gray-200 dark:border-gray-700">$2</div>
    </details>`
  ), t = t.replace(/\n\n/g, '</p><p class="my-2">'), t = t.replace(/\n/g, "<br>"), t.startsWith("<") || (t = `<p class="my-2">${t}</p>`), t;
}
function Kt(e) {
  const r = /\|(.+)\|\n\|[-:\s|]+\|\n((?:\|.+\|\n?)+)/g;
  return e.replace(r, (t, a, n) => {
    const s = a.split("|").filter((u) => u.trim()), o = n.trim().split(`
`).map(
      (u) => u.split("|").filter((i) => i.trim())
    ), c = s.map((u) => `<th class="px-3 py-2 text-left font-semibold">${u.trim()}</th>`).join(""), d = o.map(
      (u) => `<tr class="border-t border-gray-200 dark:border-gray-700">${u.map((i) => `<td class="px-3 py-2">${i.trim()}</td>`).join("")}</tr>`
    ).join("");
    return `<table class="w-full my-3 border border-gray-200 dark:border-gray-700 rounded-lg overflow-hidden">
      <thead class="bg-gray-50 dark:bg-gray-800">
        <tr>${c}</tr>
      </thead>
      <tbody>${d}</tbody>
    </table>`;
  });
}
function me(e) {
  return e.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#039;");
}
function Qt(e) {
  const r = [];
  let t = e.replace(/```(\w+)?\n([\s\S]*?)```/g, (a, n, s) => {
    const o = n ? me(n) : "", c = me(s), d = `\`\`\`${o}
${c}\`\`\``;
    return r.push(d), `__CODE_BLOCK_${r.length - 1}__`;
  });
  return t = t.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"), r.forEach((a, n) => {
    t = t.replace(`__CODE_BLOCK_${n}__`, a);
  }), t;
}
function Yt(e) {
  const r = e.input;
  return r ? r.file_path ? String(r.file_path).split("/").pop() || e.name : r.pattern ? String(r.pattern).slice(0, 30) : r.command ? String(r.command).slice(0, 40) : r.query ? String(r.query).slice(0, 30) : r.url ? String(r.url).slice(0, 40) : e.name : e.name;
}
function H({
  tool: e,
  agent: r,
  className: t = ""
}) {
  return r ? /* @__PURE__ */ React.createElement("div", { className: `chat-agent-indicator ${t}` }, /* @__PURE__ */ React.createElement("svg", { className: "w-4 h-4", fill: "none", viewBox: "0 0 24 24", stroke: "currentColor" }, /* @__PURE__ */ React.createElement(
    "path",
    {
      strokeLinecap: "round",
      strokeLinejoin: "round",
      strokeWidth: 2,
      d: "M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z"
    }
  )), /* @__PURE__ */ React.createElement("span", { className: "font-medium" }, "Task"), /* @__PURE__ */ React.createElement("span", { className: "text-gray-400 truncate max-w-[200px]" }, r.description)) : e ? /* @__PURE__ */ React.createElement("div", { className: `chat-tool-indicator ${t}` }, /* @__PURE__ */ React.createElement("svg", { className: "w-4 h-4 animate-spin", fill: "none", viewBox: "0 0 24 24", stroke: "currentColor" }, /* @__PURE__ */ React.createElement(
    "path",
    {
      strokeLinecap: "round",
      strokeLinejoin: "round",
      strokeWidth: 2,
      d: "M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"
    }
  ), /* @__PURE__ */ React.createElement(
    "path",
    {
      strokeLinecap: "round",
      strokeLinejoin: "round",
      strokeWidth: 2,
      d: "M15 12a3 3 0 11-6 0 3 3 0 016 0z"
    }
  )), /* @__PURE__ */ React.createElement("span", { className: "font-medium" }, e.name), /* @__PURE__ */ React.createElement("span", { className: "text-gray-400 truncate max-w-[200px]" }, Yt(e))) : null;
}
function ge(e) {
  return e.toLocaleTimeString("it-IT", {
    hour: "2-digit",
    minute: "2-digit"
  });
}
function Xt({
  message: e,
  className: r = ""
}) {
  const t = e.role === "user", a = e.role === "system";
  return e.segments && e.segments.length > 0 ? /* @__PURE__ */ React.createElement("div", { className: `flex flex-col gap-2 ${t ? "items-end" : "items-start"} ${r}` }, e.segments.map((n, s) => /* @__PURE__ */ React.createElement(Zt, { key: s, segment: n, isUser: t })), /* @__PURE__ */ React.createElement("span", { className: "text-xs text-gray-400 mt-1" }, ge(e.createdAt))) : /* @__PURE__ */ React.createElement("div", { className: `flex flex-col ${t ? "items-end" : "items-start"} ${r}` }, /* @__PURE__ */ React.createElement(
    "div",
    {
      className: t ? "chat-message-user" : a ? "chat-message-assistant bg-gray-100 dark:bg-gray-700 text-sm" : "chat-message-assistant"
    },
    /* @__PURE__ */ React.createElement(ae, { content: e.content, role: e.role })
  ), /* @__PURE__ */ React.createElement("span", { className: "text-xs text-gray-400 mt-1" }, ge(e.createdAt)));
}
function Zt({
  segment: e,
  isUser: r
}) {
  var t;
  return e.type === "tool" ? /* @__PURE__ */ React.createElement(
    H,
    {
      tool: {
        name: e.name || "Tool",
        id: e.id || "",
        startedAt: e.completedAt || Date.now(),
        input: e.input
      }
    }
  ) : e.type === "agent" ? /* @__PURE__ */ React.createElement(
    H,
    {
      agent: {
        type: e.agentType || "Task",
        model: e.model || "",
        description: e.description || "",
        startedAt: e.launchedAt || Date.now()
      }
    }
  ) : (t = e.content) != null && t.trim() ? /* @__PURE__ */ React.createElement("div", { className: r ? "chat-message-user" : "chat-message-assistant" }, /* @__PURE__ */ React.createElement(ae, { content: e.content, role: r ? "user" : "assistant" })) : null;
}
function er() {
  return /* @__PURE__ */ React.createElement("div", { className: "flex items-center gap-1 py-2" }, /* @__PURE__ */ React.createElement("div", { className: "w-2 h-2 bg-gray-400 rounded-full animate-bounce-dot animate-bounce-dot-1" }), /* @__PURE__ */ React.createElement("div", { className: "w-2 h-2 bg-gray-400 rounded-full animate-bounce-dot animate-bounce-dot-2" }), /* @__PURE__ */ React.createElement("div", { className: "w-2 h-2 bg-gray-400 rounded-full animate-bounce-dot animate-bounce-dot-3" }));
}
function tr({
  content: e,
  segments: r = [],
  activeTools: t = [],
  activeAgents: a = [],
  className: n = ""
}) {
  const s = r || [], o = t || [], c = a || [];
  return !e && s.every((d) => {
    var u;
    return !((u = d.content) != null && u.trim());
  }) && o.length === 0 ? /* @__PURE__ */ React.createElement("div", { className: `flex items-start ${n}` }, /* @__PURE__ */ React.createElement("div", { className: "chat-message-assistant" }, /* @__PURE__ */ React.createElement(er, null))) : /* @__PURE__ */ React.createElement("div", { className: `flex flex-col items-start gap-2 ${n}` }, s.map((d, u) => /* @__PURE__ */ React.createElement(rr, { key: u, segment: d, isLast: u === s.length - 1 })), o.map((d) => /* @__PURE__ */ React.createElement(H, { key: d.id, tool: d })), c.map((d, u) => /* @__PURE__ */ React.createElement(H, { key: `agent-${u}`, agent: d })));
}
function rr({
  segment: e,
  isLast: r
}) {
  var t;
  return e.type === "tool" ? /* @__PURE__ */ React.createElement(
    H,
    {
      tool: {
        name: e.name || "Tool",
        id: e.id || "",
        startedAt: e.completedAt || Date.now(),
        input: e.input
      }
    }
  ) : e.type === "agent" ? /* @__PURE__ */ React.createElement(
    H,
    {
      agent: {
        type: e.agentType || "Task",
        model: e.model || "",
        description: e.description || "",
        startedAt: e.launchedAt || Date.now()
      }
    }
  ) : (t = e.content) != null && t.trim() ? /* @__PURE__ */ React.createElement("div", { className: "chat-message-assistant" }, /* @__PURE__ */ React.createElement(ae, { content: e.content, role: "assistant" }), r && /* @__PURE__ */ React.createElement("span", { className: "inline-block w-2 h-4 bg-indigo-500 ml-0.5 animate-blink" })) : null;
}
function ar({ cliType: e }) {
  return /* @__PURE__ */ React.createElement("div", { className: "flex flex-col items-center justify-center h-full py-12 text-gray-400" }, /* @__PURE__ */ React.createElement(
    "div",
    {
      className: `w-16 h-16 rounded-full flex items-center justify-center text-2xl font-bold mb-4 ${e === "gemini" ? "bg-blue-100 text-blue-600 dark:bg-blue-900 dark:text-blue-400" : "bg-orange-100 text-orange-600 dark:bg-orange-900 dark:text-orange-400"}`
    },
    e === "gemini" ? "G" : "C"
  ), /* @__PURE__ */ React.createElement("p", { className: "text-lg font-medium" }, "Start the conversation"), /* @__PURE__ */ React.createElement("p", { className: "text-sm mt-1" }, "Write a message to chat with the AI"));
}
function Ne({
  messages: e,
  isStreaming: r = !1,
  streamContent: t = "",
  streamSegments: a = [],
  activeTools: n = [],
  activeAgents: s = [],
  className: o = ""
}) {
  const c = P(null), d = P(null);
  return L(() => {
    var u;
    (u = d.current) == null || u.scrollIntoView({ behavior: "smooth" });
  }, [e.length, r]), e.length === 0 && !r ? /* @__PURE__ */ React.createElement("div", { className: `flex-1 overflow-y-auto chat-scrollbar ${o}` }, /* @__PURE__ */ React.createElement(ar, null)) : /* @__PURE__ */ React.createElement(
    "div",
    {
      ref: c,
      className: `flex-1 overflow-y-auto chat-scrollbar p-4 space-y-4 ${o}`
    },
    e.map((u) => /* @__PURE__ */ React.createElement(
      Xt,
      {
        key: u.id,
        message: u,
        className: "animate-fade-in-up"
      }
    )),
    r && /* @__PURE__ */ React.createElement(
      tr,
      {
        content: t,
        segments: a,
        activeTools: n,
        activeAgents: s,
        className: "animate-fade-in-up"
      }
    ),
    /* @__PURE__ */ React.createElement("div", { ref: d })
  );
}
function nr() {
  return /* @__PURE__ */ l.createElement("svg", { className: "w-5 h-5", fill: "none", viewBox: "0 0 24 24", stroke: "currentColor" }, /* @__PURE__ */ l.createElement(
    "path",
    {
      strokeLinecap: "round",
      strokeLinejoin: "round",
      strokeWidth: 2,
      d: "M12 19l9 2-9-18-9 18 9-2zm0 0v-8"
    }
  ));
}
function sr() {
  return /* @__PURE__ */ l.createElement("svg", { className: "w-5 h-5", fill: "currentColor", viewBox: "0 0 24 24" }, /* @__PURE__ */ l.createElement("rect", { x: "6", y: "6", width: "12", height: "12", rx: "2" }));
}
function or() {
  return /* @__PURE__ */ l.createElement("svg", { className: "w-5 h-5", fill: "none", viewBox: "0 0 24 24", stroke: "currentColor" }, /* @__PURE__ */ l.createElement(
    "path",
    {
      strokeLinecap: "round",
      strokeLinejoin: "round",
      strokeWidth: 2,
      d: "M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"
    }
  ));
}
function Me({
  onSend: e,
  onStop: r,
  isStreaming: t = !1,
  pendingMessage: a,
  onClearPending: n,
  disabled: s = !1,
  placeholder: o = "Write a message...",
  className: c = ""
}) {
  const [d, u] = $(""), i = P(null), g = k(() => {
    const h = i.current;
    h && (h.style.height = "auto", h.style.height = `${Math.min(h.scrollHeight, 120)}px`);
  }, []);
  L(() => {
    g();
  }, [d, g]);
  const p = k(() => {
    const h = d.trim();
    !h || s || (e(h), u(""), i.current && (i.current.style.height = "auto"));
  }, [d, s, e]), m = k(
    (h) => {
      h.key === "Enter" && !h.shiftKey && !h.ctrlKey && (h.preventDefault(), p());
    },
    [p]
  ), b = d.trim().length > 0, y = t && b, S = t && !b, f = !t && b;
  return /* @__PURE__ */ l.createElement("div", { className: `border-t border-gray-200 dark:border-gray-700 p-3 ${c}` }, a && /* @__PURE__ */ l.createElement("div", { className: "mb-2 px-3 py-2 bg-amber-50 dark:bg-amber-900/20 rounded-lg flex items-center justify-between text-sm" }, /* @__PURE__ */ l.createElement("span", { className: "text-amber-700 dark:text-amber-300 truncate" }, "Queued: ", a.slice(0, 30), "..."), /* @__PURE__ */ l.createElement(
    "button",
    {
      onClick: n,
      className: "text-amber-600 hover:text-amber-800 dark:text-amber-400"
    },
    /* @__PURE__ */ l.createElement("svg", { className: "w-4 h-4", fill: "none", viewBox: "0 0 24 24", stroke: "currentColor" }, /* @__PURE__ */ l.createElement("path", { strokeLinecap: "round", strokeLinejoin: "round", strokeWidth: 2, d: "M6 18L18 6M6 6l12 12" }))
  )), /* @__PURE__ */ l.createElement("div", { className: "flex items-end gap-2" }, /* @__PURE__ */ l.createElement("div", { className: "flex-1 relative" }, /* @__PURE__ */ l.createElement(
    "textarea",
    {
      ref: i,
      value: d,
      onChange: (h) => u(h.target.value),
      onKeyDown: m,
      placeholder: t ? "Write to queue..." : o,
      disabled: s,
      className: "chat-input w-full px-4 py-3 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 focus:ring-2 focus:ring-indigo-500 focus:border-transparent resize-none",
      rows: 1
    }
  )), /* @__PURE__ */ l.createElement(
    "button",
    {
      onClick: S ? r : p,
      disabled: s || !f && !y && !S,
      className: `chat-send-button ${S ? "chat-send-button-stop" : y ? "chat-send-button-queue" : "chat-send-button-primary"}`
    },
    S ? /* @__PURE__ */ l.createElement(sr, null) : y ? /* @__PURE__ */ l.createElement(or, null) : /* @__PURE__ */ l.createElement(nr, null)
  )));
}
function cr() {
  return /* @__PURE__ */ React.createElement("svg", { className: "w-4 h-4", fill: "none", viewBox: "0 0 24 24", stroke: "currentColor" }, /* @__PURE__ */ React.createElement(
    "path",
    {
      strokeLinecap: "round",
      strokeLinejoin: "round",
      strokeWidth: 2,
      d: "M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
    }
  ));
}
function ir() {
  return /* @__PURE__ */ React.createElement("svg", { className: "w-5 h-5", fill: "none", viewBox: "0 0 24 24", stroke: "currentColor" }, /* @__PURE__ */ React.createElement("path", { strokeLinecap: "round", strokeLinejoin: "round", strokeWidth: 2, d: "M6 18L18 6M6 6l12 12" }));
}
function lr() {
  return /* @__PURE__ */ React.createElement("svg", { className: "w-5 h-5", fill: "none", viewBox: "0 0 24 24", stroke: "currentColor" }, /* @__PURE__ */ React.createElement(
    "path",
    {
      strokeLinecap: "round",
      strokeLinejoin: "round",
      strokeWidth: 2,
      d: "M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"
    }
  ));
}
function dr({
  isOpen: e,
  repositories: r,
  selectedRepoId: t,
  isLoading: a = !1,
  onSelect: n,
  onClose: s,
  className: o = ""
}) {
  const [c, d] = $(""), u = W(() => {
    if (!c.trim()) return r;
    const g = c.toLowerCase();
    return r.filter(
      (p) => {
        var m;
        return p.name.toLowerCase().includes(g) || ((m = p.fullName) == null ? void 0 : m.toLowerCase().includes(g));
      }
    );
  }, [r, c]), i = () => {
    d(""), s();
  };
  return e ? /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement(
    "div",
    {
      className: "fixed inset-0 bg-black/50 z-50",
      onClick: i
    }
  ), /* @__PURE__ */ React.createElement("div", { className: `fixed inset-0 z-50 flex items-center justify-center p-4 ${o}` }, /* @__PURE__ */ React.createElement(
    "div",
    {
      className: "bg-white dark:bg-gray-900 rounded-xl shadow-2xl w-full max-w-lg max-h-[80vh] flex flex-col",
      onClick: (g) => g.stopPropagation()
    },
    /* @__PURE__ */ React.createElement("div", { className: "flex items-center justify-between px-4 py-3 border-b border-gray-200 dark:border-gray-700" }, /* @__PURE__ */ React.createElement("h2", { className: "text-lg font-semibold" }, "Select Repository"), /* @__PURE__ */ React.createElement(
      "button",
      {
        onClick: i,
        className: "p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
      },
      /* @__PURE__ */ React.createElement(ir, null)
    )),
    /* @__PURE__ */ React.createElement("div", { className: "px-4 py-3 border-b border-gray-200 dark:border-gray-700" }, /* @__PURE__ */ React.createElement("div", { className: "relative" }, /* @__PURE__ */ React.createElement("span", { className: "absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" }, /* @__PURE__ */ React.createElement(cr, null)), /* @__PURE__ */ React.createElement(
      "input",
      {
        type: "text",
        value: c,
        onChange: (g) => d(g.target.value),
        placeholder: "Search repositories...",
        className: "w-full pl-10 pr-4 py-2 bg-gray-100 dark:bg-gray-800 border border-transparent focus:border-indigo-500 rounded-lg outline-none transition-colors",
        autoFocus: !0
      }
    ))),
    /* @__PURE__ */ React.createElement("div", { className: "flex-1 overflow-y-auto" }, a ? /* @__PURE__ */ React.createElement("div", { className: "flex items-center justify-center py-12" }, /* @__PURE__ */ React.createElement("div", { className: "animate-spin w-8 h-8 border-2 border-indigo-500 border-t-transparent rounded-full" })) : u.length === 0 ? /* @__PURE__ */ React.createElement("div", { className: "text-center py-12 text-gray-500" }, c ? "No repositories match your search" : "No repositories available") : /* @__PURE__ */ React.createElement("div", { className: "py-2" }, u.map((g) => /* @__PURE__ */ React.createElement(
      "button",
      {
        key: g.id,
        onClick: () => {
          n(g.id), i();
        },
        className: `w-full px-4 py-3 flex items-center gap-3 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors ${g.id === t ? "bg-indigo-50 dark:bg-indigo-900/30" : ""}`
      },
      /* @__PURE__ */ React.createElement("span", { className: "text-gray-400" }, /* @__PURE__ */ React.createElement(lr, null)),
      /* @__PURE__ */ React.createElement("div", { className: "flex-1 text-left" }, /* @__PURE__ */ React.createElement("div", { className: "font-medium" }, g.name), g.fullName && g.fullName !== g.name && /* @__PURE__ */ React.createElement("div", { className: "text-sm text-gray-500" }, g.fullName)),
      g.id === t && /* @__PURE__ */ React.createElement("span", { className: "text-indigo-600 dark:text-indigo-400" }, /* @__PURE__ */ React.createElement("svg", { className: "w-5 h-5", fill: "currentColor", viewBox: "0 0 20 20" }, /* @__PURE__ */ React.createElement(
        "path",
        {
          fillRule: "evenodd",
          d: "M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z",
          clipRule: "evenodd"
        }
      )))
    ))))
  ))) : null;
}
function ur() {
  return /* @__PURE__ */ React.createElement("svg", { className: "w-5 h-5", fill: "none", viewBox: "0 0 24 24", stroke: "currentColor" }, /* @__PURE__ */ React.createElement("path", { strokeLinecap: "round", strokeLinejoin: "round", strokeWidth: 2, d: "M6 18L18 6M6 6l12 12" }));
}
function z(e) {
  return e.toLocaleString();
}
function mr(e) {
  return `$${e.toFixed(4)}`;
}
function gr({
  value: e,
  max: r,
  label: t,
  color: a = "indigo"
}) {
  const n = Math.min(100, e / r * 100), s = {
    indigo: "bg-indigo-500",
    green: "bg-green-500",
    amber: "bg-amber-500",
    red: "bg-red-500"
  };
  return /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("div", { className: "flex justify-between text-sm mb-1" }, /* @__PURE__ */ React.createElement("span", { className: "text-gray-600 dark:text-gray-400" }, t), /* @__PURE__ */ React.createElement("span", { className: "font-mono" }, z(e), " / ", z(r))), /* @__PURE__ */ React.createElement("div", { className: "h-2 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden" }, /* @__PURE__ */ React.createElement(
    "div",
    {
      className: `h-full ${s[a]} transition-all duration-300`,
      style: { width: `${n}%` }
    }
  )));
}
function j({ label: e, value: r }) {
  return /* @__PURE__ */ React.createElement("div", { className: "flex justify-between py-2 border-b border-gray-100 dark:border-gray-800 last:border-0" }, /* @__PURE__ */ React.createElement("span", { className: "text-gray-500 dark:text-gray-400" }, e), /* @__PURE__ */ React.createElement("span", { className: "font-medium" }, r));
}
function pr({
  isOpen: e,
  session: r,
  contextInfo: t,
  usageInfo: a,
  onClose: n,
  className: s = ""
}) {
  if (!e || !r) return null;
  const o = t ? t.tokens.used / t.tokens.limit * 100 : 0, c = o > 90 ? "red" : o > 70 ? "amber" : "indigo";
  return /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("div", { className: "fixed inset-0 bg-black/50 z-50", onClick: n }), /* @__PURE__ */ React.createElement("div", { className: `fixed inset-0 z-50 flex items-center justify-center p-4 ${s}` }, /* @__PURE__ */ React.createElement(
    "div",
    {
      className: "bg-white dark:bg-gray-900 rounded-xl shadow-2xl w-full max-w-md",
      onClick: (d) => d.stopPropagation()
    },
    /* @__PURE__ */ React.createElement("div", { className: "flex items-center justify-between px-4 py-3 border-b border-gray-200 dark:border-gray-700" }, /* @__PURE__ */ React.createElement("h2", { className: "text-lg font-semibold" }, "Session Info"), /* @__PURE__ */ React.createElement(
      "button",
      {
        onClick: n,
        className: "p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
      },
      /* @__PURE__ */ React.createElement(ur, null)
    )),
    /* @__PURE__ */ React.createElement("div", { className: "p-4 space-y-6" }, /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("h3", { className: "text-sm font-medium text-gray-500 dark:text-gray-400 mb-2" }, "Session"), /* @__PURE__ */ React.createElement("div", { className: "bg-gray-50 dark:bg-gray-800 rounded-lg p-3" }, /* @__PURE__ */ React.createElement(j, { label: "Name", value: r.displayName || "Untitled" }), /* @__PURE__ */ React.createElement(
      j,
      {
        label: "CLI Type",
        value: /* @__PURE__ */ React.createElement(
          "span",
          {
            className: `px-2 py-0.5 rounded text-xs font-medium ${r.cliType === "gemini" ? "bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300" : "bg-orange-100 text-orange-700 dark:bg-orange-900 dark:text-orange-300"}`
          },
          r.cliType === "gemini" ? "Gemini CLI" : "Claude CLI"
        )
      }
    ), /* @__PURE__ */ React.createElement(j, { label: "Model", value: r.model || "Not set" }), /* @__PURE__ */ React.createElement(j, { label: "Messages", value: r.totalMessages }), /* @__PURE__ */ React.createElement(
      j,
      {
        label: "Created",
        value: new Date(r.createdAt).toLocaleDateString()
      }
    ))), t && /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("h3", { className: "text-sm font-medium text-gray-500 dark:text-gray-400 mb-2" }, "Context Usage"), /* @__PURE__ */ React.createElement("div", { className: "bg-gray-50 dark:bg-gray-800 rounded-lg p-3 space-y-3" }, /* @__PURE__ */ React.createElement(
      gr,
      {
        value: t.tokens.used,
        max: t.tokens.limit,
        label: "Total Tokens",
        color: c
      }
    ), t.categories && t.categories.length > 0 && /* @__PURE__ */ React.createElement("div", { className: "pt-2 border-t border-gray-200 dark:border-gray-700" }, /* @__PURE__ */ React.createElement("div", { className: "text-xs text-gray-500 mb-2" }, "By Category"), /* @__PURE__ */ React.createElement("div", { className: "space-y-1" }, t.categories.map((d) => /* @__PURE__ */ React.createElement("div", { key: d.name, className: "flex justify-between text-sm" }, /* @__PURE__ */ React.createElement("span", { className: "text-gray-600 dark:text-gray-400" }, d.name), /* @__PURE__ */ React.createElement("span", { className: "font-mono text-xs" }, z(d.tokens)))))))), a && /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("h3", { className: "text-sm font-medium text-gray-500 dark:text-gray-400 mb-2" }, "Usage"), /* @__PURE__ */ React.createElement("div", { className: "bg-gray-50 dark:bg-gray-800 rounded-lg p-3" }, /* @__PURE__ */ React.createElement(j, { label: "Input Tokens", value: z(a.inputTokens || 0) }), /* @__PURE__ */ React.createElement(j, { label: "Output Tokens", value: z(a.outputTokens || 0) }), a.cacheReadTokens !== void 0 && a.cacheReadTokens > 0 && /* @__PURE__ */ React.createElement(
      j,
      {
        label: "Cache Read",
        value: z(a.cacheReadTokens)
      }
    ), a.cacheWriteTokens !== void 0 && a.cacheWriteTokens > 0 && /* @__PURE__ */ React.createElement(
      j,
      {
        label: "Cache Write",
        value: z(a.cacheWriteTokens)
      }
    ), a.cost !== void 0 && /* @__PURE__ */ React.createElement(
      j,
      {
        label: "Cost",
        value: /* @__PURE__ */ React.createElement("span", { className: "text-green-600 dark:text-green-400" }, mr(a.cost))
      }
    )))),
    /* @__PURE__ */ React.createElement("div", { className: "px-4 py-3 border-t border-gray-200 dark:border-gray-700 flex justify-end" }, /* @__PURE__ */ React.createElement(
      "button",
      {
        onClick: n,
        className: "px-4 py-2 bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 dark:hover:bg-gray-700 rounded-lg transition-colors"
      },
      "Close"
    ))
  )));
}
function kr({
  config: e,
  globalContext: r,
  repositories: t = [],
  className: a = "",
  style: n,
  onClose: s,
  onExpand: o
}) {
  const c = {
    baseUrl: e.baseUrl,
    headers: e.headers,
    getAuthToken: e.getAuthToken,
    timeout: e.timeout,
    onUnauthorized: e.onUnauthorized,
    onError: e.onError
  };
  return /* @__PURE__ */ l.createElement(Tt, { config: c }, /* @__PURE__ */ l.createElement(
    "div",
    {
      className: `turbowrap-chat turbowrap-chat-${e.defaultMode || "third"} ${a}`.trim(),
      style: n,
      "data-theme": e.theme ?? "auto"
    },
    /* @__PURE__ */ l.createElement(
      fr,
      {
        config: e,
        globalContext: r,
        repositories: t,
        onClose: s,
        onExpand: o
      }
    )
  ));
}
function fr({
  config: e,
  globalContext: r,
  repositories: t,
  onClose: a,
  onExpand: n
}) {
  const { store: s, apiClient: o, isInitialized: c, initialize: d } = _t(), [u, i] = $(!1), [g, p] = $(!1), [m, b] = $(!1), [y, S] = $(null), [f, h] = $(null), { sendMessage: E, stopStream: N, isConnected: C } = Ct({
    apiUrl: e.baseUrl,
    workerUrl: e.workerUrl,
    onAction: (w, R) => {
      var M, x, A;
      w === "navigate" ? (M = e.onNavigate) == null || M.call(e, R) : w === "highlight" && ((x = e.onHighlight) == null || x.call(e, R)), (A = e.onAction) == null || A.call(e, { type: w, target: R });
    },
    onTitleUpdate: (w, R) => {
      s.actions.updateSession(w, { displayName: R });
    },
    onError: e.onError
  }), D = s.sessions, v = s.activeSessionId, I = v ? D.get(v) ?? null : null, ne = v ? s.messages.get(v) || [] : [], T = v ? s.streamState.get(v) ?? null : null, q = W(() => {
    const w = (r == null ? void 0 : r.repositoryId) || e.repositoryId;
    if (w)
      return t == null ? void 0 : t.find((R) => R.id === w);
  }, [r == null ? void 0 : r.repositoryId, e.repositoryId, t]);
  L(() => {
    if (c) return;
    (async () => {
      var R;
      try {
        const M = (r == null ? void 0 : r.repositoryId) || e.repositoryId, x = await o.getSessions({
          repositoryId: M
        });
        x.forEach((K) => {
          s.actions.addSession(K);
        });
        const A = await o.getAgents();
        s.actions.setAgents(A);
        const O = e.sessionId || (x.length > 0 ? x[0].id : null);
        if (O) {
          s.actions.setActiveSession(O);
          const K = await o.getMessages(O);
          s.actions.setMessages(O, K);
        }
        d();
      } catch (M) {
        (R = e.onError) == null || R.call(e, M instanceof Error ? M : new Error("Failed to initialize"));
      }
    })();
  }, [c, o, r == null ? void 0 : r.repositoryId, e.repositoryId, e.sessionId, s.actions, d, e.onError]), L(() => {
    if (!c) return;
    (async () => {
      var M;
      const R = r == null ? void 0 : r.repositoryId;
      if (R)
        try {
          const x = await o.getSessions({ repositoryId: R });
          if (s.actions.reset(), x.forEach((A) => {
            s.actions.addSession(A);
          }), x.length > 0) {
            s.actions.setActiveSession(x[0].id);
            const A = await o.getMessages(x[0].id);
            s.actions.setMessages(x[0].id, A);
          }
          d();
        } catch (x) {
          (M = e.onError) == null || M.call(e, x instanceof Error ? x : new Error("Failed to reload"));
        }
    })();
  }, [r == null ? void 0 : r.repositoryId]);
  const F = k(async (w) => {
    var M;
    s.actions.setActiveSession(w);
    const R = s.messages.get(w);
    if (!R || R.length === 0)
      try {
        const x = await o.getMessages(w);
        s.actions.setMessages(w, x);
      } catch (x) {
        (M = e.onError) == null || M.call(e, x instanceof Error ? x : new Error("Failed to load messages"));
      }
  }, [s, o, e.onError]), se = k(async (w) => {
    var R, M;
    try {
      const x = await o.createSession({
        cliType: w,
        repositoryId: (r == null ? void 0 : r.repositoryId) || e.repositoryId
      });
      s.actions.addSession(x), s.actions.setActiveSession(x.id), (R = e.onSessionCreate) == null || R.call(e, x);
    } catch (x) {
      (M = e.onError) == null || M.call(e, x instanceof Error ? x : new Error("Failed to create session"));
    }
  }, [o, r == null ? void 0 : r.repositoryId, e.repositoryId, s.actions, e.onSessionCreate, e.onError]), Te = k((w) => {
    var M;
    if (!v) return;
    const R = {
      id: `temp-${Date.now()}`,
      sessionId: v,
      role: "user",
      content: w,
      createdAt: /* @__PURE__ */ new Date(),
      isThinking: !1
    };
    s.actions.addMessage(v, R), (M = e.onMessageSend) == null || M.call(e, v, w), C && e.enableSharedWorker !== !1 ? E(v, w) : (o.streamMessage(v, w, {
      onChunk: (x) => {
        s.actions.appendStreamContent(v, x);
      },
      onToolStart: (x) => {
        s.actions.addActiveTool(v, {
          id: x.id,
          name: x.name,
          startedAt: Date.now()
        });
      },
      onToolEnd: (x) => {
        s.actions.removeActiveTool(v, x);
      },
      onDone: () => {
        s.actions.endStream(v);
      },
      onError: (x) => {
        var A;
        s.actions.endStream(v), (A = e.onError) == null || A.call(e, x);
      }
    }), s.actions.startStream(v));
  }, [v, s.actions, e, C, E, o]), Ce = k(() => {
    v && (N(v), s.actions.abortStream(v));
  }, [v, N, s.actions]), $e = k(async (w) => {
    var R, M;
    try {
      await o.deleteSession(w), s.actions.removeSession(w), (R = e.onSessionDelete) == null || R.call(e, w);
    } catch (x) {
      (M = e.onError) == null || M.call(e, x instanceof Error ? x : new Error("Failed to delete"));
    }
  }, [o, s.actions, e.onSessionDelete, e.onError]), Ae = k(async (w) => {
    var R;
    if (v)
      try {
        await o.updateSession(v, { model: w }), s.actions.updateSession(v, { model: w });
      } catch (M) {
        (R = e.onError) == null || R.call(e, M instanceof Error ? M : new Error("Failed to update model"));
      }
  }, [v, o, s.actions, e.onError]), De = k(async (w) => {
    var R;
    if (v)
      try {
        await o.changeBranch(v, w), s.actions.updateSession(v, { currentBranch: w });
      } catch (M) {
        (R = e.onError) == null || R.call(e, M instanceof Error ? M : new Error("Failed to change branch"));
      }
  }, [v, o, s.actions, e.onError]), Ie = k(async () => {
    var w;
    if (v)
      try {
        const [R, M] = await Promise.all([
          o.getContextInfo(v),
          o.getUsageInfo(v)
        ]);
        S(R), h({
          inputTokens: M.sessionId ? void 0 : 0,
          // Placeholder
          outputTokens: void 0,
          cacheReadTokens: void 0,
          cost: void 0,
          mcpServers: M.mcpServers
        }), b(!0);
      } catch (R) {
        (w = e.onError) == null || w.call(e, R instanceof Error ? R : new Error("Failed to load session info"));
      }
  }, [v, o, e.onError]), Le = k((w) => {
    window.dispatchEvent(new CustomEvent("turbowrap:repo-change", {
      detail: { repositoryId: w }
    })), p(!1);
  }, []), oe = W(() => Array.from(D.values()).sort((w, R) => {
    var A, O;
    const M = ((A = w.lastMessageAt) == null ? void 0 : A.getTime()) || w.createdAt.getTime();
    return (((O = R.lastMessageAt) == null ? void 0 : O.getTime()) || R.createdAt.getTime()) - M;
  }), [D]);
  return /* @__PURE__ */ l.createElement("div", { className: "flex flex-col h-full bg-white dark:bg-gray-900" }, /* @__PURE__ */ l.createElement(
    jt,
    {
      chatMode: e.defaultMode || "third",
      showHistory: u,
      onToggleHistory: () => i(!u),
      onNewChat: se,
      onExpand: n,
      onClose: a
    },
    /* @__PURE__ */ l.createElement(
      zt,
      {
        sessions: oe,
        activeSessionId: v ?? null,
        onSelect: F
      }
    )
  ), I && /* @__PURE__ */ l.createElement(
    Jt,
    {
      session: I,
      repository: q,
      branches: (r == null ? void 0 : r.branches) || [],
      currentBranch: (r == null ? void 0 : r.currentBranch) || I.currentBranch || "main",
      onModelChange: Ae,
      onRepoClick: () => p(!0),
      onBranchChange: De,
      onInfoClick: Ie
    }
  ), /* @__PURE__ */ l.createElement(
    Ne,
    {
      messages: ne,
      isStreaming: (T == null ? void 0 : T.isStreaming) || !1,
      streamContent: (T == null ? void 0 : T.content) || "",
      streamSegments: (T == null ? void 0 : T.segments) || [],
      activeTools: (T == null ? void 0 : T.activeTools) || [],
      activeAgents: (T == null ? void 0 : T.activeAgents) || [],
      className: "flex-1"
    }
  ), /* @__PURE__ */ l.createElement(
    Me,
    {
      onSend: Te,
      onStop: Ce,
      isStreaming: (T == null ? void 0 : T.isStreaming) || !1,
      placeholder: `Message ${(I == null ? void 0 : I.cliType) === "gemini" ? "Gemini" : "Claude"}...`
    }
  ), /* @__PURE__ */ l.createElement(
    Ht,
    {
      isOpen: u,
      sessions: oe,
      activeSessionId: v ?? null,
      onClose: () => i(!1),
      onSelect: (w) => {
        F(w), i(!1);
      },
      onDelete: $e,
      onNewChat: se
    }
  ), /* @__PURE__ */ l.createElement(
    dr,
    {
      isOpen: g,
      repositories: t || [],
      selectedRepoId: (r == null ? void 0 : r.repositoryId) || e.repositoryId || null,
      onSelect: Le,
      onClose: () => p(!1)
    }
  ), /* @__PURE__ */ l.createElement(
    pr,
    {
      isOpen: m,
      session: I,
      contextInfo: y || void 0,
      usageInfo: f || void 0,
      onClose: () => b(!1)
    }
  ));
}
function _e() {
  const e = te(), r = P(/* @__PURE__ */ new Map()), {
    startStream: t,
    appendStreamContent: a,
    addStreamSegment: n,
    endStream: s,
    abortStream: o,
    setStreamError: c,
    addActiveTool: d,
    removeActiveTool: u,
    addActiveAgent: i,
    addMessage: g,
    updateSession: p,
    setPendingMessage: m
  } = _((f) => f.actions), b = k(async (f, h, E) => {
    const N = _.getState().streamState.get(f);
    if (N != null && N.isStreaming) {
      m(f, h);
      return;
    }
    const C = new AbortController();
    r.current.set(f, C), t(f);
    const D = {
      id: `temp-user-${Date.now()}`,
      sessionId: f,
      role: "user",
      content: h,
      isThinking: !1,
      createdAt: /* @__PURE__ */ new Date()
    };
    g(f, D);
    try {
      await e.streamMessage(f, h, {
        signal: C.signal,
        modelOverride: E,
        onChunk: (v, I) => {
          a(f, v, I);
        },
        onThinking: (v) => {
          a(f, v);
        },
        onToolStart: (v) => {
          d(f, v), n(f, {
            type: "tool",
            name: v.name,
            id: v.id
          });
        },
        onToolEnd: (v, I) => {
          u(f, v, I);
        },
        onAgentStart: (v) => {
          i(f, v), n(f, {
            type: "agent",
            agentType: v.type,
            model: v.model,
            description: v.description
          });
        },
        onDone: (v, I) => {
          const T = _.getState().streamState.get(f), q = {
            id: v,
            sessionId: f,
            role: "assistant",
            content: (T == null ? void 0 : T.content) || "",
            segments: T == null ? void 0 : T.segments,
            isThinking: !1,
            createdAt: /* @__PURE__ */ new Date()
          };
          s(f, q);
          const F = T == null ? void 0 : T.pendingMessage;
          F && (m(f, null), setTimeout(() => b(f, F), 100));
        },
        onTitleUpdate: (v) => {
          p(f, { displayName: v });
        },
        onError: (v) => {
          c(f, v.message);
        }
      });
    } catch (v) {
      v instanceof Error && v.name === "AbortError" ? o(f) : c(f, v instanceof Error ? v.message : "Unknown error");
    } finally {
      r.current.delete(f);
    }
  }, [
    e,
    t,
    a,
    n,
    s,
    o,
    c,
    d,
    u,
    i,
    g,
    p,
    m
  ]), y = k((f) => {
    const h = r.current.get(f);
    h && (h.abort(), r.current.delete(f));
  }, []), S = k((f) => {
    var h;
    return ((h = _.getState().streamState.get(f)) == null ? void 0 : h.isStreaming) ?? !1;
  }, []);
  return L(() => () => {
    r.current.forEach((f) => {
      f.abort();
    }), r.current.clear();
  }, []), { sendMessage: b, abort: y, isStreaming: S };
}
function wr(e = {}) {
  const { sessionId: r } = e, t = _(re), a = r || (t == null ? void 0 : t.id), n = _(we), s = r ? _((y) => y.messages.get(r) ?? []) : n, o = _(xe), c = r ? _((y) => y.streamState.get(r)) : o, { setPendingMessage: d, setStreamError: u } = _((y) => y.actions), i = _e(), g = k(async (y, S) => {
    if (!a)
      throw new Error("No session selected");
    if (c != null && c.isStreaming) {
      d(a, y);
      return;
    }
    await i.sendMessage(a, y, S);
  }, [a, c == null ? void 0 : c.isStreaming, d, i]), p = k(() => {
    a && i.abort(a);
  }, [a, i]), m = k((y) => {
    a && d(a, y);
  }, [a, d]), b = k(() => {
    a && u(a, null);
  }, [a, u]);
  return {
    messages: s,
    isStreaming: (c == null ? void 0 : c.isStreaming) ?? !1,
    streamContent: (c == null ? void 0 : c.content) ?? "",
    streamSegments: (c == null ? void 0 : c.segments) ?? [],
    activeTools: (c == null ? void 0 : c.activeTools) ?? [],
    activeAgents: (c == null ? void 0 : c.activeAgents) ?? [],
    error: (c == null ? void 0 : c.error) ?? null,
    pendingMessage: (c == null ? void 0 : c.pendingMessage) ?? null,
    sendMessage: g,
    stopStream: p,
    queueMessage: m,
    clearError: b
  };
}
function xr() {
  const e = te(), r = _e(), [t, a] = $(!1), n = _(kt), s = _(re), o = _(ke), {
    addSession: c,
    updateSession: d,
    removeSession: u,
    setActiveSession: i,
    setMessages: g,
    setSessions: p
  } = _((N) => N.actions), m = k(async (N) => {
    a(!0);
    try {
      const C = await e.createSession(N);
      return c(C), await e.startSession(C.id), i(C.id), C;
    } finally {
      a(!1);
    }
  }, [e, c, i]), b = k(async (N) => {
    a(!0);
    try {
      const C = _.getState().activeSessionId;
      C && r.isStreaming(C) && r.abort(C), i(N);
      const D = _.getState().messages.get(N);
      if (!D || D.length === 0) {
        const v = await e.getMessages(N);
        g(N, v);
      }
      await e.startSession(N);
    } finally {
      a(!1);
    }
  }, [e, r, i, g]), y = k(async (N, C) => {
    const D = await e.updateSession(N, C);
    return d(N, D), D;
  }, [e, d]), S = k(async (N) => {
    await e.deleteSession(N), u(N);
  }, [e, u]), f = k(async (N) => {
    a(!0);
    try {
      const C = await e.forkSession(N);
      c(C);
      const D = await e.getMessages(C.id);
      return g(C.id, D), C;
    } finally {
      a(!1);
    }
  }, [e, c, g]), h = k(async (N) => {
    await e.startSession(N);
  }, [e]), E = k(async () => {
    a(!0);
    try {
      const N = await e.getSessions();
      p(N);
    } finally {
      a(!1);
    }
  }, [e, p]);
  return {
    sessions: n,
    activeSession: s,
    secondarySession: o,
    isLoading: t,
    createSession: m,
    selectSession: b,
    updateSession: y,
    deleteSession: S,
    forkSession: f,
    startSession: h,
    refreshSessions: E
  };
}
function Rr() {
  const e = te(), r = _(Mt), { setAgents: t } = _((y) => y.actions), [a, n] = $(""), [s, o] = $(0), [c, d] = $(!1), u = W(() => {
    if (!a) return r.slice(0, 10);
    const y = a.toLowerCase();
    return r.filter(
      (S) => S.name.toLowerCase().includes(y) || S.description.toLowerCase().includes(y)
    ).slice(0, 10);
  }, [r, a]);
  L(() => {
    o(0);
  }, [a]);
  const i = k(() => {
    o(
      (y) => y > 0 ? y - 1 : u.length - 1
    );
  }, [u.length]), g = k(() => {
    o(
      (y) => y < u.length - 1 ? y + 1 : 0
    );
  }, [u.length]), p = k(() => u[s] ?? null, [u, s]), m = k(() => {
    n(""), o(0);
  }, []), b = k(async () => {
    d(!0);
    try {
      const y = await e.getAgents();
      t(y);
    } finally {
      d(!1);
    }
  }, [e, t]);
  return {
    agents: r,
    filteredAgents: u,
    query: a,
    selectedIndex: s,
    isLoading: c,
    setQuery: n,
    selectPrevious: i,
    selectNext: g,
    getSelectedAgent: p,
    resetSelection: m,
    refreshAgents: b
  };
}
function Nr() {
  const e = _((h) => h.dualChatEnabled), r = _(Rt), t = _(Nt), a = _(re), n = _(we), s = _(xe), o = _(ke), c = _(wt), d = _(xt), {
    toggleDualChat: u,
    setSecondarySession: i,
    setActivePane: g,
    setActiveSession: p
  } = _((h) => h.actions), m = k(() => {
    u();
  }, [u]), b = k((h) => {
    i(h);
  }, [i]), y = k((h) => {
    g(h);
  }, [g]), S = k(() => {
    const h = _.getState(), E = h.activeSessionId, N = h.secondarySessionId;
    E && N && (p(N), i(E));
  }, [p, i]), f = k((h, E) => {
    E === "left" ? p(h) : i(h), g(E);
  }, [p, i, g]);
  return {
    isDualChatEnabled: e,
    isDualChatActive: r,
    activePane: t,
    leftSession: a,
    leftMessages: n,
    leftStreamState: s,
    rightSession: o,
    rightMessages: c,
    rightStreamState: d,
    toggleDualChat: m,
    setSecondarySession: b,
    setActivePane: y,
    swapSessions: S,
    openInPane: f
  };
}
function Mr({
  session: e,
  messages: r,
  isStreaming: t = !1,
  streamContent: a = "",
  streamSegments: n = [],
  activeTools: s = [],
  activeAgents: o = [],
  pendingMessage: c,
  isActive: d = !0,
  onSend: u,
  onStop: i,
  onClearPending: g,
  onFocus: p,
  className: m = ""
}) {
  const b = k(() => {
    p == null || p();
  }, [p]);
  return e ? /* @__PURE__ */ React.createElement(
    "div",
    {
      onClick: b,
      className: `flex flex-col h-full ${d ? "ring-2 ring-indigo-500 ring-opacity-50" : ""} ${m}`
    },
    /* @__PURE__ */ React.createElement("div", { className: "px-4 py-2 border-b border-gray-200 dark:border-gray-700 flex items-center gap-2" }, /* @__PURE__ */ React.createElement(
      "div",
      {
        className: `w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold ${e.cliType === "gemini" ? "bg-blue-100 text-blue-600 dark:bg-blue-900 dark:text-blue-400" : "bg-orange-100 text-orange-600 dark:bg-orange-900 dark:text-orange-400"}`
      },
      e.cliType === "gemini" ? "G" : "C"
    ), /* @__PURE__ */ React.createElement("span", { className: "font-medium truncate flex-1" }, e.displayName || "Untitled Chat"), e.model && /* @__PURE__ */ React.createElement("span", { className: "text-xs text-gray-400" }, hr(e.model))),
    /* @__PURE__ */ React.createElement(
      Ne,
      {
        messages: r,
        isStreaming: t,
        streamContent: a,
        streamSegments: n,
        activeTools: s,
        activeAgents: o,
        className: "flex-1"
      }
    ),
    /* @__PURE__ */ React.createElement(
      Me,
      {
        onSend: u,
        onStop: i,
        isStreaming: t,
        pendingMessage: c,
        onClearPending: g,
        placeholder: `Message ${e.cliType === "gemini" ? "Gemini" : "Claude"}...`
      }
    )
  ) : /* @__PURE__ */ React.createElement("div", { className: `flex flex-col h-full ${m}` }, /* @__PURE__ */ React.createElement("div", { className: "flex-1 flex items-center justify-center text-gray-400" }, /* @__PURE__ */ React.createElement("div", { className: "text-center" }, /* @__PURE__ */ React.createElement("svg", { className: "w-12 h-12 mx-auto mb-4 opacity-50", fill: "none", viewBox: "0 0 24 24", stroke: "currentColor" }, /* @__PURE__ */ React.createElement(
    "path",
    {
      strokeLinecap: "round",
      strokeLinejoin: "round",
      strokeWidth: 1.5,
      d: "M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"
    }
  )), /* @__PURE__ */ React.createElement("p", { className: "font-medium" }, "Select a chat"), /* @__PURE__ */ React.createElement("p", { className: "text-sm mt-1" }, "Choose a session from the tabs above"))));
}
function hr(e) {
  return e.includes("opus") ? "Opus" : e.includes("sonnet") ? "Sonnet" : e.includes("haiku") ? "Haiku" : e.includes("pro") ? "Pro" : e.includes("flash") ? "Flash" : e.split("-").pop() || e;
}
function _r({
  enabled: e,
  children: r,
  className: t = ""
}) {
  const a = l.Children.toArray(r);
  return !e || a.length < 2 ? /* @__PURE__ */ l.createElement("div", { className: `flex-1 flex flex-col ${t}` }, a[0]) : /* @__PURE__ */ l.createElement("div", { className: `flex-1 flex ${t}` }, /* @__PURE__ */ l.createElement("div", { className: "flex-1 flex flex-col border-r border-gray-200 dark:border-gray-700" }, a[0]), /* @__PURE__ */ l.createElement("div", { className: "flex-1 flex flex-col" }, a[1]));
}
function Tr({
  code: e,
  language: r = "text",
  className: t = ""
}) {
  const [a, n] = $(!1), s = k(async () => {
    try {
      await navigator.clipboard.writeText(e), n(!0), setTimeout(() => n(!1), 2e3);
    } catch (o) {
      console.error("Failed to copy:", o);
    }
  }, [e]);
  return /* @__PURE__ */ React.createElement("div", { className: `chat-code-block ${t}` }, /* @__PURE__ */ React.createElement("div", { className: "chat-code-header" }, /* @__PURE__ */ React.createElement("span", { className: "text-gray-400" }, r), /* @__PURE__ */ React.createElement(
    "button",
    {
      onClick: s,
      className: "text-xs text-gray-400 hover:text-white transition-colors"
    },
    a ? "Copied!" : "Copy"
  )), /* @__PURE__ */ React.createElement("pre", { className: "chat-code-content overflow-x-auto" }, /* @__PURE__ */ React.createElement("code", { className: `language-${r}` }, e)));
}
const yr = {
  info: "💡",
  warning: "⚠️",
  error: "❌",
  success: "✅",
  tip: "💡"
};
function Cr({
  type: e,
  children: r,
  className: t = ""
}) {
  return /* @__PURE__ */ l.createElement("div", { className: `chat-callout chat-callout-${e} ${t}` }, /* @__PURE__ */ l.createElement("span", { className: "mr-2 flex-shrink-0" }, yr[e]), /* @__PURE__ */ l.createElement("div", { className: "flex-1" }, r));
}
function vr(e) {
  switch (e) {
    case "reviewer":
      return "🔍";
    case "fixer":
      return "🔧";
    case "analyzer":
      return "📊";
    case "creator":
      return "✨";
    default:
      return "🤖";
  }
}
function $r({
  isOpen: e,
  agents: r,
  filter: t,
  selectedIndex: a,
  position: n,
  onSelect: s,
  onClose: o,
  onNavigate: c,
  className: d = ""
}) {
  const u = P(null), i = P(null), g = r.filter(
    (m) => m.name.toLowerCase().includes(t.toLowerCase()) || m.description.toLowerCase().includes(t.toLowerCase())
  );
  L(() => {
    i.current && i.current.scrollIntoView({ block: "nearest" });
  }, [a]);
  const p = k(
    (m) => {
      if (e)
        switch (m.key) {
          case "ArrowDown":
            m.preventDefault(), c("down");
            break;
          case "ArrowUp":
            m.preventDefault(), c("up");
            break;
          case "Enter":
            m.preventDefault(), g[a] && s(g[a]);
            break;
          case "Escape":
            m.preventDefault(), o();
            break;
        }
    },
    [e, g, a, s, o, c]
  );
  return L(() => (document.addEventListener("keydown", p), () => document.removeEventListener("keydown", p)), [p]), L(() => {
    const m = (b) => {
      u.current && !u.current.contains(b.target) && o();
    };
    if (e)
      return document.addEventListener("mousedown", m), () => document.removeEventListener("mousedown", m);
  }, [e, o]), !e || g.length === 0 ? null : /* @__PURE__ */ React.createElement(
    "div",
    {
      ref: u,
      className: `absolute bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg shadow-lg z-50 max-h-64 overflow-y-auto min-w-[280px] ${d}`,
      style: {
        bottom: `calc(100% - ${n.top}px + 8px)`,
        left: n.left
      }
    },
    /* @__PURE__ */ React.createElement("div", { className: "px-3 py-2 border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900 rounded-t-lg" }, /* @__PURE__ */ React.createElement("span", { className: "text-xs text-gray-500 font-medium" }, "Agents ", t && `matching "${t}"`)),
    /* @__PURE__ */ React.createElement("div", { className: "py-1" }, g.map((m, b) => /* @__PURE__ */ React.createElement(
      "button",
      {
        key: m.id,
        ref: b === a ? i : void 0,
        onClick: () => s(m),
        className: `w-full px-3 py-2 text-left flex items-start gap-3 transition-colors ${b === a ? "bg-indigo-50 dark:bg-indigo-900/30" : "hover:bg-gray-100 dark:hover:bg-gray-700"}`
      },
      /* @__PURE__ */ React.createElement("span", { className: "text-lg flex-shrink-0" }, vr(m.type)),
      /* @__PURE__ */ React.createElement("div", { className: "flex-1 min-w-0" }, /* @__PURE__ */ React.createElement("div", { className: "flex items-center gap-2" }, /* @__PURE__ */ React.createElement("span", { className: "font-medium text-gray-900 dark:text-white" }, "@", m.name), m.model && /* @__PURE__ */ React.createElement("span", { className: "text-xs px-1.5 py-0.5 bg-gray-100 dark:bg-gray-700 rounded text-gray-500" }, m.model)), /* @__PURE__ */ React.createElement("p", { className: "text-sm text-gray-500 dark:text-gray-400 truncate" }, m.description))
    ))),
    /* @__PURE__ */ React.createElement("div", { className: "px-3 py-1.5 border-t border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900 rounded-b-lg" }, /* @__PURE__ */ React.createElement("span", { className: "text-xs text-gray-400" }, "↑↓ navigate · Enter select · Esc close"))
  );
}
export {
  $r as AgentAutocomplete,
  Cr as Callout,
  Ue as ChatAPIClient,
  jt as ChatHeader,
  Mr as ChatPane,
  Tt as ChatProvider,
  kr as ChatWidget,
  Tr as CodeBlock,
  _r as DualPaneLayout,
  Ht as HistoryPanel,
  ae as MessageFormatter,
  Me as MessageInput,
  Xt as MessageItem,
  Ne as MessageList,
  Jt as QuickSettings,
  dr as RepoSelectorModal,
  pr as SessionInfoModal,
  zt as SessionTabs,
  tr as StreamingMessage,
  H as ToolIndicator,
  V as createInitialStreamState,
  we as selectActiveMessages,
  re as selectActiveSession,
  xe as selectActiveStreamState,
  Mt as selectAgents,
  kt as selectAllSessions,
  Sr as selectIsSessionStreaming,
  ke as selectSecondarySession,
  Oe as transformMessage,
  U as transformSession,
  Rr as useAgents,
  wr as useChat,
  te as useChatClient,
  _ as useChatStore,
  Nr as useDualChat,
  xr as useSessions,
  _e as useStreaming
};
//# sourceMappingURL=turbowrap-chat.es.js.map

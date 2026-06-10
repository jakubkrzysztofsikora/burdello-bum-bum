/**
 * Burdello MCP — Cloudflare Worker bridge for Claude.ai.
 *
 * Stateless implementation of MCP's Streamable HTTP transport. Each request
 * is one JSON-RPC call routed to the same bearer-authenticated REST surface
 * the stdio server uses (/api/v1/mcp/*). No Durable Object needed for these
 * tools.
 *
 * Setup:
 *   wrangler secret put MCP_BRIDGE_TOKEN     # bearer to the backend
 *   # (BURDELLO_API_URL is a public var in wrangler.jsonc, points at the
 *   # Cloudflare Tunnel hostname for bb-backend)
 */

export interface Env {
  BURDELLO_API_URL: string;
  MCP_BRIDGE_TOKEN: string;
}

// ---------------------------------------------------------------------------
// Tool catalogue — mirrors backend/mcp_tools/__init__.py
// ---------------------------------------------------------------------------

interface ToolDef {
  name: string;
  description: string;
  inputSchema: Record<string, unknown>;
  /** REST path on the backend (under /api/v1/mcp). */
  backendPath: string;
}

const TOOLS: ToolDef[] = [
  {
    name: "get_kanban_board",
    description:
      "Return a kanban view of one project's tasks. Provide either project_name (case-insensitive exact match) or project_id. Returns columns todo / in_progress / done / cancelled, ordered by priority then recency.",
    inputSchema: {
      type: "object",
      properties: {
        project_name: { type: "string" },
        project_id: { type: "string" },
        limit_per_column: { type: "integer", default: 50 },
      },
    },
    backendPath: "/get_kanban_board",
  },
  {
    name: "update_task_status",
    description:
      "Move a task to a new column. Valid statuses: todo, in_progress, done, cancelled. Use after finishing a unit of work or to revive a task from done.",
    inputSchema: {
      type: "object",
      properties: {
        task_id: { type: "string" },
        new_status: {
          type: "string",
          enum: ["todo", "in_progress", "done", "cancelled"],
        },
      },
      required: ["task_id", "new_status"],
    },
    backendPath: "/update_task_status",
  },
  {
    name: "list_projects",
    description:
      "Top projects by task volume; optional case-insensitive name search.",
    inputSchema: {
      type: "object",
      properties: {
        search: { type: "string" },
        limit: { type: "integer", default: 50 },
      },
    },
    backendPath: "/list_projects",
  },
  {
    name: "list_tasks",
    description:
      "List tasks. Filter by project (id or name), status, and priority.",
    inputSchema: {
      type: "object",
      properties: {
        project_id: { type: "string" },
        project_name: { type: "string" },
        status: { type: "string" },
        priority: { type: "string" },
        limit: { type: "integer", default: 50 },
      },
    },
    backendPath: "/list_tasks",
  },
  {
    name: "list_artifacts",
    description: "List artifacts (source_code, documentation, config, test, …).",
    inputSchema: {
      type: "object",
      properties: {
        project_id: { type: "string" },
        artifact_type: { type: "string" },
        limit: { type: "integer", default: 50 },
      },
    },
    backendPath: "/list_artifacts",
  },
  {
    name: "search_transcripts",
    description: "Title + raw-text ILIKE search across all transcripts.",
    inputSchema: {
      type: "object",
      properties: {
        query: { type: "string" },
        limit: { type: "integer", default: 10 },
      },
      required: ["query"],
    },
    backendPath: "/search_transcripts",
  },
  {
    name: "get_stats",
    description:
      "Total counts of transcripts / projects / tasks / artifacts.",
    inputSchema: { type: "object", properties: {} },
    backendPath: "/get_stats",
  },
];

// ---------------------------------------------------------------------------
// JSON-RPC plumbing
// ---------------------------------------------------------------------------

type Json = null | boolean | number | string | Json[] | { [k: string]: Json };

interface JsonRpcRequest {
  jsonrpc: "2.0";
  id?: number | string | null;
  method: string;
  params?: Json;
}

function rpcResult(id: JsonRpcRequest["id"], result: Json): Response {
  return new Response(
    JSON.stringify({ jsonrpc: "2.0", id: id ?? null, result }),
    { headers: { "content-type": "application/json" } },
  );
}

function rpcError(
  id: JsonRpcRequest["id"],
  code: number,
  message: string,
  data?: Json,
): Response {
  const body: Record<string, Json> = {
    jsonrpc: "2.0",
    id: id ?? null,
    error: { code, message, ...(data !== undefined ? { data } : {}) },
  };
  return new Response(JSON.stringify(body), {
    headers: { "content-type": "application/json" },
  });
}

// ---------------------------------------------------------------------------
// Backend proxy
// ---------------------------------------------------------------------------

async function callBackend(
  env: Env,
  path: string,
  payload: Record<string, unknown>,
): Promise<Json> {
  const url = `${env.BURDELLO_API_URL.replace(/\/+$/, "")}/api/v1/mcp${path}`;
  const r = await fetch(url, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      authorization: `Bearer ${env.MCP_BRIDGE_TOKEN}`,
    },
    body: JSON.stringify(payload),
  });
  if (!r.ok) {
    const text = await r.text().catch(() => "");
    throw new Error(`backend ${r.status}: ${text.slice(0, 200)}`);
  }
  return (await r.json()) as Json;
}

// ---------------------------------------------------------------------------
// MCP method handlers
// ---------------------------------------------------------------------------

const PROTOCOL_VERSION = "2025-06-18";

function handleInitialize(req: JsonRpcRequest): Response {
  return rpcResult(req.id, {
    protocolVersion: PROTOCOL_VERSION,
    capabilities: { tools: { listChanged: false } },
    serverInfo: { name: "burdello", version: "0.1.0" },
  });
}

function handleToolsList(req: JsonRpcRequest): Response {
  return rpcResult(req.id, {
    tools: TOOLS.map((t) => ({
      name: t.name,
      description: t.description,
      inputSchema: t.inputSchema as Json,
    })),
  });
}

async function handleToolsCall(
  req: JsonRpcRequest,
  env: Env,
): Promise<Response> {
  const params = (req.params ?? {}) as { name?: string; arguments?: Record<string, unknown> };
  const tool = TOOLS.find((t) => t.name === params.name);
  if (!tool) {
    return rpcError(req.id, -32602, `unknown tool: ${params.name}`);
  }
  try {
    const result = await callBackend(env, tool.backendPath, params.arguments ?? {});
    return rpcResult(req.id, {
      content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
      isError: false,
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return rpcResult(req.id, {
      content: [{ type: "text", text: `error: ${message}` }],
      isError: true,
    });
  }
}

// ---------------------------------------------------------------------------
// Worker entry
// ---------------------------------------------------------------------------

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);

    if (url.pathname === "/" || url.pathname === "/healthz") {
      return new Response(JSON.stringify({ ok: true, service: "burdello-mcp" }), {
        headers: { "content-type": "application/json" },
      });
    }

    if (url.pathname !== "/mcp") {
      return new Response("not found", { status: 404 });
    }

    // CORS preflight for Claude.ai connector probes.
    if (request.method === "OPTIONS") {
      return new Response(null, {
        status: 204,
        headers: {
          "access-control-allow-origin": "*",
          "access-control-allow-methods": "POST, OPTIONS",
          "access-control-allow-headers": "content-type, authorization, mcp-session-id, mcp-protocol-version",
        },
      });
    }

    if (request.method !== "POST") {
      return new Response("method not allowed", { status: 405 });
    }

    let body: JsonRpcRequest;
    try {
      body = (await request.json()) as JsonRpcRequest;
    } catch {
      return rpcError(null, -32700, "parse error");
    }

    let res: Response;
    switch (body.method) {
      case "initialize":
        res = handleInitialize(body);
        break;
      case "notifications/initialized":
        // No reply expected for notifications.
        return new Response(null, { status: 202 });
      case "tools/list":
        res = handleToolsList(body);
        break;
      case "tools/call":
        res = await handleToolsCall(body, env);
        break;
      case "ping":
        res = rpcResult(body.id, {});
        break;
      default:
        res = rpcError(body.id, -32601, `method not found: ${body.method}`);
    }

    // Mirror CORS on the response so the browser-side claude.ai client
    // can read the body.
    const h = new Headers(res.headers);
    h.set("access-control-allow-origin", "*");
    h.set("access-control-expose-headers", "content-type");
    return new Response(res.body, { status: res.status, headers: h });
  },
};

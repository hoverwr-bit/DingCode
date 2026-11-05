// 数据层：GET /api/* 读取，M2 写操作（改批注/单钉重跑）带 client/token + confirm。
// 与 bridge（core/runs_api.py）对应。

export interface SessionSummary {
  session: string;
  status: string;
  round: number;
  summary_line: string;
  finished: string;
  note: string;
}

/** result_payload 里 merged_pins 的每颗钉（最新轮覆盖旧轮）。 */
export interface Pin {
  id: string;
  status: string;
  summary_zh?: string;
  files?: string[];
  diff?: string;
  round?: number;
  [key: string]: unknown;
}

export interface RunPayload {
  ok: boolean;
  session: string;
  status: string;
  round: number;
  folder: string;
  summary_line: string;
  summary_en?: string;
  pins: Pin[];
  rounds: number[];
  [key: string]: unknown;
}

/** /api/runs/{sid}/pins/{pid} 的每轮历史条目。 */
export interface PinRound {
  round: number;
  status: string;
  summary_zh: string;
  diff: string;
  pin_only: boolean;
  rerun?: number | null;
  reverted: boolean;
  stale: boolean;
}

export interface PinHistory {
  ok: boolean;
  session: string;
  pin_id: string;
  pin: Pin | null;
  rounds: PinRound[];
}

/** runs note.json 里的钉：批注文本在 note/text 字段。 */
export interface NotePin {
  id: string | number;
  note?: string;
  text?: string;
  [key: string]: unknown;
}

export interface NoteDoc {
  pins?: NotePin[];
  [key: string]: unknown;
}

export interface RoundDetail {
  ok: boolean;
  session: string;
  round: number;
  summary: Record<string, unknown>;
  manifest: {
    kind: string;
    head: string;
    folder: string;
    reverted: boolean;
    files_sha256: string[];
  };
}

async function get_json<T>(url: string): Promise<T> {
  const resp = await fetch(url, { headers: { Accept: "application/json" } });
  if (!resp.ok) {
    throw new Error(`${url}: HTTP ${resp.status}`);
  }
  return (await resp.json()) as T;
}

export interface RerunResult {
  ok: boolean;
  session: string;
  pin: string;
  round: number;
}

/** 撤回单颗钉的返回：restored/removed 是被写回/删除的文件，stale 是被标记的后续轮。 */
export interface RevertResult {
  ok: boolean;
  restored?: string[];
  removed?: string[];
  stale?: number[];
  round?: number;
  conflicts?: string[];
}

// /api/session 的 client/token，M2 写操作必带。整个页面生命周期缓存一份。
let creds: { client: number; token: string } | null = null;
async function auth(): Promise<{ client: number; token: string }> {
  if (!creds) {
    creds = await get_json<{ client: number; token: string }>("/api/session");
  }
  return creds;
}

async function post_json<T>(url: string, body: Record<string, unknown>): Promise<T> {
  const { client, token } = await auth();
  const resp = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ ...body, client, token }),
  });
  const data = (await resp.json().catch(() => ({}))) as { error?: string };
  if (!resp.ok) {
    // 带上 status 和完整响应体：撤回冲突（409）要展示冲突文件列表。
    throw new ApiError(data.error || `${url}: HTTP ${resp.status}`, resp.status, data);
  }
  return data as T;
}

/** 非 2xx 的写接口响应。message 之外保留 status 与 body 供调用方细分提示。 */
export class ApiError extends Error {
  readonly status: number;
  readonly data: Record<string, unknown>;

  constructor(message: string, status: number, data: Record<string, unknown>) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.data = data;
  }
}

/** 用户对某个 engine 的覆盖（GET/POST /api/config 的 engines 字段）。 */
export interface EngineOverride {
  command?: string | string[];
  args?: string[];
  prompt_template?: string;
  timeout_sec?: number;
}

/** /api/config 的 engine_catalog 里的一项；default_* 是出厂值，自定义 engine 为 null。 */
export interface EngineRow {
  name: string;
  hidden: boolean;
  risk: string;
  custom: boolean;
  command: string | string[];
  args: string[];
  prompt_template: string;
  timeout_sec: number;
  default_command: string | string[] | null;
  default_args: string[] | null;
  default_prompt_template: string | null;
  default_timeout_sec: number | null;
}

export interface AppConfig {
  ok: boolean;
  engine: string;
  auto: boolean;
  dispatch: "auto" | "manual";
  setup_done: boolean;
  engine_path: string;
  port: number;
  app_url?: string;
  engines?: Record<string, EngineOverride>;
  engine_catalog?: EngineRow[];
}

/** 项目绑定表的一行（M6 设置页）。exists/is_git 是后端实时探测的目录状态。 */
export interface ProjectRow {
  name: string;
  folder: string;
  exists: boolean;
  is_git: boolean;
}

export interface ProjectRules {
  ok: boolean;
  name: string;
  folder: string;
  exists: boolean;
  rules: string;
  default: string;
}

/** 该会话的完整提示词（手动派活复制用）。source: prompt.md 落盘或现拼。 */
export interface SessionPrompt {
  ok: boolean;
  session: string;
  source: "prompt.md" | "built";
  prompt: string;
}

export const api = {
  sessions: () =>
    get_json<{ ok: boolean; sessions: SessionSummary[] }>("/api/sessions"),
  run: (sid: string) => get_json<RunPayload>(`/api/runs/${sid}`),
  pinHistory: (sid: string, pid: string) =>
    get_json<PinHistory>(`/api/runs/${sid}/pins/${pid}`),
  config: () => get_json<AppConfig>("/api/config"),
  /** 保存设置（M6）：patch 里的字段会写进 config.json；setup_done: true 结束首次引导。 */
  saveConfig: (patch: Partial<Omit<AppConfig, "ok" | "app_url" | "engine_catalog">>) =>
    post_json<AppConfig>("/api/config", { ...patch, confirm: "config" }),
  projects: () =>
    get_json<{ ok: boolean; projects: ProjectRow[] }>("/api/projects"),
  /** 新增/更新绑定：同名即改。folder 必须是已存在的绝对路径。 */
  saveProject: (name: string, folder: string) =>
    post_json<{ ok: boolean; projects: ProjectRow[] }>("/api/projects", {
      name,
      folder,
      confirm: "projects",
    }),
  deleteProject: (name: string) =>
    post_json<{ ok: boolean; projects: ProjectRow[] }>("/api/projects", {
      name,
      delete: true,
      confirm: "projects",
    }),
  projectRules: (name: string) =>
    get_json<ProjectRules>(
      `/api/projects/${encodeURIComponent(name)}/rules`,
    ),
  /** 保存项目的 handoff-rules.md；空串 = 删掉项目文件回到默认规则。 */
  saveProjectRules: (name: string, rules: string) =>
    post_json<{ ok: boolean; name: string }>(
      `/api/projects/${encodeURIComponent(name)}/rules`,
      { rules, confirm: name },
    ),
  sessionPrompt: async (sid: string): Promise<SessionPrompt | null> => {
    try {
      return await get_json<SessionPrompt>(`/api/runs/${sid}/prompt`);
    } catch {
      return null;
    }
  },
  round: (sid: string, n: number) =>
    get_json<RoundDetail>(`/api/runs/${sid}/rounds/${n}`),
  note: async (sid: string): Promise<NoteDoc | null> => {
    try {
      const resp = await fetch(`/api/runs/${sid}/note`);
      if (!resp.ok) return null;
      return (await resp.json()) as NoteDoc;
    } catch {
      return null;
    }
  },
  /** 修改单颗钉的批注：写源 note 文件，runs/note.json 不动。 */
  editPinNote: (sid: string, pid: string, note: string) =>
    post_json<{ ok: boolean; pin_id: string; note: string }>(
      `/api/runs/${sid}/pins/${pid}/note`,
      { confirm: pid, note },
    ),
  /** 单钉重跑：后台起 autofix --round N --pin pid，立即返回轮号，进度靠轮询。 */
  rerunPin: (sid: string, pid: string, feedback = "") =>
    post_json<RerunResult>(`/api/runs/${sid}/pins/${pid}/rerun`, {
      confirm: pid,
      ...(feedback ? { feedback } : {}),
    }),
  /** 逐颗撤回：三方合并；409 = 冲突，data.conflicts 是冲突文件列表，磁盘未动。 */
  revertPin: (sid: string, pid: string) =>
    post_json<RevertResult>(`/api/runs/${sid}/pins/${pid}/revert`, { confirm: pid }),
};

export function note_text(pin: NotePin | undefined): string {
  if (!pin) return "";
  return String(pin.note || pin.text || "");
}

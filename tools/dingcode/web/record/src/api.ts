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
    throw new Error(data.error || `${url}: HTTP ${resp.status}`);
  }
  return data as T;
}

export const api = {
  sessions: () =>
    get_json<{ ok: boolean; sessions: SessionSummary[] }>("/api/sessions"),
  run: (sid: string) => get_json<RunPayload>(`/api/runs/${sid}`),
  pinHistory: (sid: string, pid: string) =>
    get_json<PinHistory>(`/api/runs/${sid}/pins/${pid}`),
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
};

export function note_text(pin: NotePin | undefined): string {
  if (!pin) return "";
  return String(pin.note || pin.text || "");
}

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import {
  api,
  type AppConfig,
  type EngineOverride,
  type EngineRow,
  type ProjectRow,
  type ProjectRules,
} from "../api";

const props = defineProps<{ config: AppConfig | null }>();
const emit = defineEmits<{ (e: "saved", cfg: AppConfig): void }>();

// a) 派活方式 + b) 执行工具（本地编辑，点「保存设置」一次写入）
const dispatch = ref<"auto" | "manual">("auto");
const engine = ref("claude");
const enginePath = ref("");
const port = ref(0);
const saving = ref(false);
const saveError = ref("");
const saved = ref(false);

// b2) engine 目录与覆盖（本地编辑，随「保存设置」一起提交；engines 整体替换）
const catalog = ref<EngineRow[]>([]);
const savedEngine = ref("");
const savedEngines = ref<Record<string, EngineOverride>>({});
interface EngineEdit {
  command: string; // 自定义 engine 的可编辑命令；预设里是只读展示文本
  commandRaw: string | string[]; // 预设的原始命令，用来和 default_command 比较
  args: string;
  timeout_sec: number;
  prompt_template: string;
}
const edits = ref<Record<string, EngineEdit>>({});
const addedCustom = ref<string[]>([]);
const riskAck = ref(false);
const newName = ref("");
const newCommand = ref("");
const newArgs = ref("");
const newEngineError = ref("");

// c) 项目绑定表
const projects = ref<ProjectRow[]>([]);
const bindName = ref("");
const bindFolder = ref("");
const bindError = ref("");
const bindBusy = ref(false);

// d) 提示规则编辑
const rulesName = ref("");
const rulesText = ref("");
const rulesDefault = ref("");
const rulesState = ref("");
const rulesError = ref("");

// e) 记录页地址（端口改动重启后生效）
const appUrl = computed(() =>
  `${window.location.protocol}//${window.location.host}/app/`,
);
const copied = ref("");

onMounted(load);

async function load() {
  const cfg = props.config || (await api.config().catch(() => null));
  if (cfg) {
    dispatch.value = cfg.dispatch;
    engine.value = cfg.engine;
    enginePath.value = cfg.engine_path || "";
    port.value = cfg.port || 0;
    savedEngine.value = cfg.engine;
    savedEngines.value = cfg.engines || {};
    catalog.value = cfg.engine_catalog || [];
    // 给目录里的每个 engine 建本地编辑副本（已含保存过的覆盖）。
    for (const r of catalog.value) edits.value[r.name] = toEdit(r.name);
  }
  try {
    projects.value = (await api.projects()).projects || [];
  } catch {
    projects.value = [];
  }
}

// ---- b2) engine 目录与覆盖 ----
function row(name: string): EngineRow | undefined {
  return catalog.value.find((r) => r.name === name);
}

function fmtCommand(c: string | string[] | null | undefined): string {
  if (!c) return "";
  return Array.isArray(c) ? c.join(" ") : c;
}

function cmdEq(
  a: string | string[] | null | undefined,
  b: string | string[] | null | undefined,
): boolean {
  const norm = (x: string | string[] | null | undefined) =>
    x == null ? [] : Array.isArray(x) ? x : [x];
  return JSON.stringify(norm(a)) === JSON.stringify(norm(b));
}

function isCustom(name: string): boolean {
  const r = row(name);
  return (
    addedCustom.value.includes(name) ||
    !!r?.custom ||
    (!r && !!savedEngines.value[name])
  );
}

function toEdit(name: string): EngineEdit {
  const r = row(name);
  const ov = savedEngines.value[name];
  if (!r || r.custom) {
    const cmd = ov?.command ?? (r ? r.command : "");
    return {
      command: fmtCommand(cmd),
      commandRaw: cmd,
      args: (ov?.args ?? r?.args ?? []).join("\n"),
      timeout_sec: ov?.timeout_sec ?? r?.timeout_sec ?? 1800,
      prompt_template: ov?.prompt_template ?? r?.prompt_template ?? "",
    };
  }
  const cmd = ov?.command ?? r.command ?? "";
  return {
    command: fmtCommand(cmd),
    commandRaw: cmd,
    args: (ov?.args ?? r.args ?? r.default_args ?? []).join("\n"),
    timeout_sec:
      ov?.timeout_sec ?? r.timeout_sec ?? r.default_timeout_sec ?? 1800,
    prompt_template:
      ov?.prompt_template ?? r.prompt_template ?? r.default_prompt_template ?? "",
  };
}

function ensureEdit(name: string) {
  if (edits.value[name]) return;
  if (!row(name) && !savedEngines.value[name]) return;
  edits.value[name] = toEdit(name);
}

function onEngineChange() {
  riskAck.value = false;
  ensureEdit(engine.value);
}

/** 恢复默认：清掉该预设 engine 的本地覆盖，编辑副本回到 default_*（提交时即无差异）。 */
function resetDefaults(name: string) {
  const r = row(name);
  if (!r) return;
  edits.value[name] = {
    command: fmtCommand(r.default_command),
    commandRaw: r.default_command ?? "",
    args: (r.default_args || []).join("\n"),
    timeout_sec: r.default_timeout_sec ?? 1800,
    prompt_template: r.default_prompt_template || "",
  };
}

/** 删除自定义 engine：只从本次提交的 engines 里去掉，不涉及任何文件。 */
function removeCustom(name: string) {
  delete edits.value[name];
  addedCustom.value = addedCustom.value.filter((n) => n !== name);
  if (engine.value === name) {
    engine.value = savedEngine.value || visibleEngines.value[0] || "";
    onEngineChange();
  }
}

function addCustomEngine() {
  newEngineError.value = "";
  const name = newName.value.trim();
  if (!/^[a-z0-9_-]{1,32}$/.test(name)) {
    newEngineError.value = "名字只能用小写字母、数字、_ 或 -，最长 32 个字符。";
    return;
  }
  if (row(name) || addedCustom.value.includes(name)) {
    newEngineError.value = `engine「${name}」已存在。`;
    return;
  }
  const cmd = newCommand.value.trim();
  if (!cmd.startsWith("/")) {
    newEngineError.value = "命令要填存在的绝对路径（以 / 开头）。";
    return;
  }
  const args = newArgs.value
    .split("\n")
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
  if (args.filter((s) => s === "{prompt}").length !== 1) {
    newEngineError.value = "参数要一行一个，且必须恰好有一行是 {prompt}。";
    return;
  }
  addedCustom.value.push(name);
  edits.value[name] = {
    command: cmd,
    commandRaw: cmd,
    args: args.join("\n"),
    timeout_sec: 1800,
    prompt_template: "{prompt}",
  };
  engine.value = name;
  riskAck.value = false;
  newName.value = "";
  newCommand.value = "";
  newArgs.value = "";
}

const visibleEngines = computed(() => {
  const names: string[] = catalog.value
    .filter((r) => !r.hidden)
    .map((r) => r.name);
  // hidden 的（如 kimi）只在它就是当前已保存 engine 时露出；新加的自定义也要露出。
  for (const n of [savedEngine.value, engine.value, ...addedCustom.value]) {
    if (n && !names.includes(n)) names.push(n);
  }
  // 老后端没有 catalog 时保持原有 claude/codex 下拉。
  if (!catalog.value.length) names.unshift("claude", "codex");
  return names;
});

const edit = computed(() => edits.value[engine.value]);
const selectedRow = computed(() => row(engine.value));
const currentIsCustom = computed(() => isCustom(engine.value));
// 风险提示只在选中的 engine 带 risk 且不是当前已保存的 engine 时出现。
const riskNeeded = computed(
  () => !!selectedRow.value?.risk && engine.value !== savedEngine.value,
);

async function save() {
  saving.value = true;
  saveError.value = "";
  saved.value = false;
  // engines 覆盖：预设只提交与 default_* 不同的字段，自定义全字段提交。
  const enginesPatch: Record<string, EngineOverride> = {};
  for (const [name, e] of Object.entries(edits.value)) {
    const r = row(name);
    const args = e.args
      .split("\n")
      .map((s) => s.trim())
      .filter((s) => s.length > 0);
    const timeout = Number(e.timeout_sec);
    if (!Number.isInteger(timeout) || timeout < 0 || timeout > 86400) {
      saveError.value = `「${name}」的超时必须是 0–86400 的整数（0 = 不限）。`;
      saving.value = false;
      return;
    }
    if (!e.prompt_template.includes("{prompt}")) {
      saveError.value = `「${name}」的提示词模板必须含 {prompt}。`;
      saving.value = false;
      return;
    }
    if (isCustom(name)) {
      const cmd = e.command.trim();
      if (!cmd.startsWith("/")) {
        saveError.value = `「${name}」的命令必须是存在的绝对路径。`;
        saving.value = false;
        return;
      }
      if (args.filter((s) => s === "{prompt}").length !== 1) {
        saveError.value = `「${name}」的参数里必须恰好有一行是 {prompt}。`;
        saving.value = false;
        return;
      }
      enginesPatch[name] = {
        command: cmd,
        args,
        prompt_template: e.prompt_template,
        timeout_sec: timeout,
      };
    } else {
      if (!r) continue;
      const o: EngineOverride = {};
      if (!cmdEq(e.commandRaw, r.default_command)) o.command = e.commandRaw;
      if (JSON.stringify(args) !== JSON.stringify(r.default_args || []))
        o.args = args;
      if (timeout !== (r.default_timeout_sec ?? 1800))
        o.timeout_sec = timeout;
      if (e.prompt_template !== (r.default_prompt_template || ""))
        o.prompt_template = e.prompt_template;
      if (Object.keys(o).length > 0) enginesPatch[name] = o;
    }
  }
  try {
    const cfg = await api.saveConfig({
      dispatch: dispatch.value,
      engine: engine.value,
      engine_path: enginePath.value.trim(),
      port: Number(port.value) || 0,
      setup_done: true,
      ...(Object.keys(enginesPatch).length > 0
        ? { engines: enginesPatch }
        : {}),
    });
    savedEngine.value = engine.value;
    savedEngines.value = cfg.engines || {};
    if (cfg.engine_catalog) catalog.value = cfg.engine_catalog;
    addedCustom.value = [];
    riskAck.value = false;
    emit("saved", cfg);
    saved.value = true;
    if (window.location.hash === "#/setup") {
      // 保存即完成首次引导，回记录列表。
      window.location.hash = "";
    }
  } catch (err) {
    saveError.value = String(err);
  } finally {
    saving.value = false;
  }
}

async function addBinding() {
  bindError.value = "";
  const name = bindName.value.trim();
  const folder = bindFolder.value.trim();
  if (!name || !folder) {
    bindError.value = "目标名和代码目录都要填。";
    return;
  }
  bindBusy.value = true;
  try {
    projects.value = (await api.saveProject(name, folder)).projects || [];
    bindName.value = "";
    bindFolder.value = "";
  } catch (err) {
    bindError.value = String(err);
  } finally {
    bindBusy.value = false;
  }
}

async function removeBinding(name: string) {
  bindError.value = "";
  bindBusy.value = true;
  try {
    projects.value = (await api.deleteProject(name)).projects || [];
    if (rulesName.value === name) clearRules();
  } catch (err) {
    bindError.value = String(err);
  } finally {
    bindBusy.value = false;
  }
}

function editBinding(row: ProjectRow) {
  // 改 = 把这一行填回表单，同名保存即覆盖。
  bindName.value = row.name;
  bindFolder.value = row.folder;
}

// d) 规则
async function pickRules() {
  if (!rulesName.value) {
    clearRules();
    return;
  }
  rulesError.value = "";
  rulesState.value = "";
  try {
    const data: ProjectRules = await api.projectRules(rulesName.value);
    rulesText.value = data.exists ? data.rules : data.default;
    rulesDefault.value = data.default;
    rulesState.value = data.exists ? "已加载该项目的规则。" : "该项目还没有规则，已填入默认规则。";
  } catch (err) {
    rulesError.value = String(err);
  }
}

function clearRules() {
  rulesName.value = "";
  rulesText.value = "";
  rulesState.value = "";
  rulesError.value = "";
}

async function saveRules() {
  if (!rulesName.value) return;
  rulesError.value = "";
  rulesState.value = "";
  try {
    await api.saveProjectRules(rulesName.value, rulesText.value);
    rulesState.value = "已保存。";
  } catch (err) {
    rulesError.value = String(err);
  }
}

// e) 复制
async function copy(text: string, tag: string) {
  try {
    await navigator.clipboard.writeText(text);
    copied.value = tag;
  } catch {
    copied.value = "";
  }
}
</script>

<template>
  <div class="space-y-6">
    <!-- a) 派活方式 -->
    <section class="rounded-lg border border-slate-200 bg-white p-4">
      <h2 class="font-semibold">完成钉点时的派活方式</h2>
      <p class="mt-1 text-sm text-slate-500">
        决定点「完成」之后怎么把活交给 AI。之后随时可以回这个页面改。
      </p>
      <div class="mt-3 space-y-2 text-sm">
        <label class="flex items-start gap-2">
          <input v-model="dispatch" type="radio" value="auto" class="mt-1" />
          <span>
            <b>自动派给 CLI</b>
            <span class="text-slate-500">— 完成后直接在本机启动执行工具改代码；未绑定的钉不会自动跑，只记录并可在记录页复制提示词。</span>
          </span>
        </label>
        <label class="flex items-start gap-2">
          <input v-model="dispatch" type="radio" value="manual" class="mt-1" />
          <span>
            <b>复制提示词，我手动派</b>
            <span class="text-slate-500">— 完成后把完整提示词复制到剪贴板，由你贴给自己常用的 CLI；不启动任何程序。记录页随时可再次复制。</span>
          </span>
        </label>
      </div>
    </section>

    <!-- b) 执行工具 -->
    <section class="rounded-lg border border-slate-200 bg-white p-4">
      <h2 class="font-semibold">执行工具</h2>
      <p class="mt-1 text-sm text-slate-500">
        自动派活时使用的 CLI。自定义命令路径填绝对路径（支持 ~），例如
        <code class="rounded bg-slate-100 px-1">~/bin/claude-safe</code>；留空则用所选工具的默认命令。
        claude / codex 保持原有参数，可在这里改；pi / cursor / gemini 是新预设，默认不启用，选用前请看风险提示。
      </p>
      <div class="mt-3 flex flex-wrap items-center gap-4 text-sm">
        <label class="flex items-center gap-2">
          工具
          <select v-model="engine" class="rounded border border-slate-300 px-2 py-1" @change="onEngineChange">
            <option v-for="name in visibleEngines" :key="name" :value="name">{{ name }}</option>
          </select>
        </label>
        <label class="flex flex-1 items-center gap-2">
          自定义命令路径
          <input
            v-model="enginePath"
            type="text"
            placeholder="留空用默认 claude"
            class="min-w-0 flex-1 rounded border border-slate-300 px-2 py-1 font-mono text-xs"
          />
        </label>
      </div>

      <!-- 风险提示：选中的 engine 带 risk 且不是当前已保存的 engine 时出现 -->
      <div
        v-if="riskNeeded && selectedRow && selectedRow.risk"
        class="mt-3 rounded border border-amber-300 bg-amber-50 p-3 text-sm text-amber-800"
      >
        <p class="font-semibold">{{ engine }} 的风险提示</p>
        <p class="mt-1 whitespace-pre-wrap">{{ selectedRow.risk }}</p>
        <label class="mt-2 flex items-center gap-2">
          <input v-model="riskAck" type="checkbox" />
          我了解这个风险，仍要启用
        </label>
      </div>

      <!-- 选中 engine 的可编辑面板 -->
      <div v-if="edit" class="mt-4 space-y-3 rounded border border-slate-200 p-3 text-sm">
        <div class="flex items-center justify-between gap-2">
          <span class="font-medium">
            {{ engine }}<span v-if="currentIsCustom" class="ml-1 text-xs text-slate-500">自定义</span>
          </span>
          <button
            v-if="!currentIsCustom"
            class="text-xs text-blue-600 hover:underline"
            @click="resetDefaults(engine)"
          >恢复默认</button>
          <button
            v-else
            class="text-xs text-red-600 hover:underline"
            @click="removeCustom(engine)"
          >删除这个自定义 engine</button>
        </div>
        <div v-if="!currentIsCustom" class="flex flex-wrap items-center gap-2">
          <span class="text-slate-500">命令</span>
          <code class="rounded bg-slate-100 px-1 font-mono text-xs">{{ edit.command }}</code>
        </div>
        <label v-else class="flex flex-wrap items-center gap-2">
          <span class="text-slate-500">命令（绝对路径）</span>
          <input
            v-model="edit.command"
            type="text"
            class="min-w-0 flex-1 rounded border border-slate-300 px-2 py-1 font-mono text-xs"
          />
        </label>
        <div>
          <div class="text-slate-500">参数</div>
          <textarea
            v-model="edit.args"
            rows="3"
            class="mt-1 w-full rounded border border-slate-300 px-2 py-1 font-mono text-xs"
          ></textarea>
          <p class="mt-1 text-xs text-slate-500">
            一行一个参数；{prompt} 会换成提示词，{folder} 会换成绑定目录；没有 {prompt} 行时提示词追加在最后。
          </p>
        </div>
        <label class="flex flex-wrap items-center gap-2">
          超时（秒）
          <input
            v-model.number="edit.timeout_sec"
            type="number"
            min="0"
            max="86400"
            class="w-28 rounded border border-slate-300 px-2 py-1"
          />
          <span class="text-xs text-slate-500">0 = 不限，默认 1800。</span>
        </label>
        <div>
          <div class="text-slate-500">提示词模板（必须含 {prompt}）</div>
          <textarea
            v-model="edit.prompt_template"
            rows="3"
            class="mt-1 w-full rounded border border-slate-300 px-2 py-1 font-mono text-xs"
          ></textarea>
        </div>
      </div>

      <!-- 新增自定义 engine -->
      <div class="mt-4 border-t border-slate-100 pt-3 text-sm">
        <div class="text-xs font-medium text-slate-500">新增自定义 engine</div>
        <div class="mt-2 flex flex-wrap items-center gap-2">
          <input
            v-model="newName"
            type="text"
            placeholder="名字：小写字母数字 _ -，≤32"
            class="w-56 rounded border border-slate-300 px-2 py-1"
          />
          <input
            v-model="newCommand"
            type="text"
            placeholder="/绝对路径/到/命令"
            class="min-w-0 flex-1 rounded border border-slate-300 px-2 py-1 font-mono text-xs"
          />
          <button class="rounded border border-slate-300 px-3 py-1 hover:bg-slate-100" @click="addCustomEngine">添加</button>
        </div>
        <textarea
          v-model="newArgs"
          rows="2"
          placeholder="参数，一行一个；必须恰好有一行是 {prompt}"
          class="mt-2 w-full rounded border border-slate-300 px-2 py-1 font-mono text-xs"
        ></textarea>
        <p v-if="newEngineError" class="mt-1 text-sm text-red-600">{{ newEngineError }}</p>
      </div>
    </section>

    <!-- c) 项目绑定表 -->
    <section class="rounded-lg border border-slate-200 bg-white p-4">
      <h2 class="font-semibold">项目绑定</h2>
      <p class="mt-1 text-sm text-slate-500">
        应用名或网址 → 代码目录。自动派活只对这里显式绑定过的目标生效，没有绑定的钉不自动跑。
      </p>
      <div v-if="projects.length" class="mt-3 overflow-hidden rounded border border-slate-200">
        <table class="w-full text-sm">
          <thead class="bg-slate-100 text-left text-xs uppercase text-slate-500">
            <tr>
              <th class="px-3 py-2">目标（应用名 / 网址）</th>
              <th class="px-3 py-2">代码目录</th>
              <th class="px-3 py-2">状态</th>
              <th class="px-3 py-2"></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in projects" :key="row.name" class="border-t border-slate-100">
              <td class="px-3 py-2">{{ row.name }}</td>
              <td class="px-3 py-2 font-mono text-xs">{{ row.folder }}</td>
              <td class="whitespace-nowrap px-3 py-2 text-xs">
                <span v-if="!row.exists" class="text-red-600">目录不存在</span>
                <template v-else>
                  <span class="text-green-700">目录存在</span>
                  <span v-if="row.is_git" class="ml-1 text-slate-500">· git</span>
                  <span v-else class="ml-1 text-amber-600">· 非 git 仓库</span>
                </template>
              </td>
              <td class="whitespace-nowrap px-3 py-2 text-right text-xs">
                <button class="mr-2 text-blue-600 hover:underline" @click="editBinding(row)">编辑</button>
                <button class="text-red-600 hover:underline" :disabled="bindBusy" @click="removeBinding(row.name)">删除</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-else class="mt-3 text-sm text-slate-500">还没有绑定。</p>
      <div class="mt-3 flex flex-wrap items-center gap-2 text-sm">
        <input
          v-model="bindName"
          type="text"
          placeholder="应用名或网址，如 Notes 或 http://localhost:3000"
          class="min-w-0 flex-1 rounded border border-slate-300 px-2 py-1"
        />
        <input
          v-model="bindFolder"
          type="text"
          placeholder="~/projects/my-app"
          class="min-w-0 flex-1 rounded border border-slate-300 px-2 py-1 font-mono text-xs"
        />
        <button
          class="rounded bg-blue-600 px-3 py-1 text-white hover:bg-blue-700 disabled:opacity-50"
          :disabled="bindBusy"
          @click="addBinding"
        >{{ bindName && projects.some((p) => p.name === bindName.trim()) ? "更新绑定" : "添加绑定" }}</button>
      </div>
      <p v-if="bindError" class="mt-2 text-sm text-red-600">{{ bindError }}</p>
    </section>

    <!-- d) 提示规则 -->
    <section class="rounded-lg border border-slate-200 bg-white p-4">
      <h2 class="font-semibold">项目提示规则（handoff-rules.md）</h2>
      <p class="mt-1 text-sm text-slate-500">每个绑定项目一份，派活的提示词会带上。</p>
      <div class="mt-3 flex items-center gap-2 text-sm">
        <select v-model="rulesName" class="rounded border border-slate-300 px-2 py-1" @change="pickRules">
          <option value="">选择项目…</option>
          <option v-for="row in projects" :key="row.name" :value="row.name">{{ row.name }}</option>
        </select>
        <button
          class="rounded bg-slate-700 px-3 py-1 text-white hover:bg-slate-800 disabled:opacity-50"
          :disabled="!rulesName"
          @click="saveRules"
        >保存规则</button>
      </div>
      <textarea
        v-model="rulesText"
        rows="7"
        :disabled="!rulesName"
        placeholder="先在上面选择一个项目"
        class="mt-2 w-full rounded border border-slate-300 px-2 py-1 font-mono text-xs disabled:bg-slate-50"
      ></textarea>
      <p v-if="rulesState" class="mt-1 text-xs text-slate-500">{{ rulesState }}</p>
      <p v-if="rulesError" class="mt-1 text-sm text-red-600">{{ rulesError }}</p>
    </section>

    <!-- e) 记录页地址 -->
    <section class="rounded-lg border border-slate-200 bg-white p-4">
      <h2 class="font-semibold">记录页地址</h2>
      <div class="mt-3 flex flex-wrap items-center gap-2 text-sm">
        <input
          type="text"
          readonly
          :value="appUrl"
          class="min-w-0 flex-1 rounded border border-slate-200 bg-slate-50 px-2 py-1 font-mono text-xs"
        />
        <button class="rounded border border-slate-300 px-3 py-1 hover:bg-slate-100" @click="copy(appUrl, 'url')">
          {{ copied === "url" ? "已复制 ✓" : "复制" }}
        </button>
      </div>
      <label class="mt-3 flex items-center gap-2 text-sm">
        端口
        <input
          v-model.number="port"
          type="number"
          min="0"
          max="65535"
          class="w-28 rounded border border-slate-300 px-2 py-1"
        />
        <span class="text-xs text-slate-500">0 = 默认端口；改完保存，重启 DingCode 后生效。</span>
      </label>
    </section>

    <!-- 保存 -->
    <div class="flex items-center gap-3">
      <button
        class="rounded bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-50"
        :disabled="saving || (riskNeeded && !riskAck)"
        @click="save"
      >{{ saving ? "保存中…" : "保存设置" }}</button>
      <span v-if="saved" class="text-sm text-green-700">已保存。</span>
      <span v-if="saveError" class="text-sm text-red-600">{{ saveError }}</span>
    </div>
  </div>
</template>

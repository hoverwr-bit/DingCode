<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import {
  api,
  type AppConfig,
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
  }
  try {
    projects.value = (await api.projects()).projects || [];
  } catch {
    projects.value = [];
  }
}

async function save() {
  saving.value = true;
  saveError.value = "";
  saved.value = false;
  try {
    const cfg = await api.saveConfig({
      dispatch: dispatch.value,
      engine: engine.value,
      engine_path: enginePath.value.trim(),
      port: Number(port.value) || 0,
      setup_done: true,
    });
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
      </p>
      <div class="mt-3 flex flex-wrap items-center gap-4 text-sm">
        <label class="flex items-center gap-2">
          工具
          <select v-model="engine" class="rounded border border-slate-300 px-2 py-1">
            <option value="claude">claude</option>
            <option value="codex">codex</option>
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
          placeholder="应用名或网址，如 Notes 或 http://localhost:8090"
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
        :disabled="saving"
        @click="save"
      >{{ saving ? "保存中…" : "保存设置" }}</button>
      <span v-if="saved" class="text-sm text-green-700">已保存。</span>
      <span v-if="saveError" class="text-sm text-red-600">{{ saveError }}</span>
    </div>
  </div>
</template>

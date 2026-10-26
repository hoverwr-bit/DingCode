<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from "vue";
import { api, note_text, type AppConfig, type NoteDoc, type RunPayload } from "../api";
import PinCard from "./PinCard.vue";
import StatusBadge from "./StatusBadge.vue";

const props = defineProps<{ sid: string }>();
const emit = defineEmits<{ (e: "back"): void }>();

const payload = ref<RunPayload | null>(null);
const noteDoc = ref<NoteDoc | null>(null);
const config = ref<AppConfig | null>(null);
const error = ref("");
const loading = ref(true);
// M6 手动派活：完整提示词可在记录页再次复制。
const copyState = ref("");
// 设计：SPA 每 1.5s 轮询 GET /api/runs/<sid>（运行中才有意义）。
let pollTimer: ReturnType<typeof setInterval> | null = null;

async function load() {
  loading.value = true;
  error.value = "";
  try {
    payload.value = await api.run(props.sid);
    noteDoc.value = await api.note(props.sid);
    if (!config.value) {
      config.value = await api.config().catch(() => null);
    }
  } catch (err) {
    error.value = String(err);
  } finally {
    loading.value = false;
  }
}

async function copyPrompt() {
  try {
    const data = await api.sessionPrompt(props.sid);
    if (!data) {
      copyState.value = "没有可复制的提示词";
      return;
    }
    await navigator.clipboard.writeText(data.prompt);
    copyState.value = "已复制完整提示词 ✓";
  } catch {
    copyState.value = "复制失败";
  }
}

async function poll() {
  if (document.hidden) return;
  try {
    const fresh = await api.run(props.sid);
    payload.value = fresh;
    if (fresh.status !== "running" && pollTimer) {
      // 这轮结束：拉一次全量（含各钉最新 summary），然后停表。
      clearInterval(pollTimer);
      pollTimer = null;
    }
  } catch {
    // 轮询失败不打断页面，下一轮再试。
  }
}

function syncPolling() {
  const running = payload.value?.status === "running";
  if (running && !pollTimer) {
    pollTimer = setInterval(poll, 1500);
  }
}

onMounted(load);
watch(() => props.sid, load);
watch(payload, syncPolling);
onBeforeUnmount(() => {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
});

function noteOf(pid: string): string {
  const pins = noteDoc.value?.pins || [];
  const found = pins.find((p) => String(p.id) === pid);
  return note_text(found);
}

function onNoteSaved(pid: string, note: string) {
  // runs/note.json 要等下次 autofix 才重写；先在本地把列表页批注同步掉。
  const pins = noteDoc.value?.pins || [];
  const found = pins.find((p) => String(p.id) === pid);
  if (found) found.note = note;
}

function onReverted(_pid: string) {
  // 逐颗撤回改了磁盘与各轮 summary：拉一次全量刷新合并态。
  load();
}
</script>

<template>
  <div>
    <button
      class="mb-4 text-sm text-blue-600 hover:underline"
      @click="emit('back')"
    >
      ← 返回会话列表
    </button>
    <p v-if="loading" class="text-slate-500">加载中…</p>
    <p v-else-if="error" class="text-red-600">{{ error }}</p>
    <template v-else-if="payload">
      <div class="mb-4 rounded-lg border border-slate-200 bg-white p-4">
        <div class="flex items-center gap-3">
          <h2 class="font-mono text-sm font-semibold">{{ payload.session }}</h2>
          <StatusBadge :status="payload.status" />
          <button
            class="ml-auto rounded border border-blue-500 px-3 py-1 text-xs text-blue-600 hover:bg-blue-50"
            @click="copyPrompt"
          >复制提示词</button>
        </div>
        <p v-if="copyState" class="mt-1 text-right text-xs text-slate-500">{{ copyState }}</p>
        <p
          v-if="payload.status === 'manual'"
          class="mt-2 rounded bg-amber-50 px-3 py-2 text-xs text-amber-800"
        >这个会话是手动派活：没有启动任何 CLI。点右上「复制提示词」把完整提示词贴给你的执行工具。</p>
        <dl class="mt-2 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
          <dt class="text-slate-500">最新轮次</dt>
          <dd>{{ payload.round }}</dd>
          <dt class="text-slate-500">轮次列表</dt>
          <dd class="font-mono text-xs">{{ payload.rounds.join(", ") || "—" }}</dd>
          <dt class="text-slate-500">目标目录</dt>
          <dd class="font-mono text-xs">{{ payload.folder || "—" }}</dd>
          <dt class="text-slate-500">摘要</dt>
          <dd>{{ payload.summary_line || "—" }}</dd>
        </dl>
      </div>

      <p v-if="!payload.pins.length" class="text-slate-500">该会话没有钉子记录。</p>
      <div class="space-y-4">
        <PinCard
          v-for="pin in payload.pins"
          :key="pin.id"
          :sid="payload.session"
          :pin="pin"
          :note="noteOf(pin.id)"
          :run-status="payload.status"
          @note-saved="onNoteSaved"
          @reverted="onReverted"
        />
      </div>
    </template>
  </div>
</template>

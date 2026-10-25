<script setup lang="ts">
import { onMounted, ref, watch } from "vue";
import { api, note_text, type NoteDoc, type RunPayload } from "../api";
import PinCard from "./PinCard.vue";
import StatusBadge from "./StatusBadge.vue";

const props = defineProps<{ sid: string }>();
const emit = defineEmits<{ (e: "back"): void }>();

const payload = ref<RunPayload | null>(null);
const noteDoc = ref<NoteDoc | null>(null);
const error = ref("");
const loading = ref(true);

async function load() {
  loading.value = true;
  error.value = "";
  try {
    payload.value = await api.run(props.sid);
    noteDoc.value = await api.note(props.sid);
  } catch (err) {
    error.value = String(err);
  } finally {
    loading.value = false;
  }
}

onMounted(load);
watch(() => props.sid, load);

function noteOf(pid: string): string {
  const pins = noteDoc.value?.pins || [];
  const found = pins.find((p) => String(p.id) === pid);
  return note_text(found);
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
        </div>
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
        />
      </div>
    </template>
  </div>
</template>

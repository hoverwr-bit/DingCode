<script setup lang="ts">
import { onMounted, ref } from "vue";
import { api, type SessionSummary } from "../api";
import StatusBadge from "./StatusBadge.vue";

const emit = defineEmits<{ (e: "open", sid: string): void }>();

const sessions = ref<SessionSummary[]>([]);
const loading = ref(true);
const error = ref("");

onMounted(async () => {
  try {
    const data = await api.sessions();
    sessions.value = data.sessions || [];
  } catch (err) {
    error.value = String(err);
  } finally {
    loading.value = false;
  }
});

function fmt(finished: string): string {
  return (finished || "").replace("T", " ").replace("Z", " UTC");
}
</script>

<template>
  <div>
    <p v-if="loading" class="text-slate-500">加载中…</p>
    <p v-else-if="error" class="text-red-600">{{ error }}</p>
    <p v-else-if="!sessions.length" class="text-slate-500">
      暂无会话记录（runs/ 下还没有带 status.json 的会话）。
    </p>
    <div v-else class="overflow-hidden rounded-lg border border-slate-200 bg-white">
      <table class="w-full text-sm">
        <thead class="bg-slate-100 text-left text-xs uppercase text-slate-500">
          <tr>
            <th class="px-4 py-2">会话</th>
            <th class="px-4 py-2">状态</th>
            <th class="px-4 py-2">轮次</th>
            <th class="px-4 py-2">摘要</th>
            <th class="px-4 py-2">结束时间</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="item in sessions"
            :key="item.session"
            class="cursor-pointer border-t border-slate-100 hover:bg-slate-50"
            @click="emit('open', item.session)"
          >
            <td class="px-4 py-2 font-mono text-xs">{{ item.session }}</td>
            <td class="px-4 py-2"><StatusBadge :status="item.status" /></td>
            <td class="px-4 py-2">{{ item.round }}</td>
            <td class="max-w-xs truncate px-4 py-2">{{ item.summary_line }}</td>
            <td class="whitespace-nowrap px-4 py-2 text-slate-500">{{ fmt(item.finished) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

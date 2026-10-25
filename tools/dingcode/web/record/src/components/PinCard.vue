<script setup lang="ts">
import { ref } from "vue";
import { api, type Pin, type PinHistory } from "../api";
import DiffView from "./DiffView.vue";
import StatusBadge from "./StatusBadge.vue";

// 一颗钉：批注 + 状态 + summary_zh + diff。展开后拉取该钉各轮历史。
// 只读：没有改批注/重跑/撤回按钮（M2/M3 再加）。
const props = defineProps<{ sid: string; pin: Pin; note: string }>();

const open = ref(false);
const loading = ref(false);
const error = ref("");
const history = ref<PinHistory | null>(null);

async function toggle() {
  open.value = !open.value;
  if (open.value && !history.value && !loading.value) {
    loading.value = true;
    try {
      history.value = await api.pinHistory(props.sid, props.pin.id);
    } catch (err) {
      error.value = String(err);
    } finally {
      loading.value = false;
    }
  }
}

function roundLabel(h: PinHistory["rounds"][number]): string {
  const parts = [`第 ${h.round} 轮`];
  if (h.pin_only) parts.push("单钉");
  if (h.rerun != null) parts.push(`重跑 #${h.rerun}`);
  return parts.join(" · ");
}
</script>

<template>
  <section class="rounded-lg border border-slate-200 bg-white">
    <header
      class="flex cursor-pointer items-start gap-3 px-4 py-3 hover:bg-slate-50"
      @click="toggle"
    >
      <span class="mt-0.5 text-slate-400">{{ open ? "▾" : "▸" }}</span>
      <div class="min-w-0 flex-1">
        <div class="flex flex-wrap items-center gap-2">
          <span class="font-mono text-xs text-slate-500">#{{ pin.id }}</span>
          <StatusBadge :status="pin.status" />
          <span v-if="pin.round" class="text-xs text-slate-400">
            第 {{ pin.round }} 轮
          </span>
        </div>
        <p v-if="note" class="mt-1 text-sm text-slate-700">{{ note }}</p>
        <p v-if="pin.summary_zh" class="mt-1 text-sm text-slate-500">
          Claude：{{ pin.summary_zh }}
        </p>
      </div>
    </header>

    <div v-if="open" class="border-t border-slate-100 px-4 py-3">
      <p v-if="loading" class="text-sm text-slate-500">加载历史…</p>
      <p v-else-if="error" class="text-sm text-red-600">{{ error }}</p>
      <template v-else-if="history">
        <p
          v-if="!history.rounds.length"
          class="text-sm text-slate-500"
        >
          没有该钉的轮次记录。
        </p>
        <div
          v-for="h in history.rounds"
          :key="h.round"
          class="mb-4 last:mb-0"
        >
          <div class="mb-1 flex flex-wrap items-center gap-2 text-xs text-slate-500">
            <span class="font-medium text-slate-600">{{ roundLabel(h) }}</span>
            <StatusBadge :status="h.status" />
            <span v-if="h.reverted" class="text-orange-600">已撤回</span>
            <span v-if="h.stale" class="text-orange-600">基于已撤回的修改，建议重跑</span>
          </div>
          <p v-if="h.summary_zh" class="mb-1 text-sm text-slate-600">
            {{ h.summary_zh }}
          </p>
          <DiffView v-if="h.diff" :text="h.diff" />
          <p v-else class="text-xs text-slate-400">该轮无 diff。</p>
        </div>
      </template>
    </div>
  </section>
</template>

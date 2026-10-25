<script setup lang="ts">
import { ref } from "vue";
import SessionList from "./components/SessionList.vue";
import SessionDetail from "./components/SessionDetail.vue";

// 只读记录页：列表 → 详情，无任何写操作。
const current = ref("");

function open(sid: string) {
  current.value = sid;
}
</script>

<template>
  <div class="min-h-screen bg-slate-50 text-slate-800">
    <header class="border-b border-slate-200 bg-white">
      <div class="mx-auto max-w-5xl px-4 py-3 flex items-baseline gap-3">
        <h1 class="text-lg font-semibold">DingCode 会话记录</h1>
        <span class="text-xs text-slate-400">只读</span>
      </div>
    </header>
    <main class="mx-auto max-w-5xl px-4 py-6">
      <SessionDetail v-if="current" :sid="current" @back="current = ''" />
      <SessionList v-else @open="open" />
    </main>
  </div>
</template>

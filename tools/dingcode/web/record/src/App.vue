<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from "vue";
import { api, type AppConfig } from "./api";
import SessionList from "./components/SessionList.vue";
import SessionDetail from "./components/SessionDetail.vue";
import SetupView from "./components/SetupView.vue";

// 会话记录页：列表 → 详情；M2 改单钉批注、单钉重跑；M3 逐颗撤回（冲突检测）。
// M6：#/setup 设置页；config.json 没有 setup_done 时首次打开强制先过一次设置。
const current = ref("");
const route = ref(window.location.hash);
const config = ref<AppConfig | null>(null);
const booting = ref(true);

function onHash() {
  route.value = window.location.hash;
}

function open(sid: string) {
  current.value = sid;
}

onMounted(async () => {
  window.addEventListener("hashchange", onHash);
  try {
    config.value = await api.config();
    // 首次判定：旧用户（已有 config 但没确认过）和全新安装都走一次设置页。
    if (!config.value.setup_done && route.value !== "#/setup") {
      window.location.hash = "#/setup";
    }
  } catch {
    // 读不到配置不挡记录页；设置页里保存时会再校验。
  } finally {
    booting.value = false;
  }
});

onBeforeUnmount(() => {
  window.removeEventListener("hashchange", onHash);
});
</script>

<template>
  <div class="min-h-screen bg-slate-50 text-slate-800">
    <header class="border-b border-slate-200 bg-white">
      <div class="mx-auto max-w-5xl px-4 py-3 flex items-baseline gap-3">
        <h1 class="text-lg font-semibold">DingCode 会话记录</h1>
        <span class="text-xs text-slate-400">批注 · 单钉重跑 · 逐颗撤回</span>
        <a
          href="#/setup"
          class="ml-auto text-sm text-blue-600 hover:underline"
          :class="{ 'font-semibold': route === '#/setup' }"
        >设置</a>
      </div>
    </header>
    <main class="mx-auto max-w-5xl px-4 py-6">
      <p v-if="booting" class="text-slate-500">加载中…</p>
      <SetupView
        v-else-if="route === '#/setup'"
        :config="config"
        @saved="config = $event"
      />
      <template v-else>
        <SessionDetail v-if="current" :sid="current" @back="current = ''" />
        <SessionList v-else @open="open" />
      </template>
    </main>
  </div>
</template>

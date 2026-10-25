<script setup lang="ts">
import { computed } from "vue";

// 统一 diff 按行渲染：+ 绿、- 红、@@ 蓝、文件头灰。只读展示。
const props = defineProps<{ text: string }>();

interface Line {
  kind: "add" | "del" | "hunk" | "meta" | "ctx";
  text: string;
}

const lines = computed<Line[]>(() =>
  (props.text || "").split("\n").map((raw) => {
    if (raw.startsWith("+")) return { kind: "add", text: raw };
    if (raw.startsWith("-")) return { kind: "del", text: raw };
    if (raw.startsWith("@@")) return { kind: "hunk", text: raw };
    if (
      raw.startsWith("diff ") ||
      raw.startsWith("index ") ||
      raw.startsWith("--- ") ||
      raw.startsWith("+++ ")
    ) {
      return { kind: "meta", text: raw };
    }
    return { kind: "ctx", text: raw };
  })
);

const klass: Record<Line["kind"], string> = {
  add: "bg-green-50 text-green-800",
  del: "bg-red-50 text-red-800",
  hunk: "bg-blue-50 text-blue-700",
  meta: "text-slate-400",
  ctx: "text-slate-600",
};
</script>

<template>
  <pre
    class="overflow-x-auto rounded border border-slate-200 bg-white p-2 text-xs leading-5 font-mono"
  ><code><span
      v-for="(line, i) in lines"
      :key="i"
      class="block px-1"
      :class="klass[line.kind]"
      >{{ line.text || " " }}</span
    ></code></pre>
</template>

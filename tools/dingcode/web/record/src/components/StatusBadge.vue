<script setup lang="ts">
import { computed } from "vue";
import { Badge } from "frappe-ui";

const props = defineProps<{ status: string }>();

// 中文标签。未知状态显示原文。
const label = computed(() => {
  const map: Record<string, string> = {
    fixed: "已修复",
    "not-fixed": "未修复",
    unsure: "不确定",
    open: "待处理",
    done: "完成",
    running: "进行中",
    error: "出错",
    confirmed: "已确认",
    manual: "待手动派",
    failed: "失败",
  };
  return map[props.status] || props.status || "未知";
});

// frappe-ui Badge theme（0.1.278：颜色用 theme，风格用 variant/subtle）。
const theme = computed(() => {
  const map: Record<string, "green" | "red" | "orange" | "blue" | "gray"> = {
    fixed: "green",
    done: "green",
    confirmed: "green",
    "not-fixed": "red",
    error: "red",
    unsure: "orange",
    running: "blue",
    manual: "orange",
    open: "gray",
  };
  return map[props.status] || "gray";
});
</script>

<template>
  <Badge :label="label" :theme="theme" variant="subtle" size="sm" />
</template>

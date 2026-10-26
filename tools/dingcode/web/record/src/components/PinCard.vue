<script setup lang="ts">
import { ref } from "vue";
import { ApiError, api, type Pin, type PinHistory } from "../api";
import DiffView from "./DiffView.vue";
import StatusBadge from "./StatusBadge.vue";

// 一颗钉：批注 + 状态 + summary_zh + diff。展开后拉取该钉各轮历史。
// M2：可编辑批注（写源 note 文件）、单钉重跑（后台轮次，进度靠父级轮询）。
// M3：逐颗撤回（三方合并，冲突 409 时提示先重跑或整轮回滚）。
const props = defineProps<{
  sid: string;
  pin: Pin;
  note: string;
  /** 整个会话的运行状态（running 时按钮禁用并显示进度）。 */
  runStatus: string;
}>();
const emit = defineEmits<{
  (e: "note-saved", pid: string, note: string): void;
  (e: "reverted", pid: string): void;
}>();

const open = ref(false);
const loading = ref(false);
const error = ref("");
const history = ref<PinHistory | null>(null);

// 批注本地副本：props.note 来自 runs/note.json（保存后不重写），所以保存成功后直接更新本地。
// null = 还没改过；空串是合法的「清空批注」。
const localNote = ref<string | null>(null);
const noteShown = () => (localNote.value !== null ? localNote.value : props.note);
const editing = ref(false);
const draft = ref("");
const saving = ref(false);
const saveError = ref("");

// 重跑：发起后记下轮号，父级轮询 status.json 到 done。
const rerunning = ref(false);
const rerunRound = ref(0);
const rerunError = ref("");
const feedback = ref("");
const confirming = ref(false);

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

function startEdit() {
  draft.value = noteShown();
  saveError.value = "";
  editing.value = true;
}

async function saveNote() {
  saving.value = true;
  saveError.value = "";
  try {
    const res = await api.editPinNote(props.sid, props.pin.id, draft.value);
    localNote.value = res.note;
    editing.value = false;
    emit("note-saved", props.pin.id, res.note);
  } catch (err) {
    saveError.value = String(err);
  } finally {
    saving.value = false;
  }
}

async function rerun() {
  if (!confirming.value) {
    confirming.value = true;
    return;
  }
  rerunning.value = true;
  rerunError.value = "";
  try {
    const res = await api.rerunPin(props.sid, props.pin.id, feedback.value.trim());
    rerunRound.value = res.round;
    confirming.value = false;
    feedback.value = "";
  } catch (err) {
    rerunError.value = String(err);
    confirming.value = false;
  } finally {
    rerunning.value = false;
  }
}

// 撤回这颗：二次确认；409 冲突时按设计提示「先重跑或整轮回滚」并列出冲突文件。
const reverting = ref(false);
const revertConfirming = ref(false);
const revertDone = ref(false);
const revertError = ref("");

async function revert() {
  if (revertDone.value) return;
  if (!revertConfirming.value) {
    revertConfirming.value = true;
    return;
  }
  reverting.value = true;
  revertError.value = "";
  try {
    await api.revertPin(props.sid, props.pin.id);
    revertConfirming.value = false;
    revertDone.value = true;
    // 重拉该钉各轮历史：reverted / stale 立即反映到轮次列表。
    history.value = await api.pinHistory(props.sid, props.pin.id);
    emit("reverted", props.pin.id);
  } catch (err) {
    revertError.value = revertMessage(err);
    revertConfirming.value = false;
  } finally {
    reverting.value = false;
  }
}

function revertMessage(err: unknown): string {
  if (err instanceof ApiError && err.status === 409) {
    const conflicts = (err.data.conflicts as string[] | undefined) || [];
    const files = conflicts.length ? "（冲突文件：" + conflicts.join("、") + "）" : "";
    return "撤回冲突：后续轮次改动了相同区域" + files
      + "，无法自动合并，未改动任何文件。请先重跑这颗钉，或使用整轮回滚。";
  }
  return "撤回失败：" + String(err instanceof Error ? err.message : err);
}

const busy = () => props.runStatus === "running";

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
          <span v-if="busy()" class="text-xs text-blue-600">会话运行中…</span>
        </div>
        <p v-if="noteShown()" class="mt-1 text-sm text-slate-700">{{ noteShown() }}</p>
        <p v-if="pin.summary_zh" class="mt-1 text-sm text-slate-500">
          Claude：{{ pin.summary_zh }}
        </p>
      </div>
    </header>

    <div v-if="open" class="border-t border-slate-100 px-4 py-3">
      <!-- M2 操作区：编辑批注 + 重跑这颗；M3 加撤回这颗 -->
      <div class="mb-4 space-y-2">
        <div v-if="!editing" class="flex items-center gap-2">
          <button
            class="rounded border border-slate-300 px-2 py-1 text-xs text-slate-700 hover:bg-slate-100"
            :disabled="saving"
            @click="startEdit"
          >
            编辑批注
          </button>
          <button
            class="rounded bg-blue-600 px-2 py-1 text-xs text-white hover:bg-blue-700 disabled:opacity-50"
            :disabled="rerunning || busy()"
            @click="rerun"
          >
            {{ confirming ? "确认重跑？" : "重跑这颗" }}
          </button>
          <input
            v-model="feedback"
            type="text"
            placeholder="重跑反馈（可选）"
            class="w-48 rounded border border-slate-300 px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400"
            @click.stop
          />
          <button
            class="rounded border border-orange-300 px-2 py-1 text-xs text-orange-700 hover:bg-orange-50 disabled:opacity-50"
            :disabled="reverting || revertDone || busy()"
            @click="revert"
          >
            {{ revertDone ? "已撤回" : revertConfirming ? "确认撤回？" : "撤回这颗" }}
          </button>
          <span v-if="busy()" class="text-xs text-blue-600">
            正在运行，等待轮询结果…
          </span>
          <span v-else-if="rerunRound" class="text-xs text-slate-500">
            已发起第 {{ rerunRound }} 轮单钉重跑
          </span>
          <span v-if="rerunError" class="text-xs text-red-600">{{ rerunError }}</span>
          <span v-if="revertError" class="text-xs text-red-600">{{ revertError }}</span>
        </div>
        <template v-else>
          <textarea
            v-model="draft"
            rows="3"
            class="w-full rounded border border-slate-300 px-2 py-1 text-sm focus:outline-none focus:ring-1 focus:ring-blue-400"
          ></textarea>
          <div class="flex items-center gap-2">
            <button
              class="rounded bg-blue-600 px-2 py-1 text-xs text-white hover:bg-blue-700 disabled:opacity-50"
              :disabled="saving"
              @click="saveNote"
            >
              {{ saving ? "保存中…" : "保存批注" }}
            </button>
            <button
              class="rounded border border-slate-300 px-2 py-1 text-xs text-slate-700 hover:bg-slate-100"
              :disabled="saving"
              @click="editing = false"
            >
              取消
            </button>
            <span v-if="saveError" class="text-xs text-red-600">{{ saveError }}</span>
          </div>
        </template>
      </div>

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

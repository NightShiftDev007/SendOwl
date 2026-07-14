<template>
  <nav class="step-nav" :aria-label="$t('main.stepNavLabel')">
    <button
      v-for="(name, idx) in stepNames"
      :key="idx"
      type="button"
      class="step-item"
      :class="{
        active: idx + 1 === currentStep,
        reachable: reachable[idx + 1] && idx + 1 !== currentStep,
        disabled: !reachable[idx + 1],
      }"
      :disabled="!reachable[idx + 1] || idx + 1 === currentStep"
      :title="tooltipFor(idx + 1, name)"
      @click="go(idx + 1)"
    >
      <span class="idx mono">{{ idx + 1 }}</span>
      <span class="label">{{ name }}</span>
    </button>
  </nav>
</template>

<script setup>
import { computed, watch, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import {
  canReachStep,
  getWorkflowContext,
  routeForStep,
  syncWorkflowFromServer,
  touchWorkflowStep,
} from '../store/workflowContext'

const props = defineProps({
  currentStep: { type: Number, required: true },
  decisionId: { type: String, default: '' },
})

const router = useRouter()
const { t, tm } = useI18n()
const stored = getWorkflowContext()

const stepNames = computed(() => {
  const names = tm('main.stepNames')
  return Array.isArray(names) ? names : ['1', '2', '3', '4', '5']
})

// 显式依赖 serverMaxReached，确保 Step2 压锁后顶栏立刻重算
const serverMaxReached = computed(() => stored.serverMaxReached)

const ctx = computed(() => ({
  decisionId: props.decisionId || stored.decisionId || '',
  ontologyId: stored.ontologyId || '',
  simulationId: stored.simulationId || '',
  reportId: stored.reportId || '',
  currentStep: props.currentStep,
  serverMaxReached: serverMaxReached.value,
}))

const reachable = computed(() => ({
  1: canReachStep(1, ctx.value),
  2: canReachStep(2, ctx.value),
  3: canReachStep(3, ctx.value),
  4: canReachStep(4, ctx.value),
  5: canReachStep(5, ctx.value),
}))

watch(
  () => [props.currentStep, props.decisionId],
  async ([, decisionId]) => {
    const ids = {}
    if (decisionId && decisionId !== 'new') {
      ids.decisionId = decisionId
    }
    touchWorkflowStep(props.currentStep, ids)
    if (decisionId && String(decisionId).startsWith('dec_')) {
      await syncWorkflowFromServer(decisionId)
    }
  },
  { immediate: true },
)

// 同页停留时（推演跑完等）也要刷新顶栏解锁
function onVisibilityRefresh() {
  if (document.visibilityState !== 'visible') return
  const id = props.decisionId || stored.decisionId
  if (id && String(id).startsWith('dec_')) syncWorkflowFromServer(id)
}

onMounted(() => {
  document.addEventListener('visibilitychange', onVisibilityRefresh)
  window.addEventListener('focus', onVisibilityRefresh)
})

onUnmounted(() => {
  document.removeEventListener('visibilitychange', onVisibilityRefresh)
  window.removeEventListener('focus', onVisibilityRefresh)
})

function tooltipFor(step, name) {
  if (step === props.currentStep) return `${name} · ${t('main.stepNavCurrent')}`
  if (reachable.value[step]) return t('main.stepNavGo', { name })
  return t('main.stepNavLocked')
}

function go(step) {
  if (step === props.currentStep || !reachable.value[step]) return
  const route = routeForStep(step, ctx.value)
  if (route) router.push(route)
}
</script>

<style scoped>
.step-nav {
  display: flex;
  align-items: center;
  gap: 4px;
  max-width: min(560px, 48vw);
  overflow-x: auto;
  scrollbar-width: none;
}
.step-nav::-webkit-scrollbar {
  display: none;
}
.step-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: 1px solid var(--border, #e5e7eb);
  background: var(--bg, #fff);
  color: var(--ink-muted, #6b7280);
  padding: 4px 8px;
  font-size: 11px;
  line-height: 1.2;
  cursor: pointer;
  white-space: nowrap;
  flex-shrink: 0;
  transition: border-color 0.15s ease, color 0.15s ease, background 0.15s ease;
}
.step-item .idx {
  font-weight: 700;
  opacity: 0.75;
}
.step-item.active {
  border-color: var(--ink, #111);
  color: var(--ink, #111);
  background: var(--bg-muted, #f5f5f5);
  font-weight: 600;
  cursor: default;
}
.step-item.reachable {
  color: var(--ink, #111);
}
.step-item.reachable:hover {
  border-color: var(--ink, #111);
}
.step-item.disabled {
  opacity: 0.38;
  cursor: not-allowed;
}
.mono {
  font-family: var(--font-mono, ui-monospace, monospace);
}
@media (max-width: 900px) {
  .step-item .label {
    display: none;
  }
  .step-nav {
    max-width: 42vw;
  }
}
</style>

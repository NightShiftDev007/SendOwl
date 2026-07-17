<template>
  <div v-if="matrix.length > 1 || totalRuns > 1" class="run-matrix-panel">
    <div class="matrix-head">
      <div class="head-left">
        <span class="mono title">Scenario × Run</span>
        <span class="progress mono">{{ progress.done }}/{{ progress.total }}</span>
      </div>
      <span class="hint">点击查看该 Run 详情（推演范围仍是全部）</span>
    </div>

    <div class="scenario-list">
      <div
        v-for="sc in scenarios"
        :key="sc.scenario_id || sc.scenario_name"
        class="scenario-row"
        :class="{ active: sc.scenario_id === activeScenarioId }"
      >
        <div class="scenario-meta">
          <span class="dot" :style="{ background: sc.color }"></span>
          <span class="scenario-name" :title="sc.scenario_name">{{ sc.scenario_name }}</span>
          <span class="scenario-count mono">{{ sc.runs.length }}</span>
        </div>
        <div class="run-pills">
          <button
            v-for="(run, idx) in sc.runs"
            :key="run.run_id"
            type="button"
            class="run-pill"
            :class="[
              run.status,
              {
                selected: run.run_id === selectedRunId || run.sim_id === selectedSimId,
                live: isLive(run),
              },
            ]"
            :title="pillTitle(run)"
            @click="select(run, sc)"
          >
            <span v-if="isLive(run)" class="live-dot" aria-hidden="true"></span>
            <span class="pill-idx">R{{ idx + 1 }}</span>
            <span class="pill-seed mono">{{ run.seed }}</span>
            <span class="pill-status">{{ pillStatus(run) }}</span>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  matrix: { type: Array, default: () => [] },
  progress: { type: Object, default: () => ({ done: 0, total: 0 }) },
  selectedRunId: String,
  selectedSimId: String,
})

const emit = defineEmits(['select'])

const scenarios = computed(() =>
  (props.matrix || []).map((sc) => ({
    scenario_id: sc.scenario_id,
    scenario_name: sc.scenario_name || sc.kind || '方案',
    color: sc.color || '#3498db',
    runs: sc.runs || [],
  })),
)

const totalRuns = computed(() =>
  scenarios.value.reduce((n, sc) => n + (sc.runs?.length || 0), 0),
)

const activeScenarioId = computed(() => {
  for (const sc of scenarios.value) {
    const hit = (sc.runs || []).find(
      (r) => r.run_id === props.selectedRunId || r.sim_id === props.selectedSimId,
    )
    if (hit) return sc.scenario_id
  }
  return scenarios.value[0]?.scenario_id
})

function isLive(run) {
  const s = String(run?.status || '').toLowerCase()
  return s === 'running' || s === 'starting'
}

function shortStatus(status) {
  const s = String(status || '').toLowerCase()
  if (s === 'completed' || s === 'done') return 'done'
  if (s === 'running' || s === 'starting') return 'run'
  if (s === 'failed' || s === 'error') return 'fail'
  if (s === 'ready') return 'ready'
  return s.slice(0, 5) || '—'
}

function pillStatus(run) {
  const s = String(run?.status || '').toLowerCase()
  const cur = Number(run?.current_round || 0)
  const tot = Number(run?.total_rounds || 0)
  if ((s === 'running' || s === 'starting') && tot > 0) {
    return `${cur}/${tot}`
  }
  if ((s === 'completed' || s === 'done') && tot > 0) {
    return `${tot}/${tot}`
  }
  return shortStatus(run?.status)
}

function pillTitle(run) {
  const parts = [
    '查看详情',
    run?.run_id,
    `seed ${run?.seed}`,
    run?.status,
  ]
  const cur = Number(run?.current_round || 0)
  const tot = Number(run?.total_rounds || 0)
  if (tot > 0) parts.push(`round ${cur}/${tot}`)
  if (isLive(run)) parts.push('进行中')
  if (run?.error) parts.push(String(run.error))
  return parts.filter(Boolean).join(' · ')
}

function select(run, sc) {
  emit('select', {
    scenario_id: sc.scenario_id,
    scenario_name: sc.scenario_name,
    color: sc.color,
    run_id: run.run_id,
    sim_id: run.sim_id,
    seed: run.seed,
    status: run.status,
  })
}
</script>

<style scoped>
.run-matrix-panel {
  flex: 0 0 auto;
  max-height: min(28vh, 220px);
  display: flex;
  flex-direction: column;
  border-bottom: 1px solid var(--border, #eaeaea);
  background: var(--surface, #fff);
  min-height: 0;
}

.matrix-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  padding: 8px 16px;
  background: var(--bg-muted, #fafafa);
  border-bottom: 1px solid var(--border, #eaeaea);
  flex-shrink: 0;
}

.head-left {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.title {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.progress {
  font-size: 11px;
  color: var(--ink-faint, #888);
  padding: 1px 6px;
  border: 1px solid var(--border, #eaeaea);
  background: #fff;
}

.hint {
  font-size: 11px;
  color: var(--ink-faint, #999);
  white-space: nowrap;
}

.scenario-list {
  overflow-y: auto;
  padding: 8px 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-height: 0;
}

.scenario-row {
  display: grid;
  grid-template-columns: minmax(96px, 1.1fr) minmax(0, 2fr);
  gap: 8px 12px;
  align-items: center;
  padding: 6px 8px;
  border: 1px solid transparent;
  transition: background 0.15s ease, border-color 0.15s ease;
}

.scenario-row.active {
  background: var(--bg-muted, #f7f7f7);
  border-color: var(--border, #eaeaea);
}

.scenario-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.scenario-name {
  font-size: 12px;
  font-weight: 600;
  color: var(--ink, #111);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.scenario-count {
  font-size: 10px;
  color: var(--ink-faint, #999);
  flex-shrink: 0;
}

.run-pills {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  justify-content: flex-end;
}

.run-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  border: 1px solid var(--border, #e0e0e0);
  background: #fff;
  cursor: pointer;
  font-size: 11px;
  line-height: 1;
  color: var(--ink, #222);
  transition: border-color 0.15s ease, background 0.15s ease, color 0.15s ease;
  position: relative;
}

.live-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--brand, #ff5722);
  flex-shrink: 0;
  animation: live-pulse 1.2s ease-out infinite;
}

@keyframes live-pulse {
  0% { opacity: 1; transform: scale(1); }
  70% { opacity: 0.35; transform: scale(0.85); }
  100% { opacity: 1; transform: scale(1); }
}

@media (prefers-reduced-motion: reduce) {
  .live-dot {
    animation: none;
  }
}

.run-pill.live:not(.selected) {
  border-color: color-mix(in srgb, var(--brand, #ff5722) 45%, #e0e0e0);
}

.run-pill:hover {
  border-color: #999;
}

.run-pill.selected {
  border-color: #111;
  background: #111;
  color: #fff;
}

.run-pill.selected .pill-status {
  color: rgba(255, 255, 255, 0.72);
}

.pill-idx {
  font-weight: 700;
  letter-spacing: 0.02em;
}

.pill-seed {
  opacity: 0.7;
}

.pill-status {
  font-family: var(--font-mono);
  font-size: 10px;
  text-transform: uppercase;
  color: #888;
}

.run-pill.running .pill-status,
.run-pill.starting .pill-status {
  color: var(--brand, #ff5722);
}

.run-pill.completed .pill-status,
.run-pill.done .pill-status {
  color: var(--success, #1a936f);
}

.run-pill.failed .pill-status,
.run-pill.error .pill-status {
  color: var(--danger, #c0392b);
}

.run-pill.selected.running .pill-status,
.run-pill.selected.starting .pill-status,
.run-pill.selected.completed .pill-status,
.run-pill.selected.done .pill-status,
.run-pill.selected.failed .pill-status,
.run-pill.selected.error .pill-status {
  color: rgba(255, 255, 255, 0.8);
}

.mono {
  font-family: var(--font-mono);
}

@media (max-width: 720px) {
  .scenario-row {
    grid-template-columns: 1fr;
  }

  .run-pills {
    justify-content: flex-start;
  }

  .hint {
    display: none;
  }
}
</style>

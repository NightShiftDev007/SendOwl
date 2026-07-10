<template>
  <div v-if="matrix.length > 1 || totalRuns > 1" class="run-matrix-panel">
    <div class="matrix-head">
      <span class="mono">Scenario × Run</span>
      <span class="hint">点击 Run 切换下方时间线 · {{ progress.done }}/{{ progress.total }}</span>
    </div>
    <table>
      <thead>
        <tr>
          <th>方案</th>
          <th>Run</th>
          <th>Seed</th>
          <th>状态</th>
          <th>sim</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="row in flatRows"
          :key="row.run_id"
          :class="{ active: row.run_id === selectedRunId || row.sim_id === selectedSimId }"
          @click="select(row)"
        >
          <td>
            <span class="dot" :style="{ background: row.color }"></span>
            {{ row.scenario_name }}
          </td>
          <td class="mono">{{ shortId(row.run_id) }}</td>
          <td class="mono">{{ row.seed }}</td>
          <td>
            <span class="status" :class="row.status">{{ row.status }}</span>
          </td>
          <td class="mono faint">{{ shortId(row.sim_id) }}</td>
        </tr>
      </tbody>
    </table>
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

const flatRows = computed(() => {
  const rows = []
  for (const sc of props.matrix || []) {
    for (const r of sc.runs || []) {
      rows.push({
        scenario_id: sc.scenario_id,
        scenario_name: sc.scenario_name || sc.kind,
        color: sc.color || '#3498db',
        run_id: r.run_id,
        sim_id: r.sim_id,
        seed: r.seed,
        status: r.status,
      })
    }
  }
  return rows
})

const totalRuns = computed(() => flatRows.value.length)

function shortId(id) {
  if (!id) return '—'
  return String(id).slice(0, 12)
}

function select(row) {
  emit('select', row)
}
</script>

<style scoped>
.run-matrix-panel {
  border: 1px solid var(--border);
  background: var(--surface);
  margin: 0 0 12px;
}
.matrix-head {
  display: flex;
  justify-content: space-between;
  padding: 8px 12px;
  background: var(--bg-muted);
  border-bottom: 1px solid var(--border);
  font-size: 12px;
  font-weight: 700;
}
.hint {
  color: var(--ink-faint);
  font-weight: 400;
}
table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
th,
td {
  padding: 8px 10px;
  border-bottom: 1px solid var(--border);
  text-align: left;
}
tr {
  cursor: pointer;
}
tr:hover,
tr.active {
  background: var(--bg-muted);
}
.dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-right: 6px;
}
.mono {
  font-family: var(--font-mono);
}
.faint {
  color: var(--ink-faint);
}
.status {
  font-family: var(--font-mono);
  font-size: 11px;
}
.status.completed,
.status.done {
  color: var(--success);
}
.status.running {
  color: var(--brand);
}
.status.failed,
.status.error {
  color: var(--danger);
}
</style>

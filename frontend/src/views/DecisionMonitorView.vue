<template>
  <main class="page">
    <h1>运行监控</h1>
    <p class="sub">决策 {{ id }} · 状态 {{ status?.status || '…' }}</p>

    <div class="row" style="margin-bottom:16px">
      <button class="btn" @click="refresh">刷新</button>
      <RouterLink class="btn primary" :to="`/decision/${id}/compare`">查看对比</RouterLink>
    </div>

    <div class="card">
      <h2>Scenario × Run 矩阵</h2>
      <table>
        <thead>
          <tr>
            <th>方案</th>
            <th>Run</th>
            <th>Seed</th>
            <th>状态</th>
            <th>耗时</th>
            <th>错误</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="row.run_id">
            <td>{{ row.scenario_name }}</td>
            <td class="muted">{{ row.run_id }}</td>
            <td>{{ row.seed }}</td>
            <td><span class="badge" :class="statusClass(row.status)">{{ row.status }}</span></td>
            <td>{{ row.elapsed || '-' }}</td>
            <td class="muted">{{ row.error || '' }}</td>
          </tr>
        </tbody>
      </table>
      <p v-if="!rows.length" class="muted">暂无运行记录，可能仍在准备共享世界…</p>
    </div>
  </main>
</template>

<script setup>
import { computed, onMounted, onBeforeUnmount, ref } from 'vue'
import { decisionStatus, getDecision } from '../api/client'

const props = defineProps({ id: String })
const status = ref(null)
const decision = ref(null)
let timer = null

const rows = computed(() => {
  const matrix = status.value?.matrix || status.value?.runs || status.value?.scenarios || []
  if (Array.isArray(matrix) && matrix.length && matrix[0].run_id) return matrix
  // nested scenarios[].runs[]
  const out = []
  for (const s of (status.value?.scenarios || decision.value?.scenarios || [])) {
    for (const r of (s.runs || [])) {
      out.push({
        scenario_name: s.name || s.kind,
        run_id: r.id || r.run_id,
        seed: r.seed,
        status: r.status,
        elapsed: r.elapsed_sec || r.elapsed,
        error: r.error,
      })
    }
  }
  return out
})

function statusClass(s) {
  if (s === 'completed' || s === 'ready') return 'ok'
  if (s === 'failed' || s === 'error') return 'err'
  if (s === 'running' || s === 'starting') return 'warn'
  return ''
}

async function refresh() {
  try {
    const st = await decisionStatus(props.id)
    status.value = st.data || st
  } catch (_) {}
  try {
    const d = await getDecision(props.id)
    decision.value = d.data || d
  } catch (_) {}
}

onMounted(async () => {
  await refresh()
  timer = setInterval(refresh, 4000)
})
onBeforeUnmount(() => clearInterval(timer))
</script>

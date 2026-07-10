<template>
  <main class="page">
    <h1>方案对比</h1>
    <p class="sub">{{ compare?.title || id }} · {{ compare?.note || '多方案量化对比' }}</p>

    <div class="row" style="margin-bottom:16px">
      <button class="btn" :disabled="loading" @click="load">{{ loading ? '加载中…' : '刷新对比' }}</button>
      <RouterLink class="btn" :to="`/decision/${id}/monitor`">返回监控</RouterLink>
    </div>

    <p v-if="error" class="error">{{ error }}</p>

    <div class="grid grid-3" v-if="scenarios.length">
      <div class="card" v-for="s in scenarios" :key="s.scenario_id || s.name">
        <div class="row" style="margin-bottom:8px">
          <span class="dot" :style="{ background: s.color || '#3b82f6' }"></span>
          <strong>{{ s.scenario_name || s.name }}</strong>
        </div>
        <div class="kpi">
          <div><div class="muted">互动(均值)</div><div class="val">{{ fmt(s.summary?.total_actions ?? s.actions_mean) }}</div></div>
          <div><div class="muted">反对占比</div><div class="val">{{ pct(s.summary?.stance_share?.opposing ?? s.oppose_mean) }}</div></div>
          <div><div class="muted">采样数</div><div class="val">{{ s.sample_count || s.n || 1 }}</div></div>
        </div>
        <p class="muted" v-if="s.narrative">{{ s.narrative }}</p>
      </div>
    </div>

    <div class="grid grid-2" style="margin-top:16px" v-if="scenarios.length">
      <div class="card">
        <h2>传播规模对比</h2>
        <div ref="barEl" class="chart"></div>
      </div>
      <div class="card">
        <h2>观点结构</h2>
        <div ref="stanceEl" class="chart"></div>
      </div>
    </div>

    <div class="card" style="margin-top:16px" v-if="report">
      <h2>叙事报告</h2>
      <pre class="report">{{ report }}</pre>
    </div>

    <p v-if="!scenarios.length && !loading" class="muted">暂无对比数据。请确认决策已跑完，或先跑离线 smoke。</p>
  </main>
</template>

<script setup>
import { nextTick, onMounted, ref } from 'vue'
import * as echarts from 'echarts'
import { decisionCompare } from '../api/client'

const props = defineProps({ id: String })
const compare = ref(null)
const scenarios = ref([])
const report = ref('')
const loading = ref(false)
const error = ref('')
const barEl = ref(null)
const stanceEl = ref(null)

function num(v) {
  if (v == null) return null
  if (typeof v === 'object' && 'mean' in v) return Number(v.mean)
  return Number(v)
}
function fmt(v) {
  const n = num(v)
  if (n == null || Number.isNaN(n)) return '-'
  return n.toFixed(1)
}
function pct(v) {
  const n = num(v)
  if (n == null || Number.isNaN(n)) return '-'
  return `${(n * 100).toFixed(0)}%`
}

function renderCharts() {
  if (!scenarios.value.length) return
  if (barEl.value) {
    const chart = echarts.init(barEl.value)
    chart.setOption({
      backgroundColor: 'transparent',
      tooltip: {},
      xAxis: {
        type: 'category',
        data: scenarios.value.map((s) => s.scenario_name || s.name),
        axisLabel: { color: '#8b9bb4' },
      },
      yAxis: { type: 'value', axisLabel: { color: '#8b9bb4' }, splitLine: { lineStyle: { color: '#243044' } } },
      series: [{
        type: 'bar',
        data: scenarios.value.map((s) => num(s.summary?.total_actions ?? s.actions_mean) || 0),
        itemStyle: { color: (p) => scenarios.value[p.dataIndex]?.color || '#3b82f6' },
      }],
    })
  }
  if (stanceEl.value) {
    const chart = echarts.init(stanceEl.value)
    chart.setOption({
      backgroundColor: 'transparent',
      tooltip: { trigger: 'axis' },
      legend: { textStyle: { color: '#8b9bb4' } },
      xAxis: {
        type: 'category',
        data: scenarios.value.map((s) => s.scenario_name || s.name),
        axisLabel: { color: '#8b9bb4' },
      },
      yAxis: { type: 'value', max: 1, axisLabel: { color: '#8b9bb4', formatter: (v) => `${v * 100}%` }, splitLine: { lineStyle: { color: '#243044' } } },
      series: [
        { name: '赞成', type: 'bar', stack: 's', itemStyle: { color: '#22c55e' }, data: scenarios.value.map((s) => num(s.summary?.stance_share?.supportive) || 0) },
        { name: '中立', type: 'bar', stack: 's', itemStyle: { color: '#64748b' }, data: scenarios.value.map((s) => num(s.summary?.stance_share?.neutral) || 0) },
        { name: '反对', type: 'bar', stack: 's', itemStyle: { color: '#ef4444' }, data: scenarios.value.map((s) => num(s.summary?.stance_share?.opposing) || 0) },
      ],
    })
  }
}

async function load() {
  loading.value = true; error.value = ''
  try {
    const res = await decisionCompare(props.id, { report: true })
    const data = res.data || res
    compare.value = data
    scenarios.value = data.scenarios || data.items || []
    const rpt = data.report
    report.value = typeof rpt === 'string'
      ? rpt
      : (rpt?.markdown || data.narrative || scenarios.value.map((s) => s.narrative).filter(Boolean).join('\n\n'))
    await nextTick()
    renderCharts()
  } catch (e) {
    error.value = e.response?.data?.error || e.message
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; }
.kpi { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-bottom: 8px; }
.kpi .val { font-size: 20px; font-weight: 700; margin-top: 4px; }
.report {
  white-space: pre-wrap; color: #cbd5e1; font-size: 13px; line-height: 1.6;
  background: #121a26; padding: 12px; border-radius: 10px; overflow: auto;
}
</style>

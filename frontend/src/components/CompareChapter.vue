<template>
  <div v-if="compare" class="compare-chapter">
    <div class="chapter-head">
      <span class="mono">方案对比</span>
      <span class="hint">多方案指标汇总</span>
    </div>

    <div class="kpi-row" v-if="kpis.length">
      <div v-for="k in kpis" :key="k.label" class="kpi">
        <div class="kpi-label">{{ k.label }}</div>
        <div class="kpi-value mono">{{ k.value }}</div>
      </div>
    </div>

    <div ref="chartEl" class="chart" v-show="hasChart"></div>

    <div class="md" v-if="markdown" v-html="renderedMd"></div>
    <p v-else class="muted">暂无对比报告正文</p>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import * as echarts from 'echarts'

const props = defineProps({
  compare: { type: Object, default: null },
})

const chartEl = ref(null)
let chart = null

const markdown = computed(
  () =>
    props.compare?.report?.markdown ||
    props.compare?.narrative ||
    props.compare?.markdown ||
    '',
)

const renderedMd = computed(() => {
  // 轻量：保留换行
  const text = markdown.value || ''
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/\n/g, '<br/>')
})

const scenarios = computed(() => props.compare?.scenarios || props.compare?.items || [])

const kpis = computed(() => {
  const list = scenarios.value
  if (!list.length) return []
  const totalActs = list.reduce(
    (s, x) => s + (x.summary?.total_actions || x.metrics?.total_actions || 0),
    0,
  )
  return [
    { label: '方案数', value: list.length },
    { label: '总动作', value: totalActs },
  ]
})

const hasChart = computed(() => scenarios.value.length > 0)

function renderChart() {
  if (!chartEl.value || !hasChart.value) return
  if (!chart) chart = echarts.init(chartEl.value)
  const names = scenarios.value.map((s) => s.name || s.scenario_name || s.scenario_id)
  const acts = scenarios.value.map(
    (s) => s.summary?.total_actions || s.metrics?.total_actions || 0,
  )
  chart.setOption({
    tooltip: {},
    grid: { left: 40, right: 16, top: 24, bottom: 32 },
    xAxis: { type: 'category', data: names },
    yAxis: { type: 'value', name: 'actions' },
    series: [{ type: 'bar', data: acts, itemStyle: { color: '#3498db' } }],
  })
}

watch(
  () => props.compare,
  () => {
    setTimeout(renderChart, 50)
  },
  { deep: true },
)

onMounted(() => {
  setTimeout(renderChart, 50)
  window.addEventListener('resize', resize)
})

function resize() {
  chart?.resize()
}

onUnmounted(() => {
  window.removeEventListener('resize', resize)
  chart?.dispose()
  chart = null
})
</script>

<style scoped>
.compare-chapter {
  border: 1px solid var(--border);
  background: var(--surface);
  margin: 12px 0 20px;
  padding-bottom: 12px;
}
.chapter-head {
  display: flex;
  justify-content: space-between;
  padding: 10px 14px;
  border-bottom: 1px solid var(--border);
  background: var(--bg-muted);
  font-size: 12px;
  font-weight: 700;
}
.hint {
  color: var(--ink-faint);
  font-weight: 400;
}
.kpi-row {
  display: flex;
  gap: 12px;
  padding: 12px 14px;
}
.kpi {
  border: 1px solid var(--border);
  padding: 10px 14px;
  min-width: 100px;
  background: var(--bg);
}
.kpi-label {
  font-size: 11px;
  color: var(--ink-muted);
}
.kpi-value {
  font-size: 18px;
  font-weight: 700;
  margin-top: 4px;
}
.chart {
  height: 220px;
  margin: 0 14px 12px;
}
.md {
  padding: 0 14px 8px;
  font-size: 13px;
  line-height: 1.6;
  color: var(--ink);
}
.muted {
  padding: 0 14px;
  color: var(--ink-muted);
  font-size: 13px;
}
.mono {
  font-family: var(--font-mono);
}
</style>

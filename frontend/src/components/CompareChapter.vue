<template>
  <div v-if="compare" class="compare-chapter">
    <div class="chapter-head">
      <span class="mono">方案对比</span>
      <span class="hint">多方案指标汇总 · mean±std</span>
    </div>

    <div v-if="verdict" class="verdict-bar">
      <div class="verdict-label mono">结论</div>
      <div class="verdict-body">
        <strong :style="{ color: verdict.color }">{{ verdict.name }}</strong>
        <span class="verdict-meta">反对率最低 · {{ verdict.opposing }} · 互动 {{ verdict.actions }}</span>
      </div>
      <div v-if="verdict.delta" class="verdict-delta mono">{{ verdict.delta }}</div>
    </div>

    <div class="kpi-row" v-if="scenarios.length">
      <div class="kpi-card" v-for="(s, idx) in scenarios" :key="s.scenario_id || s.name || idx">
        <div class="kpi-head">
          <span class="dot" :style="{ background: s.color || 'var(--brand)' }"></span>
          <strong :title="s.scenario_name || s.name">{{ shortScenarioTitle(s, idx) }}</strong>
        </div>
        <div class="kpi-grid">
          <div>
            <div class="muted">互动</div>
            <div class="val">{{ fmtWithStd(s.summary?.total_actions) }}</div>
          </div>
          <div>
            <div class="muted">反对</div>
            <div class="val">{{ pctWithStd(s.summary?.stance_share?.opposing) }}</div>
          </div>
          <div>
            <div class="muted">级联</div>
            <div class="val">{{ fmtWithStd(s.summary?.max_cascade_depth) }}</div>
          </div>
          <div>
            <div class="muted">采样</div>
            <div class="val">{{ s.sample_count || 1 }}</div>
          </div>
        </div>
        <p class="narrative" v-if="s.narrative">{{ s.narrative }}</p>
      </div>
    </div>

    <div class="charts" v-if="scenarios.length">
      <div class="chart-card">
        <h3 class="mono">传播规模</h3>
        <div ref="barEl" class="chart"></div>
      </div>
      <div class="chart-card">
        <h3 class="mono">观点结构</h3>
        <div ref="stanceEl" class="chart"></div>
      </div>
    </div>

    <div class="chart-card full" v-if="hasCurves">
      <h3 class="mono">传播曲线叠加</h3>
      <div ref="curveEl" class="chart tall"></div>
    </div>

    <GeoPropagationMap ref="geoMapRef" v-if="scenarios.length" :scenarios="scenarios" />

    <div class="md markdown-body" v-if="markdown" v-html="renderedMd"></div>
    <p v-else class="muted pad">暂无对比报告正文</p>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import { renderMarkdown } from '../utils/markdown'
import GeoPropagationMap from './GeoPropagationMap.vue'

const props = defineProps({
  compare: { type: Object, default: null },
})

const barEl = ref(null)
const stanceEl = ref(null)
const curveEl = ref(null)
const geoMapRef = ref(null)
let charts = []
let barChart = null
let stanceChart = null
let curveChart = null

const markdown = computed(
  () =>
    props.compare?.report?.markdown ||
    props.compare?.narrative ||
    props.compare?.markdown ||
    '',
)

const renderedMd = computed(() => renderMarkdown(markdown.value))

const scenarios = computed(() => props.compare?.scenarios || props.compare?.items || [])

function shortScenarioTitle(s, idx = 0) {
  return scenarioLabel(s, idx)
}

const hasCurves = computed(() =>
  scenarios.value.some((s) => (s.activity_curve || []).length > 1),
)

function num(v) {
  if (v == null) return null
  if (typeof v === 'object' && 'mean' in v) return Number(v.mean)
  return Number(v)
}

function stdOf(v) {
  if (v == null || typeof v !== 'object' || !('std' in v)) return null
  return Number(v.std)
}

function fmt(v) {
  const n = num(v)
  return n == null || Number.isNaN(n) ? '-' : n.toFixed(1)
}

function pct(v) {
  const n = num(v)
  return n == null || Number.isNaN(n) ? '-' : `${(n * 100).toFixed(0)}%`
}

function fmtWithStd(v) {
  const base = fmt(v)
  const s = stdOf(v)
  if (base === '-' || s == null || Number.isNaN(s) || s === 0) return base
  return `${base}±${s.toFixed(1)}`
}

function pctWithStd(v) {
  const base = pct(v)
  const s = stdOf(v)
  if (base === '-' || s == null || Number.isNaN(s) || s === 0) return base
  return `${base}±${(s * 100).toFixed(0)}pt`
}

const verdict = computed(() => {
  if (!scenarios.value.length) return null
  const ranked = [...scenarios.value]
    .map((s, i) => ({
      name: scenarioLabel(s, i),
      fullName: s.scenario_name || s.name,
      color: s.color || '#FF4500',
      opposing: num(s.summary?.stance_share?.opposing),
      actions: num(s.summary?.total_actions),
    }))
    .filter((s) => s.opposing != null && !Number.isNaN(s.opposing))
    .sort((a, b) => a.opposing - b.opposing)
  if (!ranked.length) return null
  const best = ranked[0]
  const baseline =
    ranked.find((s) => /baseline/i.test(s.name || '')) || ranked[ranked.length - 1]
  let delta = ''
  if (baseline && baseline !== best && baseline.opposing != null) {
    const d = (baseline.opposing - best.opposing) * 100
    delta = `较 ${baseline.name} 反对率 ${d >= 0 ? '↓' : '↑'}${Math.abs(d).toFixed(0)}pt`
  }
  return {
    name: best.name,
    color: best.color,
    opposing: pct(best.opposing),
    actions: fmt(best.actions),
    delta,
  }
})

function disposeCharts() {
  for (const c of charts) c.dispose()
  charts = []
  barChart = null
  stanceChart = null
  curveChart = null
}

function chartToPng(chart, pixelRatio = 2) {
  if (!chart) return null
  try {
    return chart.getDataURL({
      type: 'png',
      pixelRatio,
      backgroundColor: '#ffffff',
    })
  } catch {
    return null
  }
}

/** 导出用：ECharts + 地图截图 */
async function getExportImages(pixelRatio = 1.5) {
  for (const c of charts) c.resize()
  await new Promise((r) => setTimeout(r, 120))
  const images = []
  const bar = chartToPng(barChart, pixelRatio)
  if (bar) images.push({ key: 'chart-spread', title: '传播规模', kind: 'chart', dataUrl: bar })
  const stance = chartToPng(stanceChart, pixelRatio)
  if (stance) images.push({ key: 'chart-stance', title: '观点结构', kind: 'chart', dataUrl: stance })
  const curve = chartToPng(curveChart, pixelRatio)
  if (curve) images.push({ key: 'chart-curve', title: '传播曲线叠加', kind: 'chart', dataUrl: curve })
  if (geoMapRef.value?.captureAllMaps) {
    const maps = await geoMapRef.value.captureAllMaps(pixelRatio)
    for (const m of maps) {
      const name = String(m.name || `方案${m.index + 1}`).slice(0, 24)
      images.push({
        key: `map-${m.index + 1}`,
        title: `地域传播飞线 · ${name}`,
        kind: 'map',
        dataUrl: m.dataUrl,
      })
    }
  }
  return images
}

defineExpose({ getExportImages })

function truncateLabel(text, maxLen = 12) {
  const s = String(text || '').trim()
  if (!s) return '方案'
  if (s.length <= maxLen) return s
  return `${s.slice(0, maxLen - 1)}…`
}

function scenarioLabel(s, index = 0) {
  const kind = String(s.scenario_id || s.kind || '').trim()
  // 模板 kind（A_hard / B_soft / Baseline）优先
  if (kind && !/^(default|custom|scn_)/i.test(kind) && kind.length <= 16) {
    return kind
  }
  const name = String(s.scenario_name || s.name || '').trim()
  const head = name.split(/[·•|/｜]/)[0].trim()
  // 名称过长（常为模拟需求整段）→ 用「方案N」
  if (!head || head.length > 18) {
    return `方案${index + 1}`
  }
  return truncateLabel(head, 12)
}

function categoryAxis(names) {
  return {
    type: 'category',
    data: names,
    axisLabel: {
      color: '#666',
      interval: 0,
      hideOverlap: true,
      rotate: names.length > 3 ? 20 : 0,
      fontSize: 11,
      margin: 6,
    },
    axisTick: { alignWithLabel: true },
  }
}

/** containLabel 时 left/bottom 只留缝，别再叠 48px，否则绘图区被挤小 */
function tightGrid({ top = 28, legend = false } = {}) {
  return {
    left: 8,
    right: 10,
    top: legend ? 40 : top,
    bottom: 8,
    containLabel: true,
  }
}

function renderCharts() {
  disposeCharts()
  if (!scenarios.value.length) return

  const fullNames = scenarios.value.map((s) => s.scenario_name || s.name || '')
  const shortNames = scenarios.value.map((s, i) => scenarioLabel(s, i))
  const n = scenarios.value.length
  // 单方案时加宽柱，避免中间一根细条两侧大片空白
  const barWidth = n <= 1 ? '36%' : n <= 3 ? '42%' : undefined

  if (barEl.value) {
    const chart = echarts.init(barEl.value)
    barChart = chart
    charts.push(chart)
    chart.setOption({
      tooltip: {
        trigger: 'axis',
        formatter: (params) => {
          const p = Array.isArray(params) ? params[0] : params
          const i = p?.dataIndex ?? 0
          return `${fullNames[i] || p?.name}<br/>${p?.marker || ''}${p?.value ?? '-'}`
        },
      },
      grid: tightGrid({ top: 20 }),
      xAxis: categoryAxis(shortNames),
      yAxis: { type: 'value', splitLine: { lineStyle: { color: '#eee' } } },
      series: [
        {
          type: 'bar',
          barWidth,
          barMaxWidth: n <= 1 ? 96 : 48,
          data: scenarios.value.map((s) => ({
            value: num(s.summary?.total_actions) || 0,
            itemStyle: { color: s.color || '#FF4500' },
          })),
        },
      ],
    })
  }

  if (stanceEl.value) {
    const chart = echarts.init(stanceEl.value)
    stanceChart = chart
    charts.push(chart)
    chart.setOption({
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        formatter: (params) => {
          const list = Array.isArray(params) ? params : [params]
          const i = list[0]?.dataIndex ?? 0
          const lines = list.map((p) => `${p.marker}${p.seriesName} ${(Number(p.value) * 100).toFixed(0)}%`)
          return `${fullNames[i] || list[0]?.name}<br/>${lines.join('<br/>')}`
        },
      },
      legend: {
        top: 0,
        left: 'center',
        itemWidth: 10,
        itemHeight: 10,
        itemGap: 14,
        textStyle: { color: '#666', fontSize: 11 },
      },
      grid: tightGrid({ legend: true }),
      xAxis: categoryAxis(shortNames),
      yAxis: {
        type: 'value',
        max: 1,
        axisLabel: { formatter: (v) => `${v * 100}%` },
        splitLine: { lineStyle: { color: '#eee' } },
      },
      series: [
        {
          name: '赞成',
          type: 'bar',
          stack: 's',
          barWidth,
          barMaxWidth: n <= 1 ? 96 : 48,
          itemStyle: { color: '#059669' },
          data: scenarios.value.map((s) => num(s.summary?.stance_share?.supportive) || 0),
        },
        {
          name: '中立',
          type: 'bar',
          stack: 's',
          itemStyle: { color: '#9ca3af' },
          data: scenarios.value.map((s) => num(s.summary?.stance_share?.neutral) || 0),
        },
        {
          name: '反对',
          type: 'bar',
          stack: 's',
          itemStyle: { color: '#dc2626' },
          data: scenarios.value.map((s) => num(s.summary?.stance_share?.opposing) || 0),
        },
      ],
    })
  }

  if (curveEl.value && hasCurves.value) {
    const chart = echarts.init(curveEl.value)
    curveChart = chart
    charts.push(chart)
    const series = scenarios.value.map((s, i) => {
      const curve = s.activity_curve || []
      return {
        name: scenarioLabel(s, i),
        type: 'line',
        smooth: true,
        showSymbol: false,
        lineStyle: { width: 2.5, color: s.color || '#FF4500' },
        itemStyle: { color: s.color || '#FF4500' },
        data: curve.map((p) => (typeof p === 'number' ? p : p.actions ?? p.value ?? 0)),
      }
    })
    const maxLen = Math.max(...series.map((s) => s.data.length), 1)
    chart.setOption({
      tooltip: {
        trigger: 'axis',
        formatter: (params) => {
          const list = Array.isArray(params) ? params : [params]
          const head = list[0]?.axisValueLabel || list[0]?.name || ''
          const lines = list.map((p, i) => {
            const full = fullNames[i] || p.seriesName
            return `${p.marker}${full} ${p.value ?? '-'}`
          })
          return `${head}<br/>${lines.join('<br/>')}`
        },
      },
      legend: {
        top: 0,
        left: 'center',
        type: 'scroll',
        width: '90%',
        itemWidth: 10,
        itemHeight: 10,
        itemGap: 12,
        formatter: (name) => truncateLabel(name, 14),
        textStyle: { color: '#666', fontSize: 11 },
        tooltip: { show: true },
      },
      grid: tightGrid({ legend: true }),
      xAxis: {
        type: 'category',
        data: Array.from({ length: maxLen }, (_, i) => `R${i}`),
        axisLabel: { color: '#666', fontSize: 11, margin: 6 },
        boundaryGap: false,
      },
      yAxis: {
        type: 'value',
        splitLine: { lineStyle: { color: '#eee' } },
        axisLabel: { margin: 4 },
      },
      series,
    })
  }

  // 布局稳定后再 resize，避免首绘把柱子挤到角落
  requestAnimationFrame(() => {
    for (const c of charts) c.resize()
  })
}

function resize() {
  for (const c of charts) c.resize()
}

watch(
  () => props.compare,
  () => {
    setTimeout(renderCharts, 50)
  },
  { deep: true },
)

onMounted(() => {
  setTimeout(renderCharts, 50)
  window.addEventListener('resize', resize)
})

onUnmounted(() => {
  window.removeEventListener('resize', resize)
  disposeCharts()
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
.verdict-bar {
  display: flex;
  align-items: center;
  gap: 14px;
  margin: 12px 14px;
  padding: 12px 14px;
  border: 1px solid var(--border);
  background: var(--bg);
}
.verdict-label {
  font-size: 11px;
  color: var(--ink-faint);
  letter-spacing: 0.06em;
}
.verdict-body {
  flex: 1;
  display: flex;
  flex-wrap: wrap;
  gap: 8px 14px;
  align-items: baseline;
}
.verdict-body strong {
  font-size: 16px;
}
.verdict-meta {
  font-size: 12px;
  color: var(--ink-muted);
}
.verdict-delta {
  font-size: 12px;
  color: var(--success, #1a936f);
}
.kpi-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 10px;
  padding: 0 14px 12px;
}
.kpi-card {
  border: 1px solid var(--border);
  padding: 10px 12px;
  background: var(--bg);
}
.kpi-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  font-size: 13px;
  min-width: 0;
}
.kpi-head strong {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
}
.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}
.kpi-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}
.muted {
  font-size: 11px;
  color: var(--ink-muted);
}
.val {
  font-family: var(--font-mono);
  font-size: 15px;
  font-weight: 700;
  margin-top: 2px;
}
.narrative {
  margin: 8px 0 0;
  font-size: 12px;
  color: var(--ink-muted);
  line-height: 1.4;
}
.charts {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  padding: 0 14px 12px;
}
.chart-card {
  border: 1px solid var(--border);
  padding: 10px 12px 4px;
  background: var(--bg);
}
.chart-card.full {
  margin: 0 14px 12px;
}
.chart-card h3 {
  margin: 0 0 4px;
  font-size: 11px;
  letter-spacing: 0.04em;
}
.chart {
  height: 250px;
}
.chart.tall {
  height: 280px;
}
.md {
  padding: 4px 14px 16px;
  font-size: 13px;
  line-height: 1.7;
  color: var(--ink);
}
.md :deep(.md-h2) {
  margin: 1.2em 0 0.5em;
  font-size: 18px;
  font-weight: 700;
  border-bottom: 1px solid var(--border);
  padding-bottom: 6px;
}
.md :deep(.md-h3) {
  margin: 1em 0 0.4em;
  font-size: 15px;
  font-weight: 700;
}
.md :deep(.md-h4),
.md :deep(.md-h5) {
  margin: 0.85em 0 0.35em;
  font-size: 13px;
  font-weight: 700;
}
.md :deep(.md-p) {
  margin: 0.55em 0;
}
.md :deep(.md-ul),
.md :deep(.md-ol) {
  margin: 0.5em 0 0.5em 1.2em;
  padding: 0;
}
.md :deep(.md-li),
.md :deep(.md-oli) {
  margin: 0.25em 0;
}
.md :deep(strong) {
  font-weight: 700;
}
.md :deep(.md-quote) {
  margin: 0.6em 0;
  padding: 8px 12px;
  border-left: 3px solid var(--brand, #ff4500);
  background: var(--bg-muted, #f7f7f7);
  color: var(--ink-muted);
}
.md :deep(.md-hr) {
  border: none;
  border-top: 1px solid var(--border);
  margin: 1em 0;
}
.md :deep(.md-table-wrap) {
  overflow-x: auto;
  margin: 0.75em 0 1em;
  border: 1px solid var(--border);
}
.md :deep(.md-table) {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
.md :deep(.md-table th),
.md :deep(.md-table td) {
  border: 1px solid var(--border);
  padding: 8px 10px;
  text-align: left;
  vertical-align: top;
}
.md :deep(.md-table th) {
  background: var(--bg-muted, #f5f5f5);
  font-weight: 700;
  white-space: nowrap;
}
.md :deep(.md-table tbody tr:nth-child(even)) {
  background: color-mix(in srgb, var(--bg-muted, #f7f7f7) 55%, transparent);
}
.md :deep(.inline-code) {
  font-family: var(--font-mono);
  font-size: 0.92em;
  padding: 1px 4px;
  background: var(--bg-muted, #f3f3f3);
}
.md :deep(.code-block) {
  overflow-x: auto;
  padding: 10px 12px;
  background: var(--bg-muted, #f3f3f3);
  font-size: 12px;
}
.pad {
  padding: 0 14px;
}
.mono {
  font-family: var(--font-mono);
}
@media (max-width: 900px) {
  .charts {
    grid-template-columns: 1fr;
  }
}
</style>

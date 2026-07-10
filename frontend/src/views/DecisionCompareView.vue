<template>
  <div class="compare-page">
    <AppHeader>
      <template #center>
        <span class="mono">方案对比 · {{ compare?.title || id }}</span>
      </template>
      <template #right>
        <button class="btn" :disabled="loading" @click="load">{{ loading ? '加载中…' : '刷新' }}</button>
        <RouterLink class="btn" :to="{ name: 'DecisionMonitor', params: { id } }">返回监控</RouterLink>
      </template>
    </AppHeader>

    <main class="split">
      <section class="left">
        <p v-if="error" class="error">{{ error }}</p>

        <div v-if="verdict" class="verdict-bar">
          <div class="verdict-label mono">结论</div>
          <div class="verdict-body">
            <strong :style="{ color: verdict.color }">{{ verdict.name }}</strong>
            <span class="verdict-meta">反对率最低 · {{ verdict.opposing }} · 互动 {{ verdict.actions }}</span>
          </div>
          <div v-if="verdict.delta" class="verdict-delta mono">{{ verdict.delta }}</div>
        </div>

        <div class="kpi-row" v-if="scenarios.length">
          <div class="kpi-card" v-for="s in scenarios" :key="s.scenario_id">
            <div class="kpi-head">
              <span class="dot" :style="{ background: s.color || 'var(--brand)' }"></span>
              <strong>{{ s.scenario_name }}</strong>
            </div>
            <div class="kpi-grid">
              <div>
                <div class="muted">互动</div>
                <div class="val">{{ fmt(s.summary?.total_actions) }}</div>
              </div>
              <div>
                <div class="muted">反对</div>
                <div class="val">{{ pct(s.summary?.stance_share?.opposing) }}</div>
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
            <h2 class="mono">传播规模</h2>
            <div ref="barEl" class="chart"></div>
          </div>
          <div class="chart-card">
            <h2 class="mono">观点结构</h2>
            <div ref="stanceEl" class="chart"></div>
          </div>
        </div>

        <div class="chart-card" v-if="hasCurves" style="margin-top:12px">
          <h2 class="mono">传播曲线叠加</h2>
          <div ref="curveEl" class="chart tall"></div>
        </div>

        <article class="report-style" v-if="report">
          <span class="report-tag">COMPARE REPORT</span>
          <h1>{{ compare?.title || '决策对比报告' }}</h1>
          <pre class="report-body">{{ report }}</pre>
        </article>
      </section>

      <aside class="right">
        <div class="action-bar">
          <span class="mono">Agent 采访</span>
          <div class="tabs">
            <button class="tab" :class="{ active: tab === 'chat' }" @click="tab = 'chat'">Interview</button>
          </div>
        </div>
        <div class="chat-container">
          <div class="profile-card">
            <label class="muted">Run ID</label>
            <select v-model="runId">
              <option disabled value="">选择 Run</option>
              <option v-for="r in runOptions" :key="r.id" :value="r.id">
                {{ r.label }}
              </option>
            </select>
            <label class="muted" style="margin-top:8px;display:block">Agent ID</label>
            <input v-model.number="agentId" type="number" min="0" />
          </div>
          <div class="chat-messages" ref="chatEl">
            <div
              v-for="(m, i) in messages"
              :key="i"
              class="bubble"
              :class="m.role"
            >
              {{ m.content }}
            </div>
            <p v-if="!messages.length" class="muted center">向模拟世界中的 Agent 提问</p>
          </div>
          <div class="chat-input-area">
            <textarea v-model="prompt" rows="2" placeholder="你怎么看当前政策？" @keydown.enter.exact.prevent="send" />
            <button class="cta" :disabled="sending || !runId" @click="send">
              {{ sending ? '…' : '发送' }}
            </button>
          </div>
        </div>
      </aside>
    </main>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, ref } from 'vue'
import * as echarts from 'echarts'
import AppHeader from '../components/AppHeader.vue'
import { getDecision, getDecisionCompare, interviewRun } from '../api/decision'

const props = defineProps({ id: String })
const compare = ref(null)
const scenarios = ref([])
const report = ref('')
const loading = ref(false)
const error = ref('')
const barEl = ref(null)
const stanceEl = ref(null)
const curveEl = ref(null)
const chatEl = ref(null)
const tab = ref('chat')
const runId = ref('')
const agentId = ref(0)
const prompt = ref('')
const sending = ref(false)
const messages = ref([])
const decision = ref(null)
let charts = []

const hasCurves = computed(() =>
  scenarios.value.some((s) => (s.activity_curve || []).length > 1),
)

const verdict = computed(() => {
  if (!scenarios.value.length) return null
  const ranked = [...scenarios.value]
    .map((s) => ({
      name: s.scenario_name,
      color: s.color || '#FF4500',
      opposing: num(s.summary?.stance_share?.opposing),
      actions: num(s.summary?.total_actions),
    }))
    .filter((s) => s.opposing != null && !Number.isNaN(s.opposing))
    .sort((a, b) => a.opposing - b.opposing)
  if (!ranked.length) return null
  const best = ranked[0]
  const baseline = ranked.find((s) => /baseline/i.test(s.name)) || ranked[ranked.length - 1]
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

const runOptions = computed(() => {
  const out = []
  const matrix = decision.value?.matrix
  if (Array.isArray(matrix)) {
    for (const s of matrix) {
      for (const r of s.runs || []) {
        const rid = r.run_id || r.id
        if (rid) {
          out.push({
            id: rid,
            label: `${s.scenario_name || s.name || s.kind} · ${rid}`,
          })
        }
      }
    }
  }
  if (!out.length) {
    for (const s of scenarios.value) {
      for (const r of s.runs || []) {
        if (r.run_id) out.push({ id: r.run_id, label: `${s.scenario_name} · ${r.run_id}` })
      }
    }
  }
  return out
})

function num(v) {
  if (v == null) return null
  if (typeof v === 'object' && 'mean' in v) return Number(v.mean)
  return Number(v)
}
function fmt(v) {
  const n = num(v)
  return n == null || Number.isNaN(n) ? '-' : n.toFixed(1)
}
function pct(v) {
  const n = num(v)
  return n == null || Number.isNaN(n) ? '-' : `${(n * 100).toFixed(0)}%`
}

function disposeCharts() {
  for (const c of charts) c.dispose()
  charts = []
}

function renderCharts() {
  disposeCharts()
  if (!scenarios.value.length) return
  if (barEl.value) {
    const chart = echarts.init(barEl.value)
    charts.push(chart)
    chart.setOption({
      tooltip: {},
      grid: { left: 40, right: 12, top: 20, bottom: 36 },
      xAxis: {
        type: 'category',
        data: scenarios.value.map((s) => s.scenario_name),
        axisLabel: { color: '#666' },
      },
      yAxis: { type: 'value', splitLine: { lineStyle: { color: '#eee' } } },
      series: [{
        type: 'bar',
        barMaxWidth: 42,
        data: scenarios.value.map((s) => ({
          value: num(s.summary?.total_actions) || 0,
          itemStyle: { color: s.color || '#FF4500' },
        })),
      }],
    })
  }
  if (stanceEl.value) {
    const chart = echarts.init(stanceEl.value)
    charts.push(chart)
    chart.setOption({
      tooltip: { trigger: 'axis' },
      legend: { textStyle: { color: '#666' } },
      grid: { left: 40, right: 12, top: 36, bottom: 36 },
      xAxis: {
        type: 'category',
        data: scenarios.value.map((s) => s.scenario_name),
      },
      yAxis: {
        type: 'value',
        max: 1,
        axisLabel: { formatter: (v) => `${v * 100}%` },
        splitLine: { lineStyle: { color: '#eee' } },
      },
      series: [
        { name: '赞成', type: 'bar', stack: 's', itemStyle: { color: '#059669' }, data: scenarios.value.map((s) => num(s.summary?.stance_share?.supportive) || 0) },
        { name: '中立', type: 'bar', stack: 's', itemStyle: { color: '#9ca3af' }, data: scenarios.value.map((s) => num(s.summary?.stance_share?.neutral) || 0) },
        { name: '反对', type: 'bar', stack: 's', itemStyle: { color: '#dc2626' }, data: scenarios.value.map((s) => num(s.summary?.stance_share?.opposing) || 0) },
      ],
    })
  }
  if (curveEl.value && hasCurves.value) {
    const chart = echarts.init(curveEl.value)
    charts.push(chart)
    const series = scenarios.value.map((s) => {
      const curve = s.activity_curve || []
      return {
        name: s.scenario_name,
        type: 'line',
        smooth: true,
        showSymbol: false,
        lineStyle: { width: 2.5, color: s.color || '#FF4500' },
        data: curve.map((p) => (typeof p === 'number' ? p : p.actions ?? p.value ?? 0)),
      }
    })
    const maxLen = Math.max(...series.map((s) => s.data.length), 1)
    chart.setOption({
      tooltip: { trigger: 'axis' },
      legend: { textStyle: { color: '#666' } },
      grid: { left: 40, right: 16, top: 40, bottom: 36 },
      xAxis: {
        type: 'category',
        data: Array.from({ length: maxLen }, (_, i) => `R${i}`),
      },
      yAxis: { type: 'value', splitLine: { lineStyle: { color: '#eee' } } },
      series,
    })
  }
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [cmp, dec] = await Promise.all([
      getDecisionCompare(props.id, { report: true }),
      getDecision(props.id).catch(() => null),
    ])
    const data = cmp.data || cmp
    compare.value = data
    scenarios.value = data.scenarios || []
    const rpt = data.report
    report.value =
      typeof rpt === 'string'
        ? rpt
        : rpt?.markdown ||
          data.narrative ||
          scenarios.value.map((s) => s.narrative).filter(Boolean).join('\n\n')
    decision.value = dec?.data || dec
    if (!runId.value && runOptions.value[0]) runId.value = runOptions.value[0].id
    await nextTick()
    renderCharts()
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

async function send() {
  if (!prompt.value.trim() || !runId.value) return
  const q = prompt.value.trim()
  messages.value.push({ role: 'user', content: q })
  prompt.value = ''
  sending.value = true
  try {
    const res = await interviewRun(runId.value, {
      agent_id: agentId.value,
      prompt: q,
    })
    const data = res.data || res
    const reply =
      data.reply ||
      data.response ||
      data.message ||
      (typeof data === 'string' ? data : JSON.stringify(data))
    messages.value.push({
      role: 'assistant',
      content: res.mode === 'stub' ? `（stub）${reply}` : reply,
    })
    await nextTick()
    if (chatEl.value) chatEl.value.scrollTop = chatEl.value.scrollHeight
  } catch (e) {
    messages.value.push({ role: 'assistant', content: `错误：${e.message}` })
  } finally {
    sending.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.compare-page {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: var(--bg);
  font-family: var(--font-sans);
}
.btn {
  border: 1px solid var(--border);
  background: var(--bg);
  padding: 8px 12px;
  cursor: pointer;
  text-decoration: none;
  color: inherit;
  font-size: 13px;
  font-family: var(--font-mono);
}
.verdict-bar {
  display: grid;
  grid-template-columns: auto 1fr auto;
  gap: 16px;
  align-items: center;
  border: 1px solid var(--border-strong);
  padding: 14px 16px;
  margin-bottom: 14px;
  background: var(--bg-muted);
}
.verdict-label {
  font-size: 0.72rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--ink-muted);
}
.verdict-body {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.verdict-body strong {
  font-size: 1.15rem;
}
.verdict-meta {
  font-size: 0.82rem;
  color: var(--ink-muted);
}
.verdict-delta {
  font-size: 0.8rem;
  color: var(--success);
}
.split {
  flex: 1;
  display: grid;
  grid-template-columns: 1.35fr 0.9fr;
  min-height: 0;
}
.left {
  overflow: auto;
  padding: 16px 20px 40px;
  border-right: 1px solid #eaeaea;
}
.right {
  display: flex;
  flex-direction: column;
  min-height: 0;
  background: #fafafa;
}
.kpi-row {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
  margin-bottom: 12px;
}
.kpi-card {
  border: 1px solid #eaeaea;
  border-top: 3px solid var(--brand);
  padding: 12px;
}
.kpi-head {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-bottom: 8px;
}
.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}
.kpi-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 6px;
}
.muted {
  color: #888;
  font-size: 11px;
}
.val {
  font-family: var(--font-mono);
  font-weight: 800;
  font-size: 18px;
}
.narrative {
  margin: 8px 0 0;
  font-size: 12px;
  color: #666;
  line-height: 1.5;
}
.charts {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.chart-card {
  border: 1px solid #eaeaea;
  padding: 12px;
}
.chart-card h2 {
  margin: 0 0 8px;
  font-size: 11px;
  letter-spacing: 0.06em;
}
.chart {
  height: 260px;
}
.chart.tall {
  height: 320px;
}
.report-style {
  margin-top: 16px;
  border: 1px solid #eaeaea;
  padding: 20px;
}
.report-tag {
  display: inline-block;
  background: #111;
  color: #fff;
  font-family: var(--font-mono);
  font-size: 10px;
  padding: 3px 8px;
  letter-spacing: 0.08em;
}
.report-style h1 {
  font-family: 'Times New Roman', 'Noto Serif SC', serif;
  font-size: 28px;
  margin: 12px 0 16px;
}
.report-body {
  white-space: pre-wrap;
  font-size: 13px;
  line-height: 1.65;
  color: #222;
  margin: 0;
  font-family: 'Noto Sans SC', system-ui, sans-serif;
}
.action-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 14px;
  border-bottom: 1px solid #eaeaea;
  background: #fff;
}
.tabs {
  display: flex;
  gap: 6px;
}
.tab {
  border: none;
  background: #eee;
  border-radius: 20px;
  padding: 6px 12px;
  font-size: 12px;
  cursor: pointer;
}
.tab.active {
  background: #1f2937;
  color: #fff;
}
.chat-container {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.profile-card {
  padding: 12px 14px;
  border-bottom: 1px solid #eaeaea;
  background: #fff;
}
.profile-card select,
.profile-card input,
.chat-input-area textarea {
  width: 100%;
  border: 1px solid #e5e5e5;
  padding: 8px 10px;
  font: inherit;
  box-sizing: border-box;
  margin-top: 4px;
}
.chat-messages {
  flex: 1;
  overflow: auto;
  padding: 14px;
}
.bubble {
  max-width: 85%;
  padding: 10px 12px;
  border-radius: 12px;
  margin-bottom: 10px;
  font-size: 13px;
  line-height: 1.5;
}
.bubble.user {
  margin-left: auto;
  background: #1f2937;
  color: #fff;
  border-bottom-right-radius: 4px;
}
.bubble.assistant {
  background: #eee;
  color: #111;
  border-bottom-left-radius: 4px;
}
.chat-input-area {
  display: flex;
  gap: 8px;
  padding: 12px;
  border-top: 1px solid #eaeaea;
  background: #fff;
}
.cta {
  border: none;
  background: #000;
  color: #fff;
  padding: 0 16px;
  font-weight: 700;
  cursor: pointer;
}
.cta:disabled {
  opacity: 0.4;
}
.center {
  text-align: center;
  padding: 24px;
}
.error {
  color: #dc2626;
  font-size: 13px;
}
@media (max-width: 960px) {
  .split {
    grid-template-columns: 1fr;
  }
  .kpi-row,
  .charts {
    grid-template-columns: 1fr;
  }
}
</style>

<template>
  <div class="monitor-page">
    <AppHeader>
      <template #center>
        <span class="mono">运行监控</span>
        <span class="muted mono">{{ id }}</span>
      </template>
      <template #right>
        <span class="status-indicator" :class="statusClass(status?.status)">
          <span class="dot"></span>{{ status?.status || '…' }}
        </span>
        <button class="btn" @click="refresh">刷新</button>
        <RouterLink class="btn primary" :to="{ name: 'DecisionCompare', params: { id } }">
          查看对比
        </RouterLink>
      </template>
    </AppHeader>

    <div class="control-bar">
      <div
        v-for="sc in scenarioCards"
        :key="sc.id"
        class="platform-card"
        :class="{ active: sc.id === selectedScenarioId, completed: sc.completed }"
        @click="selectScenario(sc.id)"
      >
        <div class="pc-name">{{ sc.name }}</div>
        <div class="pc-stats">
          <div><span class="k">RUNS</span><span class="v">{{ sc.runs }}</span></div>
          <div><span class="k">DONE</span><span class="v">{{ sc.done }}</span></div>
          <div><span class="k">ACTS</span><span class="v">{{ sc.acts }}</span></div>
        </div>
      </div>
      <p v-if="!scenarioCards.length" class="muted pad">暂无 Scenario，可能仍在准备共享世界…</p>
    </div>

    <main class="content-area">
      <div class="timeline-panel" ref="timelinePanel" @scroll="onTimelineScroll">
        <div class="total-pill mono">
          ACTIONS · {{ actions.length }}
          <span v-if="eventCount" class="pill-sub">· sys {{ eventCount }}</span>
        </div>
        <div class="timeline-feed">
          <div class="timeline-axis"></div>
          <article
            v-for="(a, idx) in actions"
            :key="a._key || idx"
            class="timeline-item"
            :class="idx % 2 === 0 ? 'left' : 'right'"
          >
            <div class="timeline-marker"><span class="marker-dot"></span></div>
            <div class="timeline-card">
              <div class="card-top">
                <span class="avatar">{{ avatarOf(a) }}</span>
                <strong>{{ a.agent_name || `Agent ${a.agent_id ?? '?'}` }}</strong>
                <span class="action-badge mono">{{ prettyType(a.action_type) }}</span>
              </div>
              <p class="body" v-if="contentOf(a)">{{ contentOf(a) }}</p>
              <p class="body muted" v-else>（无正文）</p>
              <div class="footer mono">
                R{{ a.round ?? a.round_num ?? '-' }}
                <span v-if="a.stance"> · {{ a.stance }}</span>
              </div>
            </div>
          </article>
          <p v-if="!actions.length" class="muted center">
            {{ selectedRunId ? '该 Run 暂无 Agent 动作（可能仅有初始帖 / 未激活 Agent）' : '选择右侧 Run 查看动作流' }}
          </p>
        </div>
      </div>

      <div class="matrix-panel">
        <h2 class="mono">Scenario × Run</h2>
        <table>
          <thead>
            <tr>
              <th>方案</th>
              <th>Run</th>
              <th>Seed</th>
              <th>状态</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="row in rows"
              :key="row.run_id"
              :class="{ active: row.run_id === selectedRunId }"
              @click="selectRun(row.run_id)"
            >
              <td>{{ row.scenario_name }}</td>
              <td class="mono muted">{{ shortId(row.run_id) }}</td>
              <td class="mono">{{ row.seed }}</td>
              <td>
                <span class="badge" :class="statusClass(row.status)">{{ row.status }}</span>
              </td>
              <td><button class="btn" @click.stop="selectRun(row.run_id)">动作流</button></td>
            </tr>
          </tbody>
        </table>
      </div>
    </main>

    <div class="system-logs">
      <div class="logs-title">SIMULATION MONITOR</div>
      <div class="logs-body">
        <div v-for="(log, i) in logs" :key="i" class="log-line">
          <span class="log-time">{{ log.time }}</span>{{ log.msg }}
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import AppHeader from '../components/AppHeader.vue'
import { getDecision, getDecisionStatus, getRunActions } from '../api/decision'

const props = defineProps({ id: String })
const status = ref(null)
const decision = ref(null)
const selectedRunId = ref('')
const selectedScenarioId = ref('')
const actions = ref([])
const eventCount = ref(0)
const logs = ref([])
const timelinePanel = ref(null)
const stickTimelineToBottom = ref(true)
const TIMELINE_BOTTOM_THRESHOLD = 80
let timer = null

const rows = computed(() => {
  const out = []
  // API: get_status → { matrix: [{ scenario_id, scenario_name, runs:[{run_id,...}] }] }
  const matrix = status.value?.matrix
  if (Array.isArray(matrix) && matrix.length) {
    for (const s of matrix) {
      for (const r of s.runs || []) {
        out.push({
          scenario_id: s.scenario_id || s.kind,
          scenario_name: s.scenario_name || s.name || s.kind,
          run_id: r.run_id || r.id,
          seed: r.seed,
          status: r.status,
          color: s.color,
        })
      }
    }
    return out
  }
  for (const s of status.value?.scenarios || decision.value?.scenarios || []) {
    for (const r of s.runs || []) {
      out.push({
        scenario_id: s.id || s.scenario_id || s.kind,
        scenario_name: s.name || s.scenario_name || s.kind,
        run_id: r.id || r.run_id,
        seed: r.seed,
        status: r.status,
        color: s.color,
      })
    }
  }
  return out
})

const scenarioCards = computed(() => {
  const map = new Map()
  for (const r of rows.value) {
    if (!map.has(r.scenario_id)) {
      map.set(r.scenario_id, {
        id: r.scenario_id,
        name: r.scenario_name,
        runs: 0,
        done: 0,
        acts: 0,
        completed: false,
      })
    }
    const sc = map.get(r.scenario_id)
    sc.runs += 1
    if (r.status === 'completed') sc.done += 1
  }
  for (const sc of map.values()) {
    sc.completed = sc.runs > 0 && sc.done === sc.runs
    if (sc.id === selectedScenarioId.value) sc.acts = actions.value.length
  }
  return [...map.values()]
})

function statusClass(s) {
  if (s === 'completed' || s === 'ready') return 'completed'
  if (s === 'failed' || s === 'error') return 'error'
  if (s === 'running' || s === 'starting') return 'processing'
  return ''
}
function shortId(id) {
  return id && id.length > 14 ? `${id.slice(0, 12)}…` : id || '-'
}
function prettyType(t) {
  return String(t || 'ACTION').replace(/_/g, ' ')
}
function contentOf(a) {
  if (a.content) return a.content
  const args = a.action_args || {}
  return args.content || args.quote_content || args.post_content || ''
}
function avatarOf(a) {
  const name = a.agent_name || ''
  if (name && name !== '?' && !name.startsWith('Agent ')) return name[0]
  if (a.agent_id != null) return String(a.agent_id).slice(-1)
  return '?'
}
function isAgentAction(a) {
  const t = String(a?.action_type || '').toUpperCase()
  if (['SIMULATION_START', 'SIMULATION_END', 'ROUND_START', 'ROUND_END', 'EVENT'].includes(t)) {
    return false
  }
  if (a?.event_type && ['simulation_start', 'simulation_end', 'round_start', 'round_end'].includes(a.event_type)) {
    return false
  }
  // 空壳 LLM_ACTION 不展示
  if (t === 'LLM_ACTION' && !contentOf(a)) return false
  if (['CREATE_POST', 'QUOTE_POST', 'REPOST', 'CREATE_COMMENT', 'LIKE_POST', 'DISLIKE_POST', 'FOLLOW'].includes(t)) {
    return true
  }
  return !!(contentOf(a) || (a?.agent_id != null && t && t !== 'LLM_ACTION'))
}
function addLog(msg) {
  const time = new Date().toLocaleTimeString('en-US', { hour12: false })
  logs.value.push({ time, msg })
  if (logs.value.length > 80) logs.value.shift()
}

function onTimelineScroll() {
  const el = timelinePanel.value
  if (!el) return
  const dist = el.scrollHeight - el.scrollTop - el.clientHeight
  stickTimelineToBottom.value = dist <= TIMELINE_BOTTOM_THRESHOLD
}

function scrollTimelineToBottom() {
  const el = timelinePanel.value
  if (!el || !stickTimelineToBottom.value) return
  el.scrollTop = el.scrollHeight
}

watch(
  () => actions.value.length,
  () => {
    nextTick(scrollTimelineToBottom)
  },
)

async function loadActions(runId) {
  if (!runId) {
    actions.value = []
    eventCount.value = 0
    return
  }
  try {
    const res = await getRunActions(runId, { limit: 500 })
    const data = res.data || {}
    const list = (data.actions || []).filter(isAgentAction)
    eventCount.value = data.event_count || 0
    actions.value = list.map((a, i) => ({ ...a, _key: `${runId}-${i}` })).reverse()
    for (const ev of data.events_summary || []) {
      if (ev.event_type === 'simulation_end') {
        addLog(`sim end · rounds=${ev.round ?? '-'} · ${runId}`)
      }
    }
    addLog(`Loaded ${actions.value.length} actions` + (eventCount.value ? ` (filtered ${eventCount.value} sys events)` : '') + ` · ${runId}`)
  } catch (e) {
    actions.value = []
    eventCount.value = 0
    addLog(`actions error: ${e.message}`)
  }
}

async function selectRun(runId) {
  selectedRunId.value = runId
  const row = rows.value.find((r) => r.run_id === runId)
  if (row) selectedScenarioId.value = row.scenario_id
  await loadActions(runId)
}

function selectScenario(sid) {
  selectedScenarioId.value = sid
  const first = rows.value.find((r) => r.scenario_id === sid)
  if (first) selectRun(first.run_id)
}

async function refresh() {
  try {
    const st = await getDecisionStatus(props.id)
    status.value = st.data || st
  } catch (_) {}
  try {
    const d = await getDecision(props.id)
    decision.value = d.data || d
  } catch (_) {}
  if (!selectedRunId.value && rows.value.length) {
    await selectRun(rows.value[0].run_id)
  } else if (selectedRunId.value) {
    await loadActions(selectedRunId.value)
  }
  addLog(`status=${status.value?.status || decision.value?.status || '?'}`)
}

onMounted(async () => {
  addLog('Monitor initialized')
  await refresh()
  timer = setInterval(refresh, 4000)
})
onBeforeUnmount(() => clearInterval(timer))
</script>

<style scoped>
.monitor-page {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: var(--bg);
  font-family: var(--font-sans);
}
.muted {
  color: var(--ink-faint);
  font-size: 12px;
}
.btn {
  border: 1px solid var(--border);
  background: var(--bg);
  padding: 8px 12px;
  cursor: pointer;
  font-size: 13px;
  text-decoration: none;
  color: inherit;
  font-family: var(--font-mono);
}
.btn.primary {
  background: var(--ink);
  color: var(--bg);
  border-color: var(--ink);
}
.status-indicator {
  display: flex;
  align-items: center;
  gap: 6px;
  font-family: var(--font-mono);
  font-size: 12px;
}
.status-indicator .dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--brand);
}
.status-indicator.completed .dot {
  background: #10b981;
}
.status-indicator.error .dot {
  background: #ef4444;
}
.control-bar {
  display: flex;
  gap: 10px;
  padding: 12px 16px;
  border-bottom: 1px solid #eaeaea;
  overflow-x: auto;
  background: #fafafa;
}
.platform-card {
  min-width: 180px;
  background: #fff;
  border: 1px solid #e5e5e5;
  padding: 10px 12px;
  cursor: pointer;
}
.platform-card.active {
  border-color: #000;
}
.platform-card.completed {
  border-color: #1a936f;
}
.pc-name {
  font-weight: 700;
  font-size: 13px;
  margin-bottom: 8px;
}
.pc-stats {
  display: flex;
  gap: 12px;
}
.pc-stats .k {
  display: block;
  font-size: 10px;
  color: #999;
  font-family: var(--font-mono);
}
.pc-stats .v {
  font-family: var(--font-mono);
  font-weight: 700;
}
.content-area {
  flex: 1;
  display: grid;
  grid-template-columns: 1.2fr 1fr;
  overflow: hidden;
  min-height: 0;
}
.timeline-panel {
  border-right: 1px solid #eaeaea;
  overflow: auto;
  position: relative;
  padding: 16px;
}
.total-pill {
  position: sticky;
  top: 0;
  display: inline-block;
  background: #111;
  color: #fff;
  font-size: 11px;
  padding: 4px 10px;
  border-radius: 999px;
  z-index: 2;
  margin-bottom: 12px;
}
.pill-sub {
  color: #aaa;
  font-weight: 400;
}
.timeline-feed {
  position: relative;
  padding: 8px 0 24px;
}
.timeline-axis {
  position: absolute;
  left: 50%;
  top: 0;
  bottom: 0;
  width: 1px;
  background: #eaeaea;
}
.timeline-item {
  width: 46%;
  margin-bottom: 14px;
  position: relative;
}
.timeline-item.left {
  margin-right: auto;
}
.timeline-item.right {
  margin-left: auto;
}
.timeline-marker {
  position: absolute;
  top: 16px;
  width: 12px;
  height: 12px;
}
.timeline-item.left .timeline-marker {
  right: -8%;
}
.timeline-item.right .timeline-marker {
  left: -8%;
}
.marker-dot {
  display: block;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #000;
}
.timeline-card {
  border: 1px solid #eaeaea;
  padding: 10px 12px;
  background: #fff;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.03);
}
.card-top {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
  margin-bottom: 6px;
}
.avatar {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: #111;
  color: #fff;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
}
.action-badge {
  font-size: 10px;
  border: 1px solid #e5e5e5;
  padding: 2px 6px;
  color: #666;
}
.body {
  margin: 0;
  font-size: 13px;
  line-height: 1.5;
  color: #222;
}
.footer {
  margin-top: 8px;
  font-size: 10px;
  color: #999;
}
.matrix-panel {
  overflow: auto;
  padding: 16px;
}
.matrix-panel h2 {
  font-size: 12px;
  margin: 0 0 12px;
  letter-spacing: 0.06em;
}
table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
th,
td {
  padding: 8px 10px;
  border-bottom: 1px solid #eee;
  text-align: left;
}
th {
  color: #999;
  font-size: 11px;
  font-family: var(--font-mono);
}
tr.active td {
  background: #fff7f3;
}
tr {
  cursor: pointer;
}
.badge {
  font-size: 11px;
  font-family: var(--font-mono);
  border: 1px solid #e5e5e5;
  padding: 2px 8px;
  border-radius: 999px;
}
.badge.completed {
  color: #059669;
  border-color: #a7f3d0;
}
.badge.error {
  color: #dc2626;
}
.badge.processing {
  color: #d97706;
}
.system-logs {
  height: 90px;
  background: #000;
  color: #ccc;
  display: flex;
  flex-direction: column;
}
.logs-title {
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.08em;
  padding: 6px 12px;
  border-bottom: 1px solid #222;
  color: #888;
}
.logs-body {
  flex: 1;
  overflow: auto;
  padding: 6px 12px;
  font-family: var(--font-mono);
  font-size: 11px;
}
.log-time {
  color: #666;
  margin-right: 8px;
}
.center {
  text-align: center;
  padding: 40px;
}
.pad {
  padding: 8px;
}
@media (max-width: 960px) {
  .content-area {
    grid-template-columns: 1fr;
  }
  .timeline-axis {
    display: none;
  }
  .timeline-item {
    width: 100%;
  }
}
</style>

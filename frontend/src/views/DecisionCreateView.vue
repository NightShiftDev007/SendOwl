<template>
  <div class="create-page">
    <AppHeader>
      <template #right>
        <span class="mono muted">创建决策任务</span>
        <RouterLink class="link" to="/">返回首页</RouterLink>
      </template>
    </AppHeader>

    <main class="content">
      <div class="brief-panel">
        <div class="box-head">
          <span class="mono">01 / 选择本体</span>
          <span class="hint">常驻本体快照作为推演世界底座</span>
        </div>
        <div class="field">
          <label>本体</label>
          <select v-model="form.ontology_id">
            <option disabled value="">请选择</option>
            <option v-for="o in ontologies" :key="o.id" :value="o.id">
              {{ o.name }} ({{ o.status }})
            </option>
          </select>
        </div>
        <div class="field">
          <label>版本 ID（可空=最新）</label>
          <input v-model="form.version_id" placeholder="自动使用最新快照" />
        </div>
        <div class="field">
          <label>任务标题</label>
          <input v-model="form.title" />
        </div>
        <div class="row">
          <div class="field grow">
            <label>每方案采样 M</label>
            <input type="number" min="1" max="5" v-model.number="form.sample_count" />
          </div>
          <div class="field grow">
            <label>最大轮数</label>
            <input type="number" min="3" max="40" v-model.number="form.max_rounds" />
          </div>
        </div>
      </div>

      <div class="brief-panel" style="margin-top:16px">
        <div class="box-head">
          <span class="mono">02 / 干预方案</span>
          <span class="hint">含 Baseline 对照</span>
        </div>
        <div
          v-for="(s, idx) in form.scenarios"
          :key="idx"
          class="scenario-card"
          :style="{ borderColor: s.color }"
        >
          <div class="row between">
            <strong>{{ s.name }}</strong>
            <span class="badge mono">{{ s.kind }}</span>
          </div>
          <div class="field">
            <label>方案名</label>
            <input v-model="s.name" />
          </div>
          <div class="field">
            <label>初始帖文案</label>
            <textarea v-model="s.content" />
          </div>
          <div class="field">
            <label>发布者提示</label>
            <input v-model="s.poster_hint" />
          </div>
        </div>
        <button class="ghost" @click="addScenario">+ 方案</button>
        <button class="cta" :disabled="busy || !form.ontology_id" @click="submit">
          {{ busy ? '创建中…' : '创建并启动推演' }}
        </button>
        <p v-if="msg" :class="err ? 'error' : 'ok'">{{ msg }}</p>
      </div>
    </main>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppHeader from '../components/AppHeader.vue'
import { listOntologies } from '../api/ontology'
import { createDecision, startDecision } from '../api/decision'

const route = useRoute()
const router = useRouter()
const ontologies = ref([])
const busy = ref(false)
const msg = ref('')
const err = ref(false)

const form = reactive({
  ontology_id: route.query.ontology_id || '',
  version_id: route.query.version_id || '',
  title: '限行新政发布策略对比',
  sample_count: 3,
  max_rounds: 10,
  scenarios: [
    {
      name: '方案A·强硬发布',
      kind: 'A_hard',
      color: '#e74c3c',
      poster_hint: 'official',
      content:
        '【江城市交管局公告】自下周一零时起主干道禁止电动自行车通行。首次违规罚款50元，三次及以上罚款500元并记入交通信用。',
    },
    {
      name: '方案B·柔性发布',
      kind: 'B_soft',
      color: '#27ae60',
      poster_hint: 'official',
      content:
        '【江城市交管局公告】电动自行车通行管理试点启动：先试点90天，换购最高补贴800元，骑手可申请临时通行证，今晚起FAQ直播答疑。',
    },
    {
      name: 'Baseline·不正式发布',
      kind: 'Baseline',
      color: '#7f8c8d',
      poster_hint: 'citizen',
      content: '听说江城要限电瓶车？有人在群里传下周江城大道不让骑了，也不知道是真是假，有官方消息吗？',
    },
  ],
})

function addScenario() {
  form.scenarios.push({
    name: `方案${form.scenarios.length + 1}`,
    kind: 'custom',
    color: '#3b82f6',
    poster_hint: 'official',
    content: '',
  })
}

async function submit() {
  busy.value = true
  err.value = false
  msg.value = ''
  try {
    const body = {
      ontology_id: form.ontology_id,
      version_id: form.version_id || undefined,
      title: form.title,
      sample_count: form.sample_count,
      max_rounds: form.max_rounds,
      scenarios: form.scenarios.map((s) => ({
        name: s.name,
        kind: s.kind,
        color: s.color,
        intervention: {
          name: s.name,
          kind: s.kind,
          initial_posts: [{ content: s.content, poster_hint: s.poster_hint || 'official' }],
        },
      })),
    }
    const created = await createDecision(body)
    const payload = created.data || created
    const decision = payload.decision || payload
    const id = decision.id || decision.decision_id
    if (!id) throw new Error('未返回 decision id')
    msg.value = `已创建 ${id}，正在启动…`
    await startDecision(id)
    router.push({ name: 'DecisionMonitor', params: { id } })
  } catch (e) {
    err.value = true
    msg.value = e.message
  } finally {
    busy.value = false
  }
}

onMounted(async () => {
  const res = await listOntologies()
  ontologies.value = res.data || []
  if (!form.ontology_id && ontologies.value[0]) {
    form.ontology_id = ontologies.value[0].id
  }
})
</script>

<style scoped>
.create-page {
  min-height: 100vh;
  background: var(--bg);
  font-family: var(--font-sans);
}
.muted { color: var(--ink-muted); font-size: 0.8rem; }
.link {
  color: var(--ink-muted);
  text-decoration: none;
  font-family: var(--font-mono);
  font-size: 0.8rem;
}
.link:hover { color: var(--brand); }
.content {
  max-width: 820px;
  margin: 0 auto;
  padding: 28px 20px 64px;
}
.brief-panel {
  border: 1px solid var(--border);
  background: var(--surface);
}
.box-head {
  display: flex;
  justify-content: space-between;
  padding: 12px 14px;
  border-bottom: 1px solid var(--border);
  background: var(--bg-muted);
  font-size: 12px;
  font-weight: 700;
}
.hint {
  color: var(--ink-faint);
  font-weight: 400;
}
.field {
  padding: 10px 14px;
}
.field label {
  display: block;
  font-size: 12px;
  color: var(--ink-muted);
  margin-bottom: 6px;
}
.field input,
.field select,
.field textarea {
  width: 100%;
  border: 1px solid var(--border);
  padding: 10px 12px;
  font: inherit;
  box-sizing: border-box;
  background: var(--bg);
  color: var(--ink);
}
.field textarea { min-height: 90px; }
.row { display: flex; gap: 10px; }
.row.between {
  justify-content: space-between;
  align-items: center;
  padding: 10px 14px 0;
}
.grow { flex: 1; }
.scenario-card {
  border: 1px solid var(--border);
  margin: 12px 14px;
  background: var(--surface-raised);
}
.badge {
  font-size: 10px;
  border: 1px solid var(--border);
  padding: 2px 8px;
  border-radius: var(--radius-sm);
  color: var(--ink-muted);
}
.cta,
.ghost {
  display: block;
  width: calc(100% - 28px);
  margin: 10px 14px;
  padding: 14px;
  border: none;
  cursor: pointer;
  font-weight: 700;
  font-family: var(--font-mono);
}
.cta {
  background: var(--ink);
  color: var(--bg);
}
.cta:hover:not(:disabled) { background: var(--brand); }
.cta:disabled { opacity: 0.4; }
.ghost {
  background: var(--bg-muted);
  border: 1px dashed var(--border);
  color: var(--ink);
}
.error {
  color: var(--danger);
  padding: 0 14px 14px;
  font-size: 13px;
}
.ok {
  color: var(--success);
  padding: 0 14px 14px;
  font-size: 13px;
}
</style>

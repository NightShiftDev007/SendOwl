<template>
  <main class="page">
    <h1>创建决策任务</h1>
    <p class="sub">选择本体版本，配置多干预方案（含 Baseline），设置采样次数后启动推演。</p>

    <div class="card">
      <div class="field">
        <label>本体</label>
        <select v-model="form.ontology_id" @change="onOntologyChange">
          <option disabled value="">请选择</option>
          <option v-for="o in ontologies" :key="o.id" :value="o.id">{{ o.name }} ({{ o.status }})</option>
        </select>
      </div>
      <div class="field">
        <label>版本 ID（可空=最新）</label>
        <input v-model="form.version_id" placeholder="自动使用最新快照版本" />
      </div>
      <div class="field">
        <label>任务标题</label>
        <input v-model="form.title" />
      </div>
      <div class="row">
        <div class="field" style="flex:1">
          <label>每方案采样次数 M</label>
          <input type="number" min="1" max="5" v-model.number="form.sample_count" />
        </div>
        <div class="field" style="flex:1">
          <label>最大轮数</label>
          <input type="number" min="3" max="40" v-model.number="form.max_rounds" />
        </div>
      </div>

      <h2 style="margin:8px 0 12px;font-size:15px;color:#cbd5e1">干预方案</h2>
      <div v-for="(s, idx) in form.scenarios" :key="idx" class="card" style="margin-bottom:10px;background:#121a26">
        <div class="row" style="justify-content:space-between;margin-bottom:8px">
          <strong>{{ s.name }}</strong>
          <span class="badge">{{ s.kind || 'custom' }}</span>
        </div>
        <div class="field">
          <label>方案名</label>
          <input v-model="s.name" />
        </div>
        <div class="field">
          <label>初始帖文案（干预内容）</label>
          <textarea v-model="s.content" />
        </div>
        <div class="field">
          <label>发布者提示（official / citizen）</label>
          <input v-model="s.poster_hint" />
        </div>
      </div>

      <div class="row">
        <button class="btn" @click="addScenario">+ 方案</button>
        <button class="btn primary" :disabled="busy || !form.ontology_id" @click="submit">
          {{ busy ? '创建中…' : '创建并启动' }}
        </button>
      </div>
      <p v-if="msg" :class="err ? 'error' : 'success'">{{ msg }}</p>
    </div>
  </main>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { listOntologies, createDecision, startDecision } from '../api/client'

const router = useRouter()
const ontologies = ref([])
const busy = ref(false)
const msg = ref('')
const err = ref(false)

const form = reactive({
  ontology_id: '',
  version_id: '',
  title: '限行新政发布策略对比',
  sample_count: 3,
  max_rounds: 10,
  scenarios: [
    {
      name: '方案A·强硬发布',
      kind: 'A_hard',
      color: '#e74c3c',
      poster_hint: 'official',
      content: '【江城市交管局公告】自下周一零时起主干道禁止电动自行车通行。首次违规罚款50元，三次及以上罚款500元并记入交通信用。',
    },
    {
      name: '方案B·柔性发布',
      kind: 'B_soft',
      color: '#27ae60',
      poster_hint: 'official',
      content: '【江城市交管局公告】电动自行车通行管理试点启动：先试点90天，换购最高补贴800元，骑手可申请临时通行证，今晚起FAQ直播答疑。',
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

function onOntologyChange() {
  const o = ontologies.value.find((x) => x.id === form.ontology_id)
  if (o?.latest_version_id) form.version_id = o.latest_version_id
}

async function submit() {
  busy.value = true; err.value = false; msg.value = ''
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
          initial_posts: [
            { content: s.content, poster_hint: s.poster_hint || 'official' },
          ],
        },
      })),
    }
    const created = await createDecision(body)
    const payload = created.data || created
    const decision = payload.decision || payload
    const id = decision.id || decision.decision_id || payload.id
    if (!id) throw new Error('创建成功但未返回 decision id')
    msg.value = `已创建 ${id}，正在启动…`
    await startDecision(id)
    router.push(`/decision/${id}/monitor`)
  } catch (e) {
    err.value = true
    msg.value = e.response?.data?.error || e.message
  } finally {
    busy.value = false
  }
}

onMounted(async () => {
  const res = await listOntologies()
  ontologies.value = res.data || res.ontologies || res || []
  if (!Array.isArray(ontologies.value)) ontologies.value = ontologies.value.items || []
})
</script>

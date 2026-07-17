<template>
  <div class="scenario-editor">
    <div class="editor-head" @click="expanded = !expanded">
      <span class="mono">方案配置</span>
      <span class="hint">
        <template v-if="isGtv">
          干预/提示（对 CRM 种子底座干什么）：Baseline + 加推/换人/谈价协商
          <strong v-if="modelValue.length">· N={{ modelValue.length }}</strong>
        </template>
        <template v-else>
          默认 1 个方案（单次推演）；展开可添加对比方案
          <strong v-if="modelValue.length">· N={{ modelValue.length }}</strong>
        </template>
      </span>
      <span class="toggle">{{ expanded ? '收起' : '展开' }}</span>
    </div>

    <div v-show="expanded" class="editor-body">
      <div class="row meta" v-if="!isGtv">
        <label>
          每方案采样 M
          <input
            type="number"
            min="1"
            max="5"
            :value="sampleCount"
            @input="$emit('update:sampleCount', Number($event.target.value) || 1)"
          />
        </label>
        <label>
          最大轮数
          <input
            type="number"
            min="3"
            max="40"
            :value="maxRounds"
            @input="$emit('update:maxRounds', Number($event.target.value) || 10)"
          />
        </label>
      </div>
      <p v-else class="gtv-disclaimer">
        谈价 = 与业主协商（敏感性分析），非公司单方改挂牌价；成功率可人工假设，默认 30%。
      </p>

      <div
        v-for="(s, idx) in modelValue"
        :key="idx"
        class="scenario-card"
        :style="{ borderColor: s.color || '#3498db' }"
      >
        <div class="row between">
          <strong>{{ s.name || `方案${idx + 1}` }}</strong>
          <button
            v-if="modelValue.length > 1"
            type="button"
            class="ghost-sm"
            @click="removeAt(idx)"
          >
            删除
          </button>
        </div>
        <label>
          方案名
          <input :value="s.name" @input="patch(idx, { name: $event.target.value })" />
        </label>

        <template v-if="isGtv">
          <div v-if="isBaseline(s)" class="baseline-tag">Baseline · 不施加干预</div>
          <template v-else>
            <label class="check">
              <input
                type="checkbox"
                :checked="!!s.gtv?.boost_exposure?.enabled"
                @change="patchGtv(idx, 'boost_exposure', { enabled: $event.target.checked, factor: s.gtv?.boost_exposure?.factor ?? 1.5, listing_scope: 'all' })"
              />
              加推带看（提升曝光/带看热度）
            </label>
            <label v-if="s.gtv?.boost_exposure?.enabled" class="indent">
              加推倍数
              <input
                type="number"
                min="1"
                max="5"
                step="0.1"
                :value="s.gtv?.boost_exposure?.factor ?? 1.5"
                @input="patchGtv(idx, 'boost_exposure', { ...(s.gtv?.boost_exposure || {}), enabled: true, factor: Number($event.target.value) || 1.5 })"
              />
            </label>

            <label class="check">
              <input
                type="checkbox"
                :checked="!!s.gtv?.reassign_broker?.enabled"
                @change="patchGtv(idx, 'reassign_broker', { enabled: $event.target.checked, to_user_id: s.gtv?.reassign_broker?.to_user_id || '', listing_scope: 'all' })"
              />
              换维护人
            </label>
            <label v-if="s.gtv?.reassign_broker?.enabled" class="indent">
              目标经纪人 user_id
              <input
                :value="s.gtv?.reassign_broker?.to_user_id || ''"
                @input="patchGtv(idx, 'reassign_broker', { ...(s.gtv?.reassign_broker || {}), enabled: true, to_user_id: $event.target.value })"
              />
            </label>

            <label class="check">
              <input
                type="checkbox"
                :checked="!!s.gtv?.negotiate_deal?.enabled"
                @change="patchGtv(idx, 'negotiate_deal', { enabled: $event.target.checked, success_rate: s.gtv?.negotiate_deal?.success_rate ?? 0.3, concession_pct: s.gtv?.negotiate_deal?.concession_pct ?? 0.05, listing_scope: 'all' })"
              />
              谈价协商（两段式：谈成 / 谈不成）
            </label>
            <div v-if="s.gtv?.negotiate_deal?.enabled" class="indent row2">
              <label>
                谈判成功率 p
                <input
                  type="number"
                  min="0"
                  max="1"
                  step="0.05"
                  :value="s.gtv?.negotiate_deal?.success_rate ?? 0.3"
                  @input="patchGtv(idx, 'negotiate_deal', { ...(s.gtv?.negotiate_deal || {}), enabled: true, success_rate: Number($event.target.value) })"
                />
              </label>
              <label>
                让步幅度
                <input
                  type="number"
                  min="0"
                  max="0.5"
                  step="0.01"
                  :value="s.gtv?.negotiate_deal?.concession_pct ?? 0.05"
                  @input="patchGtv(idx, 'negotiate_deal', { ...(s.gtv?.negotiate_deal || {}), enabled: true, concession_pct: Number($event.target.value) })"
                />
              </label>
            </div>
          </template>
        </template>

        <template v-else>
          <label>
            初始帖文案
            <textarea
              :value="s.content"
              @input="patch(idx, { content: $event.target.value })"
            />
          </label>
          <label>
            发布者提示
            <input
              :value="s.poster_hint"
              @input="patch(idx, { poster_hint: $event.target.value })"
            />
          </label>
        </template>
      </div>

      <p v-if="modelValue.length > 1 && !hasBaseline" class="baseline-hint">
        多方案对比建议包含 Baseline·不干预，便于衡量干预效果
      </p>
      <div class="actions">
        <button type="button" class="ghost" @click="addScenario">+ 添加方案</button>
        <button
          type="button"
          class="ghost"
          :disabled="hasBaseline"
          @click="addBaseline"
        >
          + Baseline
        </button>
        <button type="button" class="ghost" @click="loadDemo">
          {{ isGtv ? '填入 GTV 三方案示例' : '填入限行三方案示例' }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  modelValue: { type: Array, default: () => [] },
  sampleCount: { type: Number, default: 1 },
  maxRounds: { type: Number, default: 10 },
  /** opinion | gtv_deal */
  mode: { type: String, default: 'opinion' },
})

const emit = defineEmits(['update:modelValue', 'update:sampleCount', 'update:maxRounds'])

const expanded = ref(false)
const isGtv = computed(() => String(props.mode || '').toLowerCase() === 'gtv_deal')

const colors = ['#3498db', '#e74c3c', '#27ae60', '#7f8c8d', '#9b59b6']

const BASELINE_SCENARIO = {
  name: 'Baseline·不干预',
  kind: 'baseline',
  color: '#7f8c8d',
  poster_hint: 'citizen',
  content: '',
  gtv: {},
}

function isBaseline(s) {
  return /baseline/i.test(String(s?.kind || '')) || /baseline/i.test(String(s?.name || ''))
}

const hasBaseline = computed(() => props.modelValue.some(isBaseline))

function patch(idx, fields) {
  const next = props.modelValue.map((s, i) => (i === idx ? { ...s, ...fields } : s))
  emit('update:modelValue', next)
}

function patchGtv(idx, key, value) {
  const s = props.modelValue[idx] || {}
  const gtv = { ...(s.gtv || {}), [key]: value }
  patch(idx, { gtv })
}

function removeAt(idx) {
  emit(
    'update:modelValue',
    props.modelValue.filter((_, i) => i !== idx),
  )
}

function addScenario() {
  const i = props.modelValue.length
  const base = {
    name: `方案${i + 1}`,
    kind: 'custom',
    color: colors[i % colors.length],
    poster_hint: 'official',
    content: '',
  }
  if (isGtv.value) {
    base.gtv = {
      boost_exposure: { enabled: false, factor: 1.5, listing_scope: 'all' },
      negotiate_deal: {
        enabled: false,
        success_rate: 0.3,
        concession_pct: 0.05,
        listing_scope: 'all',
      },
    }
  }
  emit('update:modelValue', [...props.modelValue, base])
  expanded.value = true
}

function addBaseline() {
  if (hasBaseline.value) return
  emit('update:modelValue', [...props.modelValue, { ...BASELINE_SCENARIO }])
  expanded.value = true
}

/** 供父组件在应用多方案前确保含 Baseline */
function ensureBaseline() {
  if (props.modelValue.length <= 1 || hasBaseline.value) return props.modelValue
  const next = [...props.modelValue, { ...BASELINE_SCENARIO }]
  emit('update:modelValue', next)
  return next
}

defineExpose({ ensureBaseline, hasBaseline, isBaseline })

function loadDemo() {
  if (isGtv.value) {
    emit('update:sampleCount', 1)
    emit('update:modelValue', [
      {
        name: '方案A·加推带看',
        kind: 'boost',
        color: '#e74c3c',
        gtv: {
          boost_exposure: { enabled: true, factor: 1.8, listing_scope: 'all' },
        },
      },
      {
        name: '方案B·谈价协商',
        kind: 'nego',
        color: '#27ae60',
        gtv: {
          negotiate_deal: {
            enabled: true,
            success_rate: 0.3,
            concession_pct: 0.05,
            listing_scope: 'all',
          },
        },
      },
      { ...BASELINE_SCENARIO },
    ])
    expanded.value = true
    return
  }
  emit('update:sampleCount', 3)
  emit('update:modelValue', [
    {
      name: '方案A·强硬发布',
      kind: 'A_hard',
      color: '#e74c3c',
      poster_hint: 'official',
      content:
        '【丰台交通支队公告】自下周一零时起，丽泽路、丰台南路、南三环辅路（丰台段）、北京西站南广场周边指定机动车道禁止电动自行车通行。首次违规罚款50元，三次及以上罚款500元并记入交通信用。',
    },
    {
      name: '方案B·柔性发布',
      kind: 'B_soft',
      color: '#27ae60',
      poster_hint: 'official',
      content:
        '【丰台交通支队公告】电动自行车通行管理试点启动：先在丽泽路与丰台南路试点90天，换购最高补贴800元，骑手可申请临时通行证，今晚起FAQ直播答疑。',
    },
    {
      name: 'Baseline·不正式发布',
      kind: 'Baseline',
      color: '#7f8c8d',
      poster_hint: 'citizen',
      content:
        '听说丰台要限电瓶车？有人在群里传下周丽泽路、丰台南路不让骑了，房山骑手也慌，也不知道是真是假，有官方消息吗？',
    },
  ])
  expanded.value = true
}
</script>

<style scoped>
.scenario-editor {
  border: 1px solid var(--border);
  background: var(--surface);
  margin: 12px 0;
}
.editor-head {
  display: flex;
  gap: 12px;
  align-items: center;
  padding: 10px 14px;
  cursor: pointer;
  background: var(--bg-muted);
  border-bottom: 1px solid var(--border);
  font-size: 12px;
  font-weight: 700;
}
.hint {
  flex: 1;
  color: var(--ink-faint);
  font-weight: 400;
}
.toggle {
  font-family: var(--font-mono);
  color: var(--brand);
}
.editor-body {
  padding: 12px 14px 16px;
}
.gtv-disclaimer {
  margin: 0 0 12px;
  font-size: 12px;
  color: var(--ink-muted);
  line-height: 1.45;
}
.row.meta {
  display: flex;
  gap: 16px;
  margin-bottom: 12px;
}
.row.meta label,
.scenario-card label {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 12px;
  color: var(--ink-muted);
  margin-bottom: 8px;
}
.scenario-card label.check {
  flex-direction: row;
  align-items: center;
  gap: 8px;
}
.scenario-card label.indent {
  margin-left: 22px;
}
.row2 {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
  margin-left: 22px;
}
.row.meta input,
.scenario-card input,
.scenario-card textarea {
  border: 1px solid var(--border);
  padding: 8px 10px;
  font: inherit;
  background: var(--bg);
  color: var(--ink);
}
.scenario-card textarea {
  min-height: 72px;
}
.scenario-card {
  border: 1px solid var(--border);
  border-left-width: 3px;
  padding: 10px 12px;
  margin-bottom: 10px;
  background: var(--surface-raised);
}
.baseline-tag {
  font-size: 12px;
  color: var(--ink-muted);
  margin-bottom: 6px;
}
.row.between {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}
.baseline-hint {
  margin: 0 0 10px;
  font-size: 12px;
  color: var(--ink-muted);
  line-height: 1.4;
}
.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.ghost,
.ghost-sm {
  border: 1px dashed var(--border);
  background: var(--bg-muted);
  color: var(--ink);
  cursor: pointer;
  font-family: var(--font-mono);
}
.ghost:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.ghost {
  display: block;
  width: 100%;
  padding: 10px;
  margin-top: 8px;
}
.ghost-sm {
  padding: 2px 8px;
  font-size: 11px;
}
</style>

<template>
  <div class="home">
    <AppHeader show-subtitle>
      <template #right>
        <RouterLink class="nav-link" to="/decision/new">{{ $t('home.createDecision') }}</RouterLink>
      </template>
    </AppHeader>

    <div class="main">
      <!-- Briefing hero -->
      <section class="briefing">
        <div class="briefing-copy">
          <p class="kicker">
            <span class="kicker-mark"></span>
            {{ $t('home.tagline') }}
            <span class="version">{{ $t('home.version') }}</span>
          </p>
          <h1 class="title">
            {{ $t('home.heroTitle1') }}
            <span class="title-accent">{{ $t('home.heroTitle2') }}</span>
          </h1>
          <p class="desc">
            <i18n-t keypath="home.heroDesc" tag="span">
              <template #brand><strong>{{ $t('home.heroDescBrand') }}</strong></template>
              <template #agentScale><em>{{ $t('home.heroDescAgentScale') }}</em></template>
              <template #optimalSolution><code>{{ $t('home.heroDescOptimalSolution') }}</code></template>
            </i18n-t>
          </p>
          <p class="slogan">{{ $t('home.slogan') }}</p>
        </div>

        <aside class="status-rail">
          <div class="rail-head">
            <span class="rail-dot" :class="{ ok: engineOk }"></span>
            <span class="mono">{{ $t('home.systemStatus') }}</span>
          </div>
          <div class="stat">
            <div class="stat-label">{{ $t('home.statOntologies') }}</div>
            <div class="stat-value mono">{{ stats.ontologies }}</div>
          </div>
          <div class="stat">
            <div class="stat-label">{{ $t('home.statDecisions') }}</div>
            <div class="stat-value mono">{{ stats.decisions }}</div>
          </div>
          <div class="stat">
            <div class="stat-label">{{ $t('home.statEngine') }}</div>
            <div class="stat-value mono">{{ engineOk ? $t('common.ready') : '…' }}</div>
          </div>
          <p class="rail-note">{{ $t('home.systemReadyDesc') }}</p>
        </aside>
      </section>

      <!-- Work area -->
      <section class="work-grid">
        <div class="workflow">
          <div class="panel-head">
            <span class="mono">{{ $t('home.workflowSequence') }}</span>
          </div>
          <ol class="flow-list">
            <li v-for="n in 5" :key="n" class="flow-item">
              <span class="flow-num mono">{{ String(n).padStart(2, '0') }}</span>
              <div>
                <div class="flow-title">{{ $t(`home.step0${n}Title`) }}</div>
                <div class="flow-desc">{{ $t(`home.step0${n}Desc`) }}</div>
              </div>
            </li>
          </ol>
        </div>

        <div class="brief-panel">
          <div class="panel-head">
            <span class="mono">{{ $t('home.realitySeed') }}</span>
            <span class="panel-meta">{{ $t('home.supportedFormats') }}</span>
          </div>

          <div
            class="upload-zone"
            :class="{ 'drag-over': isDragOver, 'has-files': files.length > 0 }"
            @dragover.prevent="handleDragOver"
            @dragleave.prevent="handleDragLeave"
            @drop.prevent="handleDrop"
            @click="triggerFileInput"
          >
            <input
              ref="fileInput"
              type="file"
              multiple
              accept=".pdf,.md,.txt"
              @change="handleFileSelect"
              style="display: none"
              :disabled="loading"
            />
            <div v-if="files.length === 0" class="upload-placeholder">
              <div class="upload-icon">↑</div>
              <div class="upload-title">{{ $t('home.dragToUpload') }}</div>
              <div class="upload-hint">{{ $t('home.orBrowse') }}</div>
            </div>
            <div v-else class="file-list">
              <div v-for="(file, index) in files" :key="index" class="file-item">
                <span class="file-name">{{ file.name }}</span>
                <button type="button" @click.stop="removeFile(index)" class="remove-btn">×</button>
              </div>
            </div>
          </div>

          <div class="panel-head sub">
            <span class="mono">{{ $t('home.simulationPrompt') }}</span>
            <span class="panel-meta">{{ $t('home.engineBadge') }}</span>
          </div>
          <textarea
            v-model="formData.simulationRequirement"
            class="prompt-input"
            :placeholder="$t('home.promptPlaceholder')"
            rows="5"
            :disabled="loading"
          />

          <button
            class="cta"
            @click="startSimulation"
            :disabled="!canSubmit || loading"
          >
            <span>{{ loading ? $t('home.initializing') : $t('home.startEngine') }}</span>
            <span class="cta-arrow">→</span>
          </button>
        </div>
      </section>

      <HistoryDatabase />
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import AppHeader from '../components/AppHeader.vue'
import HistoryDatabase from '../components/HistoryDatabase.vue'
import { setPendingUpload } from '../store/pendingUpload.js'
import { listOntologies } from '../api/ontology'
import { health, listDecisions } from '../api/decision'

const router = useRouter()

const formData = ref({ simulationRequirement: '' })
const files = ref([])
const loading = ref(false)
const isDragOver = ref(false)
const fileInput = ref(null)
const engineOk = ref(false)
const stats = ref({ ontologies: '—', decisions: '—' })

const canSubmit = computed(
  () => formData.value.simulationRequirement.trim() !== '' && files.value.length > 0,
)

const triggerFileInput = () => {
  if (!loading.value) fileInput.value?.click()
}

const handleFileSelect = (event) => {
  addFiles(Array.from(event.target.files || []))
}

const handleDragOver = () => {
  if (!loading.value) isDragOver.value = true
}

const handleDragLeave = () => {
  isDragOver.value = false
}

const handleDrop = (e) => {
  isDragOver.value = false
  if (loading.value) return
  addFiles(Array.from(e.dataTransfer.files || []))
}

const addFiles = (newFiles) => {
  const valid = newFiles.filter((file) => {
    const ext = file.name.split('.').pop()?.toLowerCase()
    return ['pdf', 'md', 'txt'].includes(ext)
  })
  files.value.push(...valid)
}

const removeFile = (index) => {
  files.value.splice(index, 1)
}

const startSimulation = () => {
  if (!canSubmit.value || loading.value) return
  setPendingUpload(files.value, formData.value.simulationRequirement)
  router.push({ name: 'OntologyWorkspace', params: { ontologyId: 'new' } })
}

onMounted(async () => {
  try {
    const [h, o, d] = await Promise.all([
      health().catch(() => null),
      listOntologies().catch(() => null),
      listDecisions().catch(() => null),
    ])
    engineOk.value = h?.status === 'ok' || h?.data?.status === 'ok'
    const oList = o?.data?.ontologies || o?.ontologies || (Array.isArray(o?.data) ? o.data : [])
    const dList = d?.data?.decisions || d?.decisions || (Array.isArray(d?.data) ? d.data : [])
    stats.value = {
      ontologies: Array.isArray(oList) ? String(oList.length) : '—',
      decisions: Array.isArray(dList) ? String(dList.length) : '—',
    }
  } catch {
    engineOk.value = false
  }
})
</script>

<style scoped>
.home {
  min-height: 100vh;
  background: var(--bg);
  color: var(--ink);
}

.main {
  max-width: var(--content-max);
  margin: 0 auto;
  padding: var(--space-7) var(--space-5) var(--space-8);
}

.nav-link {
  font-family: var(--font-mono);
  font-size: 0.8rem;
  color: var(--ink);
  text-decoration: none;
  border-bottom: 1px solid transparent;
  padding-bottom: 2px;
  transition: border-color 0.15s ease-out, color 0.15s ease-out;
}

.nav-link:hover {
  color: var(--brand);
  border-bottom-color: var(--brand);
}

/* Briefing */
.briefing {
  display: grid;
  grid-template-columns: minmax(0, 1.6fr) minmax(240px, 0.9fr);
  gap: var(--space-7);
  margin-bottom: var(--space-7);
  align-items: start;
}

.kicker {
  display: flex;
  align-items: center;
  gap: 10px;
  font-family: var(--font-mono);
  font-size: 0.78rem;
  color: var(--ink-muted);
  margin-bottom: var(--space-4);
}

.kicker-mark {
  width: 10px;
  height: 10px;
  background: var(--brand);
  flex-shrink: 0;
}

.version {
  color: var(--ink-faint);
}

.title {
  font-size: clamp(2.4rem, 5vw, 3.6rem);
  line-height: 1.15;
  font-weight: 600;
  letter-spacing: -0.03em;
  margin: 0 0 var(--space-5);
  text-wrap: balance;
}

.title-accent {
  display: inline;
  box-decoration-break: clone;
  border-bottom: 3px solid var(--brand);
  padding-bottom: 2px;
}

.desc {
  font-size: 1.05rem;
  line-height: 1.75;
  color: var(--ink-secondary);
  max-width: 62ch;
  margin-bottom: var(--space-4);
}

.desc strong {
  color: var(--ink);
  font-weight: 600;
}

.desc em {
  font-style: normal;
  color: var(--brand);
  font-weight: 600;
}

.desc code {
  font-family: var(--font-mono);
  font-size: 0.92em;
  background: var(--bg-muted);
  padding: 1px 6px;
  border-radius: var(--radius-xs);
}

.slogan {
  font-family: var(--font-mono);
  font-size: 0.85rem;
  color: var(--ink-muted);
}

/* Status rail */
.status-rail {
  border: 1px solid var(--border-strong);
  background: var(--surface);
  padding: var(--space-4);
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.rail-head {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--ink-muted);
  padding-bottom: var(--space-3);
  border-bottom: 1px solid var(--border);
}

.rail-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--ink-faint);
}

.rail-dot.ok {
  background: var(--success);
}

.stat {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: var(--space-3);
}

.stat-label {
  font-size: 0.85rem;
  color: var(--ink-muted);
}

.stat-value {
  font-size: 1.35rem;
  font-weight: 700;
}

.rail-note {
  margin-top: var(--space-2);
  font-size: 0.8rem;
  line-height: 1.5;
  color: var(--ink-faint);
}

/* Work grid */
.work-grid {
  display: grid;
  grid-template-columns: minmax(0, 0.95fr) minmax(0, 1.2fr);
  gap: var(--space-5);
  margin-bottom: var(--space-7);
}

.workflow,
.brief-panel {
  border: 1px solid var(--border);
  background: var(--surface);
}

.panel-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--space-3);
  padding: 12px 16px;
  border-bottom: 1px solid var(--border);
  font-size: 0.78rem;
  background: var(--bg-muted);
}

.panel-head.sub {
  margin-top: var(--space-4);
  border-top: 1px solid var(--border);
}

.panel-meta {
  color: var(--ink-faint);
  font-family: var(--font-mono);
  font-size: 0.72rem;
}

.flow-list {
  list-style: none;
  padding: var(--space-3) 0;
}

.flow-item {
  display: grid;
  grid-template-columns: 40px 1fr;
  gap: var(--space-3);
  padding: 12px 16px;
}

.flow-num {
  font-size: 0.85rem;
  font-weight: 700;
  color: var(--brand);
  padding-top: 2px;
}

.flow-title {
  font-weight: 600;
  font-size: 0.95rem;
  margin-bottom: 2px;
}

.flow-desc {
  font-size: 0.82rem;
  color: var(--ink-muted);
  line-height: 1.45;
}

.upload-zone {
  margin: 16px;
  border: 1px dashed var(--border);
  min-height: 140px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: border-color 0.15s ease-out, background 0.15s ease-out;
  background: var(--surface-raised);
}

.upload-zone:hover,
.upload-zone.drag-over {
  border-color: var(--brand);
  background: var(--brand-soft);
}

.upload-zone.has-files {
  border-style: solid;
  align-items: stretch;
  justify-content: stretch;
  padding: 12px;
}

.upload-placeholder {
  text-align: center;
  color: var(--ink-muted);
}

.upload-icon {
  font-size: 1.6rem;
  margin-bottom: 8px;
  color: var(--ink);
}

.upload-title {
  font-weight: 600;
  color: var(--ink);
  margin-bottom: 4px;
}

.upload-hint {
  font-size: 0.8rem;
}

.file-list {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.file-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  background: var(--bg);
  border: 1px solid var(--border);
  font-family: var(--font-mono);
  font-size: 0.8rem;
}

.remove-btn {
  border: none;
  background: transparent;
  cursor: pointer;
  font-size: 1.1rem;
  color: var(--ink-muted);
  line-height: 1;
}

.remove-btn:hover {
  color: var(--danger);
}

.prompt-input {
  display: block;
  width: calc(100% - 32px);
  margin: 16px;
  border: 1px solid var(--border);
  padding: 12px;
  resize: vertical;
  min-height: 120px;
  font-family: var(--font-mono);
  font-size: 0.85rem;
  line-height: 1.55;
  color: var(--ink);
  background: var(--bg);
}

.prompt-input:focus {
  outline: none;
  border-color: var(--ink);
}

.cta {
  display: flex;
  width: calc(100% - 32px);
  margin: 0 16px 16px;
  align-items: center;
  justify-content: space-between;
  padding: 14px 18px;
  border: none;
  background: var(--ink);
  color: var(--bg);
  font-family: var(--font-mono);
  font-size: 0.9rem;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s ease-out;
}

.cta:hover:not(:disabled) {
  background: var(--brand);
}

.cta:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.cta-arrow {
  font-size: 1.1rem;
}

@media (max-width: 900px) {
  .briefing,
  .work-grid {
    grid-template-columns: 1fr;
  }
}
</style>

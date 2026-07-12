<template>
  <div class="recycle-bin" :class="{ empty: items.length === 0 && !loading }">
    <div class="section-header">
      <div class="section-line"></div>
      <span class="section-title">{{ $t('trash.title') }}</span>
      <div class="section-line"></div>
    </div>

    <div v-if="loading" class="loading-state">
      <span class="loading-spinner"></span>
      <span class="loading-text">{{ $t('history.loadingText') }}</span>
    </div>

    <div v-else-if="items.length === 0" class="empty-hint">
      {{ $t('trash.empty') }}
    </div>

    <div v-else class="trash-list">
      <div v-for="item in items" :key="`${item.kind}-${item.id}`" class="trash-row">
        <div class="trash-main">
          <span class="trash-kind" :class="item.kind">{{ kindLabel(item.kind) }}</span>
          <div class="trash-text">
            <div class="trash-title">{{ truncate(item.title, 48) }}</div>
            <div class="trash-meta mono">
              {{ formatId(item.id) }}
              <span v-if="item.trashed_at"> · {{ $t('trash.trashedAt') }} {{ formatDateTime(item.trashed_at) }}</span>
            </div>
          </div>
        </div>
        <div class="trash-actions">
          <button
            type="button"
            class="btn restore"
            :disabled="busyKey === keyOf(item)"
            @click.stop="restore(item)"
          >{{ $t('trash.restore') }}</button>
          <button
            type="button"
            class="btn purge"
            :disabled="busyKey === keyOf(item)"
            @click.stop="purge(item)"
          >{{ $t('trash.purge') }}</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onActivated, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { listTrash, purgeTrashItem, restoreTrashItem } from '../api/trash'

const props = defineProps({
  refreshToken: { type: Number, default: 0 },
})
const emit = defineEmits(['changed'])

const { t } = useI18n()
const route = useRoute()
const items = ref([])
const loading = ref(true)
const busyKey = ref(null)

const keyOf = (item) => `${item.kind}:${item.id}`

const kindLabel = (kind) =>
  kind === 'decision' ? t('trash.kindDecision') : t('trash.kindOntology')

const truncate = (text, max) => {
  const s = String(text || '')
  return s.length > max ? `${s.slice(0, max)}…` : s
}

const formatId = (id) => {
  if (!id) return '—'
  if (id.startsWith('dec_')) return `DEC_${id.slice(4, 10).toUpperCase()}`
  if (id.startsWith('ont_')) return `ONT_${id.slice(4, 10).toUpperCase()}`
  return id.slice(0, 12).toUpperCase()
}

const formatDateTime = (dateStr) => {
  if (!dateStr) return ''
  try {
    const d = new Date(dateStr)
    const y = d.toISOString().slice(0, 10)
    const h = String(d.getHours()).padStart(2, '0')
    const m = String(d.getMinutes()).padStart(2, '0')
    return `${y} ${h}:${m}`
  } catch {
    return String(dateStr).slice(0, 16)
  }
}

const loadTrash = async () => {
  try {
    loading.value = true
    const res = await listTrash()
    items.value = res?.data || []
  } catch (e) {
    console.error('加载回收站失败:', e)
    items.value = []
  } finally {
    loading.value = false
  }
}

const restore = async (item) => {
  if (!item || busyKey.value) return
  busyKey.value = keyOf(item)
  try {
    const res = await restoreTrashItem(item.kind, item.id)
    if (!res?.success) throw new Error(res?.error || t('common.unknownError'))
    await loadTrash()
    emit('changed')
  } catch (e) {
    window.alert(t('trash.restoreFailed', { error: e.message || e }))
  } finally {
    busyKey.value = null
  }
}

const purge = async (item) => {
  if (!item || busyKey.value) return
  const title = truncate(item.title, 40) || item.id
  if (!window.confirm(t('trash.purgeConfirm', { title }))) return
  busyKey.value = keyOf(item)
  try {
    const res = await purgeTrashItem(item.kind, item.id)
    if (!res?.success) throw new Error(res?.error || t('common.unknownError'))
    // 本地先移除这一条，避免整表刷新异常时看起来像被清空
    items.value = items.value.filter((x) => keyOf(x) !== keyOf(item))
    await loadTrash()
    emit('changed')
  } catch (e) {
    window.alert(t('trash.purgeFailed', { error: e.message || e }))
  } finally {
    busyKey.value = null
  }
}

watch(() => props.refreshToken, () => loadTrash())
watch(() => route.path, (p) => { if (p === '/') loadTrash() })

onMounted(loadTrash)
onActivated(loadTrash)

defineExpose({ loadTrash })
</script>

<style scoped>
.recycle-bin {
  position: relative;
  width: 100%;
  margin-top: 8px;
  padding: 20px 0 40px;
}

.recycle-bin.empty {
  padding-bottom: 24px;
}

.section-header {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 24px;
  margin-bottom: 20px;
  font-family: var(--font-mono);
  padding: 0 40px;
}

.section-line {
  flex: 1;
  height: 1px;
  background: linear-gradient(90deg, transparent, #E5E7EB, transparent);
  max-width: 300px;
}

.section-title {
  font-size: 0.8rem;
  font-weight: 500;
  color: #9CA3AF;
  letter-spacing: 3px;
  text-transform: uppercase;
}

.empty-hint {
  text-align: center;
  color: #9CA3AF;
  font-family: var(--font-mono);
  font-size: 0.75rem;
  letter-spacing: 0.5px;
  padding: 8px 0 4px;
}

.loading-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  padding: 24px;
  color: #9CA3AF;
}

.loading-spinner {
  width: 20px;
  height: 20px;
  border: 2px solid #E5E7EB;
  border-top-color: #6B7280;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.trash-list {
  max-width: 920px;
  margin: 0 auto;
  padding: 0 40px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.trash-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 16px;
  background: #fff;
  border: 1px solid #E5E7EB;
}

.trash-main {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  min-width: 0;
  flex: 1;
}

.trash-kind {
  flex-shrink: 0;
  font-family: var(--font-mono);
  font-size: 0.65rem;
  font-weight: 600;
  letter-spacing: 0.5px;
  padding: 3px 6px;
  border-radius: 2px;
  text-transform: uppercase;
}

.trash-kind.decision {
  background: #FEF3C7;
  color: #B45309;
}

.trash-kind.ontology {
  background: #DBEAFE;
  color: #1D4ED8;
}

.trash-text {
  min-width: 0;
}

.trash-title {
  font-size: 0.9rem;
  font-weight: 600;
  color: #111827;
  line-height: 1.4;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.trash-meta {
  margin-top: 4px;
  font-size: 0.7rem;
  color: #9CA3AF;
}

.trash-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}

.btn {
  height: 30px;
  padding: 0 12px;
  border-radius: 6px;
  font-family: var(--font-mono);
  font-size: 0.7rem;
  font-weight: 600;
  letter-spacing: 0.4px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn.restore {
  border: 1px solid #E5E7EB;
  background: #fff;
  color: #374151;
}

.btn.restore:hover:not(:disabled) {
  border-color: #111827;
  color: #111827;
}

.btn.purge {
  border: 1px solid #FECACA;
  background: #FEF2F2;
  color: #DC2626;
}

.btn.purge:hover:not(:disabled) {
  background: #FEE2E2;
  border-color: #F87171;
}

@media (max-width: 768px) {
  .trash-list { padding: 0 20px; }
  .trash-row {
    flex-direction: column;
    align-items: stretch;
  }
  .trash-actions { justify-content: flex-end; }
}
</style>

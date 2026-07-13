/**
 * 统一进度订阅：主通道 SSE → onOpen 一次快照 → CLOSED 才唯一 interval 降级。
 * UI 优先消费 ProgressEnvelope（data.envelope 或整包即 envelope）。
 */
import { ref, onUnmounted } from 'vue'
import { subscribeDecision, subscribeTask } from '../api/sse'

function pickEnvelope(data) {
  if (!data || typeof data !== 'object') return null
  if (data.envelope && typeof data.envelope === 'object') return data.envelope
  if (data.scope && data.id != null && data.progress != null) return data
  return null
}

/**
 * @param {object} opts
 * @param {'decision'|'task'} opts.scope
 * @param {string|(() => string)} opts.id
 * @param {() => Promise<object|null>} [opts.fetchSnapshot]  onOpen / 降级时拉快照
 * @param {(envelope: object, raw: object) => void} [opts.onUpdate]
 * @param {(envelope: object, raw: object) => void} [opts.onDone]
 * @param {(err: Error) => void} [opts.onError]
 * @param {number} [opts.pollMs=3000] 仅 SSE CLOSED 后启用
 */
export function useProgress(opts = {}) {
  const envelope = ref(null)
  const connected = ref(false)
  const degraded = ref(false)

  let stream = null
  let pollTimer = null
  let stopped = false

  const resolveId = () => {
    const id = typeof opts.id === 'function' ? opts.id() : opts.id
    return id ? String(id) : ''
  }

  const apply = (raw, { done = false } = {}) => {
    const env = pickEnvelope(raw) || raw
    if (env) envelope.value = env
    if (done) opts.onDone?.(env, raw)
    else opts.onUpdate?.(env, raw)
  }

  const stopPoll = () => {
    if (pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
    }
    degraded.value = false
  }

  const startPoll = () => {
    if (stopped || pollTimer || !opts.fetchSnapshot) return
    degraded.value = true
    const tick = async () => {
      if (stopped) return
      try {
        const snap = await opts.fetchSnapshot()
        if (snap) apply(snap)
        const st = String(
          pickEnvelope(snap)?.raw_status ||
            pickEnvelope(snap)?.status ||
            snap?.status ||
            '',
        ).toLowerCase()
        if (
          ['completed', 'failed', 'prepared', 'prepare_failed', 'done', 'success'].includes(
            st,
          )
        ) {
          stopPoll()
          apply(snap, { done: true })
        }
      } catch (e) {
        opts.onError?.(e)
      }
    }
    tick()
    pollTimer = setInterval(tick, opts.pollMs || 3000)
  }

  const closeStream = () => {
    if (stream) {
      try {
        stream.close()
      } catch (_) {
        /* ignore */
      }
      stream = null
    }
    connected.value = false
  }

  const stop = () => {
    stopped = true
    stopPoll()
    closeStream()
  }

  const start = async () => {
    stop()
    stopped = false
    const id = resolveId()
    if (!id) return

    const handlers = {
      onOpen: async () => {
        connected.value = true
        stopPoll()
        if (opts.fetchSnapshot) {
          try {
            const snap = await opts.fetchSnapshot()
            if (snap) apply(snap)
          } catch (_) {
            /* ignore */
          }
        }
      },
      onEvent: (data) => apply(data),
      onDone: (data) => {
        apply(data, { done: true })
        closeStream()
        stopPoll()
      },
      onError: (err) => {
        connected.value = false
        opts.onError?.(err instanceof Error ? err : new Error(String(err || 'sse error')))
        // EventSource 通常会自重连；仅在无法建立时降级
        if (!stream?.es || stream.es.readyState === 2) {
          closeStream()
          startPoll()
        }
      },
    }

    try {
      if (opts.scope === 'task') {
        stream = subscribeTask(id, handlers)
      } else {
        stream = subscribeDecision(id, handlers)
      }
    } catch (e) {
      opts.onError?.(e)
      startPoll()
    }
  }

  onUnmounted(() => stop())

  return {
    envelope,
    connected,
    degraded,
    start,
    stop,
    pickEnvelope,
  }
}

export { pickEnvelope }

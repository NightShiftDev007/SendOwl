/**
 * SSE 订阅封装
 * - subscribeTask(taskId): /api/tasks/:id/events
 * - subscribeDecision(decisionId): /api/decision/:id/events
 * - subscribeStream(url, handlers, eventNames): 通用流
 *
 * 重连靠 EventSource 自动重连；onOpen 时可再拉 status 快照补齐。
 */

function buildUrl(path) {
  const base = import.meta.env.VITE_API_BASE_URL || ''
  if (!base) return path
  return `${String(base).replace(/\/$/, '')}${path}`
}

/**
 * @param {string} url
 * @param {{ onEvent?: Function, onDone?: Function, onError?: Function, onOpen?: Function }} handlers
 * @param {string[]} [eventNames=['progress']] 业务进度事件名列表
 * @returns {{ close: Function, es: EventSource }}
 */
export function subscribeStream(url, handlers = {}, eventNames = ['progress']) {
  const { onEvent, onDone, onError, onOpen } = handlers
  let closed = false
  let es = null
  let fallbackNotified = false
  const names = Array.isArray(eventNames) && eventNames.length ? eventNames : ['progress']

  const open = () => {
    if (closed) return
    es = new EventSource(url)

    es.onopen = () => {
      fallbackNotified = false
      try {
        onOpen?.()
      } catch (_) {
        /* ignore */
      }
    }

    for (const name of names) {
      es.addEventListener(name, (ev) => {
        try {
          const data = JSON.parse(ev.data)
          onEvent?.(data, name)
        } catch (e) {
          onError?.(e)
        }
      })
    }

    es.addEventListener('done', (ev) => {
      let data = null
      try {
        data = JSON.parse(ev.data)
      } catch (_) {
        data = { raw: ev.data }
      }
      try {
        // 终态只走 onDone，避免与 progress 重复处理
        onDone?.(data)
      } finally {
        close()
      }
    })

    // 业务失败帧（勿与原生 connection error 混淆）
    es.addEventListener('task_error', (ev) => {
      try {
        const data = JSON.parse(ev.data)
        const retryable =
          data?.retryable === true ||
          String(data?.error || '') === 'task_not_found' ||
          String(data?.status || '') === 'pending'
        onError?.(data)
        // 可重试错误：不 onDone、不主动 close（生成器结束后 EventSource CLOSED → 走降级）
        if (retryable) return
        if (String(data?.status || '') === 'failed') {
          onDone?.(data)
          close()
        }
      } catch (e) {
        onError?.(e)
      }
    })

    // 兼容旧 event: error 业务帧
    es.addEventListener('error', (ev) => {
      if (!(ev instanceof MessageEvent) || !ev.data) return
      try {
        const data = JSON.parse(ev.data)
        const retryable =
          data?.retryable === true ||
          String(data?.error || '') === 'task_not_found' ||
          String(data?.status || '') === 'pending'
        onError?.(data)
        if (retryable) return
        if (String(data?.status || '') === 'failed') {
          onDone?.(data)
          close()
        }
      } catch (_) {
        /* ignore parse of native error Event */
      }
    })

    es.onerror = () => {
      if (closed) return
      // 重连中（CONNECTING）不降级；仅彻底关闭时通知一次
      if (es && es.readyState === EventSource.CLOSED && !fallbackNotified) {
        fallbackNotified = true
        onError?.(new Error('sse_closed'))
      }
    }
  }

  const close = () => {
    closed = true
    if (es) {
      try {
        es.close()
      } catch (_) {
        /* ignore */
      }
      es = null
    }
  }

  open()
  return { close, get es() { return es } }
}

/** @deprecated 内部兼容：等同 subscribeStream */
function subscribeSse(url, handlers = {}) {
  return subscribeStream(url, handlers, ['progress'])
}

/** 订阅 TaskManager 任务进度 */
export function subscribeTask(taskId, handlers = {}) {
  if (!taskId) throw new Error('缺少 task_id')
  const url = buildUrl(`/api/tasks/${encodeURIComponent(taskId)}/events`)
  return subscribeStream(url, handlers, ['progress'])
}

/** 订阅 Decision 推演进度 */
export function subscribeDecision(decisionId, handlers = {}) {
  if (!decisionId) throw new Error('缺少 decision_id')
  const url = buildUrl(`/api/decision/${encodeURIComponent(decisionId)}/events`)
  return subscribeStream(url, handlers, ['progress'])
}

/** Step2 prepare 预览（profiles + config）；自动把 dec_* 解析为 sim_* */
export function subscribePreparePreview(simOrDecId, handlers = {}, platform = 'reddit') {
  if (!simOrDecId) throw new Error('缺少 simulation_id')

  let closed = false
  let inner = null

  const close = () => {
    closed = true
    if (inner) {
      try {
        inner.close()
      } catch (_) {
        /* ignore */
      }
      inner = null
    }
  }

  ;(async () => {
    try {
      const { resolveSimContext } = await import('./simulation')
      const { simId } = await resolveSimContext(simOrDecId)
      if (closed) return
      if (!simId) {
        handlers.onError?.(new Error('无法解析 simulation_id'))
        return
      }
      const q = platform ? `?platform=${encodeURIComponent(platform)}` : ''
      const url = buildUrl(
        `/api/simulation/${encodeURIComponent(simId)}/prepare/preview/events${q}`,
      )
      const stream = subscribeStream(url, handlers, ['preview'])
      if (closed) {
        stream.close()
        return
      }
      inner = stream
    } catch (e) {
      if (!closed) handlers.onError?.(e)
    }
  })()

  return {
    close,
    get es() {
      return inner?.es ?? null
    },
  }
}

/** Step3 动作增量 */
export function subscribeSimulationActions(simId, handlers = {}, limit = 200) {
  if (!simId) throw new Error('缺少 simulation_id')
  const url = buildUrl(
    `/api/simulation/${encodeURIComponent(simId)}/actions/events?limit=${encodeURIComponent(limit)}`,
  )
  return subscribeStream(url, handlers, ['actions'])
}

/** Step4 报告日志增量；自动把 dec_* 解析为 report_* */
export function subscribeReportLogs(reportId, handlers = {}, opts = {}) {
  if (!reportId) throw new Error('缺少 report_id')

  let closed = false
  let inner = null

  const close = () => {
    closed = true
    if (inner) {
      try {
        inner.close()
      } catch (_) {
        /* ignore */
      }
      inner = null
    }
  }

  ;(async () => {
    try {
      const { resolveReportId } = await import('./report')
      let rid = String(reportId).startsWith('report_') ? reportId : null
      if (!rid) {
        // 报告刚生成时可能尚未落盘：短重试解析
        for (let i = 0; i < 8; i++) {
          if (closed) return
          rid = await resolveReportId(reportId)
          if (rid && String(rid).startsWith('report_')) break
          await new Promise((r) => setTimeout(r, 1500))
        }
      }
      if (closed) return

      // 仍解析不到：走 onError 降级轮询，勿合成 completed（避免错过后续日志）
      if (!rid || !String(rid).startsWith('report_')) {
        handlers.onError?.(new Error('report_not_ready'))
        return
      }

      const agentFrom = opts.agentFrom ?? opts.agent_from ?? 0
      const consoleFrom = opts.consoleFrom ?? opts.console_from ?? 0
      const url = buildUrl(
        `/api/report/${encodeURIComponent(rid)}/logs/events?agent_from=${encodeURIComponent(agentFrom)}&console_from=${encodeURIComponent(consoleFrom)}`,
      )
      const stream = subscribeStream(url, handlers, ['logs'])
      if (closed) {
        stream.close()
        return
      }
      inner = stream
    } catch (e) {
      if (!closed) handlers.onError?.(e)
    }
  })()

  return {
    close,
    get es() {
      return inner?.es ?? null
    },
  }
}

export default {
  subscribeStream,
  subscribeTask,
  subscribeDecision,
  subscribePreparePreview,
  subscribeSimulationActions,
  subscribeReportLogs,
}

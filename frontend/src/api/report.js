/**
 * 报告执行面 API → /api/report/*
 * 路由参数多为 decisionId，内部解析为 sim_id
 */
import service, { requestWithRetry } from './index'
import { resolveSimContext } from './simulation'
import { getDecisionCompare, getDecisionStatus } from './decision'

export const generateReport = async (data = {}) => {
  const { simId, decisionId, detail } = await resolveSimContext(data)
  const scenarioCount =
    detail?.scenarios?.length || detail?.matrix?.length || 1

  // N>1：同时触发生成叙事报告，并保留对比报告能力
  if (scenarioCount > 1 && decisionId) {
    // 异步启动首个 sim 的叙事报告（不阻塞）
    requestWithRetry(
      () =>
        service.post('/api/report/generate', {
          simulation_id: simId,
          force_regenerate: data.force_regenerate ?? false,
        }),
      2,
      1000,
    ).catch(() => {})

    const res = await getDecisionCompare(decisionId, { report: true })
    const payload = res.data || {}
    return {
      success: true,
      data: {
        report_id: decisionId,
        simulation_id: decisionId,
        decision_id: decisionId,
        sim_id: simId,
        status: 'completed',
        mode: 'compare',
        markdown: payload.report?.markdown || payload.narrative || '',
        title: payload.title || payload.decision?.title,
        compare: payload,
      },
    }
  }

  return requestWithRetry(
    () =>
      service.post('/api/report/generate', {
        simulation_id: simId,
        force_regenerate: data.force_regenerate ?? false,
        simulation_requirement: data.simulation_requirement,
      }),
    3,
    1000,
  )
}

export const getReportStatus = async (reportId) => {
  // reportId 可能是 report_* 或 decisionId
  if (String(reportId || '').startsWith('report_')) {
    return service.get('/api/report/generate/status', {
      params: { report_id: reportId },
    })
  }
  try {
    const { simId } = await resolveSimContext(reportId)
    const bySim = await service.get(`/api/report/by-simulation/${simId}`)
    const rid = bySim.data?.report_id || bySim.data?.id
    if (rid) {
      return service.get('/api/report/generate/status', {
        params: { report_id: rid },
      })
    }
  } catch (_) {
    /* fallthrough */
  }
  return {
    success: true,
    data: { report_id: reportId, status: 'pending' },
  }
}

export const getAgentLog = async (reportId, fromLine = 0) => {
  let rid = reportId
  if (!String(reportId || '').startsWith('report_')) {
    try {
      const { simId } = await resolveSimContext(reportId)
      const bySim = await service.get(`/api/report/by-simulation/${simId}`)
      rid = bySim.data?.report_id || bySim.data?.id || reportId
    } catch (_) {
      /* keep */
    }
  }
  return service.get(`/api/report/${rid}/agent-log`, {
    params: { from_line: fromLine },
  })
}

export const getConsoleLog = async (reportId, fromLine = 0) => {
  let rid = reportId
  if (!String(reportId || '').startsWith('report_')) {
    try {
      const { simId } = await resolveSimContext(reportId)
      const bySim = await service.get(`/api/report/by-simulation/${simId}`)
      rid = bySim.data?.report_id || bySim.data?.id || reportId
    } catch (_) {
      /* keep */
    }
  }
  return service.get(`/api/report/${rid}/console-log`, {
    params: { from_line: fromLine },
  })
}

export const getReport = async (reportId) => {
  if (String(reportId || '').startsWith('report_')) {
    return service.get(`/api/report/${reportId}`)
  }
  // decisionId：优先叙事报告，否则对比报告
  try {
    const { simId, decisionId } = await resolveSimContext(reportId)
    try {
      const bySim = await service.get(`/api/report/by-simulation/${simId}`)
      if (bySim.data) {
        return {
          success: true,
          data: {
            ...bySim.data,
            simulation_id: decisionId || reportId,
            decision_id: decisionId || reportId,
            sim_id: simId,
          },
        }
      }
    } catch (_) {
      /* fallthrough to compare */
    }
    if (decisionId) {
      const res = await getDecisionCompare(decisionId, { report: true })
      const payload = res.data || {}
      const markdown =
        payload.report?.markdown || payload.narrative || payload.markdown || ''
      return {
        success: true,
        data: {
          report_id: decisionId,
          simulation_id: decisionId,
          decision_id: decisionId,
          sim_id: simId,
          markdown,
          content: markdown,
          status: 'completed',
          mode: 'compare',
        },
      }
    }
  } catch (e) {
    return { success: false, error: e.message }
  }
  return service.get(`/api/report/${reportId}`)
}

export const chatWithReport = async (data = {}) => {
  try {
    const { simId } = await resolveSimContext(data)
    return requestWithRetry(
      () =>
        service.post('/api/report/chat', {
          ...data,
          simulation_id: simId,
        }),
      3,
      1000,
    )
  } catch (e) {
    // 兜底：尝试用决策下的 run 采访
    const decisionId = data.simulation_id || data.report_id || data.decision_id
    let runId = data.run_id
    if (!runId && decisionId) {
      try {
        const st = await getDecisionStatus(decisionId)
        for (const sc of st.data?.matrix || []) {
          const hit = (sc.runs || []).find((r) => r.run_id)
          if (hit) {
            runId = hit.run_id
            break
          }
        }
      } catch (_) {
        /* ignore */
      }
    }
    if (!runId) {
      return {
        success: true,
        data: {
          response: '当前没有可对话的模拟环境。请先完成推演。',
          answer: '当前没有可对话的模拟环境。请先完成推演。',
        },
      }
    }
    const { interviewRun } = await import('./decision')
    const res = await interviewRun(runId, {
      agent_id: data.agent_id ?? 0,
      prompt: data.message || data.prompt,
    })
    const payload = res.data || {}
    const answer =
      payload.reply || payload.response || payload.answer || payload.message || ''
    return { success: true, data: { ...payload, response: answer, answer } }
  }
}

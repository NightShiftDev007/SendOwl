import { getDecisionCompare, interviewRun } from './decision'

export const generateReport = async (data) => {
  const id = data.simulation_id || data.decision_id
  return getDecisionCompare(id, { report: true })
}

export const getReportStatus = async (reportId) => ({
  success: true,
  data: { report_id: reportId, status: 'completed' },
})

export const getAgentLog = async () => ({ success: true, data: { lines: [], next_line: 0 } })
export const getConsoleLog = async () => ({ success: true, data: { lines: [], next_line: 0 } })

export const getReport = async (reportId) => {
  const res = await getDecisionCompare(reportId, { report: true })
  const payload = res.data || res
  return {
    success: true,
    data: {
      report_id: reportId,
      markdown: payload.report?.markdown || payload.narrative || '',
      title: payload.title,
      status: 'completed',
    },
  }
}

export const chatWithReport = async (data) => {
  const runId = data.run_id || data.simulation_id
  if (!runId) {
    return {
      success: true,
      data: { reply: '请先选择一个 Run 再采访 Agent。' },
    }
  }
  return interviewRun(runId, {
    agent_id: data.agent_id,
    prompt: data.message || data.prompt,
  })
}

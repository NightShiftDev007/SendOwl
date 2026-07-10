import axios from 'axios'

const http = axios.create({
  baseURL: '',
  timeout: 120000,
})

export async function listOntologies() {
  const { data } = await http.get('/api/ontology/list')
  return data
}

export async function createOntology(formData) {
  const { data } = await http.post('/api/ontology/create', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return data
}

export async function getOntology(id) {
  const { data } = await http.get(`/api/ontology/${id}`)
  return data
}

export async function buildOntology(id, body = {}) {
  const { data } = await http.post(`/api/ontology/${id}/build`, body)
  return data
}

export async function buildStatus(id, taskId) {
  const { data } = await http.get(`/api/ontology/${id}/build/status`, {
    params: { task_id: taskId },
  })
  return data
}

export async function snapshotOntology(id) {
  const { data } = await http.post(`/api/ontology/${id}/snapshot`)
  return data
}

export async function getOntologyGraph(id) {
  const { data } = await http.get(`/api/ontology/${id}/graph`)
  return data
}

export async function listDecisions() {
  const { data } = await http.get('/api/decision/list')
  return data
}

export async function createDecision(body) {
  const { data } = await http.post('/api/decision/create', body)
  return data
}

export async function getDecision(id) {
  const { data } = await http.get(`/api/decision/${id}`)
  return data
}

export async function startDecision(id) {
  const { data } = await http.post(`/api/decision/${id}/start`)
  return data
}

export async function decisionStatus(id) {
  const { data } = await http.get(`/api/decision/${id}/status`)
  return data
}

export async function decisionCompare(id, params = {}) {
  const { data } = await http.get(`/api/decision/${id}/compare`, { params })
  return data
}

export async function health() {
  const { data } = await http.get('/health')
  return data
}

/**
 * 临时存储待上传的文件和需求
 * 用于首页点击启动引擎后立即跳转，在Process页面再进行API调用
 */
import { reactive } from 'vue'

const state = reactive({
  files: [],
  simulationRequirement: '',
  template: '',
  isPending: false
})

/**
 * @param {File[]} files
 * @param {string} requirement
 * @param {{ template?: string }} [options]
 */
export function setPendingUpload(files, requirement, options = {}) {
  state.files = files
  state.simulationRequirement = requirement
  state.template = (options.template || '').trim()
  state.isPending = true
}

export function getPendingUpload() {
  return {
    files: state.files,
    simulationRequirement: state.simulationRequirement,
    template: state.template,
    isPending: state.isPending
  }
}

export function clearPendingUpload() {
  state.files = []
  state.simulationRequirement = ''
  state.template = ''
  state.isPending = false
}

export default state

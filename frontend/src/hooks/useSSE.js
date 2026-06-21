import { ref, onUnmounted } from 'vue'

/**
 * 封装 EventSource，支持多事件类型监听
 * @param {string} url - SSE 端点 URL
 * @returns {{ events, status, close }}
 */
export function useSSE(url) {
  // 所有收到的事件，格式：{ type, data, timestamp }
  const events = ref([])
  // 'idle' | 'connecting' | 'open' | 'closed' | 'error'
  const status = ref('idle')

  let es = null

  function connect(urlOverride) {
    if (es) close()

    status.value = 'connecting'
    es = new EventSource(urlOverride || url)

    es.onopen = () => {
      status.value = 'open'
    }

    es.onerror = () => {
      // EventSource 内置重试逻辑，这里只记录状态
      // 如果连接已关闭（readyState=2），标记为 error
      if (es && es.readyState === EventSource.CLOSED) {
        status.value = 'error'
      }
    }

    // step 事件：AI 侧用 event: step + data.step 子类型分发中间结果
    es.addEventListener('step', (e) => {
      let parsed = null
      try { parsed = JSON.parse(e.data) } catch { parsed = e.data }
      const subtype = parsed?.step
      if (subtype) {
        events.value.push({ type: subtype, data: parsed?.data ?? parsed, timestamp: Date.now() })
      }
    })

    // result / error / heartbeat
    es.addEventListener('result', (e) => {
      let data = null
      try { data = JSON.parse(e.data) } catch { data = e.data }
      events.value.push({ type: 'result', data, timestamp: Date.now() })
      status.value = 'closed'
      close()
    })

    es.addEventListener('error', (e) => {
      let data = null
      try { data = JSON.parse(e.data) } catch { data = e.data }
      events.value.push({ type: 'error', data, timestamp: Date.now() })
      status.value = 'error'
      close()
    })

    // 管理员强制释放会话（UC-11）
    es.addEventListener('force_close', (e) => {
      let data = null
      try { data = JSON.parse(e.data) } catch { data = e.data }
      events.value.push({ type: 'force_close', data, timestamp: Date.now() })
      status.value = 'closed'
      close()
    })

    // heartbeat 不入列表
  }

  function close() {
    if (es) {
      es.close()
      es = null
    }
    if (status.value !== 'error') {
      status.value = 'closed'
    }
  }

  // 组件卸载时自动关闭，防止连接泄漏
  onUnmounted(close)

  return { events, status, connect, close }
}

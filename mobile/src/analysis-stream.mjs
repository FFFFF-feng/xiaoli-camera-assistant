/** Consume the same upload response incrementally; never resubmit on stream failure. */
export async function readAnalysis(response, onEvent) {
  const invalid = () => new Error('分析响应格式不正确，请稍后重试。');
  const complete = value => {
    if (!value || typeof value.request_id !== 'string' || !value.result?.scene || !value.result?.recommendation) throw invalid();
    return value;
  };
  if (!response.headers.get('content-type')?.includes('application/x-ndjson')) {
    return complete(await response.json());
  }
  if (!response.body) throw invalid();
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let pending = '';
  let final = null;
  function line(value) {
    if (!value.trim()) return;
    let event;
    try { event = JSON.parse(value); } catch { throw invalid(); }
    if (!event || typeof event.type !== 'string') throw invalid();
    if (event.type === 'error') throw new Error(typeof event.detail === 'string' ? event.detail : '分析未完成，请稍后重试。');
    if (event.type === 'result') {
      const { type, elapsed_seconds, ...envelope } = event;
      final = complete(envelope);
    }
    onEvent(event);
  }
  try {
    while (true) {
      const { done, value } = await reader.read();
      pending += done ? decoder.decode() : decoder.decode(value, { stream: true });
      if (pending.length > 2_000_000) throw invalid();
      let newline;
      while ((newline = pending.indexOf('\n')) >= 0) {
        line(pending.slice(0, newline));
        pending = pending.slice(newline + 1);
        if (final) return final;
      }
      if (done) { line(pending); break; }
    }
    if (!final) throw new Error('分析连接已结束，完整方案未完成。请稍后重试。');
    return final;
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}

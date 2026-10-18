// Wall-clock time grows while the request is waiting. Event timestamps are
// fixed service-side observations and must never be used as live durations.
export function liveElapsed(startedAt,now=performance.now()) {
  if(!Number.isFinite(startedAt)||!Number.isFinite(now)||now<startedAt)return 0;
  return (now-startedAt)/1000;
}

export function fixedEventSeconds(value) {
  return Number.isFinite(value)&&value>=0?value:0;
}

export function statusSeconds(elapsed,statusStartedAt) {
  if(!Number.isFinite(elapsed)||!Number.isFinite(statusStartedAt))return 0;
  return Math.max(0,elapsed-statusStartedAt);
}

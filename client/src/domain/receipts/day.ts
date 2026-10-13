export function receiptDayClock(value:{server_time:string;expires_at:string},receivedAt=Date.now()) {
  const server=Date.parse(value.server_time); const end=Date.parse(value.expires_at)
  const valid=Number.isFinite(server)&&Number.isFinite(end)&&end>server
  const remaining=(now:number)=>valid?Math.max(0,end-server-(now-receivedAt)):0
  return {expired:(now=Date.now())=>remaining(now)<=0,delay:(now=Date.now())=>remaining(now)}
}

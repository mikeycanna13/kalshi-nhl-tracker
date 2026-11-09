/**
 * Free-tier scheduled trigger for NHL/Kalshi RESEARCH ONLY.
 *
 * Deploy to Cloudflare Workers Free, set secret GITHUB_RESEARCH_TOKEN (fine-
 * grained access to this single repo, Contents: read/write). This Worker only
 * creates uniquely named scheduler/triggers/*.json on the research branch.
 * No Railway service, no sportsbooks, no trading/order API and no writes to main.
 *
 * Wrangler example: npx wrangler deploy --config scheduler/wrangler.toml
 */
export const REPO = "mikeycanna13/kalshi-nhl-tracker";
export const BRANCH = "research/nhl-model-benchmarks";
const ET = "America/New_York";
const NHL = "https://api-web.nhle.com/v1/score/";
const GH = "https://api.github.com/repos/" + REPO + "/contents/";

export function easternParts(value) {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: ET, year:"numeric", month:"2-digit", day:"2-digit",
    hour:"2-digit",minute:"2-digit", hourCycle:"h23"
  }).formatToParts(new Date(value));
  const obj = Object.fromEntries(parts.map(p=>[p.type,p.value]));
  const date = `${obj.year}-${obj.month}-${obj.day}`;
  return {date, hour:Number(obj.hour),minute:Number(obj.minute)};
}

function plusDay(iso) {
  const t = new Date(iso + "T12:00:00Z").getTime();
  return new Date(t + 86400000).toISOString().slice(0,10);
}

export function dueTriggers(now, schedules) {
  const current=new Date(now);
  if (!Number.isFinite(current.getTime())) throw new Error("Invalid UTC date");
  const local=easternParts(current);
  const today=local.date, tomorrow=plusDay(today);
  const byId=new Map();
  for (const [day,games] of Object.entries(schedules)) {
    if (day !== today && day !== tomorrow) continue;
    for (const g of games||[]) {
      if (!["FUT","PRE"].includes(g.gameState) || ![2,3].includes(Number(g.gameType))) continue;
      const start=Date.parse(g.startTimeUTC);
      const id=Number(g.id);
      if (!Number.isFinite(start) || !Number.isInteger(id) || id<=0 ||
          start<=current.getTime() || easternParts(start).date !== day) continue;
      byId.set(id,{id,date:day,start});
    }
  }
  const groups=new Map();
  function add(game,window,bucket) {
    const path=`scheduler/triggers/${game.date}/${window}_${bucket}.json`;
    if (!groups.has(path)) groups.set(path,{path,window,bucket,date:game.date,game_ids:[]});
    groups.get(path).game_ids.push(game.id);
  }
  for (const g of byId.values()) {
    if (g.date===today && local.hour===10 && local.minute<25) add(g,"morning","1000ET");
    for (const [window,minutes] of [["two_hours",120],["fifteen_minutes",15]]) {
      const cutoff=g.start - minutes*60000;
      if (Math.abs(current.getTime()-cutoff)<=8*60000) {
        const slot=new Date(Math.floor(cutoff/900000)*900000).toISOString()
          .replaceAll("-","").replaceAll(":","").slice(0,13)+"Z";
        add(g,window,slot);
      }
    }
  }
  return [...groups.values()].sort((a,b)=>a.path.localeCompare(b.path)).map(x=>({
    path:x.path,
    data:{
      schema:"nhl_scheduler_trigger_v1",
      target_date:x.date,window:x.window,bucket:x.bucket,
      game_ids:[...new Set(x.game_ids)].sort((a,b)=>a-b),
      issued_at_utc:current.toISOString(),research_branch:BRANCH,
      note:"research_only_no_trading"
    }
  }));
}

async function getJson(url,fetcher) {
  const response=await fetcher(url,{
    headers:{"Accept":"application/json","User-Agent":"NHL-Research-Free-Scheduler"}
  });
  if (!response.ok) throw new Error(`NHL API HTTP ${response.status}`);
  return response.json();
}

export async function createTrigger(trigger,token,fetcher=fetch) {
  if (!token) throw new Error("GITHUB_RESEARCH_TOKEN must be configured as a secret");
  if (!/^scheduler\/triggers\/\d{4}-\d{2}-\d{2}\/(morning|two_hours|fifteen_minutes)_[A-Za-z0-9T_-]+\.json$/.test(trigger.path))
    throw new Error("Refusing unexpected trigger path");
  const url=GH+trigger.path.split("/").map(encodeURIComponent).join("/");
  const headers={
    "Authorization":"Bearer "+token,
    "Accept":"application/vnd.github+json",
    "X-GitHub-Api-Version":"2022-11-28",
    "User-Agent":"NHL-Research-Free-Scheduler"
  };
  async function exists() {
    const response=await fetcher(url+"?ref="+encodeURIComponent(BRANCH),{headers});
    if (response.status===404) return false;
    if (!response.ok) throw new Error(`GitHub read HTTP ${response.status}`);
    const body=await response.json();
    if (!body.sha || body.type!=="file") throw new Error("Unexpected GitHub trigger response");
    return true;
  }
  if (await exists()) return "already_exists";
  const payload={
    message:"research: scheduled NHL pregame capture "+trigger.path,
    branch:BRANCH,
    content:btoa(JSON.stringify(trigger.data))
  };
  const response=await fetcher(url,{
    method:"PUT",headers:{...headers,"Content-Type":"application/json"},
    body:JSON.stringify(payload)
  });
  if (response.status===201) {
    const body=await response.json();
    if (body.commit?.sha) return "created";
    throw new Error("Missing GitHub commit hash");
  }
  if ([409,422].includes(response.status) && await exists()) return "already_exists";
  throw new Error(`GitHub write HTTP ${response.status}`);
}

export async function run(now,env,fetcher=fetch) {
  const local=easternParts(now);
  const tomorrow=plusDay(local.date);
  const dates=[local.date,tomorrow];
  const results=await Promise.all(dates.map(d=>getJson(NHL+d,fetcher)));
  const schedules=Object.fromEntries(results.map((r,i)=>[dates[i],r.games||[]]));
  const triggers=dueTriggers(now,schedules);
  const statuses=[];
  // Dry runs never need a GitHub secret and never write to GitHub.
  for (const trigger of triggers) {
    const status=env?.ENABLE_TRIGGER_WRITES === "true"
      ? await createTrigger(trigger,env.GITHUB_RESEARCH_TOKEN,fetcher)
      : "dry_run";
    statuses.push({path:trigger.path,status});
  }
  return {at_utc:new Date(now).toISOString(),games:results.reduce((n,r)=>n+(r.games||[]).length,0),
          mode:env?.ENABLE_TRIGGER_WRITES==="true"?"execute":"dry_run",
          due:triggers.length,statuses};
}

export default {
  async scheduled(_controller,env,ctx) {
    ctx.waitUntil(run(new Date(),env).then(result=>{
      console.log(JSON.stringify(result));
    }).catch(error=>{
      console.error("NHL research scheduler failed:",error.message);
      throw error;
    }));
  }
};

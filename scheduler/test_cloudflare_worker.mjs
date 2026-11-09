import test from "node:test";
import assert from "node:assert/strict";
import {dueTriggers,easternParts,run,createTrigger,BRANCH} from "./cloudflare_worker.mjs";

const start="2026-11-11T00:00:00Z"; // Nov 10 at 7 PM New York
const game=(id=123,s=start)=>({id,gameType:2,gameState:"FUT",startTimeUTC:s});
const games={"2026-11-10":[game()],"2026-11-11":[]};

test("New York dates correctly cross UTC midnight",()=>{
  assert.equal(easternParts(start).date,"2026-11-10");
});
test("10 AM ET daily morning trigger",()=>{
  const rows=dueTriggers("2026-11-10T15:05:00Z",games);
  assert.equal(rows.length,1);
  assert.equal(rows[0].data.window,"morning");
  assert.equal(rows[0].data.target_date,"2026-11-10");
});
test("correct two hour pregame trigger",()=>{
  const rows=dueTriggers("2026-11-10T22:00:00Z",games);
  assert.equal(rows.length,1);
  assert.equal(rows[0].data.window,"two_hours");
});
test("correct 15 minute pregame trigger",()=>{
  const rows=dueTriggers("2026-11-10T23:45:00Z",games);
  assert.equal(rows.length,1);
  assert.equal(rows[0].data.window,"fifteen_minutes");
});
test("duplicate simultaneous games collapse to one trigger",()=>{
  const rows=dueTriggers("2026-11-10T23:45:00Z",{
    "2026-11-10":[game(20),game(10)]
  });
  assert.deepEqual(rows[0].data.game_ids,[10,20]);
});
test("no trigger after puckdrop",()=>{
  assert.equal(dueTriggers("2026-11-11T00:01:00Z",games).length,0);
});
test("ignore games already live",()=>{
  assert.equal(dueTriggers("2026-11-10T15:05:00Z",{"2026-11-10":[{...game(),gameState:"LIVE"}]}).length,0);
});
test("summer daylight saving 10 AM still works",()=>{
  const x=dueTriggers("2026-07-10T14:05:00Z",{
    "2026-07-10":[game(2,"2026-07-10T23:00:00Z")]
  });
  assert.equal(x[0].data.window,"morning");
});
test("run dry makes only public NHL fetches, never GitHub writes",async()=>{
  const seen=[];
  const fake=async url=>{
    seen.push(url);
    if (!url.includes("api-web.nhle.com")) throw new Error("Unexpected external request");
    return {ok:true,json:async()=>({games:[game()]})};
  };
  const output=await run("2026-11-10T15:05:00Z",{},fake);
  assert.equal(output.mode,"dry_run");
  assert.equal(output.statuses[0].status,"dry_run");
  assert.equal(seen.length,2);
});
test("create trigger is create-only, branch restricted",async()=>{
  const trigger=dueTriggers("2026-11-10T15:05:00Z",games)[0];
  const seen=[];
  const fake=async(url,options)=>{
    seen.push({url,options});
    if (options.method==="PUT") return {status:201,json:async()=>({commit:{sha:"test_commit"}})};
    return {status:404};
  };
  assert.equal(await createTrigger(trigger,"TEST_SECRET",fake),"created");
  const push=seen.find(x=>x.options.method==="PUT");
  assert.equal(JSON.parse(push.options.body).branch,BRANCH);
  assert.equal(JSON.parse(atob(JSON.parse(push.options.body).content)).target_date,"2026-11-10");
  assert.ok(!JSON.stringify(push.options.body).includes("TEST_SECRET"));
});
test("do not rewrite existing trigger",async()=>{
  const trigger=dueTriggers("2026-11-10T15:05:00Z",games)[0];
  let puts=0;
  const fake=async(_url,options)=>{
    if (options.method==="PUT") puts++;
    return {status:200,ok:true,json:async()=>({sha:"exists",type:"file"})};
  };
  assert.equal(await createTrigger(trigger,"TEST_SECRET",fake),"already_exists");
  assert.equal(puts,0);
});
test("reject writes without token",async()=>{
  const trigger=dueTriggers("2026-11-10T15:05:00Z",games)[0];
  await assert.rejects(()=>createTrigger(trigger,""),/GITHUB_RESEARCH_TOKEN/);
});

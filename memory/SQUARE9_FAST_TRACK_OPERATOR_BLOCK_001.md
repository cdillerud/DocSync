# Square9 Fast-Track — Operator Block #001

Run on the prod VM. Bare lines only. **Do not paste any line
that starts with three backticks.** No markdown fences in the
operator copy.

## Step 1 — pull latest, rebuild frontend, restart backend

Pull the latest hub commit into the prod VM (operator's normal
deployment path), then:

    cd /opt/gpi-hub

    docker compose build frontend

    docker compose up -d frontend backend

    docker compose ps

Expected: frontend + backend both `Up`. No errors in
`docker compose logs --tail 50 frontend backend 2>&1 | head -n 80`.

## Step 2 — verify SearchPage live

    curl -s -o /tmp/sp.out -w "HTTP %{http_code}\n" http://localhost:3000/search

    head -c 800 /tmp/sp.out

    curl -s "http://localhost:8001/api/documents/search?q=invoice&limit=3" | python3 -c "import sys,json;d=json.load(sys.stdin);print('total:',d.get('total'),'method:',d.get('search_method'),'first_doc:',d.get('results',[{}])[0].get('doc_id') if d.get('results') else None)"

Expected: HTTP 200 on the page; backend returns
`total >= 1` and `search_method = "text_index"` on the curl.

## Step 3 — G2 sales mailbox config (CONFIG ONLY, NO CODE)

Append (or update) the two env vars to `backend/.env` on the
prod VM. **Do not delete or modify any existing key.** Preserve
`MONGO_URL`, `DB_NAME`, and any other protected variable
exactly as-is.

    grep -E "^(SALES_EMAIL_POLLING_ENABLED|SALES_EMAIL_POLLING_USER)=" backend/.env

If those rows already exist, **edit them in place**. If they
do not exist, append them:

    cat >> backend/.env <<EOF
    SALES_EMAIL_POLLING_ENABLED=true
    SALES_EMAIL_POLLING_USER=hub-sales-intake@gamerpackaging.com
    EOF

Verify the file is shaped correctly (no duplicates, no stray
blank lines mid-file):

    grep -E "^(SALES_EMAIL_POLLING_ENABLED|SALES_EMAIL_POLLING_USER|EMAIL_POLLING_ENABLED)=" backend/.env

If `EMAIL_POLLING_ENABLED` is currently `false` and you intend
the unified poller to run, set it `true` the same way. If you
want only the sales-side path active for now, leave
`EMAIL_POLLING_ENABLED` as it is — the sales worker is gated by
`SALES_EMAIL_POLLING_ENABLED` independently.

Restart backend so the new env vars take effect:

    docker compose up -d backend

    sleep 5

    docker compose exec -T backend printenv SALES_EMAIL_POLLING_ENABLED SALES_EMAIL_POLLING_USER

Expected: `true` and `hub-sales-intake@gamerpackaging.com`
(or whatever the real address is).

## Step 4 — G2 prove ingest (one cycle)

Trigger one sales-poll cycle. The unified poller runs on its
own schedule, but we'll force one cycle and inspect the result.

    docker compose exec -T -w /app backend python -u -c "import asyncio; from services.email_polling_service import run_sales_email_poll; print(asyncio.run(run_sales_email_poll()))"

Expected output is a dict with `mailbox`, `run_id`, and
counters. If you see `{"skipped": True, "reason": "SALES_EMAIL_POLLING_USER not configured"}`, the env var did not load — restart again with `docker compose down backend && docker compose up -d backend`.

Inspect intake history for the sales mailbox:

    docker compose exec -T backend python -u -c "import asyncio,os,json; from motor.motor_asyncio import AsyncIOMotorClient; exec('async def m():\n db=AsyncIOMotorClient(os.environ[\"MONGO_URL\"])[os.environ[\"DB_NAME\"]]\n total=await db.mail_intake_log.count_documents({})\n sales=await db.mail_intake_log.count_documents({\"mailbox\":{\"$regex\":\"sales\",\"$options\":\"i\"}})\n runs=0\n if \"sales_mail_poll_runs\" in await db.list_collection_names():\n  runs=await db.sales_mail_poll_runs.count_documents({})\n  last=await db.sales_mail_poll_runs.find_one({}, sort=[(\"started_at\",-1)])\n  print(json.dumps({\"mail_intake_total\":total,\"mail_intake_sales\":sales,\"sales_runs\":runs,\"last_run\":last},default=str,indent=2))\n else:\n  print(json.dumps({\"mail_intake_total\":total,\"mail_intake_sales\":sales,\"sales_runs\":0}))'); asyncio.run(m())"

## Step 5 — C1 archive reach (read-only)

    curl -s http://localhost:8001/api/square9/migration-status | python3 -c "import sys,json;d=json.load(sys.stdin);print(json.dumps(d,indent=2))"

    docker compose exec -T backend python -u -c "import asyncio,os,json; from motor.motor_asyncio import AsyncIOMotorClient; exec('async def m():\n db=AsyncIOMotorClient(os.environ[\"MONGO_URL\"])[os.environ[\"DB_NAME\"]]\n total=await db.hub_documents.count_documents({})\n with_sp=await db.hub_documents.count_documents({\"sharepoint_web_url\":{\"\$nin\":[None,\"\"]}})\n with_stage=await db.hub_documents.count_documents({\"square9_stage\":{\"\$exists\":True,\"\$ne\":None}})\n with_archived=await db.hub_documents.count_documents({\"square9_archived_stage\":{\"\$exists\":True,\"\$ne\":None}})\n print(json.dumps({\"hub_documents_total\":total,\"with_sharepoint_url\":with_sp,\"with_square9_stage\":with_stage,\"with_archived_stage\":with_archived}))'); asyncio.run(m())"

Operator one-line answer (after running the above):

> Square9 holds approximately N docs that are not in the hub
> or SharePoint, and routine retrieval need is `<active /
> none / unknown>`.

## Step 6 — C2 mailbox inventory

    docker compose exec -T backend python -u -c "import asyncio,os,json; from motor.motor_asyncio import AsyncIOMotorClient; from datetime import datetime,timezone,timedelta; exec('async def m():\n db=AsyncIOMotorClient(os.environ[\"MONGO_URL\"])[os.environ[\"DB_NAME\"]]\n sources=await db.mailbox_sources.find({},{\"_id\":0,\"mailbox_address\":1,\"category\":1,\"enabled\":1,\"last_polled_at\":1}).to_list(50)\n cutoff=datetime.now(timezone.utc)-timedelta(days=7)\n by_mailbox=await db.mail_intake_log.aggregate([{\"\$match\":{\"created_at\":{\"\$gte\":cutoff}}},{\"\$group\":{\"_id\":\"\$mailbox\",\"count\":{\"\$sum\":1}}}]).to_list(50)\n print(json.dumps({\"mailbox_sources\":sources,\"mail_intake_7d_by_mailbox\":by_mailbox},default=str,indent=2))'); asyncio.run(m())"

Operator one-line answer:

> Warehouse / shipping users currently rely on `<separate
> Square9 inbox / the same hub-ap-intake@ stream / nothing —
> they don't touch a mailbox>`.

## Step 7 — C4 split usage (last 30 days)

    docker compose exec -T backend python -u -c "import asyncio,os,json; from motor.motor_asyncio import AsyncIOMotorClient; from datetime import datetime,timezone,timedelta; exec('async def m():\n db=AsyncIOMotorClient(os.environ[\"MONGO_URL\"])[os.environ[\"DB_NAME\"]]\n cutoff=datetime.now(timezone.utc)-timedelta(days=30)\n total=await db.workflow_events.count_documents({\"event_type\":{\"\$regex\":\"split\",\"\$options\":\"i\"},\"ts\":{\"\$gte\":cutoff}})\n by_type=await db.workflow_events.aggregate([{\"\$match\":{\"event_type\":{\"\$regex\":\"split\",\"\$options\":\"i\"},\"ts\":{\"\$gte\":cutoff}}},{\"\$group\":{\"_id\":\"\$event_type\",\"count\":{\"\$sum\":1}}}]).to_list(50)\n print(json.dumps({\"split_events_30d_total\":total,\"by_event_type\":by_type},default=str,indent=2))'); asyncio.run(m())"

## Step 8 — C5 scanner inflow (read-only + operator)

    docker compose exec -T backend python -u -c "import asyncio,os,json; from motor.motor_asyncio import AsyncIOMotorClient; from datetime import datetime,timezone,timedelta; exec('async def m():\n db=AsyncIOMotorClient(os.environ[\"MONGO_URL\"])[os.environ[\"DB_NAME\"]]\n cutoff=datetime.now(timezone.utc)-timedelta(days=14)\n top=await db.mail_intake_log.aggregate([{\"\$match\":{\"created_at\":{\"\$gte\":cutoff}}},{\"\$group\":{\"_id\":\"\$sender_email\",\"count\":{\"\$sum\":1}}},{\"\$sort\":{\"count\":-1}},{\"\$limit\":40}]).to_list(40)\n print(json.dumps({\"top_senders_14d\":top},default=str,indent=2))'); asyncio.run(m())"

Operator one-line answer:

> Scanner / MFP inflow today: `<None — all email or hub
> upload / Yes — N docs/week from <device or person> /
> Unknown — checking with <team>>`.

## Paste-back (one message)

Send back the output of Steps 2 / 3-verify / 4 / 5 / 6 / 7 / 8
plus the three operator one-line answers (C1, C2, C5). I will
then:

- Mark G2 done if Step 4 shows `mail_intake_sales > 0` or a
  clean `last_run`.
- Final-classify each conditional gate based on Step 5–8.
- Build the next user-visible piece if any conditional flips
  to BUILD-THIS-WEEK.
- Otherwise advance to Wed shadow phase.

Single attempt expected; if a step errors, paste the error and
move on to the next step. No need for a fresh-session restart
unless the SSH session itself drops.

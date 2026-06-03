# Software — Notion & Telegram Integration

The Bottle Feed Logger is firmware-driven (see `firmware/`), but it depends on a Notion integration. This doc is the full setup for the cloud side.

---

## Notion setup (required)

### 1. Create an integration

1. Go to **https://www.notion.so/my-integrations**
2. Click **New integration**
3. Name it something like `Feed Logger`
4. Associate it with your workspace
5. Under **Capabilities**, "Insert content" is enough (the device only creates rows). You can leave read enabled too.
6. Submit, then copy the **Internal Integration Secret** — this is your `NOTION_TOKEN`. It looks like `ntn_xxxxxxxx...` (newer) or `secret_xxxxxxxx...` (older).

> Treat this token like a password. Anyone with it can write to (and depending on capabilities, read) the databases you share with it.

### 2. Create the Feed Log database

In Notion, create a new **database — table** named **Feed Log** with these properties (column names must match `config.h` exactly):

| Property name | Type | Notes |
|---------------|------|-------|
| `Name` | Title | Exists by default; firmware fills it with e.g. "Feed 165 mL" |
| `Start` | Date | **Enable "Include time"** in the property options |
| `End` | Date | Include time |
| `Duration (min)` | Number | Integer minutes |
| `Volume (mL)` | Number | Integer mL |
| `Notes` | Text | Free text |

If you rename any column, update the matching `PROP_*` define in `config.h`.

### 3. Share the database with the integration

This step is the one people forget, and it makes the API return permission errors if skipped.

1. Open the Feed Log database as a **full page**
2. Click the **•••** menu (top-right)
3. Choose **Connections** → **Connect to** → select your `Feed Logger` integration

### 4. Get the database ID

Open the database as a full page and look at the URL:

```
https://www.notion.so/<workspace>/<DATABASE_ID>?v=<view_id>
```

The `DATABASE_ID` is the 32-character hex string before the `?`. Copy it into `config.h` as `NOTION_DB_ID`. (Notion sometimes shows it with dashes; the firmware works with or without them, but the plain 32-char form is safest.)

### 5. Test from your computer first (optional but smart)

Before flashing, confirm your token + database work with a quick `curl`:

```bash
curl -X POST https://api.notion.com/v1/pages \
  -H "Authorization: Bearer $NOTION_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Notion-Version: 2022-06-28" \
  -d '{
    "parent": { "database_id": "'"$NOTION_DB_ID"'" },
    "properties": {
      "Name":           { "title":  [ { "text": { "content": "Test feed" } } ] },
      "Start":          { "date":   { "start": "2026-05-28T02:42:00-04:00" } },
      "End":            { "date":   { "start": "2026-05-28T03:01:00-04:00" } },
      "Duration (min)": { "number": 19 },
      "Volume (mL)":    { "number": 165 }
    }
  }'
```

If a row appears in your database, the cloud side is good and any later problem is on the device. If you get an error, read it — it usually names the exact property that's wrong or tells you the integration lacks access.

### Notion API version

The firmware sends `Notion-Version: 2022-06-28`. This has been stable for a long time, but confirm the current recommended version at **developers.notion.com** and update `NOTION_VERSION` in `config.h` if needed. `[Needs verification]`

---

## Telegram setup (optional)

Only needed if you set `ENABLE_TELEGRAM 1` in `config.h`.

1. In Telegram, message **@BotFather** → `/newbot` → copy the bot token (or reuse your existing bot)
2. Message your bot once, then visit `https://api.telegram.org/bot<TOKEN>/getUpdates` to find your numeric chat ID
3. Put both into `config.h` (`BOT_TOKEN`, `CHAT_ID`)
4. If you reused your existing bot from a previous project and it returns **401 Unauthorized**, regenerate the token via @BotFather (this matches the earlier auth issue you ran into)

When enabled, each logged feed also sends a short message like "🍼 Fed 165 mL in 19 min".

---

## Future: dashboards & summaries (Phase 2+)

Once feeds are flowing into Notion, you can build on top **without touching the device**:

- **Notion views:** group by day, sum `Volume (mL)`, chart feeds over time — all native Notion
- **Daily summary:** a small script (or your Telegram bot) that reads the database each morning and posts "yesterday: 6 feeds, 880 mL"
- **Claude API summaries:** feed the Notion data to the Claude API for natural-language trends ("gaps between night feeds lengthened this week")
- **Local web dashboard:** served by the ESP32 or a Pi Zero, if you ever want it off-Notion

These are out of scope for the weekend MVP but the data model is ready for them.

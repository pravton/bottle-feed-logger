#!/usr/bin/env bash
# =============================================================================
# Notion Feed Log — connection test
#
# Posts ONE test row to your Feed Log database. If it succeeds, your Notion
# integration + database + sharing are all correct, and the device half
# of the project just needs to hit the same endpoint.
#
# HOW TO USE:
#   1. Fill in NOTION_TOKEN and NOTION_DB_ID below.
#   2. Save the file.
#   3. In a terminal:  bash notion-test.sh
#   4. Check your Notion Feed Log — a "Test feed" row should appear.
#
# Expected on success: a big JSON blob ending with "object": "page" ...
# Expected on failure: a JSON error naming the problem (permission / property /
# database_id). The troubleshooting doc explains each.
# =============================================================================

# ---- FILL IN THESE TWO ------------------------------------------------------
NOTION_TOKEN="PASTE_YOUR_INTEGRATION_TOKEN_HERE"   # starts with ntn_ or secret_
NOTION_DB_ID="PASTE_YOUR_32CHAR_DATABASE_ID_HERE" # from the database URL
# ----------------------------------------------------------------------------

# Refuse to run with the placeholders still in place
if [[ "$NOTION_TOKEN" == PASTE_* || "$NOTION_DB_ID" == PASTE_* ]]; then
  echo "❌ Edit this file and replace NOTION_TOKEN and NOTION_DB_ID first."
  exit 1
fi

echo "→ Posting a test row to Notion..."
echo

curl -sS -X POST https://api.notion.com/v1/pages \
  -H "Authorization: Bearer $NOTION_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Notion-Version: 2022-06-28" \
  -d '{
    "parent": { "database_id": "'"$NOTION_DB_ID"'" },
    "properties": {
      "Name":           { "title":     [ { "text": { "content": "Test feed" } } ] },
      "Start":          { "date":      { "start": "2026-05-28T02:42:00-04:00" } },
      "End":            { "date":      { "start": "2026-05-28T03:01:00-04:00" } },
      "Duration (min)": { "number":    19 },
      "Volume (mL)":    { "number":    165 },
      "Notes":          { "rich_text": [ { "text": { "content": "Sent from notion-test.sh" } } ] }
    }
  }' | sed 's/.\{200\}/&\n/g'

echo
echo
echo "→ Done. If you see a JSON blob with \"object\": \"page\" above, success — check your Notion DB."
echo "  If you see \"object\": \"error\", read the \"message\" field — it names the exact problem."

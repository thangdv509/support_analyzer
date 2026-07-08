"""
Backfill shop_domain for all existing records in grading + sumtag collections.
Fetches Crisp conversation meta for each unique session_id and updates MongoDB.
"""
import os
import time
from dotenv import load_dotenv
from crisp_api import Crisp

load_dotenv()

from database.tunnel import ensure_tunnel
from database.connection import get_db

WEBSITE_ID = "17e47fa7-bddf-4074-b627-df66a29a740e"
GRADING_COLS = ["grading_deco", "grading_searchpie"]
SUMTAG_COLS  = ["sumtag_deco", "sumtag_searchpie"]
ALL_COLS     = GRADING_COLS + SUMTAG_COLS


def _extract_domain(app: str, meta_data: dict) -> str | None:
    if "DECO" in (app or "").upper():
        # "shop" chứa full domain như "natural-sloth.myshopify.com"
        return meta_data.get("shop") or None
    # SearchPie: "name" là myshopify subdomain (string) hoặc store ID (int)
    name = meta_data.get("name")
    if isinstance(name, str) and name.strip():
        return f"{name.strip()}.myshopify.com"
    return None


def main():
    ensure_tunnel()
    db = get_db()

    client = Crisp()
    client.set_tier("plugin")
    client.authenticate(os.getenv("CRISP_IDENTIFIER"), os.getenv("CRISP_KEY"))

    # Collect all unique (session_id, app) from grading collections
    sessions: dict[str, str] = {}  # session_id → app
    for col_name in GRADING_COLS:
        for doc in db[col_name].find({}, {"session_id": 1, "app": 1}):
            sid = doc.get("session_id")
            if sid and sid not in sessions:
                sessions[sid] = doc.get("app", "")

    # Also collect session_ids from sumtag that are NOT in grading
    for col_name in SUMTAG_COLS:
        for doc in db[col_name].find({}, {"session_id": 1, "app": 1}):
            sid = doc.get("session_id")
            if sid and sid not in sessions:
                sessions[sid] = doc.get("app", "")

    total = len(sessions)
    print(f"Found {total} unique sessions to backfill")

    updated = skipped = errors = 0
    session_list = list(sessions.items())

    # Skip sessions có shop_domain là string đúng (không phải số, không bắt đầu bằng chữ số)
    # DECO records cũ có DECO_shopId (int) và SearchPie "123.myshopify.com" sẽ bị re-process
    already_done: set[str] = set()
    db2 = get_db()
    for col_name in ALL_COLS:
        for doc in db2[col_name].find(
            {"shop_domain": {"$type": "string", "$not": {"$regex": r"^\d"}}},
            {"session_id": 1},
        ):
            already_done.add(doc["session_id"])
    print(f"  {len(already_done)} sessions already have valid domain — skipping")

    for i, (sid, app) in enumerate(session_list, 1):
        if i % 50 == 0:
            print(f"  [{i}/{total}] updated={updated} skipped={skipped} errors={errors}")

        if sid in already_done:
            skipped += 1
            continue

        # Fetch Crisp meta with retry
        meta_data = {}
        for attempt in range(3):
            try:
                meta = client.website.get_conversation_metas(WEBSITE_ID, sid)
                meta_data = meta.get("data", {}) if meta else {}
                break
            except Exception as e:
                if "rate_limited" in str(e):
                    wait = 60 + attempt * 30
                    print(f"  ⏳ Rate limited on {sid}, sleeping {wait}s...")
                    time.sleep(wait)
                else:
                    errors += 1
                    break
            time.sleep(0.3)

        shop_domain = _extract_domain(app, meta_data)
        if not shop_domain:
            skipped += 1
            continue

        # Update all collections that have this session_id
        for col_name in ALL_COLS:
            db[col_name].update_many(
                {"session_id": sid},
                {"$set": {"shop_domain": shop_domain}},
            )

        updated += 1
        time.sleep(0.3)

    print(f"\n✅ Done: {updated} updated, {skipped} no domain found, {errors} errors")


if __name__ == "__main__":
    main()

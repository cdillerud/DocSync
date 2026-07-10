import asyncio
import base64
import json
import os
import sys
sys.path.insert(0, '.')

TRAINING = {
    "507240_6317549_2026-07-08.pdf": "DS NOT International",
    "507240_6319027_2026-07-09.pdf": "Vendor Credit memo",
    "507240_6319336_2026-07-09.pdf": "WH NOT International",
}
TEST = {
    "4222_001.pdf": "DS NOT International",
}


async def get_fresh_extraction(db, file_name):
    from services.document_intel_helpers import _call_llm_for_extraction

    doc = await db.hub_documents.find_one({"file_name": file_name})
    if not doc or not doc.get("file_content_b64"):
        return None, None

    content = base64.b64decode(doc["file_content_b64"])
    tmp_path = f"/tmp/fewshot_{file_name}"
    with open(tmp_path, "wb") as f:
        f.write(content)

    result = await _call_llm_for_extraction(tmp_path, file_name)
    return result, doc


async def main():
    from motor.motor_asyncio import AsyncIOMotorClient
    client = AsyncIOMotorClient(os.environ['MONGO_URL'])
    db = client[os.environ['DB_NAME']]

    print("=== Getting fresh extraction for training examples ===")
    training_data = {}
    for fname, folder in TRAINING.items():
        result, doc = await get_fresh_extraction(db, fname)
        if result:
            training_data[fname] = {"folder": folder, "fields": result.get("extracted_fields", {})}
            print(f"  {fname} -> {folder} (extracted {len(result.get('extracted_fields', {}))} fields)")
        else:
            print(f"  {fname} -> NOT FOUND in Hub, skipping")

    print()
    print("=== Getting fresh extraction for held-out test cases ===")
    test_data = {}
    for fname, folder in TEST.items():
        result, doc = await get_fresh_extraction(db, fname)
        if result:
            test_data[fname] = {"actual_folder": folder, "fields": result.get("extracted_fields", {})}
            print(f"  {fname} -> actual answer: {folder} (extracted {len(result.get('extracted_fields', {}))} fields)")
        else:
            print(f"  {fname} -> NOT FOUND in Hub, skipping")

    print()
    print("=== Building few-shot prompt and asking Gemini to predict each held-out case ===")

    from emergentintegrations.llm.chat import LlmChat, UserMessage
    EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY", "")

    examples_text = "\n\n".join(
        f"EXAMPLE: {fname}\nExtracted fields: {json.dumps(d['fields'], default=str)}\nCorrect folder: {d['folder']}"
        for fname, d in training_data.items()
    )

    for fname, d in test_data.items():
        prompt = f"""You are helping file AP documents into the correct SharePoint folder.
Here are real examples of documents and their CORRECT folder,
as determined by an experienced AP team member:

{examples_text}

Now, based on these examples, predict the correct folder for this NEW document
(which may be from a different vendor than the examples above):

Extracted fields: {json.dumps(d['fields'], default=str)}

Respond with ONLY the folder name (one of: DS NOT International, WH NOT International, Vendor Credit memo), nothing else."""

        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=f"fewshot-test-{fname}",
            system_message="You are a precise document routing assistant.",
        ).with_model("gemini", "gemini-2.5-pro")

        prediction = (await chat.send_message(UserMessage(text=prompt))).strip()
        actual = d["actual_folder"]
        match = "✓ CORRECT" if prediction.lower() == actual.lower() else "✗ WRONG"
        print(f"  {fname}")
        print(f"    predicted: {prediction!r}")
        print(f"    actual:    {actual!r}")
        print(f"    {match}")
        print()


asyncio.run(main())

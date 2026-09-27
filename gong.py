"""Export Gong transcripts for a customer to a single text file.

Calls are pulled from the Gong ``extensive`` search endpoint, paginating with a
``cursor`` in the request body until the response returns no further cursor.
Each call is kept only if a party is linked to the target Salesforce Account.
The retrieved calls are cached to ``gong_calls.json``; the cache is reused on
subsequent runs. For every matching call the transcript is fetched from the
``transcript`` endpoint and its sentences written to ``gong_transcripts.txt``.
"""

import base64
import json
import os
import urllib.request

EXTENSIVE_URL = "https://api.gong.io/v2/calls/extensive"
TRANSCRIPT_URL = "https://api.gong.io/v2/calls/transcript"
SF_ACCOUNT_ID = "0015e00000UKtuYAAT"
CALLS_FILE = "gong_calls.json"
OUTPUT_FILE = "gong_transcripts.txt"
TRANSCRIPT_SEPARATOR = "-" * 40
MAX_PAGES = 200

EXTENSIVE_BODY = {
    "filter": {},
    "contentSelector": {
        "context": "Extended",
        "contextTiming": ["Now", "TimeOfCall"],
        "exposedFields": {"parties": True},
    },
}


def authorization_header():
    """Build the HTTP Basic auth header expected by the Gong API."""
    access_key = os.environ["SB_GONG_ACCESSKEY"]
    secret_key = os.environ["SB_GONG_ACCESSSECRETKEY"]
    encoded = base64.b64encode(f"{access_key}:{secret_key}".encode()).decode()
    return "Basic " + encoded


def post_json(url, body, headers):
    """POST a JSON body to a Gong endpoint and decode the JSON response."""
    data = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={**headers, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_all_calls(headers):
    """Paginate up to MAX_PAGES of the extensive endpoint via the returned cursor."""
    calls = []
    cursor = None
    for page in range(1, MAX_PAGES + 1):
        print(f"Fetching calls page {page}...")
        body = dict(EXTENSIVE_BODY)
        if cursor:
            body["cursor"] = cursor
        response = post_json(EXTENSIVE_URL, body, headers)
        calls.extend(response.get("calls") or [])
        cursor = (response.get("records") or {}).get("cursor")
        if not cursor:
            break
    if cursor:
        print(f"Reached maximum of {MAX_PAGES} pages; results truncated.")
    return calls


def get_calls(headers):
    """Return the retrieved calls, reusing the on-disk cache when present."""
    if os.path.exists(CALLS_FILE):
        with open(CALLS_FILE, encoding="utf-8") as handle:
            return json.load(handle)
    calls = fetch_all_calls(headers)
    with open(CALLS_FILE, "w", encoding="utf-8") as handle:
        json.dump(calls, handle, indent=2)
    return calls


def matches_account(call):
    """True when a party links a Salesforce Account with the target id."""
    for context in call.get("context") or []:
        if context.get("system") != "Salesforce":
            continue
        for obj in context.get("objects") or []:
            if obj.get("objectType") == "Account":
                if obj.get("objectId") == SF_ACCOUNT_ID:
                    return True
    return False


def fetch_transcript(call_id, headers):
    """Fetch the transcript response for a single call id."""
    print(f"Fetching transcript for call {call_id}...")
    body = {"filter": {"callIds": [call_id]}}
    return post_json(TRANSCRIPT_URL, body, headers)


def extract_sentence_texts(response):
    """Pull transcript.sentences[].text out of a transcript response."""
    payloads = []
    if isinstance(response, list):
        payloads = response
    else:
        record = response.get("transcript")
        if record is None:
            record = response.get("results") or response
        payloads = record if isinstance(record, list) else [record]
    texts = []
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        for sentence in payload.get("sentences") or []:
            text = sentence.get("text")
            if text:
                texts.append(text)
    return texts


def format_transcript(call, texts):
    """Render one transcript block: separator, title, started, then text."""
    meta = call.get("metaData") or {}
    block = [
        TRANSCRIPT_SEPARATOR,
        meta.get("title", ""),
        meta.get("started", ""),
        "\n".join(texts),
    ]
    return "\n".join(block)


def main():
    headers = {"Authorization": authorization_header()}
    calls = get_calls(headers)
    matching = [call for call in calls if matches_account(call)]

    with open(OUTPUT_FILE, "w", encoding="utf-8") as out:
        for call in matching:
            call_id = (call.get("metaData") or {}).get("id")
            if not call_id:
                continue
            response = fetch_transcript(call_id, headers)
            out.write(format_transcript(call, extract_sentence_texts(response)))
            out.write("\n\n")

    print(f"Exported {len(matching)} transcripts to {os.path.abspath(OUTPUT_FILE)}")


if __name__ == "__main__":
    main()

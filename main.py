"""Export Zendesk emails for a customer to a single text file.

Tickets are pulled from the Zendesk global search endpoint, paginating with the
``page`` query param until the response reports ``next_page`` as null. For each
ticket, only the requested fields are written out.
"""

import base64
import json
import os
import urllib.parse
import urllib.request

SEARCH_URL = "https://octopuscd.zendesk.com/api/v2/search.json"
ORGANIZATION_ID = "14070083368847"
QUERY = f"type:ticket organization_id:{ORGANIZATION_ID} created>2025-10-01"
OUTPUT_FILE = f"zendesk_emails_{ORGANIZATION_ID}.txt"


def authorization_header():
    """Build the HTTP Basic auth header expected by Zendesk app tokens."""
    username = os.environ["SB_ZENDESK_USER"]
    access_token = os.environ["SB_ZENDESK_ACCESSTOKEN"]
    encoded = base64.b64encode(f"{username}/token:{access_token}".encode()).decode()
    return "Basic " + encoded


def fetch_page(page, headers):
    """Fetch a single page of search results (1-indexed)."""
    params = {
        "query": QUERY,
        "sort_by": "created_at",
        "sort_order": "desc",
        "page": page,
    }
    url = f"{SEARCH_URL}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(request) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_all_tickets(headers):
    """Paginate through every search result, stopping when next_page is null."""
    all_tickets = []
    page = 1
    while True:
        data = fetch_page(page, headers)
        results = data.get("results") or []
        all_tickets.extend(results)
        if data.get("next_page") is None:
            break
        page += 1
    return all_tickets


def _text(value):
    """Render any field value as a string, treating None as empty."""
    return "" if value is None else str(value)


def extract_email(ticket):
    """Pull just the requested fields from a ticket into a flat dict."""
    via = ticket.get("via") or {}
    source = via.get("source") or {}
    # Some Zendesk responses return the source as a list; normalize to first.
    if isinstance(source, list):
        source = source[0] if source else {}
    sender = source.get("from") or {}
    recipient = source.get("to") or {}
    return {
        "status": _text(ticket.get("status")),
        "created_at": _text(ticket.get("created_at")),
        "subject": _text(ticket.get("subject")),
        "via.source.from.name": _text(sender.get("name")),
        "via.source.from.address": _text(sender.get("address")),
        "via.source.to.address": _text(recipient.get("address")),
        "description": _text(ticket.get("description")),
    }


def format_email(email):
    """Render a single exported email as a readable text block."""
    lines = [
        f"status: {email['status']}",
        f"created_at: {email['created_at']}",
        f"subject: {email['subject']}",
        f"via.source.from.name: {email['via.source.from.name']}",
        f"via.source.from.address: {email['via.source.from.address']}",
        f"via.source.to.address: {email['via.source.to.address']}",
        "description:",
        email["description"],
    ]
    return "\n".join(lines)


def main():
    headers = {"Authorization": authorization_header()}
    tickets = fetch_all_tickets(headers)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as out:
        for ticket in tickets:
            out.write(format_email(extract_email(ticket)))
            out.write("\n\n")

    print(f"Exported {len(tickets)} emails to {os.path.abspath(OUTPUT_FILE)}")


if __name__ == "__main__":
    main()

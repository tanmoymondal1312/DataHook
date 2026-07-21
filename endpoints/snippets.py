"""Generate ready-to-copy integration snippets for an endpoint.

Each snippet is built from the endpoint's ingest URL, API key and the ordered
list of attribute keys, using type-aware placeholder values so a developer can
paste and run immediately.
"""

import json


def _placeholder(attr_type: str):
    return {
        "text": "example",
        "email": "user@example.com",
        "number": 42,
        "phone": "+1 555 0100",
        "date": "2025-01-31",
        "boolean": True,
    }.get(attr_type, "example")


def _sample_payload(attributes):
    """{key: placeholder} dict preserving attribute order."""
    return {attr.key: _placeholder(attr.type) for attr in attributes}


def build_snippets(endpoint, attributes):
    """Return {"js_fetch": str, "curl": str, "html_form": str}."""
    url = endpoint.ingest_url
    api_key = endpoint.api_key
    payload = _sample_payload(attributes)

    pretty_json = json.dumps(payload, indent=2)
    compact_json = json.dumps(payload)

    js_fetch = (
        f"fetch(\"{url}\", {{\n"
        f"  method: \"POST\",\n"
        f"  headers: {{\n"
        f"    \"Content-Type\": \"application/json\",\n"
        f"    \"X-API-Key\": \"{api_key}\"\n"
        f"  }},\n"
        f"  body: JSON.stringify({_indent_json(pretty_json, 2)})\n"
        f"}})\n"
        f"  .then(r => r.json())\n"
        f"  .then(console.log);"
    )

    curl = (
        f"curl -X POST \"{url}\" \\\n"
        f"  -H \"Content-Type: application/json\" \\\n"
        f"  -H \"X-API-Key: {api_key}\" \\\n"
        f"  -d '{compact_json}'"
    )

    html_form = _build_html_form(url, attributes)

    return {"js_fetch": js_fetch, "curl": curl, "html_form": html_form}


def _indent_json(pretty_json: str, spaces: int) -> str:
    """Re-indent a pretty JSON block so it nests cleanly inside a JS body."""
    pad = " " * spaces
    lines = pretty_json.split("\n")
    return ("\n" + pad).join(lines) if len(lines) > 1 else pretty_json


def _build_html_form(url: str, attributes) -> str:
    inputs = []
    for attr in attributes:
        input_type = {
            "email": "email",
            "number": "number",
            "date": "date",
            "phone": "tel",
        }.get(attr.type, "text")
        required = " required" if attr.required else ""
        inputs.append(
            f"  <label>{attr.label}\n"
            f"    <input type=\"{input_type}\" name=\"{attr.key}\"{required}>\n"
            f"  </label>"
        )
    body = "\n".join(inputs) if inputs else "  <!-- no attributes defined yet -->"
    # Note: the API key is intentionally NOT embedded in the plain HTML form,
    # since forms expose it client-side. Post the form to a small proxy that adds
    # the X-API-Key header, or use the JS/curl snippets for authenticated calls.
    return (
        f"<form action=\"{url}\" method=\"POST\">\n"
        f"{body}\n"
        f"  <button type=\"submit\">Submit</button>\n"
        f"</form>"
    )

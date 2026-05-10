import json
import os
import uuid
import httpx
import xml.etree.ElementTree as ET

CARDDAV_URL = "https://contacts.icloud.com"

ICLOUD_CONTACT_TOOLS = [
    {
        "name": "icloud_search_contacts",
        "description": "Search iCloud Contacts by name, email, or phone number. Returns matching contacts with their details.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search term (name, email, or phone number)",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Max contacts to return (default 10, max 50)",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "icloud_list_contacts",
        "description": "List all iCloud Contacts (or a subset). Use icloud_search_contacts for specific lookups.",
        "input_schema": {
            "type": "object",
            "properties": {
                "max_results": {
                    "type": "integer",
                    "description": "Max contacts to return (default 20, max 100)",
                },
            },
        },
    },
    {
        "name": "icloud_get_contact",
        "description": "Get full details of a specific iCloud contact by their URL/ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "contact_id": {
                    "type": "string",
                    "description": "The contact URL or ID",
                },
            },
            "required": ["contact_id"],
        },
    },
    {
        "name": "icloud_create_contact",
        "description": "Create a new contact in iCloud Contacts.",
        "input_schema": {
            "type": "object",
            "properties": {
                "first_name": {
                    "type": "string",
                    "description": "First name",
                },
                "last_name": {
                    "type": "string",
                    "description": "Last name",
                },
                "email": {
                    "type": "string",
                    "description": "Email address",
                },
                "phone": {
                    "type": "string",
                    "description": "Phone number",
                },
                "company": {
                    "type": "string",
                    "description": "Company / organization name",
                },
                "notes": {
                    "type": "string",
                    "description": "Additional notes",
                },
            },
            "required": ["first_name"],
        },
    },
    {
        "name": "icloud_delete_contact",
        "description": "Delete a contact from iCloud Contacts by their URL/ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "contact_id": {
                    "type": "string",
                    "description": "The contact URL or ID to delete",
                },
            },
            "required": ["contact_id"],
        },
    },
]


def _get_auth():
    icloud_email = os.environ.get("ICLOUD_EMAIL", "")
    icloud_password = os.environ.get("ICLOUD_APP_PASSWORD", "")
    if not icloud_email or not icloud_password:
        raise RuntimeError(
            "iCloud not configured. Set ICLOUD_EMAIL and ICLOUD_APP_PASSWORD environment variables."
        )
    return (icloud_email, icloud_password)


def _discover_addressbook_url(auth):
    """Discover the default addressbook URL via PROPFIND."""
    # Step 1: Find principal URL
    body = '<?xml version="1.0" encoding="utf-8"?><d:propfind xmlns:d="DAV:"><d:prop><d:current-user-principal/></d:prop></d:propfind>'
    resp = httpx.request(
        "PROPFIND", CARDDAV_URL, content=body, auth=auth,
        headers={"Content-Type": "application/xml", "Depth": "0"},
        timeout=30,
    )
    resp.raise_for_status()

    ns = {"d": "DAV:"}
    root = ET.fromstring(resp.text)
    principal_href = root.find(".//d:current-user-principal/d:href", ns)
    if principal_href is None:
        raise RuntimeError("Could not discover CardDAV principal URL")
    principal_url = CARDDAV_URL + principal_href.text

    # Step 2: Find addressbook-home-set
    body = '<?xml version="1.0" encoding="utf-8"?><d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:carddav"><d:prop><c:addressbook-home-set/></d:prop></d:propfind>'
    resp = httpx.request(
        "PROPFIND", principal_url, content=body, auth=auth,
        headers={"Content-Type": "application/xml", "Depth": "0"},
        timeout=30,
    )
    resp.raise_for_status()

    ns2 = {"d": "DAV:", "c": "urn:ietf:params:xml:ns:carddav"}
    root = ET.fromstring(resp.text)
    home_href = root.find(".//c:addressbook-home-set/d:href", ns2)
    if home_href is None:
        raise RuntimeError("Could not discover addressbook home URL")
    home_url = CARDDAV_URL + home_href.text

    # Step 3: Find actual addressbook collections
    body = '<?xml version="1.0" encoding="utf-8"?><d:propfind xmlns:d="DAV:"><d:prop><d:resourcetype/><d:displayname/></d:prop></d:propfind>'
    resp = httpx.request(
        "PROPFIND", home_url, content=body, auth=auth,
        headers={"Content-Type": "application/xml", "Depth": "1"},
        timeout=30,
    )
    resp.raise_for_status()

    root = ET.fromstring(resp.text)
    ns3 = {"d": "DAV:", "c": "urn:ietf:params:xml:ns:carddav"}
    for response in root.findall(".//d:response", ns3):
        href = response.find("d:href", ns3)
        restype = response.find(".//d:resourcetype", ns3)
        if restype is not None:
            # Check for addressbook resource type
            ab = restype.find("{urn:ietf:params:xml:ns:carddav}addressbook")
            if ab is not None and href is not None:
                return CARDDAV_URL + href.text

    raise RuntimeError("Could not find any addressbook in iCloud account")


def _fetch_all_vcards(auth, addressbook_url):
    """Fetch all vCards from the addressbook."""
    body = """<?xml version="1.0" encoding="utf-8"?>
<c:addressbook-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:carddav">
  <d:prop>
    <d:getetag/>
    <c:address-data/>
  </d:prop>
</c:addressbook-query>"""

    resp = httpx.request(
        "REPORT", addressbook_url, content=body, auth=auth,
        headers={"Content-Type": "application/xml", "Depth": "1"},
        timeout=60,
    )
    resp.raise_for_status()
    return _parse_carddav_response(resp.text)


def _parse_carddav_response(xml_text):
    """Parse a CardDAV REPORT response into a list of contacts."""
    ns = {"d": "DAV:", "c": "urn:ietf:params:xml:ns:carddav"}
    root = ET.fromstring(xml_text)
    contacts = []

    for response in root.findall(".//d:response", ns):
        href = response.find("d:href", ns)
        address_data = response.find(".//c:address-data", ns)
        if href is not None and address_data is not None and address_data.text:
            vcard_text = address_data.text
            contact = _parse_vcard(vcard_text)
            if contact and contact.get("name"):
                contact["url"] = CARDDAV_URL + href.text if not href.text.startswith("http") else href.text
                contacts.append(contact)

    return contacts


def _parse_vcard(vcard_text):
    """Parse a vCard string into a dict."""
    contact = {
        "name": "",
        "first_name": "",
        "last_name": "",
        "emails": [],
        "phones": [],
        "company": "",
        "notes": "",
    }

    for line in vcard_text.split("\n"):
        line = line.strip()
        if not line or line.startswith("BEGIN:") or line.startswith("END:") or line.startswith("VERSION:"):
            continue

        # Handle folded lines
        upper_line = line.upper()

        if upper_line.startswith("FN"):
            contact["name"] = _get_vcard_value(line)
        elif upper_line.startswith("N;") or upper_line.startswith("N:"):
            parts = _get_vcard_value(line).split(";")
            if len(parts) >= 2:
                contact["last_name"] = parts[0]
                contact["first_name"] = parts[1]
            elif len(parts) == 1:
                contact["last_name"] = parts[0]
        elif upper_line.startswith("EMAIL"):
            email = _get_vcard_value(line)
            if email:
                contact["emails"].append(email)
        elif upper_line.startswith("TEL"):
            phone = _get_vcard_value(line)
            if phone:
                contact["phones"].append(phone)
        elif upper_line.startswith("ORG"):
            contact["company"] = _get_vcard_value(line).replace(";", " ").strip()
        elif upper_line.startswith("NOTE"):
            contact["notes"] = _get_vcard_value(line)

    return contact


def _get_vcard_value(line):
    """Extract value from a vCard line (handles parameters like TYPE=)."""
    # Line format: PROPERTY;PARAMS:VALUE or PROPERTY:VALUE
    colon_idx = line.find(":")
    if colon_idx == -1:
        return ""
    return line[colon_idx + 1:].strip()


def _contact_summary(contact):
    """Create a clean summary of a contact."""
    result = {
        "name": contact.get("name", ""),
        "url": contact.get("url", ""),
    }
    if contact.get("emails"):
        result["emails"] = contact["emails"]
    if contact.get("phones"):
        result["phones"] = contact["phones"]
    if contact.get("company"):
        result["company"] = contact["company"]
    if contact.get("notes"):
        result["notes"] = contact["notes"][:200]
    return result


def _contact_matches(contact, query):
    """Check if a contact matches a search query."""
    q = query.lower()
    searchable = [
        contact.get("name", ""),
        contact.get("first_name", ""),
        contact.get("last_name", ""),
        contact.get("company", ""),
    ] + contact.get("emails", []) + contact.get("phones", [])

    return any(q in s.lower() for s in searchable if s)


async def execute_icloud_contact_tool(name: str, input_data: dict, chat_id: int) -> str:
    try:
        auth = _get_auth()
    except RuntimeError as e:
        return json.dumps({"error": str(e)})

    try:
        addressbook_url = _discover_addressbook_url(auth)
    except Exception as e:
        return json.dumps({"error": f"iCloud Contacts connection failed: {str(e)}"})

    if name == "icloud_search_contacts":
        query = input_data["query"]
        max_results = min(input_data.get("max_results", 10), 50)

        contacts = _fetch_all_vcards(auth, addressbook_url)
        matches = [c for c in contacts if _contact_matches(c, query)]
        matches = matches[:max_results]

        return json.dumps({
            "query": query,
            "contacts": [_contact_summary(c) for c in matches],
            "count": len(matches),
        })

    elif name == "icloud_list_contacts":
        max_results = min(input_data.get("max_results", 20), 100)

        contacts = _fetch_all_vcards(auth, addressbook_url)
        contacts.sort(key=lambda c: c.get("name", "").lower())
        contacts = contacts[:max_results]

        return json.dumps({
            "contacts": [_contact_summary(c) for c in contacts],
            "count": len(contacts),
        })

    elif name == "icloud_get_contact":
        contact_id = input_data["contact_id"]

        contacts = _fetch_all_vcards(auth, addressbook_url)
        for c in contacts:
            if c.get("url") == contact_id:
                return json.dumps(_contact_summary(c))

        return json.dumps({"error": f"Contact not found: {contact_id}"})

    elif name == "icloud_create_contact":
        first_name = input_data.get("first_name", "")
        last_name = input_data.get("last_name", "")
        email = input_data.get("email", "")
        phone = input_data.get("phone", "")
        company = input_data.get("company", "")
        notes = input_data.get("notes", "")

        uid = str(uuid.uuid4())
        full_name = f"{first_name} {last_name}".strip()

        vcard = (
            "BEGIN:VCARD\r\n"
            "VERSION:3.0\r\n"
            f"UID:{uid}\r\n"
            f"FN:{full_name}\r\n"
            f"N:{last_name};{first_name};;;\r\n"
        )
        if email:
            vcard += f"EMAIL;TYPE=INTERNET:{email}\r\n"
        if phone:
            vcard += f"TEL;TYPE=CELL:{phone}\r\n"
        if company:
            vcard += f"ORG:{company}\r\n"
        if notes:
            vcard += f"NOTE:{notes}\r\n"
        vcard += "END:VCARD\r\n"

        contact_url = f"{addressbook_url}{uid}.vcf"
        resp = httpx.put(
            contact_url, content=vcard, auth=auth,
            headers={"Content-Type": "text/vcard; charset=utf-8"},
            timeout=30,
        )

        if resp.status_code in (201, 204):
            return json.dumps({
                "status": "created",
                "name": full_name,
                "url": contact_url,
            })
        else:
            return json.dumps({"error": f"Failed to create contact: HTTP {resp.status_code}"})

    elif name == "icloud_delete_contact":
        contact_id = input_data["contact_id"]

        resp = httpx.delete(contact_id, auth=auth, timeout=30)
        if resp.status_code in (200, 204):
            return json.dumps({"status": "deleted", "contact_id": contact_id})
        else:
            return json.dumps({"error": f"Failed to delete contact: HTTP {resp.status_code}"})

    return json.dumps({"error": f"Unknown contact tool: {name}"})

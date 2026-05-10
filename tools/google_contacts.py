import json
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from config import GOOGLE_TOKEN_PATH

SCOPES = ["https://www.googleapis.com/auth/contacts"]

GOOGLE_CONTACT_TOOLS = [
    {
        "name": "google_search_contacts",
        "description": "Search Google Contacts by name, email, or phone number. Returns matching contacts with their details.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search term (name, email, or phone number)",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Max contacts to return (default 10, max 30)",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "google_list_contacts",
        "description": "List Google Contacts. Returns contacts sorted by name.",
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
        "name": "google_get_contact",
        "description": "Get full details of a specific Google contact by resource name.",
        "input_schema": {
            "type": "object",
            "properties": {
                "resource_name": {
                    "type": "string",
                    "description": "The contact resource name (e.g. 'people/c1234567890')",
                },
            },
            "required": ["resource_name"],
        },
    },
    {
        "name": "google_create_contact",
        "description": "Create a new contact in Google Contacts.",
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
                "job_title": {
                    "type": "string",
                    "description": "Job title",
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
        "name": "google_delete_contact",
        "description": "Delete a contact from Google Contacts by resource name.",
        "input_schema": {
            "type": "object",
            "properties": {
                "resource_name": {
                    "type": "string",
                    "description": "The contact resource name (e.g. 'people/c1234567890')",
                },
            },
            "required": ["resource_name"],
        },
    },
]

PERSON_FIELDS = "names,emailAddresses,phoneNumbers,organizations,biographies,addresses,birthdays"


def _get_people_service():
    """Get authenticated Google People API service."""
    creds = None
    try:
        creds = Credentials.from_authorized_user_file(GOOGLE_TOKEN_PATH, SCOPES)
    except (FileNotFoundError, ValueError):
        pass

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(GOOGLE_TOKEN_PATH, "w") as f:
            f.write(creds.to_json())
    elif not creds or not creds.valid:
        raise RuntimeError(
            "Google Contacts not authenticated. Run 'python auth_gmail.py' to set up authentication (includes Contacts scope)."
        )

    return build("people", "v1", credentials=creds)


def _format_contact(person):
    """Format a Google People API person resource into a clean dict."""
    result = {"resource_name": person.get("resourceName", "")}

    names = person.get("names", [])
    if names:
        result["name"] = names[0].get("displayName", "")
        result["first_name"] = names[0].get("givenName", "")
        result["last_name"] = names[0].get("familyName", "")

    emails = person.get("emailAddresses", [])
    if emails:
        result["emails"] = [e.get("value", "") for e in emails]

    phones = person.get("phoneNumbers", [])
    if phones:
        result["phones"] = [
            {"number": p.get("value", ""), "type": p.get("type", "")}
            for p in phones
        ]

    orgs = person.get("organizations", [])
    if orgs:
        result["company"] = orgs[0].get("name", "")
        result["job_title"] = orgs[0].get("title", "")

    bios = person.get("biographies", [])
    if bios:
        result["notes"] = bios[0].get("value", "")[:300]

    addresses = person.get("addresses", [])
    if addresses:
        result["addresses"] = [
            a.get("formattedValue", "") for a in addresses
        ]

    birthdays = person.get("birthdays", [])
    if birthdays:
        bday = birthdays[0].get("date", {})
        if bday:
            parts = [str(bday.get("year", "")), str(bday.get("month", "")).zfill(2), str(bday.get("day", "")).zfill(2)]
            result["birthday"] = "-".join(p for p in parts if p and p != "0" and p != "00")

    return result


async def execute_google_contact_tool(name: str, input_data: dict, chat_id: int) -> str:
    try:
        service = _get_people_service()
    except RuntimeError as e:
        return json.dumps({"error": str(e)})

    if name == "google_search_contacts":
        query = input_data["query"]
        max_results = min(input_data.get("max_results", 10), 30)

        try:
            result = service.people().searchContacts(
                query=query,
                pageSize=max_results,
                readMask="names,emailAddresses,phoneNumbers,organizations,biographies",
            ).execute()
        except Exception as e:
            return json.dumps({"error": f"Search failed: {str(e)}"})

        contacts = []
        for item in result.get("results", []):
            person = item.get("person", {})
            contacts.append(_format_contact(person))

        return json.dumps({"query": query, "contacts": contacts, "count": len(contacts)})

    elif name == "google_list_contacts":
        max_results = min(input_data.get("max_results", 20), 100)

        try:
            result = service.people().connections().list(
                resourceName="people/me",
                pageSize=max_results,
                personFields=PERSON_FIELDS,
                sortOrder="FIRST_NAME_ASCENDING",
            ).execute()
        except Exception as e:
            return json.dumps({"error": f"List failed: {str(e)}"})

        contacts = []
        for person in result.get("connections", []):
            contacts.append(_format_contact(person))

        return json.dumps({"contacts": contacts, "count": len(contacts)})

    elif name == "google_get_contact":
        resource_name = input_data["resource_name"]

        try:
            person = service.people().get(
                resourceName=resource_name,
                personFields=PERSON_FIELDS,
            ).execute()
        except Exception as e:
            return json.dumps({"error": f"Contact not found: {str(e)}"})

        return json.dumps(_format_contact(person))

    elif name == "google_create_contact":
        body = {"names": [{}]}
        body["names"][0]["givenName"] = input_data.get("first_name", "")
        if input_data.get("last_name"):
            body["names"][0]["familyName"] = input_data["last_name"]

        if input_data.get("email"):
            body["emailAddresses"] = [{"value": input_data["email"]}]
        if input_data.get("phone"):
            body["phoneNumbers"] = [{"value": input_data["phone"]}]
        if input_data.get("company") or input_data.get("job_title"):
            body["organizations"] = [{}]
            if input_data.get("company"):
                body["organizations"][0]["name"] = input_data["company"]
            if input_data.get("job_title"):
                body["organizations"][0]["title"] = input_data["job_title"]
        if input_data.get("notes"):
            body["biographies"] = [{"value": input_data["notes"]}]

        try:
            person = service.people().createContact(body=body).execute()
        except Exception as e:
            return json.dumps({"error": f"Failed to create contact: {str(e)}"})

        return json.dumps({
            "status": "created",
            "resource_name": person.get("resourceName", ""),
            "name": person.get("names", [{}])[0].get("displayName", ""),
        })

    elif name == "google_delete_contact":
        resource_name = input_data["resource_name"]

        try:
            service.people().deleteContact(resourceName=resource_name).execute()
        except Exception as e:
            return json.dumps({"error": f"Failed to delete contact: {str(e)}"})

        return json.dumps({"status": "deleted", "resource_name": resource_name})

    return json.dumps({"error": f"Unknown contact tool: {name}"})

"""REISift account vocabulary and approved calling/SMS interpretations.

See docs/GATE1_TAG_MAPPING.md. Salesforce and the legacy mapper are separate.
Empty values mean no update, not an unmapped label or a request to clear a field.
"""

PROPERTY_STATUSES = frozenset({
    "Dead Deal", "dnc", "lead", "Appointment", "Offer Accepted", "under_contract",
    "Committed to List", "Contract Signed", "Expired Listing", "On Market Listing",
    "sold", "buyer", "prospecting", "New", "Not Yet Reached", "Follow Up", "Converted",
})
PHONE_STATUSES = frozenset({"Correct", "Correct DNC", "Wrong", "Wrong DNC", "No Answer", "Dead", "DNC"})
PHONE_TAGS = frozenset({"Voicemail", "Contacted", "Correct", "Wrong Number", "DNC"})

# Existing supported property interpretations, corrected to active account values.
PROPERTY_MAPPING = {
    "new": "lead", "decision maker": "lead", "decision maker - lead": "lead",
    "decision maker - nyi": "Follow Up", "not interested": "Follow Up",
    "callback": "lead", "follow up": "Follow Up", "spanish speaker": "Follow Up",
    "influencer": "Follow Up", "listed property": "On Market Listing",
    "maybe later": "Follow Up", "maybe later (sms)": "Follow Up",
    "abv mv": "Follow Up", "abv mv (sms)": "Follow Up", "sold": "sold",
    "wrong number": "Follow Up", "voicemail": "Follow Up", "no answer": "Follow Up",
    "dead call": "Follow Up", "dead call / disconnected": "Follow Up", "disconnected": "Follow Up",
    "dnc - decision maker": "dnc", "dnc - unknown": "", "dnc": "",
}

PHONE_MAPPING = {
    "new": ("Correct", "Contacted"),
    "decision maker": ("Correct", "Correct,Contacted"),
    "decision maker - lead": ("Correct", "Correct,Contacted"),
    "decision maker - nyi": ("Correct", "Correct,Contacted"),
    "not interested": ("Correct", "Contacted"),
    "callback": ("Correct", "Contacted"), "follow up": ("Correct", "Contacted"),
    "spanish speaker": ("Correct", "Contacted"), "influencer": ("Correct", "Contacted"),
    "listed property": ("Correct", "Contacted"), "maybe later": ("Correct", "Contacted"),
    "maybe later (sms)": ("Correct", "Contacted"), "abv mv": ("Correct", "Contacted"),
    "abv mv (sms)": ("Correct", "Contacted"),
    "wrong number": ("Wrong", "Wrong Number"), "voicemail": ("No Answer", "Voicemail"),
    "no answer": ("No Answer", ""), "dead call": ("Dead", ""),
    "dead call / disconnected": ("Dead", ""), "disconnected": ("Dead", ""),
    "dnc - decision maker": ("Correct DNC", "DNC"),
    "dnc - unknown": ("DNC", "DNC"), "dnc": ("DNC", "DNC"),
}


def validate_mappings(properties, phones):
    if any(value and value not in PROPERTY_STATUSES for value in properties.values()):
        raise ValueError("Property mapping contains a status outside the active REISift vocabulary")
    for status, tags in phones.values():
        if status and status not in PHONE_STATUSES:
            raise ValueError("Phone mapping contains an unsupported REISift status")
        if any(tag and tag not in PHONE_TAGS for tag in tags.split(",")):
            raise ValueError("Phone mapping contains an unsupported REISift tag")


def resolve_labels(labels, properties=PROPERTY_MAPPING, phones=PHONE_MAPPING):
    """Interpret both targets independently, retaining partial, approved evidence."""
    prop_values = {properties[label] for label in labels if label in properties and properties[label]}
    prop_unknown = [label for label in labels if label not in properties]
    phone_unknown = [label for label in labels if label not in phones]
    prop_reason = "conflicting_property_labels" if len(prop_values) > 1 else "unmapped_property_labels" if prop_unknown or not labels else ""
    status = next(iter(prop_values)) if len(prop_values) == 1 else ""
    if "dnc" in prop_values:
        status = "dnc"
    statuses = {phones[label][0] for label in labels if label in phones and phones[label][0]}
    tags = {tag for label in labels if label in phones for tag in phones[label][1].split(",") if tag}
    dnc = any("DNC" in value for value in statuses)
    bases = {value.replace(" DNC", "") for value in statuses if value != "DNC"}
    phone_reason = "conflicting_phone_labels" if len(bases) > 1 else "unmapped_phone_labels" if phone_unknown or not labels else ""
    if len(bases) > 1:
        # Opt-out is still known even when correctness is contradictory.
        phone_status = "DNC" if dnc else ""
        tags = {"DNC"} if dnc else set()
    else:
        base = next(iter(bases), "")
        phone_status = f"{base} DNC" if dnc and base in {"Correct", "Wrong"} else "DNC" if dnc else base
    return {
        "status": status, "phone_status": phone_status,
        "phone_tag": ",".join(tag for tag in ("Correct", "Contacted", "Voicemail", "Wrong Number", "DNC") if tag in tags),
        "property_validation_reason": prop_reason, "phone_validation_reason": phone_reason,
        "unmapped_property_labels": "|".join(prop_unknown), "unmapped_phone_labels": "|".join(phone_unknown),
    }


validate_mappings(PROPERTY_MAPPING, PHONE_MAPPING)

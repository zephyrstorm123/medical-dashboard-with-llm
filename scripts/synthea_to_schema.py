"""Map Synthea FHIR bundles to the clinic's table-shaped JSON schema.

Run from the repository root:
    python scripts/synthea_to_schema.py
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any

TABLES = (
    "patients",
    "encounters",
    "problems",
    "medications",
    "allergies",
    "lab_results",
    "vitals",
)

VITAL_FIELDS = {
    "8480-6": "systolic",
    "8462-4": "diastolic",
    "8867-4": "heart_rate",
    "9279-1": "resp_rate",
    "8310-5": "temp_c",
    "2708-6": "spo2",
    "29463-7": "weight_kg",
    "8302-2": "height_cm",
}


def code_text(concept: dict[str, Any] | None) -> str | None:
    if not isinstance(concept, dict):
        return None
    text = concept.get("text")
    if isinstance(text, str) and text:
        return text
    for coding in concept.get("coding", []):
        display = coding.get("display")
        if isinstance(display, str) and display:
            return display
    return None


def code_value(concept: dict[str, Any] | None) -> str | None:
    if not isinstance(concept, dict):
        return None
    for coding in concept.get("coding", []):
        code = coding.get("code")
        if isinstance(code, str) and code:
            return code
    return None


def source_id(reference: str | None) -> str | None:
    if not reference:
        return None
    return reference.removeprefix("urn:uuid:").rsplit("/", 1)[-1]


def iso_date(value: str | None) -> str | None:
    if not value or len(value) < 10:
        return None
    try:
        return date.fromisoformat(value[:10]).isoformat()
    except ValueError:
        return None


def timestamp(resource: dict[str, Any]) -> str | None:
    effective = resource.get("effectiveDateTime") or resource.get("issued")
    if not effective:
        effective = resource.get("effectivePeriod", {}).get("start")
    return effective if isinstance(effective, str) else None


def allocate(next_ids: dict[str, int], table: str) -> int:
    value = next_ids[table]
    next_ids[table] += 1
    return value


def patient_row(resource: dict[str, Any], patient_id: int) -> dict[str, Any]:
    names = resource.get("name", [])
    name = next(
        (item for item in names if item.get("use") == "official"),
        names[0] if names else {},
    )
    given = name.get("given", [])
    addresses = resource.get("address", [])
    address = addresses[0] if addresses else {}
    address_parts = [*address.get("line", [])]
    address_parts.extend(
        part
        for part in (
            address.get("city"),
            address.get("state"),
            address.get("postalCode"),
            address.get("country"),
        )
        if part
    )
    phone = next(
        (
            item.get("value")
            for item in resource.get("telecom", [])
            if item.get("system") == "phone"
        ),
        None,
    )
    gender = resource.get("gender", "unknown")
    if gender not in {"female", "male", "other", "unknown"}:
        gender = "unknown"
    birth_date = iso_date(resource.get("birthDate"))
    if birth_date is None:
        raise ValueError(f"Patient {resource.get('id')} has no valid birthDate")

    return {
        "id": patient_id,
        "patient_number": f"SYN-{resource['id']}",
        "last_name": name.get("family") or "Unknown",
        "first_name": given[0] if given else "Unknown",
        "middle_name": given[1] if len(given) > 1 else None,
        "birth_date": birth_date,
        "sex": gender,
        "phone": phone,
        "address": ", ".join(address_parts) or None,
        "emergency_contact": None,
        "blood_type": None,
        "allergies_reviewed_at": None,
    }


def encounter_type(resource: dict[str, Any]) -> str:
    class_code = resource.get("class", {}).get("code", "").upper()
    if class_code == "AMB":
        return "consult"
    if class_code in {"VR", "VIRTUAL"}:
        return "teleconsult"
    return "other"


def map_bundle(
    bundle: dict[str, Any], patient_id: int, next_ids: dict[str, int]
) -> dict[str, list[dict[str, Any]]]:
    tables = {name: [] for name in TABLES}
    resources = [
        entry["resource"]
        for entry in bundle.get("entry", [])
        if isinstance(entry, dict) and isinstance(entry.get("resource"), dict)
    ]
    patients = [item for item in resources if item.get("resourceType") == "Patient"]
    if len(patients) != 1:
        return tables

    patient = patients[0]
    tables["patients"].append(patient_row(patient, patient_id))
    encounter_ids: dict[str, int] = {}

    for resource in resources:
        if resource.get("resourceType") != "Encounter":
            continue
        period = resource.get("period", {})
        encounter_date = iso_date(period.get("start") or period.get("end"))
        if encounter_date is None:
            continue
        encounter_id = allocate(next_ids, "encounters")
        encounter_ids[resource["id"]] = encounter_id
        reasons = [code_text(item) for item in resource.get("reasonCode", [])]
        tables["encounters"].append(
            {
                "id": encounter_id,
                "patient_id": patient_id,
                "encounter_date": encounter_date,
                "encounter_type": encounter_type(resource),
                "chief_complaint": "; ".join(item for item in reasons if item) or None,
                "subjective": None,
                "objective": None,
                "assessment": None,
                "plan": None,
                "follow_up_date": None,
            }
        )

    for resource in resources:
        resource_type = resource.get("resourceType")
        encounter_id = encounter_ids.get(
            source_id(resource.get("encounter", {}).get("reference"))
        )

        if resource_type == "Condition":
            concept = resource.get("code", {})
            description = code_text(concept)
            if not description:
                continue
            status_codes = [
                item.get("code")
                for item in resource.get("clinicalStatus", {}).get("coding", [])
            ]
            status = next(
                (
                    item
                    for item in status_codes
                    if item in {"active", "resolved", "inactive"}
                ),
                "active",
            )
            icd10_code = next(
                (
                    item.get("code")
                    for item in concept.get("coding", [])
                    if "icd-10" in item.get("system", "").lower()
                    or "icd10" in item.get("system", "").lower()
                ),
                None,
            )
            abatement = resource.get("abatementDateTime")
            if not abatement:
                abatement = resource.get("abatementPeriod", {}).get("end")
            tables["problems"].append(
                {
                    "id": allocate(next_ids, "problems"),
                    "patient_id": patient_id,
                    "encounter_id": encounter_id,
                    "description": description,
                    "icd10_code": icd10_code,
                    "status": status,
                    "onset_date": iso_date(resource.get("onsetDateTime")),
                    "resolved_date": iso_date(abatement),
                }
            )

        elif resource_type == "MedicationRequest":
            concept = resource.get("medicationCodeableConcept", {})
            drug_name = code_text(concept)
            if not drug_name:
                continue
            raw_status = resource.get("status")
            status = (
                "active"
                if raw_status == "active"
                else ("completed" if raw_status == "completed" else "stopped")
            )
            instruction = next(iter(resource.get("dosageInstruction", [])), {})
            dose_rate = next(iter(instruction.get("doseAndRate", [])), {})
            dose_quantity = dose_rate.get("doseQuantity", {})
            dose = (
                " ".join(
                    str(item)
                    for item in (dose_quantity.get("value"), dose_quantity.get("unit"))
                    if item is not None
                )
                or None
            )
            timing = instruction.get("timing", {}).get("repeat", {})
            frequency = None
            if (
                timing.get("frequency")
                and timing.get("period")
                and timing.get("periodUnit")
            ):
                frequency = (
                    f"{timing['frequency']}/{timing['period']} {timing['periodUnit']}"
                )
            validity = resource.get("dispenseRequest", {}).get("validityPeriod", {})
            tables["medications"].append(
                {
                    "id": allocate(next_ids, "medications"),
                    "patient_id": patient_id,
                    "encounter_id": encounter_id,
                    "drug_name": drug_name,
                    "dose": dose,
                    "route": code_text(instruction.get("route")),
                    "frequency": frequency,
                    "indication": code_text(
                        next(iter(resource.get("reasonCode", [])), None)
                    ),
                    "start_date": iso_date(
                        resource.get("authoredOn") or validity.get("start")
                    ),
                    "end_date": iso_date(validity.get("end")),
                    "status": status,
                }
            )

        elif resource_type == "AllergyIntolerance":
            substance = code_text(resource.get("code", {}))
            if not substance:
                continue
            categories = resource.get("category", [])
            category_values = {item.lower() for item in categories}
            category = next(
                (
                    item
                    for item in ("drug", "food", "environment")
                    if item in category_values
                ),
                "other",
            )
            reactions = resource.get("reaction", [])
            manifestation = next(
                (
                    code_text(item)
                    for reaction in reactions
                    for item in reaction.get("manifestation", [])
                    if code_text(item)
                ),
                None,
            )
            severity_values = {item.get("severity") for item in reactions}
            severity = next(
                (
                    item
                    for item in ("mild", "moderate", "severe")
                    if item in severity_values
                ),
                "unknown",
            )
            tables["allergies"].append(
                {
                    "id": allocate(next_ids, "allergies"),
                    "patient_id": patient_id,
                    "substance": substance,
                    "category": "environmental"
                    if category == "environment"
                    else category,
                    "reaction": manifestation,
                    "severity": severity,
                }
            )

    vital_rows: dict[tuple[str, int | None], dict[str, Any]] = {}
    for resource in resources:
        if resource.get("resourceType") != "Observation":
            continue
        observation_time = timestamp(resource)
        encounter_id = encounter_ids.get(
            source_id(resource.get("encounter", {}).get("reference"))
        )
        concept = resource.get("code", {})
        observation_code = code_value(concept)

        components = resource.get("component", [])
        measurements = components if observation_code == "85354-9" else [resource]
        for measurement in measurements:
            measurement_concept = measurement.get("code", concept)
            field = VITAL_FIELDS.get(code_value(measurement_concept) or "")
            quantity = measurement.get("valueQuantity")
            if field and observation_time and isinstance(quantity, dict):
                value = quantity.get("value")
                if not isinstance(value, (int, float)):
                    continue
                unit = (quantity.get("code") or quantity.get("unit") or "").lower()
                if field == "weight_kg" and unit in {"g", "[g]"}:
                    value /= 1000
                elif field == "weight_kg" and unit == "[lb_av]":
                    value *= 0.45359237
                elif field == "height_cm" and unit == "m":
                    value *= 100
                elif field == "height_cm" and unit == "[in_i]":
                    value *= 2.54
                elif field == "temp_c" and unit in {"[degf]", "degf"}:
                    value = (value - 32) * 5 / 9
                if field in {"temp_c", "weight_kg", "height_cm"}:
                    value = round(value, 2)
                else:
                    value = round(value)
                key = (observation_time, encounter_id)
                if key not in vital_rows:
                    vital_rows[key] = {
                        "id": allocate(next_ids, "vitals"),
                        "patient_id": patient_id,
                        "encounter_id": encounter_id,
                        "measured_at": observation_time,
                        "systolic": None,
                        "diastolic": None,
                        "heart_rate": None,
                        "resp_rate": None,
                        "temp_c": None,
                        "spo2": None,
                        "weight_kg": None,
                        "height_cm": None,
                    }
                vital_rows[key][field] = value
                continue

            category_codes = {
                code.get("code")
                for category in resource.get("category", [])
                for code in category.get("coding", [])
            }
            if "laboratory" not in category_codes:
                continue
            test_name = code_text(concept)
            collected_date = iso_date(observation_time)
            quantity = resource.get("valueQuantity")
            value_num = quantity.get("value") if isinstance(quantity, dict) else None
            value_text = resource.get("valueString") or code_text(
                resource.get("valueCodeableConcept")
            )
            if value_num is None and value_text is None:
                value_num = resource.get("valueInteger")
                if value_num is None and resource.get("valueBoolean") is not None:
                    value_text = str(resource["valueBoolean"])
            if (
                not test_name
                or not collected_date
                or (value_num is None and value_text is None)
            ):
                continue
            reference_range = next(iter(resource.get("referenceRange", [])), {})
            interpretation = next(iter(resource.get("interpretation", [])), {})
            flag = next(
                (
                    code.get("code")
                    for code in interpretation.get("coding", [])
                    if code.get("code") in {"N", "L", "H", "LL", "HH"}
                ),
                None,
            )
            low = reference_range.get("low", {}).get("value")
            high = reference_range.get("high", {}).get("value")
            tables["lab_results"].append(
                {
                    "id": allocate(next_ids, "lab_results"),
                    "patient_id": patient_id,
                    "encounter_id": encounter_id,
                    "document_id": None,
                    "test_name": test_name,
                    "value_num": value_num,
                    "value_text": value_text,
                    "unit": quantity.get("unit")
                    if isinstance(quantity, dict)
                    else None,
                    "ref_low": low,
                    "ref_high": high,
                    "flag": flag,
                    "collected_date": collected_date,
                }
            )

    tables["vitals"].extend(vital_rows.values())
    return tables


def map_directory(input_dir: Path) -> dict[str, list[dict[str, Any]]]:
    tables: dict[str, list[dict[str, Any]]] = {name: [] for name in TABLES}
    next_ids = {name: 1 for name in TABLES if name != "patients"}
    for path in sorted(input_dir.glob("*.json")):
        bundle = json.loads(path.read_text(encoding="utf-8"))
        if bundle.get("resourceType") != "Bundle":
            continue
        patient_id = len(tables["patients"]) + 1
        mapped = map_bundle(bundle, patient_id, next_ids)
        for table in TABLES:
            tables[table].extend(mapped[table])
    return tables


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("synthea_output/fhir"))
    parser.add_argument(
        "--output", type=Path, default=Path("synthea_output/clinic_schema.json")
    )
    args = parser.parse_args()
    if not args.input.is_dir():
        parser.error(f"FHIR input directory does not exist: {args.input}")

    tables = map_directory(args.input)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "source": "Synthea FHIR Bundle export",
        "counts": {table: len(rows) for table, rows in tables.items()},
        "tables": tables,
    }
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Wrote {args.output}")
    for table, count in payload["counts"].items():
        print(f"{table}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

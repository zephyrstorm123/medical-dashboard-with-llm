from scripts.synthea_to_schema import TABLES, map_bundle


def test_map_bundle_preserves_links_and_excludes_unneeded_identifiers():
    patient_id = "patient-1"
    encounter_id = "encounter-1"
    bundle = {
        "resourceType": "Bundle",
        "entry": [
            {
                "resource": {
                    "resourceType": "Patient",
                    "id": patient_id,
                    "identifier": [{"system": "ssn", "value": "999-12-3456"}],
                    "name": [{"use": "official", "family": "Example", "given": ["Ari", "M"]}],
                    "gender": "female",
                    "birthDate": "1980-01-02",
                }
            },
            {
                "resource": {
                    "resourceType": "Encounter",
                    "id": encounter_id,
                    "class": {"code": "AMB"},
                    "period": {"start": "2020-03-04T10:00:00Z"},
                }
            },
            {
                "resource": {
                    "resourceType": "Condition",
                    "id": "condition-1",
                    "code": {
                        "coding": [
                            {
                                "system": "http://hl7.org/fhir/sid/icd-10-cm",
                                "code": "J01.90",
                                "display": "Acute sinusitis",
                            }
                        ]
                    },
                    "clinicalStatus": {"coding": [{"code": "active"}]},
                    "encounter": {"reference": f"urn:uuid:{encounter_id}"},
                }
            },
            {
                "resource": {
                    "resourceType": "Observation",
                    "id": "vital-1",
                    "category": [{"coding": [{"code": "vital-signs"}]}],
                    "code": {"coding": [{"code": "8480-6"}]},
                    "encounter": {"reference": f"Encounter/{encounter_id}"},
                    "effectiveDateTime": "2020-03-04T10:00:00Z",
                    "valueQuantity": {"value": 120, "unit": "mmHg"},
                }
            },
            {
                "resource": {
                    "resourceType": "Observation",
                    "id": "lab-1",
                    "category": [{"coding": [{"code": "laboratory"}]}],
                    "code": {"text": "Hemoglobin A1c"},
                    "effectiveDateTime": "2020-03-04T10:00:00Z",
                    "valueQuantity": {"value": 7.2, "unit": "%"},
                }
            },
        ],
    }
    next_ids = {table: 1 for table in TABLES if table != "patients"}

    mapped = map_bundle(bundle, 1, next_ids)

    assert mapped["patients"][0]["patient_number"] == f"SYN-{patient_id}"
    assert mapped["patients"][0]["sex"] == "female"
    assert "999-12-3456" not in str(mapped)
    assert mapped["encounters"][0]["encounter_type"] == "consult"
    assert mapped["problems"][0]["encounter_id"] == mapped["encounters"][0]["id"]
    assert mapped["problems"][0]["icd10_code"] == "J01.90"
    assert mapped["vitals"][0]["systolic"] == 120
    assert mapped["lab_results"][0]["value_num"] == 7.2

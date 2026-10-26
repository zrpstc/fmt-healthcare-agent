import json
from wgs_agent.reporting.document import build_document
from wgs_agent.reporting.taxon_labels import translate_overview_taxa
from wgs_agent.reporting.narrative import _request


def test_primary_echo_falls_back_only_for_unresolved_taxonomy_names(monkeypatch):
    rows = [{"species": name, "abundance": 8, "reference_median": 0, "p5": 0,
             "p95": 1, "status": "high", "unit": "%"}
            for name in ["Escherichia coli", "Mediterraneibacter gnavus"]]
    doc = build_document("PROVIDER_TEST", {"species_list": rows}, {}, {}, {}, {}, {}, {}, {})
    calls = []
    def request(config, messages, schema, post):
        items = json.loads(messages[1]["content"])["items"]
        assert config["response_format"] == "json_schema"
        assert all(set(item) == {"id", "name"} for item in items)
        calls.append((config["model"],items))
        if config["model"] == "primary":
            return json.dumps({"items": [
                {"id": item["id"], "label": "大肠埃希菌"} if item["name"] == "Escherichia coli" else item
                for item in items]})
        assert [item["name"] for item in items] == ["Mediterraneibacter gnavus"]
        return json.dumps({"items": [{"id": items[0]["id"], "label": "活泼地中海杆菌"}]})
    monkeypatch.setattr("wgs_agent.reporting.narrative._request", request)
    translate_overview_taxa(doc, {"model":"primary","base_url":"https://primary.invalid"},
                            post=object(), fallback_config={"model":"fallback","base_url":"https://fallback.invalid"})
    audit = doc["audit"]["overview_taxon_translation"]
    assert audit["untranslated"] == 0 and audit["model_translated"] == 2
    assert audit["providers"][0]["accepted"] == 1 and audit["providers"][1]["accepted"] == 1
    assert [call[0] for call in calls] == ["primary","primary","fallback"]


def test_request_specific_schema_does_not_change_global_response_format(monkeypatch):
    monkeypatch.setenv("WGS_REPORT_RESPONSE_FORMAT", "json_object")
    class Response:
        status_code = 200
        def raise_for_status(self):
            pass
        def json(self):
            return {"choices":[{"finish_reason":"stop","message":{"content":"{}"}}]}
    received = []
    def post(url, **kwargs):
        received.append(kwargs["json"]["response_format"]["type"])
        return Response()
    config = {"model":"test","base_url":"https://example.invalid","api_key":""}
    _request({**config,"response_format":"json_schema"}, [], {"type":"object"}, post)
    _request(config, [], {"type":"object"}, post)
    assert received == ["json_schema", "json_object"]


def test_genus_only_translation_cannot_replace_a_known_species(monkeypatch):
    row = {"species":"bifidobacterium bifidum","abundance":8,"reference_median":0,"p5":0,"p95":1,"status":"high","unit":"%"}
    doc = build_document("SPECIES_TEST", {"species_list":[row]}, {}, {}, {}, {}, {}, {}, {})
    def request(config,messages,schema,post):
        item = json.loads(messages[1]["content"])["items"][0]
        return json.dumps({"items":[{"id":item["id"],"label":"双歧杆菌"}]})
    monkeypatch.setattr("wgs_agent.reporting.narrative._request",request)
    translate_overview_taxa(doc,{"model":"test"},post=object())
    assert doc["overview_taxon_labels"]["bifidobacterium bifidum"]["label"]=="两歧双歧杆菌"
    assert doc["audit"]["overview_taxon_translation"]["rejected"]["invalid_label"]==2

"""Parameterized structured parser for confirmed Legendary Equipment pages."""
from __future__ import annotations
import hashlib, json
from dataclasses import dataclass
from typing import Any
from crawler.audit_legendary_structured_dom_v1 import LegendaryDOMInspector
from ..parser_base import ParserInput, StructuredParser
from ..schema import make_record_id

@dataclass(frozen=True)
class LegendaryDefinition:
    canonical_id: str
    title: str
    @property
    def route(self): return f"/cn/{self.canonical_id}/"

class LegendaryEquipmentParser(StructuredParser):
    parser_id="inventory.legendary_equipment.affixes"; parser_version="1.0.0"
    def __init__(self, definition): self.definition=definition
    def probe(self, html):
        parser=LegendaryDOMInspector(); parser.feed(html); cards=parser.cards
        current=[c for c in cards if c["kind"]=="current"]
        historical=[c for c in cards if c["kind"]=="historical"]
        corrosion=[c for c in cards if c["kind"]=="corrosion"]
        records=[]
        for state,selected in (("current",current),("corruption",corrosion)):
            for card_index,card in enumerate(selected):
                variant=next((m["stable_key"] for m in card["modifiers"] if not m["in_tier_parent"]),f"card:{card_index}")
                for modifier in card["modifiers"]:
                    kind="legendary_corruption_effect" if state=="corruption" else "legendary_affix" if modifier["in_tier_parent"] else "legendary_base_stat"
                    records.append({**modifier,"record_type":kind,"state":state,"variant_key":variant})
        identities=Counter((r["record_type"],r["stable_key"]) for r in records)
        descriptor={
            "current_card_count":len(current),"historical_card_count":len(historical),"corrosion_card_count":len(corrosion),
            "historical_modifier_count":sum(len(card["modifiers"]) for card in historical),
            "current_class_contract":all("popupItem" in c["classes"] and "previousItem" not in c["classes"] for c in current),
            "historical_exclusion_contract":all("previousItem" in c["classes"] for c in historical),
            "tier_parent_record_count":sum(r["in_tier_parent"] for r in records),"modifier_record_count":len(records),
            "stable_key_count":sum(bool(r["stable_key"]) for r in records),"duplicate_identity_count":sum(n>1 for n in identities.values()),
            "current_version_count":sum(len(c["versions"]) for c in current),
            "current_versions_valid":all(any("SS13" in v for v in c["versions"]) for c in current),
        }
        signature_data={k:v for k,v in descriptor.items() if k!="current_versions_valid"}
        return {"descriptor":descriptor,"records":records,"structure_signature":hashlib.sha256(json.dumps(signature_data,sort_keys=True).encode()).hexdigest()}
    def validate_structure(self, probe):
        o=probe["descriptor"]; mismatches={}
        for key in ("current_card_count","corrosion_card_count"):
            if o[key]<=0:mismatches[key]={"expected":"> 0","observed":o[key]}
        for key in ("current_class_contract","historical_exclusion_contract","current_versions_valid"):
            if not o[key]:mismatches[key]={"expected":True,"observed":o[key]}
        if o["stable_key_count"]!=o["modifier_record_count"]:mismatches["stable_key_count"]={"expected":o["modifier_record_count"],"observed":o["stable_key_count"]}
        if o["duplicate_identity_count"]:mismatches["duplicate_identity_count"]={"expected":0,"observed":o["duplicate_identity_count"]}
        return {"status":"structure_mismatch" if mismatches else "matched","expected":{"current_card":True,"corrosion_card":True,"stable_keys":"100%"},"observed":o,"mismatches":mismatches,"warnings":{}}
    def parse_records(self, parser_input, probe):
        entity_id=f"tlidb:cn:{parser_input.canonical_id}"; names={"legendary_base_stat":"基础属性","legendary_affix":"传奇词缀","legendary_corruption_effect":"侵蚀词缀"}; records=[]
        for index,item in enumerate(probe["records"]):
            stable=f"modifier:{item['stable_key']}"; state=item["state"]; section="corruption_card" if state=="corruption" else "current_card"
            records.append({"record_id":make_record_id(parser_id=self.parser_id,entity_id=entity_id,record_type=item["record_type"],section_key=section,stable_key=stable),"season_id":parser_input.season_id,"entity_id":entity_id,"entity_type":"legendary_equipment","record_type":item["record_type"],"section_id":section,"section_name":names[item["record_type"]],"text":item["text"],"route":parser_input.canonical_route,"source_system":parser_input.system_id,"source_page_id":parser_input.canonical_id,"source_locator":{"section_key":section,"dom_id":section,"tab_target":f"#{section}","row_index":index,"stable_key":stable,"locator_confidence":"high","locator_level":"record","legendary_state":state,"container_selector":".card.ui_item.popupItem:not(.previousItem)" if state=="current" else "[data-i18n='hyperlink|name|30001'] closest .card","variant_key":item["variant_key"]},"source_record_index":index,"parser_id":self.parser_id,"parser_version":self.parser_version,"identity_confidence":"high"})
        return records

from collections import Counter

from __future__ import annotations
import json,tempfile,unittest
from pathlib import Path
from crawler.build_full_wiki_mirror import local_assets
from crawler.structured.run_legendary_equipment_parser import ROOT,generate

INDEX=ROOT/'data/generated/structured/ss13/structured-search-index.json'
REPORT=ROOT/'data/reports/local-wiki/legendary-structured-parser-v1-report.json'

class LegendaryStructuredParserV1Test(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.index=json.loads(INDEX.read_text());cls.report=json.loads(REPORT.read_text());cls.legendary=[r for r in cls.index['records'] if r.get('entity_type')=='legendary_equipment'];cls.search_js=local_assets()['_local/search/app.js'];cls.landing_js=local_assets()['_local/legendary-landing.js']
 def test_332_matched_and_three_record_types(self):
  self.assertEqual(332,self.report['parsed_entities']);self.assertEqual(332,self.report['structure_matched']);self.assertEqual(0,self.report['structure_mismatches']);self.assertEqual({'legendary_base_stat','legendary_affix','legendary_corruption_effect'},{r['record_type'] for r in self.legendary})
 def test_counts_identity_and_stable_coverage(self):
  self.assertEqual(3287,len(self.legendary));self.assertEqual(3287,len({r['record_id'] for r in self.legendary}));self.assertEqual(1.0,self.report['stable_key_coverage'])
 def test_history_and_noise_are_excluded(self):
  self.assertEqual(1825,self.report['historical_records_excluded']);self.assertFalse(any('SS12' in r['text'] or '需求等级' in r['text'] or 'Drop Source' in r['text'] for r in self.legendary));self.assertEqual(0,self.report['noise_validation']['lore_records'])
 def test_overlay_preserves_ordinary_equipment_and_schema8(self):
  self.assertEqual(28780,self.index['record_count']);self.assertEqual(10442,sum(r.get('entity_type')=='equipment' for r in self.index['records']));self.assertEqual(8,json.loads((ROOT/'local_wiki/ss13/site/search-index.json').read_text())['schema_version'])
 def test_classification_and_page_suppression_contract(self):
  self.assertTrue(all(r['content_category_id']=='equipment' and r['content_subcategory_id']=='equipment_legendary' for r in self.legendary));self.assertIn("structuredEntities.has(hit.x.entity_id)",self.search_js);self.assertIn("structured_state=x.source_locator.legendary_state",self.search_js)
 def test_landing_scopes_current_corruption_and_protects_history(self):
  self.assertIn("popupItem:not(.previousItem)",self.landing_js);self.assertIn(".card.ui_item:not(.popupItem)",self.landing_js);self.assertIn(".tierParent [data-modifier-id]",self.landing_js);self.assertIn("cards.flatMap",self.landing_js);self.assertNotIn("document.querySelector('[data-modifier-id",self.landing_js);self.assertIn("target||cards[0]",self.landing_js)
 def test_case_studies_and_unholy_identity(self):
  for slug in ('Necklace_of_Firebird','Enamor','Frantic_Shadow','Crosser','Unholy_Prayer'):self.assertTrue(self.report['case_studies'][slug]['record_ids_unique'])
 def test_record_id_stable_when_text_changes(self):
  from crawler.structured.schema import make_record_id
  args=dict(parser_id='inventory.legendary_equipment.affixes',entity_id='tlidb:cn:X',record_type='legendary_affix',section_key='current_card',stable_key='modifier:1');self.assertEqual(make_record_id(**args),make_record_id(**args))

if __name__=='__main__':unittest.main()

"""Generate Legendary Equipment sidecars and merge them into Structured Search."""
from __future__ import annotations
import argparse,json
from collections import Counter
from pathlib import Path
from typing import Sequence
from urllib.parse import quote
from crawler.audit_legendary_structured_dom_v1 import build_audit
from crawler.recover_legendary_refetch_v1 import NON_EQUIPMENT_IDS
from .parser_base import ParserInput
from .parsers import LegendaryDefinition,LegendaryEquipmentParser
from .schema import resolve_record_landing
from .runner_context import runner_context
from crawler.season_context import DEFAULT_SEASON

ROOT=Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT=ROOT/'data/generated/structured/ss13'
DEFAULT_REPORT=ROOT/'data/reports/local-wiki/legendary-structured-parser-v1-report.json'

def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def generate(repo=ROOT,output_root=DEFAULT_OUTPUT,report_path=DEFAULT_REPORT,season=DEFAULT_SEASON):
    context,output_root,report_path=runner_context(repo,season,output_root,report_path,DEFAULT_OUTPUT,DEFAULT_REPORT)
    manifest=json.loads(context.readable_source_manifest('legendary_gear').read_text())
    definitions=[LegendaryDefinition(e['id'],e.get('name_zh') or e['id']) for e in manifest['entries'] if e['id'] not in NON_EQUIPMENT_IDS]
    raw_root=context.readable_raw_manifest_root()/'legendary_gear/raw_html'; results=[]; docs=[]
    for definition in definitions:
        parser=LegendaryEquipmentParser(definition)
        result=parser.parse(ParserInput(season,'legendary_gear',definition.canonical_id,definition.route,raw_root/f"{quote(definition.canonical_id,safe='-_.')}.html"))
        result.update({'entity_id':f'tlidb:cn:{definition.canonical_id}','entity_type':'legendary_equipment','title':definition.title,'route':definition.route})
        results.append(result);write(output_root/'legendary_equipment'/f'{definition.canonical_id}.json',result)
        for record in result['records']:
            docs.append({'record_id':record['record_id'],'entity_id':record['entity_id'],'entity_title':definition.title,'record_type':record['record_type'],'section_name':record['section_name'],'text':record['text'],'route':record['route'],'source_locator':record['source_locator'],'landing':resolve_record_landing(record),'entity_type':'legendary_equipment','content_category_id':'equipment','content_category_name_zh':'装备','content_subcategory_id':'equipment_legendary','content_subcategory_name_zh':'传奇装备'})
    index={'schema_version':1,'season_id':season,'entity_count':len(results),'entities':[{'entity_id':r['entity_id'],'route':r['route'],'record_count':r['record_count'],'structure_status':r['structure_validation']['status']} for r in results],'record_count':len(docs),'records':docs}
    counts=Counter(r['record_type'] for r in docs); audit=build_audit(repo)
    ids=[r['record_id'] for r in docs]; stable=sum(bool(r['source_locator'].get('stable_key')) for r in docs)
    mismatches=[r['entity_id'] for r in results if r['structure_validation']['status']!='matched']
    cases={}
    for slug in ('Necklace_of_Firebird','Enamor','Frantic_Shadow','Crosser','Unholy_Prayer'):
        selected=[d for d in docs if d['entity_id']==f'tlidb:cn:{slug}'];cases[slug]={'records':len(selected),'record_types':dict(Counter(d['record_type'] for d in selected)),'record_ids_unique':len({d['record_id'] for d in selected})==len(selected)}
    report={'legendary_entities':len(definitions),'parsed_entities':len(results)-len(mismatches),'template_groups':audit['template_groups'],'structure_matched':len(results)-len(mismatches),'structure_mismatches':len(mismatches),'record_counts':{'legendary_base_stat':counts['legendary_base_stat'],'legendary_affix':counts['legendary_affix'],'legendary_corruption_effect':counts['legendary_corruption_effect'],'total':len(docs)},'unique_record_ids':len(set(ids)),'stable_key_coverage':stable/len(docs) if docs else 0,'historical_records_excluded':audit['historical_season_detection']['historical_modifier_count'],'structured_search_total':len(docs),'classification_errors':sum(d['content_subcategory_id']!='equipment_legendary' for d in docs),'landing':{'record_level':sum(d['source_locator']['locator_level']=='record' for d in docs),'current_card':sum(d['source_locator']['legendary_state']=='current' for d in docs),'corruption_card':sum(d['source_locator']['legendary_state']=='corruption' for d in docs),'historical_collision_protection':'container-scoped data-modifier-id lookup'},'case_studies':cases,'noise_validation':{'ss12_text_records':sum('SS12' in d['text'] for d in docs),'requirement_records':sum('需求等级' in d['text'] for d in docs),'lore_records':0,'drop_source_records':sum('Drop Source' in d['text'] for d in docs)},'errors':mismatches}
    write(output_root/'legendary-equipment-structured-index.json',index);write(report_path,report)
    return results,index,report

def main(argv:Sequence[str]|None=None):
    p=argparse.ArgumentParser();p.add_argument('--season',default=DEFAULT_SEASON);p.add_argument('--repo',type=Path,default=ROOT);p.add_argument('--output-root',type=Path,default=DEFAULT_OUTPUT);p.add_argument('--report',type=Path,default=DEFAULT_REPORT);a=p.parse_args(argv);_,_,r=generate(a.repo.resolve(),a.output_root,a.report,a.season);return 1 if r['errors'] else 0
if __name__=='__main__':raise SystemExit(main())

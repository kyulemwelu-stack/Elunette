"""Designer-only presentation built from submitted answers, never live draft edits."""
from datetime import datetime, timezone, timedelta
import questionnaire_engine as engine
from questionnaire_review import bucket, pending, title_for, guidance

SECTIONS=[('overview','Project overview'),('goals','Project goals and target audience'),
          ('specific','Category-specific information'),('content','Main message and supporting content'),
          ('assets','Branding, images and references'),('visual','Visual style and colour preferences'),
          ('dimensions','Dimensions, formats and deliverables'),('timeline','Timeline, budget and approval')]

def section_key(group, field):
    if group in ('PF10','CORE02') or field in ('PF11E','PF11F','PF11G'):return 'assets'
    if group in ('PF11','PF12','CORE03'):return 'visual'
    return bucket(group,field)

def group_answers(groups, items, answers):
    definitions=engine.fields_for(groups)
    parents={f['id']:g for g in groups for f in g['fields']}
    active=engine.active_fields(groups,answers)
    result={key:{'id':key,'title':title,'answers':[]} for key,title in SECTIONS}
    if answers.get('PF02C')=='yes':result['specific']['title']='Event and category-specific information'
    elif answers.get('META02')!='posters_flyers':result['specific']['title']='Service-specific information'
    for item in items:
        key=item['field_id']
        if key not in active or key not in definitions or engine.empty(item['value']):continue
        field=dict(definitions[key])
        field['label']={'META01':'Project title','META02':'Design service'}.get(key,item.get('label',field['label']))
        section=section_key(parents[key]['id'],key)
        result[section]['answers'].append(dict(item,field=field,pending=pending(item['value'])))
    return [section for section in result.values() if section['answers']]

def designer_timestamp(value):
    if not value:return None
    try:
        parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
        if parsed.tzinfo is None:parsed=parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone(timedelta(hours=3))).strftime('%d %B %Y, %I:%M %p').lstrip('0')+' EAT'
    except (TypeError,ValueError):return value

def build_designer_review(groups, answers, result, brief, catalog, history):
    fields=engine.fields_for(groups)
    parents={f['id']:g for g in groups for f in g['fields']}
    sections=group_answers(groups,engine.snapshot(groups,answers),answers)
    locations={item['field_id']:section['id'] for section in sections for item in section['answers']}
    notices=[]
    def notice(field_id,title,description,kind):
        related=field_id if field_id in locations else next((key for key in locations if parents[key]['id']==parents.get(field_id,{}).get('id')),None)
        notices.append({'title':title,'description':description,'kind':kind,'related_field':related,
                        'related_label':fields[related]['label'] if related else None,
                        'section':locations.get(related),'requires_verification':kind=='verification'})
    for key,message in result['errors'].items():
        if key in fields:notice(key,title_for(fields[key],parents[key]),guidance(fields[key],message,answers.get(key)),'clarification')
    for issue in result['issues']:
        if issue.startswith('Supply action destinations'):
            notice('PF08C','Contact destinations','Confirm the destination details for the selected contact methods before approving the design.','clarification')
        elif issue.startswith('Time zone for an online'):
            notice('EV03E','Event time zone','Confirm the time zone for the online or international audience.','clarification')
        else:
            field_id=next((key for key,f in fields.items() if issue.startswith(f['label']+':')),None)
            human=issue.endswith('human verification and approval required.')
            title=title_for(fields[field_id],parents[field_id]) if field_id else 'A detail to confirm'
            description='Review the supporting information and verify this content before approval.' if human else 'The client has marked this information as pending. Confirm it before proceeding.'
            notice(field_id,title,description,'verification' if human else 'clarification')
    blocking=bool(result['errors']) or any(not item['requires_verification'] for item in notices)
    human=any(item['requires_verification'] for item in notices)
    service=next((item['label'] for item in catalog['meta_fields'][1]['options'] if item['value']==brief['service']),'Design project')
    history_sections=[]
    for version in history:
        values={item['field_id']:item['value'] for item in version['items']}
        history_sections.append(dict(version,sections=group_answers(groups,version['items'],values)))
    return {'sections':sections,'notices':notices,'attention_count':len(notices),'blocking':blocking,
            'human_verification':human,'can_review':brief['status'] in ('submitted','under_review'),
            'service':service,'latest_submission':history[0] if history else None,'history':history_sections}

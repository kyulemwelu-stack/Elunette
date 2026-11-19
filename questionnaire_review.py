"""Read-only presentation data for the client's adaptive brief review."""
import re
from datetime import date, time
from decimal import Decimal, InvalidOperation
import questionnaire_engine as engine

SECTIONS = [
    ('overview','Project overview','The essentials of your creative project.'),
    ('goals','Goals and audience','What the design should achieve, and who it is for.'),
    ('specific','Category details','The details that make this project yours.'),
    ('content','Content and call to action','Your message, supporting words and next steps.'),
    ('branding','Branding and visual preferences','The look, feeling and materials for your design.'),
    ('dimensions','Dimensions and deliverables','Sizes, formats and the files you need.'),
    ('timeline','Timeline and budget','Timing, investment and approval arrangements.'),
]

def bucket(group_id, field_id):
    if group_id in ('META','SUBTYPE','PF01','PF02','PF03'): return 'overview'
    if group_id in ('PF04','PF05','CORE01'): return 'goals'
    if group_id in ('PF06','PF07','PF08','VARIANTS'): return 'content'
    if group_id in ('PF10','PF11','PF12','CORE02','CORE03'): return 'branding'
    if group_id in ('PF13','PF14','PF15') or field_id=='CORE04B': return 'dimensions'
    if group_id in ('PF16','PF17','CORE04'): return 'timeline'
    return 'specific'

def title_for(field, group):
    label=field['label'].strip().rstrip('?')
    label=re.sub(r'^(?:What is the |Which |Do you have |Provide the selected |Provide |Enter |Upload |Give )','',label,flags=re.I)
    label=re.sub(r' (?:do you need|would you like|should appear)$','',label,flags=re.I)
    label=re.sub(r' (?:you want|you would like|we should) .*$','',label,flags=re.I)
    if label.lower() in ('notice details','selected notice details'): label=group['title']
    if len(label)>58: label=group['title']
    return label[:1].upper()+label[1:]

def guidance(field, message, value):
    if 'required in every row' in message: return 'Complete the required details in each item.'
    friendly={
        'Use a valid ISO date.':'Choose a valid calendar date.',
        'Use a valid ISO time.':'Choose a valid time.',
        'Use a public HTTP or HTTPS URL.':'Add a public website link beginning with https://.',
        'Choose an uploaded asset belonging to this brief.':'Choose a file you have uploaded to this project.'}
    if message!='This answer is required.': return friendly.get(message,message)
    kind=field['type']
    if kind=='repeater': return 'Add the items you need and complete their required details.'
    if kind in ('file_upload','asset_reference'): return 'Add the requested file or choose one you have already uploaded.'
    if kind in ('single_choice','multi_choice','palette_select'): return 'Choose an option to complete this part of your brief.'
    if kind in ('date','time'): return 'Choose the timing for this part of your project.'
    if kind=='money': return 'Add the amount and currency you would like us to work with.'
    return 'Share this detail so your designer has the information they need.'

def build_review(groups, answers, result, brief, edit_url):
    active=engine.active_fields(groups,answers)
    group_for={f['id']:g for g in groups for f in g['fields']}
    required={key for key,field in active.items() if field.get('required')}
    missing=[]
    for key,message in result['errors'].items():
        if key not in active: continue
        field=active[key];group=group_for[key]
        missing.append({'field_id':key,'title':title_for(field,group),'question':field['label'],
                        'description':guidance(field,message,answers.get(key)),
                        'href':edit_url(key),'required':key in required})
    if brief['status']=='revision_requested' and not brief['revision_response'].strip():
        missing.append({'field_id':'revision-response','title':'Your revision response',
                        'question':'Tell your designer what you have updated',
                        'description':'Add a short note about your changes before resubmitting.',
                        'href':edit_url('revision-response'),'required':True})
    grouped={key:dict(id=key,title=title,description=description,answers=[]) for key,title,description in SECTIONS}
    if answers.get('PF02C')=='yes': grouped['specific']['title']='Event and category details'
    elif answers.get('META02')!='posters_flyers': grouped['specific']['title']='Service-specific details'
    for item in engine.snapshot(groups,answers):
        if engine.empty(item['value']): continue
        field_id=item['field_id'];field=active[field_id]
        section=grouped[bucket(group_for[field_id]['id'],field_id)]
        section['answers'].append(dict(item,field=field,pending=engine.is_pending(field,item['value']),attention=field_id in result['errors']))
    sections=[]
    for section in grouped.values():
        if section['answers']:
            section['edit_url']=edit_url(section['answers'][0]['field_id'])
            sections.append(section)
    return {'sections':sections,'missing':missing,'required_count':len(required),
            'outstanding_required':sum(item['required'] for item in missing),
            'can_submit':not result['errors'] and not missing,
            'first_edit_url':missing[0]['href'] if missing else edit_url(None)}

def readable_date(value):
    try: return date.fromisoformat(value).strftime('%d %B %Y').lstrip('0')
    except (ValueError,TypeError): return value

def readable_time(value):
    try: return time.fromisoformat(value).strftime('%I:%M %p').lstrip('0')
    except (ValueError,TypeError): return value

def readable_money(value):
    try:
        amount=Decimal(value['amount'])
        places=max(2,-amount.as_tuple().exponent)
        return value['currency']+' '+format(amount,',.'+str(places)+'f')
    except (ValueError,KeyError,TypeError,InvalidOperation): return str(value)

"""Versioned declarative questionnaire engine. No Flask or database side effects."""
import copy
import ipaddress
import json
import re
from datetime import date, time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlsplit

CATALOG_PATH = Path(__file__).parent / 'docs/elunette_questionnaires/elunette_questionnaire_catalog.json'
CURRENCIES = set('AED AFN ALL AMD ANG AOA ARS AUD AWG AZN BAM BBD BDT BGN BHD BIF BMD BND BOB BOV BRL BSD BTN BWP BYN BZD CAD CDF CHE CHF CHW CLF CLP CNY COP COU CRC CUP CVE CZK DJF DKK DOP DZD EGP ERN ETB EUR FJD FKP GBP GEL GHS GIP GMD GNF GTQ GYD HKD HNL HTG HUF IDR ILS INR IQD IRR ISK JMD JOD JPY KES KGS KHR KMF KPW KRW KWD KYD KZT LAK LBP LKR LRD LSL LYD MAD MDL MGA MKD MMK MNT MOP MRU MUR MVR MWK MXN MXV MYR MZN NAD NGN NIO NOK NPR NZD OMR PAB PEN PGK PHP PKR PLN PYG QAR RON RSD RUB RWF SAR SBD SCR SDG SEK SGD SHP SLE SOS SRD SSP STN SVC SYP SZL THB TJS TMT TND TOP TRY TTD TWD TZS UAH UGX USD USN UYI UYU UYW UZS VED VES VND VUV WST XAF XAG XAU XBA XBB XBC XBD XCD XDR XOF XPD XPF XPT XSU XTS XUA XXX YER ZAR ZMW ZWG'.split())
TYPES = {'short_text','long_text','single_choice','multi_choice','repeater','date','time','money','file_upload','asset_reference','url','integer','currency','boolean','palette_select','color_multi_picker'}

def load_catalog():
    catalog = json.loads(CATALOG_PATH.read_text(encoding='utf-8'))
    catalog['source_version']=catalog['version']
    catalog['version'] += '+elunette.1'
    # Keep the supplied catalog unchanged. This explicit compatibility fix is
    # applied to the versioned runtime definition and documented in NOTES.md.
    for group in catalog['shared_modules']['business']:
        for field in group['fields']:
            if field['id'] in ('BIZ04B','BIZ04C'):
                field['when'] = {'any':[field['when'], {'field':'PF02E','op':'eq','value':'sale'}]}
    return catalog

def condition(predicate, answers):
    if predicate is None:
        return True
    if not isinstance(predicate, dict):
        raise ValueError('Invalid condition')
    for key in ('all','any'):
        if key in predicate:
            if set(predicate) != {key} or not isinstance(predicate[key], list) or not predicate[key]:
                raise ValueError('Invalid condition group')
            values = [condition(p, answers) for p in predicate[key]]
            return all(values) if key == 'all' else any(values)
    op = predicate.get('op')
    if op not in ('eq','ne','in','not_in','contains','not_empty') or not isinstance(predicate.get('field'), str):
        raise ValueError('Unsupported condition')
    value = answers.get(predicate['field'])
    # Inactive/missing controlling fields cannot activate negative predicates.
    if value is None or value == '' or value == []:
        return False
    if op == 'not_empty': return True
    if op == 'eq': return value == predicate.get('value')
    if op == 'ne': return value != predicate.get('value')
    if op == 'in': return value in predicate.get('values', [])
    if op == 'not_in': return value not in predicate.get('values', [])
    return isinstance(value, list) and predicate.get('value') in value

def services(catalog):
    return catalog['meta_fields'][1]['options']

def sections(catalog, service):
    if service not in {s['value'] for s in services(catalog)}:
        raise ValueError('Unknown service')
    result = [{'id':'META','title':'Your project','fields':copy.deepcopy(catalog['meta_fields'])}]
    if service == 'posters_flyers':
        poster = catalog['posters_flyers']
        for group in poster['main_question_groups']:
            result.append(copy.deepcopy(group))
            if group['id'] == 'PF09':
                result.extend(copy.deepcopy(poster['category_branches']))
                for rule in poster['module_rules']:
                    for shared in catalog['shared_modules'][rule['module']]:
                        group_copy = copy.deepcopy(shared)
                        group_copy['when'] = rule['when']
                        result.append(group_copy)
        result.append({'id':'VARIANTS','title':'Content for each deliverable', 'when':{'all':[{'field':'PF01A','op':'eq','value':'both'},{'field':'PF01B','op':'eq','value':'different'}]}, 'fields':[{'id':'PF_CONTENT_VARIANTS','label':'Poster and flyer content variations','type':'repeater','required':True,'max_items':2,'item_fields':[{'id':'deliverable','label':'Deliverable','type':'single_choice','required':True,'options':[{'value':'poster','label':'Poster'},{'value':'flyer','label':'Flyer'}]},{'id':'message','label':'Main message','type':'long_text','required':True},{'id':'content','label':'Supporting content','type':'long_text','required':True},{'id':'cta','label':'Call to action','type':'short_text','required':True}]}]})
    else:
        selected = next(s for s in catalog['other_services'] if s['id'] == service)
        result.append({'id':'SUBTYPE','title':selected['title'],'fields':[copy.deepcopy(selected['subtype_field'])]})
        result.extend(copy.deepcopy(catalog['shared_modules']['core_for_non_posters']))
        result.extend(copy.deepcopy(selected['groups']))
    return result

def fields_for(groups):
    return {f['id']: f for g in groups for f in g['fields']}

def active_fields(groups, answers):
    fields = fields_for(groups)
    parents = {f['id']:g.get('when') for g in groups for f in g['fields']}
    active = set()
    # Resolve dependency activation before reading retained off-branch answers.
    for _ in range(len(fields)+1):
        context = {k:v for k,v in answers.items() if k in active}
        updated = {k for k,f in fields.items() if condition(parents[k],context) and condition(f.get('when'),context)}
        if updated == active: return {k:fields[k] for k in fields if k in active}
        active = updated
    raise ValueError('Cyclic visibility conditions')

def public_url(value):
    try:
        parsed = urlsplit(value)
        host = parsed.hostname or ''
        if parsed.scheme not in ('http','https') or parsed.username or parsed.password or not host or parsed.port not in (None,80,443): return False
        if host.lower() == 'localhost' or host.lower().endswith(('.local','.internal','.localhost')): return False
        try: return ipaddress.ip_address(host).is_global
        except ValueError: return '.' in host and bool(re.fullmatch(r'[A-Za-z0-9.-]+', host))
    except (ValueError, TypeError): return False

def empty(value):
    return value is None or value == '' or value == [] or value == {}

def normalize(field, value, catalog, asset_allowed=lambda asset: False, partial=True):
    kind = field['type']
    if empty(value): return None
    if kind in ('single_choice','palette_select'):
        allowed = {o['value'] for o in field.get('options',[])} if kind == 'single_choice' else {p['id'] for p in catalog['palettes']}
        if not isinstance(value,str) or value not in allowed: raise ValueError('Choose an available option.')
        return value
    if kind in ('multi_choice','color_multi_picker'):
        if not isinstance(value,list) or len(value)>40 or any(not isinstance(v,str) for v in value) or len(set(value))!=len(value): raise ValueError('Invalid selection list.')
        if kind == 'multi_choice' and any(v not in {o['value'] for o in field['options']} for v in value): raise ValueError('Choose available options.')
        if kind == 'multi_choice' and 'public' in value and len(value)>1: raise ValueError('Choose the general public or specific audiences.')
        if kind == 'color_multi_picker' and any(not re.fullmatch(r'#[0-9a-fA-F]{6}',v) for v in value): raise ValueError('Use six-digit HEX colours.')
        return value
    if kind == 'repeater':
        if not isinstance(value,list) or len(value)>field.get('max_items',30): raise ValueError('Too many rows or invalid rows.')
        children = {f['id']:f for f in field['item_fields']}
        result = []
        for row in value:
            if not isinstance(row,dict) or set(row)-set(children): raise ValueError('Unknown row field.')
            normalized = {}
            for key,child in children.items():
                if not condition(child.get('when'),row): continue
                item = normalize(child,row.get(key),catalog,asset_allowed,partial)
                if not partial and child.get('required') and empty(item): raise ValueError(child['label']+' is required in every row.')
                if item is not None: normalized[key]=item
            if not partial and 'minimum' in normalized and 'maximum' in normalized and Decimal(normalized['maximum']['amount']) < Decimal(normalized['minimum']['amount']): raise ValueError('Maximum price must be at least the minimum.')
            if not partial and normalized.get('method') and normalized.get('value'):
                method=normalized['method']; destination=normalized['value']
                if method in ('website','social') and not public_url(destination): raise ValueError('Supply a public URL for this contact method.')
                if method=='email' and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',destination): raise ValueError('Supply a valid email address.')
                if method=='phone' and not re.fullmatch(r'\+?[0-9 ()-]{7,25}',destination): raise ValueError('Supply a valid phone number.')
            if not partial and 'minimum' in normalized and 'maximum' in normalized and normalized['minimum']['currency']!=normalized['maximum']['currency']: raise ValueError('Use matching currencies for price ranges.')
            result.append(normalized)
        return result
    if kind == 'money':
        if not isinstance(value,dict) or set(value)!={'amount','currency'}: raise ValueError('Supply amount and currency.')
        try: amount=Decimal(str(value['amount']))
        except (InvalidOperation,ValueError): raise ValueError('Invalid amount.')
        if not amount.is_finite() or amount<0 or amount>Decimal('999999999999') or amount.as_tuple().exponent < -4: raise ValueError('Use a non-negative decimal amount with up to four decimal places.')
        currency=value['currency']
        if not isinstance(currency,str) or currency not in CURRENCIES: raise ValueError('Use a three-letter ISO currency code.')
        return {'amount':str(amount),'currency':currency}
    if kind in ('file_upload','asset_reference'):
        if type(value) is not int or not asset_allowed(value): raise ValueError('Choose an uploaded asset belonging to this brief.')
        return value
    if kind == 'boolean':
        if type(value) is not bool: raise ValueError('Invalid boolean.')
        return value
    if kind == 'integer':
        if type(value) is not int or value < 0 or value > 1000000000: raise ValueError('Use a non-negative whole number.')
        return value
    if not isinstance(value,str): raise ValueError('Use text for this field.')
    value=value.strip()
    if len(value) > (12000 if kind=='long_text' else 2000): raise ValueError('This answer is too long.')
    if kind in ('date','time'):
        try:
            if kind=='date' and not re.fullmatch(r'\d{4}-\d{2}-\d{2}',value): raise ValueError()
            (date if kind=='date' else time).fromisoformat(value)
        except ValueError: raise ValueError('Use a valid ISO '+kind+'.')
    if kind=='url' and not public_url(value): raise ValueError('Use a public HTTP or HTTPS URL.')
    if kind=='currency' and value not in CURRENCIES: raise ValueError('Use an ISO currency code.')
    return value

def validate(groups, answers, catalog, asset_allowed=lambda asset:False, partial=True):
    fields=fields_for(groups)
    errors={}
    clean={}
    if not isinstance(answers,dict): return {}, {'_form':'Answers must be an object.'}
    for key,value in answers.items():
        if key not in fields:
            errors[key]='Unknown field for this service.'
            continue
        try:
            item=normalize(fields[key],value,catalog,asset_allowed,True)
            if item is not None: clean[key]=item
        except ValueError as error: errors[key]=str(error)
    active=active_fields(groups,clean)
    if partial:
        return clean,errors
    if not partial:
        for key,field in active.items():
            if field.get('required') and empty(clean.get(key)): errors[key]='This answer is required.'
            if not empty(clean.get(key)):
                try: normalize(field,clean[key],catalog,asset_allowed,False)
                except ValueError as error: errors[key]=str(error)
    live={k:v for k,v in clean.items() if k in active}
    for low,high in [('EV02C','EV02D'),('BIZ05B','BIZ05C'),('EV03B','EV03C')]:
        if live.get(low) and live.get(high) and live[high]<live[low]: errors[high]='End must be on or after start.'
    for low,high in [('PF17B','PF17C'),('CORE04D','CORE04E')]:
        if live.get(low) and live.get(high):
            if live[low]['currency']!=live[high]['currency'] or Decimal(live[high]['amount'])<Decimal(live[low]['amount']): errors[high]='Use matching currencies and a maximum at least the minimum.'
    if live.get('PF08D'):
        for row in live['PF08D']:
            if row.get('method') and row['method'] not in live.get('PF08C',[]): errors['PF08D']='Each destination must match a selected action method.'
    if live.get('BIZ04C'):
        for amount in re.findall(r'(-?\d+(?:\.\d+)?)\s*%',live['BIZ04C']):
            if not Decimal('0')<=Decimal(amount)<=Decimal('100'): errors['BIZ04C']='Percentage offers must be between 0 and 100.'
    if not partial and live.get('PF08E')=='yes':
        destinations=[live.get('PF08F'),live.get('EV04F')]+[row.get('destination') or row.get('value') or row.get('url') for row in live.get('PF08D',[])]
        if not any(public_url(v) for v in destinations if isinstance(v,str)): errors['PF08F']='A QR code needs an approved public destination URL.'
    if not partial and 'PF_CONTENT_VARIANTS' in active:
        if {row.get('deliverable') for row in live.get('PF_CONTENT_VARIANTS',[])}!={'poster','flyer'}: errors['PF_CONTENT_VARIANTS']='Provide one poster and one flyer variation.'
    return clean,errors

def assessment(groups, answers, catalog, asset_allowed=lambda asset:False):
    clean, errors=validate(groups,answers,catalog,asset_allowed,partial=False)
    active=active_fields(groups,clean)
    required=[k for k,f in active.items() if f.get('required')]
    complete=sum(not empty(clean.get(k)) and k not in errors for k in required)
    def pending(value):
        if isinstance(value,dict): return any(pending(v) for v in value.values())
        if isinstance(value,list): return any(pending(v) for v in value)
        return value in ('pending','partial','working')
    issues=[f['label']+': information is pending.' for k,f in active.items() if pending(clean.get(k))]
    methods=clean.get('PF08C',[]) if 'PF08C' in active else []
    destinations={row.get('method') for row in clean.get('PF08D',[]) if row.get('value')}
    if set(methods)-{'pending'}-destinations: issues.append('Supply action destinations for each selected contact method before design approval.')
    for key in ('BIZ07B','AW04','COR10','SM07','BM07','PK10','PK15'):
        if key in active and not empty(clean.get(key)): issues.append(active[key]['label']+': human verification and approval required.')
    if clean.get('EV04A') in ('online','hybrid') and not clean.get('EV03E'): issues.append('Time zone for an online or international event is needed before design approval.')
    return {'percentage':round(100*complete/len(required)) if required else 100,'errors':errors,'issues':issues,'ready':not errors and not issues}

def snapshot(groups, answers):
    active=active_fields(groups,answers)
    return [{'field_id':k,'label':f['label'],'value':answers[k]} for k,f in active.items() if k in answers]

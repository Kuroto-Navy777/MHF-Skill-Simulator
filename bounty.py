"""Rain bounty filters, based on the community translation dated 2026-01-19.
Only equipment constraints with known data mappings are enforced; never certify submission eligibility.
"""
from catalog import armor_rank, normalized, ARMOR

SOURCE='https://docs.google.com/document/d/1PudqeBC0PhYS5MSk_1l0njpzwW_O985dR3_F_YvHHR8'
GROUPS={'Bronze':list(range(1,22)), 'Silver':list(range(1,21)), 'Gold':list(range(1,22)), 'ABYSS':[22,23,24], 'Free':list(range(1,26)), 'Event':[1,2,3,4,5,6,8,9,13,14,15,17,20,21,24]}
G={'g_level','G級覇種','覇種武器','烈種武器','始種武器','quasi_g','g_evolution','prayer_g','exotic'}
HR={'normal_hr','HC武器','親方印','sp','剛種武器','天嵐武器','覇種武器','hr_evolution','prayer_hr'}
EVOL={'g_evolution','hr_evolution','zenith_evolution','evolution_unknown'}
PRAY={'prayer_g','prayer_hr'}
ZEN={'zenith','zenith_evolution'}

# Each preset is independent of the user exclusions and cannot relax them.
def rules(selection):
    if not isinstance(selection,dict): raise ValueError('Invalid bounty selection')
    group=selection.get('group'); n=selection.get('number'); mode=selection.get('mode','solo')
    if group not in GROUPS or type(n) is not int or n not in GROUPS[group] or mode not in ('solo','multi'): raise ValueError('Unknown bounty / mode')
    r={'group':group,'number':n,'mode':mode,'armor_ranks':None,'armor_prefix':None,'no_paid_armor':False,'armor_max_rarity':None,'cuff':'any','no_secret':False,'no_futai':False,'secret_weapon':None,'weapon_allow':None,'weapon_deny':set(),'weapon_types_deny':set(),'max_rarity':None,'no_sigils':False,'warnings':[],'partial':False}
    def warn(ja,en):
        r['warnings'].append({'ja':ja,'en':en});r['partial']=True
    def g_only(paid=True):
        r['armor_ranks']=['G','GF','GX']+(['GP','GS'] if paid else []);r['no_paid_armor']=not paid
        r['weapon_allow']=set(G)
    def standard_g():
        g_only();r['weapon_deny']|=EVOL|{'rng_cat'};r['weapon_types_deny'].add('MS');r['no_secret']=r['no_futai']=True;r['cuff']='g'
        warn('ネカフェ武器の完全な識別は未対応。','Net cafe weapon classification is incomplete.')
    def paid_weapon(): warn('課金・ネカフェ・通常生産の武器分類は元DBでは完全に判別できません。','Paid, net cafe and ordinary production weapon categories cannot be fully verified from the DB.')
    if group=='Bronze':
        g_only(False);r['weapon_deny']|=EVOL|PRAY|{'exotic','rng_cat'};r['weapon_types_deny'].add('MS');r['cuff']='g';r['no_secret']=n!=21;r['no_futai']=True;paid_weapon()
    elif group=='Silver':
        r['weapon_deny']|=EVOL|PRAY;r['weapon_types_deny'].add('MS');r['no_futai']=True;paid_weapon()
        if n<=8: g_only(False);r['cuff']='g'
        else:
            r['armor_ranks']=['Z','ZF','ZY','ZX'];r['armor_prefix']='コリニィ';r['weapon_allow']={'zenith'}|({'tower'} if n>=18 else set());r['max_rarity']=11
    elif group=='Gold':
        if n<=10: r['armor_ranks']=['Z'];r['cuff']='none';r['no_futai']=True;r['weapon_deny']|=ZEN
        if 11<=n<=18: r['armor_ranks']=['G','GF','GX','GP','GS','Z','ZF','ZY','ZX','other']
        if n<=17: paid_weapon()
        if n!=21: r['weapon_types_deny'].add('MS')
        if n==18: warn('Gold18のマグスパ条件は資料内で矛盾するため、暫定的に禁止。','Gold 18 contradicts itself on Magnet Spike; conservatively excluded.')
        if n<=20:r['weapon_deny']|=EVOL
        if n<=18:r['weapon_deny'].add('tower')
        if n in (1,7,10):r['weapon_deny']|=PRAY
        if n in (1,2,5,6,7,8,9,10):r['weapon_deny'].add('exotic')
        warn('ゲーム内の受注制限を必ず確認してください。','Check the in-game quest restrictions.')
    elif group=='ABYSS':
        if n==22:r['weapon_deny']|=EVOL
        if n==24 or n==22 and mode=='multi':r['weapon_types_deny'].add('MS')
        warn('ゲーム内の受注制限を必ず確認してください。','Check the in-game quest restrictions.')
    elif group=='Free':
        if n in (8,16,17,19,23,25):
            standard_g()
            if n==8:r['cuff']='none';r['weapon_deny'].clear()
            if n==25:r['no_secret']=False;r['secret_weapon']='Tonfas'
        elif n==9:
            # Common rows in the source table are applied conservatively to both categories.
            r['no_secret']=r['no_futai']=True;r['cuff']='none';r['weapon_types_deny'].add('MS')
            if mode=='solo':
                g_only();r['weapon_deny']|=EVOL|{'exotic','G級覇種','覇種武器','烈種武器','始種武器'};r['weapon_types_deny'].add('MS');paid_weapon()
            else:
                r['armor_ranks']=['other'];r['weapon_allow']=set(HR)-EVOL-{'剛種武器','天嵐武器','覇種武器'};r['no_secret']=r['no_futai']=True;r['cuff']='none';paid_weapon()
                warn('G級スキル全般・極ノ型の禁止は手動確認。','Check all G-rank skills and Extreme Style manually.')
            warn('Free09はソロ/マルチがG級/上位の提出区分です。共通欄の秘伝・不退・カフ禁止は両方に適用。','Free 09 solo/multi refers to G-rank/HR submission categories. Common no-secret, no-Futai and no-cuff rows are applied to both.')
        elif n in (4,12,13,14,20):
            r['weapon_deny']|=EVOL|{'tower'}
            if n in (12,13,14,20):paid_weapon()
            if n in (14,20) or n==4 and mode=='multi':r['weapon_types_deny'].add('MS')
            if n==14:
                r['armor_ranks']=['G','GF','GX','GP','GS'];r['no_secret']=True;r['cuff']='g'
                if mode=='multi':r['weapon_allow']=set(G)
            if n==4 and mode=='solo' or n in (12,13):warn('マグスパ固有の武器名・属性制限は手動確認。','Check Magnet Spike name/element restrictions manually.')
        elif n==5:
            if mode=='multi':r['cuff']='none'
            warn('マグスパ固有の進化・天廊制限は手動確認。','Check Magnet Spike evolution/tower restrictions manually.')
        elif n==10:r['weapon_types_deny'].add('MS')
        elif n==15: r['no_paid_armor']=True;r['cuff']='none';paid_weapon();warn('HR帯/G級昇格済みの条件分岐は手動確認。','Check HR versus G-rank progression branch manually.')
        elif n==21:r['armor_prefix']='ホープ';r['armor_ranks']=['other'];r['max_rarity']=5;r['cuff']='none';r['no_secret']=r['no_futai']=True;warn('未強化Lv・決意武器・極ノ型は手動確認。','Check unupgraded level, Determination weapons and Extreme Style manually.')
        elif n==22:r['armor_ranks']=['other'];r['armor_max_rarity']=7;r['weapon_allow']=set(HR);r['cuff']='none';r['no_secret']=r['no_futai']=True;warn('極ノ型などを手動確認。','Check Extreme Style and other conditions manually.')
        else:warn('個別条件・参加人数・クエストを資料で確認。','Check individual conditions, party and quest in the source.')
    elif group=='Event':
        if n in (3,4):
            g_only();r['weapon_deny']|=EVOL|{'exotic'};r['weapon_types_deny'].add('MS');r['no_secret']=r['no_futai']=True;r['cuff']='none' if mode=='multi' else 'g';paid_weapon()
        elif n==8:r['weapon_types_deny']|={'MS','Lance','GL'};r['weapon_deny']|=EVOL|PRAY|ZEN|{'tower'};warn('提出対象クエストの制限。前提クエストは別条件。','Submission quest only; prerequisite has different restrictions.')
        elif n==9:r['no_sigils']=True;r['weapon_deny']|=EVOL|{'tower'}
        elif n in (13,14,15):
            r['weapon_types_deny'].add('MS')
            if n in (13,14):r['weapon_deny']|=EVOL
            if n==14:r['weapon_deny'].add('tower')
        elif n==17:r['weapon_types_deny']|={'MS','Tonfas'};r['weapon_deny']|=EVOL|PRAY|ZEN|{'tower'}
        else:warn('個別条件は資料で確認。','Check individual conditions in the source.')
        warn('開催期間・受注条件は最新Discordで確認。','Verify event dates and quest rules in current Discord.')
    # Even fully machine-readable equipment rules do not establish full submission eligibility.
    warn('2026-01-19版の参考資料。NPC・人数・型・提出条件・最新変更は手動確認。','Reference dated 2026-01-19. Check NPCs, party, style, submission and current changes manually.')
    return r

# Source classification, not Rain availability.
def item_allowed(row,r):
    if not r:return True
    if row['kind'] in ARMOR:
        rank=armor_rank(row['ja'],row['en'],row['type_name'])
        if r['armor_ranks'] is not None and rank not in r['armor_ranks']:return False
        if r['armor_prefix'] and not normalized(row['ja']).startswith(normalized(r['armor_prefix'])):return False
        if r['no_paid_armor'] and (row['class_code'] or '').startswith(('(ガ','(キ','(パ','(ネ')):return False
        if r['group']=='Free' and r['number'] in (9,22) and r['armor_ranks']==['other'] and ('Ｇ級' in (row['type_name'] or '') or '辿異' in (row['type_name'] or '')):return False
        if r['armor_max_rarity'] is not None and (row['rarity'] is None or row['rarity']>r['armor_max_rarity']):return False
    if row['kind']=='cuff':
        if r['cuff']=='none':return False
        if r['cuff']=='g' and not (row['class_code'] in ('(S_Ｇ)','(P_Ｇ)') or normalized(row['ja']).startswith('g') and '辿' not in (row['class_code'] or '')):return False
    return True

def weapon_allowed(row,r):
    if not r:return True
    return (r['weapon_allow'] is None or row['category'] in r['weapon_allow']) and row['category'] not in r['weapon_deny'] and (r['max_rarity'] is None or row['rarity'] is not None and row['rarity']<=r['max_rarity'])

def banned_skill(name,r,wt,secrets):
    return bool(r and (r['no_futai'] and name=='不退' or (r['no_secret'] or r['secret_weapon']==wt) and name in secrets))

def public_rules(selection):
    r=rules(selection)
    return {k:sorted(v) if isinstance(v,set) else v for k,v in r.items()}

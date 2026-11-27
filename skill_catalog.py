"""Presentation categories and source-backed skill reference; no DB migration."""
import json
from skill_engine import WEAPON_SECRET

# Categories are UI suggestions, not official game categories.
GROUPS = {
    'offense': '剛撃 攻撃 一匹狼 一閃 達人 閃転 痛撃 巧撃 属撃 変撃 劇物の心得 特殊攻撃 怪奇 爆弾強化 砲術師 逆境 底力 断食 溜め短縮 溜め威力 尻上がり 適応撃 闘覇 血気活性 纏雷 贅撃 雌伏 猛進 幕無 一点突破 獅子奮迅 不退 火属性攻撃 水属性攻撃 雷属性攻撃 氷属性攻撃 龍属性攻撃 属性攻撃 反射 代償 氷界創生',
    'survival': '体力 回復速度 回復 吸血 薬草学 生命力 防御 要塞 ガード性能 自動防御 とんずら 怒 全耐性ＵＰ 火耐性 水耐性 雷耐性 氷耐性 龍耐性 毒 麻痺 睡眠 耐状態異常 気絶 脱臭 耐雪 声帯 対防御DOWN 耐酔 爆破耐性 磁力耐性 結晶耐性 凍結耐性 三界の護り 聴覚保護 耐震 風圧 耐暑 耐寒 警戒 超回避 地形 回避性能 回避距離 受け身 審判 根性 絶対防御 恩寵 黒ノ命脈 炎寵',
    'melee': '研ぎ師 斬れ味 巧流 刀匠 匠 剣術 剣神 爆撃剣 猛毒剣 麻痺剣 睡眠剣 火炎剣 水激剣 雷神剣 氷結剣 龍王剣 武器捌き',
    'ranged': '射手 通常弾強化 貫通弾強化 散弾強化 通常弾追加 貫通弾追加 散弾追加 榴弾追加 拡散弾追加 毒瓶追加 麻痺瓶追加 睡眠瓶追加 装着 穏射 装填数 速射 連射 装填 反動 扇射 精密射撃 弾調合 弾丸節約術 狙撃 空隙',
    'support': '気力回復 はらへり スタミナ 食事 食いしん坊 鼓舞 笛吹き名人 体術 腕利き 手練 調合師 効果持続 広域 気まぐれ 投擲 強肩 高速設置 鉄腕 ナイフ使い 地図 千里眼 気配 煽動 平常心 絆 ひらめき 捕獲上手 救援 いたわり 移動速度 喝 支援 抜納術',
    'gathering': '狩人 肉焼き 釣り 調合成功率 錬金術 運搬 高速収集 採取 剥ぎ取り 運気 圧力 モンスター ブリーダー 盗み無効',
}
CATEGORIES = {name: group for group, names in GROUPS.items() for name in names.split()}


def category(kind, name):
    if kind == 'zenith': return 'zenith'
    if name in WEAPON_SECRET.values(): return 'secret'
    return CATEGORIES.get(name, 'other')


def catalog(db):
    # Read the exact XML-derived level names, signed thresholds, and relation names.
    query = '''SELECT s.id,s.kind,s.ja AS family_ja,s.en AS family_en,s.metadata,
        l.points,l.ja,l.en,l.rules_json FROM skills s JOIN skill_levels l ON l.skill_id=s.id
        ORDER BY s.kind,s.id,l.points'''
    result = []
    for row in db.execute(query):
        x = dict(row)
        meta = json.loads(x.pop('metadata'))
        rules = json.loads(x.pop('rules_json'))
        x['category'] = category(x['kind'], x['family_ja'])
        x['target'] = {lang: meta.get(lang, {}).get('Target') for lang in ('ja','en')}
        x['relations'] = {lang: [{'type': g['tag'], 'name': c['attributes']['Name']}
            for g in rules.get(lang, {}).get('children', [])
            if g['tag'] in ('ContainedSkills', 'DeactivateSkills')
            for c in g['children'] if 'Name' in c['attributes']] for lang in ('ja','en')}
        result.append(x)
    return result

# Descriptions are read only from the user's verified local Ferias archive.
# Exact English tier name and signed threshold must agree; ambiguous text is omitted.
from functools import lru_cache
import re
import zipfile
from collections import defaultdict
from lxml import html


def description_key(kind, name, points):
    return kind, re.sub(r'\s+', '', name).casefold(), points


@lru_cache(maxsize=2)
def descriptions(path, mtime_ns):
    found = defaultdict(set)
    with zipfile.ZipFile(path) as archive:
        for kind, suffix in [('normal','koneta/skill.htm'),('zenith','koneta/skill_zenith.htm')]:
            members = [n for n in archive.namelist() if n.endswith('/'+suffix) or n==suffix]
            if len(members)!=1: continue
            root = html.fromstring(archive.read(members[0]))
            for row in root.xpath('//table[1]/tr|//table[1]/tbody/tr'):
                cells = [' '.join(x.text_content().split()) for x in row.xpath('./td')]
                if len(cells)<3: continue
                name, point, detail = cells[-3:]
                if re.fullmatch(r'[+-]?\d+', point) and detail:
                    found[description_key(kind,name,int(point))].add(detail)
    return {k:next(iter(v)) for k,v in found.items() if len(v)==1}

# Manually checked spelling aliases; matching kind and signed threshold remain mandatory.
# No fuzzy or nearest-name lookup is used at runtime.
DESCRIPTION_ALIASES = {
    '片手剣技【剣聖】':'Sword Saint', '双剣技【双龍】':'Dual Dragon', '大剣技【剣王】':'Sword King',
    '太刀技【刀神】':'Katana God', '鎚技【鈍器獣】':'Blunt Beast', '狩猟笛技【奏帝】':'Flamboyant Emperor',
    '槍技【天槍】':'Heavenly Spear', '銃槍技【砲皇】':'Cannon Emperor', '剣斧技【斬将】':'Edge Marshal',
    '穿龍棍技【穿凰】':'Piercing Phoenix', '重銃技【銃仙】':'Gun Sage', '軽銃技【銃傑】':'Gun Prodigy', '弓技【弓鬼】':'Bow Demon',
    '磁力弱点':'Magnet Vulnerability', '凍結耐性':'Freeze Resistance', '節約名人':'Saving Master', '節約達人':'Saving Expert',
    '移動速度UP+1':'Movement Speed Up+1', '移動速度UP+2':'Movement Speed Up+2', '最期ノ閃黒':'Dark Finale',
    '薬仙人':'Medical Sage', '状態異常追撃':'Status Pursuit', 'スタミナ回復遅延':'Stamina Rec Down',
    'スタミナ急速回復【小】':'Stamina Rec (Small)', 'スタミナ急速回復【大】':'Stamina Recovery Up (Large)',
    '状態異常無効【多種】':'S.Immunity (Myriad)', '麻痺倍加':'Para Doubled', '麻痺半減':'Para Halved', '麻痺無効':'Negate Para',
    '睡眠無効':'Negate Sleep', '気絶無効':'Negate Stun', '毒倍加':'Double Poison', '毒無効':'Negate Poison',
    '業物+1':'Razor Sharp+1','業物+2':'Razor Sharp+2', '通常弾・連射矢威力UP':'Normal/Rapid Up',
    '貫通弾・貫通矢威力UP':'Pierce/Pierce Up','散弾・拡散矢威力UP':'Pellet/Spread Up','通常弾全レベル追加':'Normal S All',
    'ボマー':'Bomber','はらへり倍加【大】':'Hunger Up (Lg)','はらへり倍加【小】':'Hunger Up (Sm)',
    '高級耳栓':'High-Grade Earplugs','超高級耳栓':'Super HG Earplugs','風圧【小】無効':'Wind Res (Small)','風圧【大】無効':'Wind Res (Large)',
    '調合成功率+30%':'Combining+30%', '最大数弾生産':'Maximum Bullets','アイテム使用弱化':'Item Duration Down','アイテム使用強化':'Item Duration Up',
    'ランナー':'Marathon Runner','絶倫':'Peerless','スローライフ':'Slow Eating','早食い':'Speed Eating',
    '地形ダメージ増【大】':'Hazard Prone (Large)','地形ダメージ増【小】':'Hazard Prone (Small)',
    '地形ダメージ減【大】':'Hazard Res (Large)','地形ダメージ減【小】':'Hazard Res (Small)',
    '砲術師':'Artillery Novice','砲術王':'Artillery Expert','砲術神':'Artillery God','格闘王':'Kickboxing King',
    '圧力【小】':'Pressure (Small)','圧力【大】':'Pressure (Large)','麻痺ビン追加':'Para Coating Add','吸血強化+1':'Vampirism Up',
}
for ja,en in [('剣斧','Switch Axe'),('磁斬鎚','Magnet Spike')]:
    for j,e in [('未熟','Novice'),('達人','Expert'),('皆伝','Kaiden')]:
        DESCRIPTION_ALIASES[f'{ja}技【{j}】']=f'{en} Tech ({e})'
for i in range(1,6): DESCRIPTION_ALIASES[f'見切り+{i}']=f'Critical Eye+{i}'
for i in (-1,1,2,3):
    DESCRIPTION_ALIASES[f'調合師{i:+d}']=f'Combo Expert{i:+d}'
    DESCRIPTION_ALIASES[f'装填速度{i:+d}']=f'Reload Speed{i:+d}'
for i in (1,2,3):
    DESCRIPTION_ALIASES[f'反動軽減+{i}']=f'Recoil Reduction+{i}'
    DESCRIPTION_ALIASES[f'麻痺剣+{i}']=f'Para Sword+{i}'
for i in (5,10): DESCRIPTION_ALIASES[f'各耐性+{i}']=f'All Res Up+{i}'
for j,e in [('火','Fire'),('水','Water'),('雷','Thunder'),('氷','Ice'),('龍','Dragon')]:
    for a,b in [('小','Small'),('大','Large')]: DESCRIPTION_ALIASES[f'{j}属性攻撃強化【{a}】']=f'{e} Attack ({b})'
for j,e in [('暑','Heat'),('寒','Cold')]:
    for a,b in [('小','Small'),('大','Large')]: DESCRIPTION_ALIASES[f'{j}さ倍加【{a}】']=f'{e} Surge ({b})'
for j,e in [('貫通弾','Pierce S'),('散弾','Pellet S'),('徹甲榴弾','Crag S'),('拡散弾','Cluster S')]:
    DESCRIPTION_ALIASES[j+'ＬＶ１追加']=e+' Lv1 Add'
    DESCRIPTION_ALIASES[j+'ＬＶ1&2追加']=e+(' Lv1&Lv2 Add' if j in ('徹甲榴弾','拡散弾') else ' Lv1&2 Add')
    DESCRIPTION_ALIASES[j+'全レベル追加']=e+' All'
for a,b in [('小','Small'),('中','Medium'),('大','Large'),('特大','Very Large'),('絶大','Absolute')]:
    DESCRIPTION_ALIASES[f'攻撃力UP【{a}】']=f'Attack Up ({b})'


def matched_description(row, details):
    direct=details.get(description_key(row['kind'],row['en'],row['points']))
    if direct: return direct
    alias=DESCRIPTION_ALIASES.get(row['ja'])
    return details.get(description_key(row['kind'],alias,row['points'])) if alias else None

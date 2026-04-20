import re
import streamlit as st
from PyPDF2 import PdfReader
from PIL import Image
from pdf2image import convert_from_bytes
import easyocr

st.set_page_config(page_title="KC 인증 및 품질 분석기", layout="wide")

# -----------------------------
# OCR 리더 캐시
# -----------------------------
@st.cache_resource
def get_ocr_reader():
    # 영어 + 중국어(간체/번체)
    return easyocr.Reader(["en", "ch_sim", "ch_tra"], gpu=False)

# -----------------------------
# 텍스트 유틸
# -----------------------------
def normalize_text(text):
    return re.sub(r"\s+", " ", text.lower()).strip()

def find_keywords(text, keywords):
    found = []
    for kw in keywords:
        if kw.lower() in text:
            found.append(kw)
    return found

# -----------------------------
# PDF 텍스트 추출 (1차: PyPDF2)
# -----------------------------
def extract_text_from_pdf_pypdf2(pdf_bytes):
    text = ""
    try:
        from io import BytesIO
        reader = PdfReader(BytesIO(pdf_bytes))
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
    except Exception as e:
        text += f"\n[PDF 읽기 오류] {e}"
    return text.strip()

# -----------------------------
# OCR fallback
# -----------------------------
def extract_text_from_pdf_ocr(pdf_bytes):
    reader = get_ocr_reader()
    images = convert_from_bytes(pdf_bytes, dpi=200)
    ocr_texts = []

    for img in images:
        results = reader.readtext(img)
        page_lines = []
        for item in results:
            if len(item) >= 2:
                page_lines.append(item[1])
        ocr_texts.append("\n".join(page_lines))

    return "\n\n".join(ocr_texts).strip()

def smart_extract_text(pdf_file):
    """
    1) PyPDF2 추출 시도
    2) 텍스트가 너무 적으면 OCR fallback
    """
    pdf_bytes = pdf_file.read()
    pypdf_text = extract_text_from_pdf_pypdf2(pdf_bytes)

    extracted_by = "PyPDF2"
    final_text = pypdf_text

    if len(pypdf_text.strip()) < 30:
        try:
            ocr_text = extract_text_from_pdf_ocr(pdf_bytes)
            if len(ocr_text.strip()) > len(pypdf_text.strip()):
                final_text = ocr_text
                extracted_by = "OCR(EasyOCR)"
        except Exception as e:
            final_text = pypdf_text + f"\n\n[OCR 실패] {e}"

    return final_text.strip(), extracted_by

# -----------------------------
# KC 인증 판단
# -----------------------------
def judge_certifications(spec_text):
    text = normalize_text(spec_text)

    safety_keywords = [
        # English
        "220v", "110v", "ac", "dc", "adapter", "adaptor", "battery", "lithium",
        "power", "power supply", "rated voltage", "rated current", "input", "output",
        "charger", "charging", "watt", "volt", "hz", "usb power", "built-in battery",
        # Chinese
        "电源", "适配器", "电池", "锂电", "锂离子", "充电", "充电器",
        "额定电压", "额定电流", "输入", "输出", "功率"
    ]

    emc_keywords = [
        # English
        "emc", "emi", "ems", "pcb", "circuit", "controller", "ic", "sensor",
        "display", "led", "driver", "switching", "smps", "usb", "module",
        "board", "microcontroller", "electromagnetic",
        # Chinese
        "电磁兼容", "电磁", "电路", "线路板", "控制器", "传感器",
        "显示", "驱动", "模块", "主板", "芯片", "电子"
    ]

    rf_keywords = [
        # English
        "bluetooth", "wifi", "wi-fi", "wireless", "rf", "2.4ghz", "5ghz",
        "zigbee", "lte", "5g", "4g", "nfc", "gps", "gnss", "lora",
        "antenna", "transmitter", "receiver", "ble", "pairing",
        # Chinese
        "蓝牙", "无线", "射频", "天线", "发射", "接收", "配对",
        "无线路由", "无线局域网", "近场通信", "定位"
    ]

    found_safety = find_keywords(text, safety_keywords)
    found_emc = find_keywords(text, emc_keywords)
    found_rf = find_keywords(text, rf_keywords)

    kc_safety = "필수" if found_safety else "해당 없음"
    kc_emc = "필수" if found_emc else "해당 없음"
    kc_rf = "필수" if found_rf else "해당 없음"

    reasons = []
    if found_safety:
        reasons.append(f"- KC 안전인증 관련 키워드 발견: {', '.join(found_safety[:12])}")
    else:
        reasons.append("- KC 안전인증 관련 전원/배터리/정격 키워드를 찾지 못했습니다.")

    if found_emc:
        reasons.append(f"- KC EMC 관련 키워드 발견: {', '.join(found_emc[:12])}")
    else:
        reasons.append("- KC EMC 관련 전자회로/전자파 키워드를 찾지 못했습니다.")

    if found_rf:
        reasons.append(f"- KC RF 무선인증 관련 키워드 발견: {', '.join(found_rf[:12])}")
    else:
        reasons.append("- KC RF 관련 무선통신 키워드를 찾지 못했습니다.")

    if kc_rf == "필수":
        kc_emc = "필수"
        reasons.append("- 무선 기능이 있으면 일반적으로 전자회로가 포함되므로 EMC도 함께 검토가 필요합니다.")

    return {
        "kc_safety": kc_safety,
        "kc_emc": kc_emc,
        "kc_rf": kc_rf,
        "reason": "\n".join(reasons)
    }

# -----------------------------
# 제품 카테고리 KC 기준 DB
# -----------------------------
KC_DB = [
    # ── 헤어/미용 기기 ──
    {"id": "hair_dryer", "ko": "헤어드라이기/전기드라이기",
     "zh": ["吹风机","电吹风","护发吹风机","负离子吹风机","智能吹风机"],
     "en": ["hair dryer","blow dryer","hair blower","ionic hair dryer"],
     "safety": {"req": True, "std": "KC 60335-2-23", "note": "전기 헤어케어 기기 안전기준"},
     "emc": {"req": True, "std": "CISPR 14-1", "note": "모터/스위칭전원 전자파 방출"},
     "rf": {"req": False, "cond": "Bluetooth·WiFi 기능 탑재 시 필요", "std": "KN 300 328"}},
    {"id": "hair_straightener", "ko": "헤어고데기/스트레이트너/컬링기",
     "zh": ["直发器","卷发棒","直发梳","负离子直板夹","卷发器"],
     "en": ["hair straightener","flat iron","curling iron","curling wand","hair curler"],
     "safety": {"req": True, "std": "KC 60335-2-23", "note": "전기 헤어케어 기기 안전기준"},
     "emc": {"req": True, "std": "CISPR 14-1", "note": "히팅 소자 및 전자제어"},
     "rf": {"req": False, "cond": "무선 기능 탑재 시 필요"}},
    {"id": "electric_shaver", "ko": "전기면도기/제모기",
     "zh": ["电动剃须刀","剃须刀","脱毛仪","电动脱毛器"],
     "en": ["electric shaver","electric razor","epilator","hair remover"],
     "safety": {"req": True, "std": "KC 60335-2-8", "note": "전기면도기/제모기 안전기준"},
     "emc": {"req": True, "std": "CISPR 14-1"},
     "rf": {"req": False, "cond": "무선/충전 기능 탑재 시 필요"}},
    {"id": "electric_toothbrush", "ko": "전동칫솔",
     "zh": ["电动牙刷","声波牙刷","超声波牙刷"],
     "en": ["electric toothbrush","sonic toothbrush","ultrasonic toothbrush"],
     "safety": {"req": True, "std": "KC 60335-2-52"},
     "emc": {"req": True, "std": "CISPR 14-1"},
     "rf": {"req": False, "cond": "Bluetooth 앱 연동 시 필요"}},
    {"id": "massager", "ko": "마사지기/안마기",
     "zh": ["按摩仪","按摩器","眼部按摩仪","颈部按摩仪","头皮按摩仪","振动按摩器"],
     "en": ["massager","massage device","eye massager","neck massager","scalp massager"],
     "safety": {"req": True, "std": "KC 60335-2-32", "note": "마사지 기기 안전기준"},
     "emc": {"req": True, "std": "CISPR 14-1"},
     "rf": {"req": False, "cond": "Bluetooth/무선 기능 탑재 시 필요"}},
    # ── 가전 ──
    {"id": "fan", "ko": "선풍기/서큘레이터",
     "zh": ["风扇","电风扇","循环扇","台扇","落地扇","塔扇"],
     "en": ["fan","electric fan","air circulator","tower fan","desk fan"],
     "safety": {"req": True, "std": "KC 60335-2-80"},
     "emc": {"req": True, "std": "CISPR 14-1"},
     "rf": {"req": False, "cond": "무선 리모컨·WiFi 탑재 시 필요"}},
    {"id": "air_purifier", "ko": "공기청정기",
     "zh": ["空气净化器","净化器","除菌器","空气消毒机"],
     "en": ["air purifier","air cleaner","hepa filter","air sanitizer"],
     "safety": {"req": True, "std": "KC 60335-2-65"},
     "emc": {"req": True, "std": "CISPR 14-1"},
     "rf": {"req": False, "cond": "WiFi·앱 연동 탑재 시 필요"}},
    {"id": "humidifier", "ko": "가습기",
     "zh": ["加湿器","超声波加湿器","雾化器"],
     "en": ["humidifier","ultrasonic humidifier","mist maker"],
     "safety": {"req": True, "std": "KC 60335-2-98"},
     "emc": {"req": True, "std": "CISPR 14-1"},
     "rf": {"req": False, "cond": "WiFi 탑재 시 필요"}},
    {"id": "heater", "ko": "전기히터/온풍기",
     "zh": ["暖风机","电暖器","取暖器","电热扇","暖气机"],
     "en": ["space heater","electric heater","fan heater","ceramic heater","infrared heater"],
     "safety": {"req": True, "std": "KC 60335-2-30"},
     "emc": {"req": True, "std": "CISPR 14-1"},
     "rf": {"req": False, "cond": "스마트 기능 탑재 시 필요"}},
    {"id": "vacuum", "ko": "청소기/진공청소기",
     "zh": ["吸尘器","无线吸尘器","手持吸尘器","扫地机器人"],
     "en": ["vacuum cleaner","cordless vacuum","robot vacuum","handheld vacuum"],
     "safety": {"req": True, "std": "KC 60335-2-2"},
     "emc": {"req": True, "std": "CISPR 14-1"},
     "rf": {"req": False, "cond": "로봇청소기·WiFi 탑재 시 필요"}},
    {"id": "iron", "ko": "전기다리미",
     "zh": ["电熨斗","蒸汽熨斗","手持挂烫机"],
     "en": ["electric iron","steam iron","garment steamer"],
     "safety": {"req": True, "std": "KC 60335-2-3"},
     "emc": {"req": True, "std": "CISPR 14-1"},
     "rf": {"req": False}},
    {"id": "kettle", "ko": "전기포트/전기주전자",
     "zh": ["电热水壶","电水壶","热水壶","烧水壶"],
     "en": ["electric kettle","electric water boiler"],
     "safety": {"req": True, "std": "KC 60335-2-15"},
     "emc": {"req": True, "std": "CISPR 14-1"},
     "rf": {"req": False, "cond": "스마트 기능 탑재 시 필요"}},
    {"id": "blender", "ko": "믹서기/블렌더/푸드프로세서",
     "zh": ["榨汁机","搅拌机","料理机","食品加工机","果汁机"],
     "en": ["blender","juicer","food processor","mixer"],
     "safety": {"req": True, "std": "KC 60335-2-14"},
     "emc": {"req": True, "std": "CISPR 14-1"},
     "rf": {"req": False}},
    # ── 전원/충전 ──
    {"id": "charger", "ko": "충전기/어댑터/전원공급장치",
     "zh": ["充电器","充电头","适配器","电源适配器","快充"],
     "en": ["charger","adapter","power adapter","power supply","usb charger","fast charger"],
     "safety": {"req": True, "std": "KC 62368-1", "note": "IT/AV 전원 어댑터 안전기준"},
     "emc": {"req": True, "std": "CISPR 32"},
     "rf": {"req": False, "cond": "무선충전(Qi) 탑재 시 필요"}},
    {"id": "power_bank", "ko": "보조배터리/파워뱅크",
     "zh": ["充电宝","移动电源"],
     "en": ["power bank","portable charger","battery pack"],
     "safety": {"req": True, "std": "KC 62368-1 / KC 62133"},
     "emc": {"req": True, "std": "CISPR 32"},
     "rf": {"req": False}},
    {"id": "wireless_charger", "ko": "무선충전기(Qi)",
     "zh": ["无线充电器","无线充电板","无线充"],
     "en": ["wireless charger","qi charger","inductive charger"],
     "safety": {"req": True, "std": "KC 62368-1"},
     "emc": {"req": True, "std": "CISPR 32"},
     "rf": {"req": True, "std": "KN 303 417 (Qi)", "note": "무선전력전송 → 전파인증 필수"}},
    # ── 조명 ──
    {"id": "led_lamp", "ko": "LED 조명/스마트조명",
     "zh": ["LED灯","LED灯泡","智能灯","台灯","落地灯"],
     "en": ["led lamp","led bulb","smart light","desk lamp","floor lamp"],
     "safety": {"req": True, "std": "KC 62560 / KC 60598"},
     "emc": {"req": True, "std": "CISPR 15"},
     "rf": {"req": False, "cond": "Bluetooth·Zigbee 탑재 시 필요"}},
    # ── 무선 오디오 ──
    {"id": "bluetooth_speaker", "ko": "블루투스 스피커/이어폰/헤드폰",
     "zh": ["蓝牙音箱","蓝牙耳机","无线耳机","无线音箱"],
     "en": ["bluetooth speaker","wireless earphone","wireless headphone","tws","earbuds"],
     "safety": {"req": True, "std": "KC 62368-1"},
     "emc": {"req": True, "std": "CISPR 32"},
     "rf": {"req": True, "std": "KN 300 328 (BT)", "note": "무선 기능 → 전파인증 필수"}},
    {"id": "earphone_wired", "ko": "유선이어폰/헤드폰",
     "zh": ["有线耳机","耳塞式耳机","头戴耳机","有线耳麦"],
     "en": ["wired earphone","wired headphone","earbuds wired","in-ear monitor"],
     "safety": {"req": True, "std": "KC 62368-1"},
     "emc": {"req": True, "std": "CISPR 32"},
     "rf": {"req": False}},
    # ── 웨어러블 ──
    {"id": "smart_watch", "ko": "스마트워치/스마트밴드",
     "zh": ["智能手表","智能手环","运动手表"],
     "en": ["smart watch","smartwatch","fitness tracker","smart band"],
     "safety": {"req": True, "std": "KC 62368-1"},
     "emc": {"req": True, "std": "CISPR 32"},
     "rf": {"req": True, "std": "KN 300 328 / KN 301 893", "note": "BT·WiFi → 전파인증 필수"}},
    # ── 스마트기기 ──
    {"id": "tablet", "ko": "태블릿/스마트패드",
     "zh": ["平板电脑","智能平板","电子阅读器","学习机"],
     "en": ["tablet","ipad","smart pad","e-reader","drawing tablet","learning tablet"],
     "safety": {"req": True, "std": "KC 62368-1"},
     "emc": {"req": True, "std": "CISPR 32"},
     "rf": {"req": True, "std": "KN 300 328 / KN 301 893", "note": "WiFi/BT 필수 탑재 → 전파인증 필수"}},
    {"id": "smart_plug", "ko": "스마트플러그/스마트콘센트",
     "zh": ["智能插座","智能开关","WiFi插座","智能插排"],
     "en": ["smart plug","smart socket","wifi plug","iot switch","smart outlet"],
     "safety": {"req": True, "std": "KC 60884-1", "note": "플러그/콘센트 안전기준"},
     "emc": {"req": True, "std": "CISPR 14-1"},
     "rf": {"req": True, "std": "KN 300 328", "note": "WiFi/BT 탑재 → 전파인증 필수"}},
    # ── 기타 전자기기 ──
    {"id": "robot", "ko": "로봇청소기/가정용로봇",
     "zh": ["扫地机器人","清洁机器人","拖地机器人"],
     "en": ["robot vacuum","robotic cleaner","robot mop"],
     "safety": {"req": True, "std": "KC 60335-2-2"},
     "emc": {"req": True, "std": "CISPR 14-1"},
     "rf": {"req": True, "std": "KN 300 328", "note": "WiFi/BT 탑재 → 전파인증 필수"}},
    {"id": "camera", "ko": "카메라/웹캠/IP카메라",
     "zh": ["摄像头","网络摄像机","IP摄像机","监控摄像头","行车记录仪"],
     "en": ["camera","webcam","ip camera","security camera","dashcam"],
     "safety": {"req": True, "std": "KC 62368-1"},
     "emc": {"req": True, "std": "CISPR 32"},
     "rf": {"req": False, "cond": "WiFi·BT 탑재 시 필요"}},
    {"id": "portable_projector", "ko": "미니빔/포터블프로젝터",
     "zh": ["微型投影仪","便携投影仪","口袋投影仪","手持投影仪"],
     "en": ["mini projector","portable projector","pocket projector","pico projector"],
     "safety": {"req": True, "std": "KC 62368-1"},
     "emc": {"req": True, "std": "CISPR 32"},
     "rf": {"req": False, "cond": "WiFi/BT 탑재 시 필요"}},
    {"id": "usb_hub", "ko": "USB허브/도킹스테이션",
     "zh": ["USB集线器","扩展坞","USB分线器","多功能扩展坞","Type-C扩展坞"],
     "en": ["usb hub","docking station","multiport hub","usb splitter","type-c hub"],
     "safety": {"req": True, "std": "KC 62368-1"},
     "emc": {"req": True, "std": "CISPR 32"},
     "rf": {"req": False}},
    {"id": "drone", "ko": "드론/무인기",
     "zh": ["无人机","飞行器","航拍无人机","四轴飞行器"],
     "en": ["drone","uav","quadcopter","fpv drone","aerial drone"],
     "safety": {"req": True, "std": "KC 62368-1 / 항공안전법 적용"},
     "emc": {"req": True, "std": "CISPR 32"},
     "rf": {"req": True, "std": "KN 300 328", "note": "조종 무선신호 → 전파인증 필수 + 초경량비행장치 신고 필요"}},
    # ── 뷰티/미용 기기 ──
    {"id": "led_mask", "ko": "LED마스크/광치료기기",
     "zh": ["LED面罩","光疗面罩","LED美容仪","红蓝光面罩","光子嫩肤仪","LED灯板"],
     "en": ["led mask","led face mask","phototherapy mask","light therapy mask","red light therapy","blue light device","led panel"],
     "safety": {"req": True, "std": "KC 60335-2-32", "note": "미용기기 안전기준 + IEC 62471 광생물학적 안전 고려"},
     "emc": {"req": True, "std": "CISPR 14-1"},
     "rf": {"req": False, "cond": "Bluetooth 앱 연동 시 필요"}},
    {"id": "rf_beauty", "ko": "RF미용기기/고주파미용기/리프팅기기",
     "zh": ["射频美容仪","RF美容仪","高频美容仪","提拉紧肤仪","热玛吉","射频仪"],
     "en": ["rf beauty device","radio frequency beauty","rf facial","rf lifting","rf skin tightening","thermagic","fractional rf"],
     "safety": {"req": True, "std": "KC 60335-2-32", "note": "의도적 RF 방출 → 전파인증 별도 확인 필수"},
     "emc": {"req": True, "std": "CISPR 14-1", "note": "의도적 RF 방출기기 추가 EMC 검토 필요"},
     "rf": {"req": True, "std": "방송통신기자재 등의 적합성평가", "note": "의도적 RF(고주파) 에너지 방출 → 전파인증 필수"}},
    {"id": "ems_device", "ko": "EMS기기/미세전류기기/전기자극기",
     "zh": ["EMS仪","微电流仪","电刺激仪","EMS腹肌贴","EMS面部仪","微电流美容仪"],
     "en": ["ems device","ems stimulator","microcurrent device","electrical muscle stimulation","ems facial","ems abs"],
     "safety": {"req": True, "std": "KC 60335-2-32 / IEC 60601-1", "note": "전기자극 출력에 따라 의료기기 분류 가능"},
     "emc": {"req": True, "std": "CISPR 14-1"},
     "rf": {"req": False, "cond": "Bluetooth/무선 탑재 시 필요"}},
    {"id": "ipl_laser", "ko": "IPL제모기/레이저제모기/홈레이저",
     "zh": ["IPL脱毛仪","激光脱毛仪","家用脱毛仪","光子脱毛","脱毛器"],
     "en": ["ipl hair removal","laser hair removal","ipl device","home laser","photoepilator","intense pulsed light"],
     "safety": {"req": True, "std": "KC 60335-2-8 + IEC 62471", "note": "광생물학적 안전 기준 별도 검토 필수"},
     "emc": {"req": True, "std": "CISPR 14-1"},
     "rf": {"req": False, "cond": "Bluetooth 앱 탑재 시 필요"}},
    {"id": "ultrasonic_beauty", "ko": "초음파미용기/초음파클렌저/HIFU",
     "zh": ["超声波美容仪","超声波洁面仪","HIFU仪","聚焦超声","超声导入仪"],
     "en": ["ultrasonic beauty","ultrasonic facial","hifu device","ultrasonic cleaner face","sonic facial"],
     "safety": {"req": True, "std": "KC 60335-2-32", "note": "초음파 출력 레벨에 따라 의료기기 분류 가능"},
     "emc": {"req": True, "std": "CISPR 14-1"},
     "rf": {"req": False, "cond": "무선 기능 탑재 시 필요"}},
    {"id": "nail_lamp", "ko": "네일램프/UV젤램프/네일드라이어",
     "zh": ["美甲灯","UV灯","LED美甲灯","光疗灯","固化灯"],
     "en": ["nail lamp","uv nail lamp","led nail lamp","gel nail lamp","nail dryer","uv curing lamp"],
     "safety": {"req": True, "std": "KC 60598-1 / IEC 62471", "note": "UV 방출 기기 광생물학적 안전 검토"},
     "emc": {"req": True, "std": "CISPR 15"},
     "rf": {"req": False}},
    {"id": "galvanic", "ko": "갈바닉기기/이온영동기기/피부관리기",
     "zh": ["离子导入仪","高频仪","电流美容仪","离子美容仪","导入仪"],
     "en": ["galvanic device","iontophoresis","ion infusion","galvanic facial","skin infusion device"],
     "safety": {"req": True, "std": "KC 60335-2-32"},
     "emc": {"req": True, "std": "CISPR 14-1"},
     "rf": {"req": False, "cond": "무선 기능 탑재 시 필요"}},
    {"id": "facial_steamer", "ko": "페이셜스티머/미안기/스팀기",
     "zh": ["蒸脸仪","补水仪","面部蒸汽仪","美颜仪","纳米喷雾仪"],
     "en": ["facial steamer","face steamer","nano mist sprayer","beauty steamer","steam facial"],
     "safety": {"req": True, "std": "KC 60335-2-23", "note": "스팀 발생 가열 소자 포함"},
     "emc": {"req": True, "std": "CISPR 14-1"},
     "rf": {"req": False, "cond": "무선 기능 탑재 시 필요"}},
    {"id": "blackhead_remover", "ko": "블랙헤드제거기/모공흡입기",
     "zh": ["吸黑头仪","毛孔清洁仪","真空吸附仪","毛孔吸尘器"],
     "en": ["blackhead remover","pore vacuum","suction blackhead","comedone extractor"],
     "safety": {"req": True, "std": "KC 60335-2-32"},
     "emc": {"req": True, "std": "CISPR 14-1"},
     "rf": {"req": False, "cond": "무선 기능 탑재 시 필요"}},
    {"id": "heated_eye_mask", "ko": "전기눈마스크/온열안대/온열눈찜질기",
     "zh": ["热敷眼罩","电热眼罩","蒸汽眼罩","加热眼罩","护眼仪"],
     "en": ["heated eye mask","electric eye mask","steam eye mask","eye warmer","thermal eye mask"],
     "safety": {"req": True, "std": "KC 60335-2-32", "note": "가열 소자 안전기준 적용"},
     "emc": {"req": True, "std": "CISPR 14-1"},
     "rf": {"req": False, "cond": "Bluetooth 앱 탑재 시 필요"}},
    {"id": "hair_growth", "ko": "두피케어기기/모발성장기기",
     "zh": ["生发仪","激光生发帽","头皮护理仪","毛发生长仪","低能量激光"],
     "en": ["hair growth device","laser hair growth","scalp treatment device","lllt helmet","hair regrowth device"],
     "safety": {"req": True, "std": "KC 60335-2-32 / IEC 62471", "note": "레이저/LED 광출력 IEC 62471 검토 필요"},
     "emc": {"req": True, "std": "CISPR 14-1"},
     "rf": {"req": False, "cond": "Bluetooth 탑재 시 필요"}},
    {"id": "cosmetic_fridge", "ko": "화장품냉장고/미니냉장고",
     "zh": ["化妆品冰箱","美容冰箱","护肤品冰箱","迷你冰箱","小冰箱"],
     "en": ["cosmetic fridge","beauty fridge","skincare fridge","mini fridge","makeup fridge"],
     "safety": {"req": True, "std": "KC 60335-2-24", "note": "냉장기기 안전기준"},
     "emc": {"req": True, "std": "CISPR 14-1"},
     "rf": {"req": False, "cond": "WiFi/스마트 기능 탑재 시 필요"}},
    {"id": "neck_massager", "ko": "목마사지기/경추견인기",
     "zh": ["颈椎牵引器","颈部按摩仪","颈椎按摩器","脖子按摩仪","电动颈部按摩"],
     "en": ["neck traction","cervical traction","neck massager electric","neck stretcher"],
     "safety": {"req": True, "std": "KC 60335-2-32"},
     "emc": {"req": True, "std": "CISPR 14-1"},
     "rf": {"req": False, "cond": "무선 기능 탑재 시 필요"}},
    {"id": "foot_massager", "ko": "발마사지기/종아리마사지기",
     "zh": ["足部按摩仪","脚底按摩器","小腿按摩仪","腿部按摩仪","气压按摩"],
     "en": ["foot massager","foot spa","leg massager","calf massager","air compression leg"],
     "safety": {"req": True, "std": "KC 60335-2-32"},
     "emc": {"req": True, "std": "CISPR 14-1"},
     "rf": {"req": False, "cond": "무선/Bluetooth 탑재 시 필요"}},
    {"id": "sonic_cleaner", "ko": "전동세안기/소닉클렌저",
     "zh": ["洁面仪","电动洗脸刷","硅胶洁面仪","声波洁面仪","振动洁面刷"],
     "en": ["electric facial cleansing","sonic cleanser","silicone cleanser","facial brush","cleansing device"],
     "safety": {"req": True, "std": "KC 60335-2-23"},
     "emc": {"req": True, "std": "CISPR 14-1"},
     "rf": {"req": False, "cond": "무선 기능 탑재 시 필요"}},
    {"id": "hair_cap", "ko": "헤어트리트먼트캡/스팀헤어캡",
     "zh": ["蒸汽发膜帽","电热护发帽","加热发膜帽","蒸汽焗油帽"],
     "en": ["hair treatment cap","steam hair cap","heated hair cap","electric hair cap","hair steamer cap"],
     "safety": {"req": True, "std": "KC 60335-2-23", "note": "발열 소자 포함 헤어케어 기기"},
     "emc": {"req": True, "std": "CISPR 14-1"},
     "rf": {"req": False}},
]

# -----------------------------
# 제품 카테고리 매칭
# -----------------------------
WIRELESS_PATTERN = re.compile(
    r"bluetooth|wifi|wi-fi|wireless|무선|蓝牙|无线|zigbee|nfc|rf|ble", re.IGNORECASE
)

def match_product_categories(text):
    lower = text.lower()
    matched = []
    has_wireless = bool(WIRELESS_PATTERN.search(text))

    for p in KC_DB:
        en_match = any(k.lower() in lower for k in p["en"])
        zh_match = any(k in text for k in p["zh"])
        ko_names = p["ko"].replace("/", "|").split("|")
        ko_match = any(k.lower() in lower for k in ko_names)

        if en_match or zh_match or ko_match:
            matched_by = "영어" if en_match else ("중국어" if zh_match else "한국어")
            rf_required = p["rf"]["req"] or (has_wireless and bool(p["rf"].get("cond")))
            matched.append({**p, "matched_by": matched_by, "rf_required": rf_required, "has_wireless": has_wireless})

    return matched, has_wireless

# -----------------------------
# 분석 내용 생성
# -----------------------------
def build_factory_checklist(cert_result, spec_text):
    items = [
        "- 공장 기본정보 확인: 사업자 정보, 생산 품목, 주요 거래처, 월 생산량",
        "- 생산 라인 확인: 조립/검사/포장 공정 분리 여부",
        "- 원부자재 보관 상태 확인: LOT 관리, 오염/습기 방지",
        "- 품질관리 체계 확인: IQC, IPQC, OQC 운영 여부",
        "- 불량 대응 프로세스 확인: 재작업, 폐기, 원인 분석",
        "- 시험장비 보유 여부 확인: 전원시험, 외관검사, 내구검사 도구",
        "- 생산이력 추적 여부 확인: 시리얼, 바코드, 생산일자 관리",
        "- 인증 대응자료 보유 여부 확인: 부품 스펙서, 시험성적서, 회로자료"
    ]

    if cert_result["kc_safety"] == "필수":
        items.append("- 안전 관련 부품(어댑터, 배터리, 전원부)의 인증서/사양서 보유 여부 확인")
    if cert_result["kc_emc"] == "필수":
        items.append("- EMC 대응을 위한 접지, 차폐, 회로 안정화 설계 여부 확인")
    if cert_result["kc_rf"] == "필수":
        items.append("- 안테나 구조, 무선모듈 사양, 주파수 대역 자료 확보 여부 확인")

    return "\n".join(items)

def build_first_quality_check(spec_text):
    norm = normalize_text(spec_text)
    items = [
        "- 외관 확인: 스크래치, 찍힘, 오염, 단차 여부",
        "- 치수 확인: 주요 규격, 허용오차, 조립 상태",
        "- 기능 확인: 전원, 버튼, 표시창, 기본 동작 테스트",
        "- 구성품 확인: 본체, 케이블, 설명서, 액세서리 누락 여부",
        "- 마감 확인: 인쇄 품질, 로고 위치, 색상 편차",
        "- 냄새/소음/발열 확인",
        "- 포장 전 제품 보호상태 확인"
    ]

    if "battery" in norm or "charging" in norm or "电池" in norm or "充电" in norm:
        items.append("- 배터리 관련 확인: 충전 테스트, 지속시간, 보호회로 동작 확인")
    if "bluetooth" in norm or "wifi" in norm or "wireless" in norm or "蓝牙" in norm or "无线" in norm:
        items.append("- 무선 연결 품질 확인: 페어링 시간, 연결거리, 끊김 여부")
    if "led" in norm or "display" in norm or "显示" in norm:
        items.append("- 표시부 확인: 점등 불량, 밝기 편차, 표시 오류")

    return "\n".join(items)

def build_cert_sample_plan(cert_result):
    items = [
        "- 인증 샘플 수량 사전 확인 및 예비 샘플 확보",
        "- 양산품과 동일한 BOM 기준으로 샘플 제작",
        "- 제품 라벨 정보 정리: 모델명, 정격, 제조자, 제조국",
        "- 사용자 설명서 초안 준비",
        "- 부품 스펙서 및 회로/블록도(있는 경우) 확보",
        "- 시험 중 파손/수정 가능성 대비 예비 샘플 준비"
    ]

    if cert_result["kc_safety"] == "필수":
        items.append("- 전원부/어댑터/배터리 관련 인증서 및 정격 자료 준비")
    if cert_result["kc_emc"] == "필수":
        items.append("- 동작 모드별 시험 조건 및 worst-case 상태 정리")
    if cert_result["kc_rf"] == "필수":
        items.append("- 주파수 정보, 안테나 사양, 무선모듈 자료 준비")

    return "\n".join(items)

def build_second_quality_check(cert_result):
    items = [
        "- 인증 샘플과 양산품 일치 여부 확인",
        "- 수정/개선사항 반영 여부 재확인",
        "- 최종 외관 품질 및 기능 안정성 확인",
        "- 기본 내구 테스트: 낙하, 반복동작, 진동",
        "- 라벨 문구/모델명/정격표기 일치 여부 확인",
        "- 설명서/패키지/본품 간 정보 일치 여부 확인",
        "- 출하 전 랜덤 샘플링 기준 수립"
    ]

    if cert_result["kc_rf"] == "필수":
        items.append("- 무선 연결 안정성, 통신거리, 간섭 여부 재확인")
    if cert_result["kc_safety"] == "필수":
        items.append("- 장시간 동작 시 발열, 충전 안정성 재확인")

    return "\n".join(items)

def build_package_plan(spec_text, cert_result):
    norm = normalize_text(spec_text)
    cautions = []
    strengths = []

    if cert_result["kc_safety"] == "필수":
        cautions.append("전원/배터리 관련 주의문구 및 정격표기 필요")
    if cert_result["kc_rf"] == "필수":
        cautions.append("무선 기능 및 모델 정보 표기 정리 필요")
    if "glass" in norm or "fragile" in norm or "玻璃" in norm:
        cautions.append("파손주의 포장 설계 필요")
    if "portable" in norm or "compact" in norm or "便携" in norm:
        strengths.append("휴대성 강조 패키지 문구 구성 가능")
    if "metal" in norm or "premium" in norm or "金属" in norm:
        strengths.append("프리미엄 소재감 강조 가능")

    if not cautions:
        cautions.append("기본 법정표기 및 운송 안정성 위주 설계 권장")
    if not strengths:
        strengths.append("제품 핵심 기능 중심의 간결한 패키지 메시지 구성이 적합")

    return "[특이사항]\n- " + "\n- ".join(cautions) + "\n\n[장점]\n- " + "\n- ".join(strengths)

def build_detail_page_points(spec_text, cert_result):
    norm = normalize_text(spec_text)
    points = []
    usp = []

    if "portable" in norm or "compact" in norm or "便携" in norm:
        points.append("- 작고 가벼워 어디서나 편리하게 사용 가능")
        usp.append("- 휴대성과 사용 편의성")
    if "battery" in norm or "charging" in norm or "电池" in norm or "充电" in norm:
        points.append("- 충전식 사용으로 공간 제약 없이 활용 가능")
        usp.append("- 무선/충전 기반 활용성")
    if "bluetooth" in norm or "wifi" in norm or "wireless" in norm or "蓝牙" in norm or "无线" in norm:
        points.append("- 무선 연결로 복잡한 케이블 없이 간편한 사용")
        usp.append("- 스마트 연결성")
    if "led" in norm or "display" in norm or "显示" in norm:
        points.append("- 직관적인 표시부로 상태 확인이 쉬움")
        usp.append("- 직관적 인터페이스")
    if "metal" in norm or "premium" in norm or "金属" in norm:
        points.append("- 소재와 마감에서 느껴지는 높은 완성도")
        usp.append("- 고급스러운 디자인 완성도")

    if cert_result["kc_safety"] == "필수" or cert_result["kc_emc"] == "필수" or cert_result["kc_rf"] == "필수":
        points.append("- 국내 유통 전 인증 검토 포인트를 반영한 제품")
        usp.append("- 국내 유통 대응력")

    if not points:
        points = [
            "- 제품 핵심 기능을 한눈에 이해할 수 있도록 구조화 필요",
            "- 사용 장면 중심 이미지와 함께 장점 전달 권장"
        ]
    if not usp:
        usp = ["- 기능 중심의 명확한 포지셔닝"]

    return "[상세페이지 소구점]\n" + "\n".join(points) + "\n\n[USP]\n" + "\n".join(sorted(set(usp)))

# -----------------------------
# UI
# -----------------------------
st.title("KC 인증 및 품질 프로세스 분석기")
st.caption("영어/중국어 규격서 PDF와 제품 사진을 바탕으로 KC 인증 필요 여부 및 품질/패키지/상세페이지 포인트를 정리합니다.")

with st.sidebar:
    st.header("사용 방법")
    st.write("1. 영어 또는 중국어 규격서 PDF를 업로드하세요.")
    st.write("2. 제품 사진을 업로드하세요.")
    st.write("3. 분석 실행 버튼을 누르세요.")
    st.info("주의: 본 결과는 참고용 1차 자동판단입니다. 최종 인증 여부는 전문기관 검토가 필요합니다.")

pdf_file = st.file_uploader("규격서 PDF 업로드", type=["pdf"])
image_files = st.file_uploader("제품 사진 업로드", type=["png", "jpg", "jpeg"], accept_multiple_files=True)
extra_notes = st.text_area(
    "추가 메모(선택)",
    placeholder="예: English spec sheet / Chinese user manual / Bluetooth rechargeable lamp"
)

col1, col2 = st.columns([1, 1])

with col1:
    st.subheader("업로드 미리보기")
    if pdf_file:
        st.success(f"PDF 업로드 완료: {pdf_file.name}")
    else:
        st.warning("PDF를 업로드해주세요.")

    if image_files:
        st.success(f"이미지 {len(image_files)}장 업로드 완료")
        preview_cols = st.columns(min(len(image_files), 3))
        for idx, img_file in enumerate(image_files[:3]):
            image = Image.open(img_file)
            preview_cols[idx % 3].image(image, caption=img_file.name, use_container_width=True)
    else:
        st.warning("제품 사진을 업로드해주세요.")

with col2:
    st.subheader("분석 기준")
    st.write("- 1차로 PyPDF2로 텍스트를 추출합니다.")
    st.write("- 텍스트가 거의 없으면 OCR(EasyOCR)로 자동 재시도합니다.")
    st.write("- 영어/중국어 키워드 기준으로 KC 안전, EMC, RF 필요 여부를 추정합니다.")
    st.write("- 제품 카테고리 DB(43종)로 적용 KC 표준까지 안내합니다.")

if st.button("분석 실행", type="primary", use_container_width=True):
    if not pdf_file:
        st.error("규격서 PDF를 업로드한 뒤 다시 실행해주세요.")
    else:
        spec_text, extracted_by = smart_extract_text(pdf_file)
        combined_text = spec_text + "\n" + extra_notes

        cert_result = judge_certifications(combined_text)
        factory_checklist = build_factory_checklist(cert_result, combined_text)
        first_quality = build_first_quality_check(combined_text)
        cert_sample = build_cert_sample_plan(cert_result)
        second_quality = build_second_quality_check(cert_result)
        package_plan = build_package_plan(combined_text, cert_result)
        detail_page = build_detail_page_points(combined_text, cert_result)

        # 제품 카테고리 매칭
        matched_cats, has_wireless = match_product_categories(combined_text)

        st.divider()
        st.header("분석 결과")
        st.info(f"텍스트 추출 방식: {extracted_by}")

        st.subheader("1. KC 안전인증: 필수 / 해당 없음")
        st.write(cert_result["kc_safety"])

        st.subheader("2. KC EMC 인증: 필수 / 해당 없음")
        st.write(cert_result["kc_emc"])

        st.subheader("3. KC RF 무선인증: 필수 / 해당 없음")
        st.write(cert_result["kc_rf"])

        st.subheader("4. 판단 근거")
        st.text(cert_result["reason"])

        # ── 제품 카테고리별 KC 표준 (신규) ──────────────────
        st.divider()
        st.subheader("📋 제품 카테고리별 KC 인증 기준")
        if has_wireless:
            st.info("🔵 무선 기능 키워드 감지됨 — 조건부 RF 인증 항목도 필수로 표시됩니다.")

        if matched_cats:
            for cat in matched_cats:
                with st.expander(f"🔍 {cat['ko']}  ·  매칭: {cat['matched_by']} 키워드"):
                    c1, c2, c3 = st.columns(3)

                    with c1:
                        st.markdown("**🔴 KC 안전인증**")
                        label = "✅ 필수" if cat["safety"]["req"] else "➖ 불필요"
                        st.write(label)
                        st.caption(f"기준: {cat['safety']['std']}")
                        if cat["safety"].get("note"):
                            st.caption(f"📌 {cat['safety']['note']}")

                    with c2:
                        st.markdown("**🟣 EMC 적합성**")
                        label = "✅ 필수" if cat["emc"]["req"] else "➖ 불필요"
                        st.write(label)
                        st.caption(f"기준: {cat['emc']['std']}")
                        if cat["emc"].get("note"):
                            st.caption(f"📌 {cat['emc']['note']}")

                    with c3:
                        st.markdown("**🔵 RF 전파인증**")
                        if cat["rf_required"]:
                            if cat["rf"].get("req"):
                                st.write("✅ 필수")
                            else:
                                st.write("⚠️ 조건부 필수")
                                st.caption(f"조건: {cat['rf'].get('cond','')}")
                        else:
                            if cat["rf"].get("cond"):
                                st.write("➖ 현재 불필요")
                                st.caption(f"단, {cat['rf'].get('cond','')}")
                            else:
                                st.write("➖ 불필요")
                        if cat["rf"].get("std"):
                            st.caption(f"기준: {cat['rf']['std']}")
                        if cat["rf"].get("note"):
                            st.caption(f"📌 {cat['rf']['note']}")
        else:
            st.warning("DB에서 매칭되는 제품 카테고리를 찾지 못했습니다. 키워드를 추가 메모란에 직접 입력해보세요.")
            st.caption("지원 카테고리: 헤어드라이기, 고데기, 면도기, 마사지기, LED마스크, RF미용기, EMS기기, IPL제모기, 초음파미용기, 네일램프, 스티머, 블루투스기기, 충전기, 보조배터리, 드론 등 43종")
        # ─────────────────────────────────────────────────────

        st.divider()
        st.subheader("5. 공장 참관 체크리스트")
        st.markdown(factory_checklist)

        st.subheader("6. 1차 품질 검수")
        st.markdown(first_quality)

        st.subheader("7. 인증 샘플 준비")
        st.markdown(cert_sample)

        st.subheader("8. 2차 품질 검수")
        st.markdown(second_quality)

        st.subheader("9. 패키지 기획(특이사항, 장점)")
        st.markdown(package_plan)

        st.subheader("10. 상세페이지 소구점, USP")
        st.markdown(detail_page)

        with st.expander("추출된 규격서 텍스트 보기"):
            if spec_text:
                st.text_area("추출 텍스트", spec_text, height=350)
            else:
                st.warning("PDF에서 텍스트를 추출하지 못했습니다.")

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
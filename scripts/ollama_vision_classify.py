#!/usr/bin/env python3
"""
Ollama 视觉分类模块 - 使用 qwen3.5vl 模型识别图片并分类

分类类型：
- IMG: 产品图片
- CERT: 产品证书
- LIC: 产品生产批文
- PROC: 产品生产工艺及特色亮点
- TEST: 近三年产品检测报告
- CONT: 近三年销售合同
- INVO: 近三年销售发票
- REPO: 用户使用报告
- UNKN: 未分类
"""
import requests
import base64
import json
import re
from pathlib import Path
from typing import Dict, Optional


# 类型KEY字典
TYPE_KEYS = {
    "IMG": "产品图片",
    "CERT": "产品证书",
    "LIC": "产品生产批文",
    "PROC": "产品生产工艺及特色亮点",
    "TEST": "近三年产品检测报告",
    "CONT": "近三年销售合同",
    "INVO": "近三年销售发票",
    "REPO": "用户使用报告",
    "UNKN": "未分类"
}

# 类型缩写字典
TYPE_ABBREVIATIONS = {
    "产品图片": "IMG",
    "产品证书": "CERT",
    "产品生产批文": "LIC",
    "产品生产工艺及特色亮点": "PROC",
    "近三年产品检测报告": "TEST",
    "近三年销售合同": "CONT",
    "近三年销售发票": "INVO",
    "用户使用报告": "REPO",
    "未分类": "UNKN"
}

# 图片格式扩展名
IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.gif'}

# 通用分类提示词
PROMPT = """你是一个高新技术企业材料分类专家。请分析图片内容。

## 你的任务：
1. 判断图片属于哪种材料类型
2. 提取图片上所有可见文字

## 分类KEY（只能选一个）：
- IMG: 产品图片（产品实拍照片、外观图等）
- CERT: 产品证书（认证证书、资质证书、检测报告等）
- LIC: 产品生产批文（生产许可证、注册批文等）
- PROC: 产品生产工艺及特色亮点（工艺流程图、生产线照片等）
- TEST: 近三年产品检测报告（质检报告、检测结果等）
- CONT: 近三年销售合同（购销合同、协议等）
- INVO: 近三年销售发票（增值税发票、收据等）
- REPO: 用户使用报告（用户反馈、体验报告等）
- UNKN: 未分类（无法确定类型时使用）

## 输出格式（严格JSON，不要有任何额外文字）：
{"key": "类型KEY", "image_text": "图片上所有文字内容"}

## image_text 提取要求：
- 提取图片上所有可见文字，保持原有顺序
- 文字之间用"; "分隔
- 如果图片无文字，image_text 设为空字符串""

## 重要规则：
1. 只输出JSON，不要任何解释
2. 不要在image_text中包含类型名称或解释性文字，只包含图片原始文字
"""

# 分类型专用提示词 - 用于提取结构化信息用于命名
TYPE_SPECIFIC_PROMPTS = {
    "INVO": """你是一个发票信息提取专家。请从图片中提取发票关键信息。

## 输出格式（严格JSON）：
{
    "invoice_code": "发票代码",
    "invoice_number": "发票号码",
    "date": "开票日期",
    "products": ["产品1名称", "产品2名称"],
    "total_amount": "价税合计大写",
    "seller": "销售方名称",
    "buyer": "购买方名称"
}

## 提取规则：
- invoice_code: 发票代码（可选，没有则为空字符串）
- invoice_number: 发票号码（必须提取）
- date: 开票日期如"2024年01月01日"
- products: 产品名称列表，只提取主要产品名称，最多5个
- total_amount: 价税合计大写金额
- seller: 销售方名称
- buyer: 购买方名称
- 如果无法提取某字段，设为空字符串""
- 只输出JSON，不要任何解释
""",

    "CONT": """你是一个合同信息提取专家。请从图片中提取合同关键信息。

## 输出格式（严格JSON）：
{
    "contract_number": "合同编号",
    "date": "签订日期",
    "products": ["产品1名称", "产品2名称"],
    "total_amount": "合同总金额大写",
    "party_a": "甲方名称",
    "party_b": "乙方名称"
}

## 提取规则：
- contract_number: 合同编号（必须提取）
- date: 签订日期如"2024年01月01日"
- products: 产品名称列表，只提取主要产品名称，最多5个
- total_amount: 合同总金额大写
- party_a: 甲方（买方）名称
- party_b: 乙方（卖方）名称
- 如果无法提取某字段，设为空字符串""
- 只输出JSON，不要任何解释
""",

    "CERT": """你是一个证书信息提取专家。请从图片中提取证书关键信息。

## 输出格式（严格JSON）：
{
    "cert_type": "证书类型如新药证书/生产许可证/ISO证书",
    "cert_number": "证书编号",
    "product_name": "产品名称",
    "holder": "持有人/企业名称",
    "date": "发证日期",
    "issuer": "发证机构"
}

## 提取规则：
- cert_type: 证书类型
- cert_number: 证书编号（必须提取）
- product_name: 产品名称（必须提取）
- holder: 持有人或企业名称
- date: 发证日期
- issuer: 发证机构
- 如果无法提取某字段，设为空字符串""
- 只输出JSON，不要任何解释
""",

    "TEST": """你是一个检测报告信息提取专家。请从图片中提取检测报告关键信息。

## 输出格式（严格JSON）：
{
    "report_number": "报告编号",
    "product_name": "产品名称",
    "batch_number": "批号",
    "test_date": "检验日期",
    "result": "检验结论",
    "tester": "检验机构"
}

## 提取规则：
- report_number: 报告编号（必须提取）
- product_name: 产品名称（必须提取）
- batch_number: 批号
- test_date: 检验日期
- result: 检验结论如"合格"
- tester: 检验机构/单位
- 如果无法提取某字段，设为空字符串""
- 只输出JSON，不要任何解释
""",

    "LIC": """你是一个许可证信息提取专家。请从图片中提取许可证关键信息。

## 输出格式（严格JSON）：
{
    "license_type": "许可证类型如生产许可证/注册证",
    "license_number": "许可证编号",
    "product_name": "产品名称",
    "holder": "持有人",
    "date": "发证日期",
    "issuer": "发证机构"
}

## 提取规则：
- license_type: 许可证类型
- license_number: 许可证编号（必须提取）
- product_name: 产品名称（必须提取）
- holder: 持有人/企业
- date: 发证日期
- issuer: 发证机构
- 如果无法提取某字段，设为空字符串""
- 只输出JSON，不要任何解释
""",

    "REPO": """你是一个用户报告信息提取专家。请从图片中提取报告关键信息。

## 输出格式（严格JSON）：
{
    "customer_name": "客户名称",
    "product_name": "产品名称",
    "report_date": "报告日期",
    "feedback": "主要反馈内容摘要"
}

## 提取规则：
- customer_name: 客户名称（必须提取）
- product_name: 产品名称
- report_date: 填写/报告日期
- feedback: 主要反馈内容摘要，最多50字
- 如果无法提取某字段，设为空字符串""
- 只输出JSON，不要任何解释
""",

    "PROC": """你是一个工艺文件信息提取专家。请从图片中提取工艺关键信息。

## 输出格式（严格JSON）：
{
    "doc_type": "文档类型如工艺规程/操作规程",
    "product_name": "产品名称",
    "process_name": "工艺名称",
    "version": "版本号"
}

## 提取规则：
- doc_type: 文档类型
- product_name: 产品名称
- process_name: 工艺名称
- version: 版本号
- 如果无法提取某字段，设为空字符串""
- 只输出JSON，不要任何解释
""",

    "IMG": """你是一个产品图片信息提取专家。请从图片中提取产品关键信息。

## 输出格式（严格JSON）：
{
    "product_name": "产品名称",
    "brand": "品牌",
    "description": "产品描述"
}

## 提取规则：
- product_name: 产品名称（如果能看到）
- brand: 品牌名称
- description: 产品描述摘要，最多30字
- 如果无法提取某字段，设为空字符串""
- 只输出JSON，不要任何解释
"""
}


def get_type_specific_prompt(file_type: str) -> str:
    """获取指定类型的专用提示词"""
    return TYPE_SPECIFIC_PROMPTS.get(file_type, PROMPT)


def parse_llm_response(response: str) -> dict:
    """解析LLM响应（JSON格式）"""
    if not response:
        return {"key": "UNKN", "image_text": ""}

    # 去除 markdown 代码块
    response = re.sub(r'^```json\s*', '', response, flags=re.MULTILINE)
    response = re.sub(r'^```\s*$', '', response, flags=re.MULTILINE)
    response = response.strip()

    # 尝试提取JSON（支持多行JSON）
    json_patterns = [
        r'\{[^{}]*\}',  # 简单单层
        r'\{[\s\S]*?\}',  # 多行复杂JSON
    ]

    for pattern in json_patterns:
        json_matches = re.findall(pattern, response)
        for match in json_matches:
            try:
                result = json.loads(match)
                # 确保包含必要的字段（处理字段名变体）
                key = result.get("key") or result.get("image") or result.get("type") or result.get("category")
                text = result.get("image_text") or result.get("text") or result.get("content") or result.get("description")

                if key:
                    # 清理 key 值，只保留有效的类型KEY
                    key_upper = str(key).upper()
                    valid_keys = ["IMG", "CERT", "LIC", "PROC", "TEST", "CONT", "INVO", "REPO", "UNKN"]
                    matched_key = "UNKN"
                    for vk in valid_keys:
                        if vk in key_upper:
                            matched_key = vk
                            break
                    return {
                        "key": matched_key,
                        "image_text": text if text else ""
                    }
            except (json.JSONDecodeError, AttributeError):
                continue

    # 回退：尝试从原始文本中提取
    result = {"key": "UNKN", "image_text": ""}
    response_upper = response.upper()

    # 提取类型
    valid_keys = ["IMG", "CERT", "LIC", "PROC", "TEST", "CONT", "INVO", "REPO", "UNKN"]
    for k in valid_keys:
        if k in response_upper:
            result["key"] = k
            break

    # 尝试提取文本内容
    text_patterns = [
        r'image_text["\s:]+["\']([^"\']*)["\']',
        r'text["\s:]+["\']([^"\']*)["\']',
        r'content["\s:]+["\']([^"\']*)["\']',
    ]
    for pattern in text_patterns:
        text_match = re.search(pattern, response, re.DOTALL)
        if text_match and text_match.group(1).strip():
            result["image_text"] = text_match.group(1).strip()
            break

    # 如果没有提取到文本，用描述字段
    if not result["image_text"]:
        desc_match = re.search(r'description["\s:]+["\']([^"\']*)["\']', response, re.DOTALL)
        if desc_match:
            result["image_text"] = desc_match.group(1).strip()

    return result


def classify_image(img_path: str,
                  ollama_url: str = "http://192.168.1.26:11434",
                  model: str = "qwen3.5:0.8b",
                  think: bool = True,
                  timeout: int = 120) -> Dict[str, str]:
    """
    使用 Ollama API 识别图片并提取文字

    Args:
        img_path: 图片文件路径
        ollama_url: Ollama 服务地址
        model: 模型名称
        think: 是否开启思考模式
        timeout: 超时时间（秒）

    Returns:
        {"key": "类型KEY", "image_text": "图片文字内容"}
    """
    # 读取图片并转为 base64
    with open(img_path, "rb") as f:
        img_base64 = base64.b64encode(f.read()).decode("utf-8")

    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": PROMPT,
                "images": [img_base64]
            }
        ],
        "think": think,
        "format": "json",
        "stream": False
    }

    try:
        response = requests.post(
            f"{ollama_url}/api/chat",
            json=payload,
            timeout=timeout
        )
        if response.status_code == 200:
            result = response.json()
            raw_response = result["message"]["content"].strip()

            # 解析响应
            parsed = parse_llm_response(raw_response)
            return parsed
        else:
            return {"key": "UNKN", "image_text": f"HTTP {response.status_code}"}
    except Exception as e:
        return {"key": "UNKN", "image_text": str(e)}


def is_image_file(file_path: str) -> bool:
    """判断是否为图片文件"""
    return Path(file_path).suffix.lower() in IMAGE_EXTS


def classify_file(file_path: str,
                   ollama_url: str = "http://192.168.1.26:11434",
                   model: str = "qwen3.5:0.8b",
                   think: bool = True,
                   timeout: int = 120) -> Dict[str, str]:
    """
    分类单个文件（自动判断是否为图片）

    Args:
        file_path: 文件路径
        ollama_url: Ollama 服务地址
        model: 模型名称
        think: 是否开启思考模式
        timeout: 超时时间（秒）

    Returns:
        {"key": "类型KEY", "image_text": "图片文字内容"}
    """
    if is_image_file(file_path):
        return classify_image(file_path, ollama_url, model, think, timeout)
    else:
        # 非图片文件，返回未分类（应由调用方先转换）
        return {"key": "UNKN", "image_text": "非图片文件"}


def parse_structured_response(response: str) -> dict:
    """解析结构化信息响应"""
    if not response:
        return {}

    # 去除 markdown 代码块
    response = re.sub(r'^```json\s*', '', response, flags=re.MULTILINE)
    response = re.sub(r'^```\s*$', '', response, flags=re.MULTILINE)
    response = response.strip()

    # 尝试提取JSON
    json_patterns = [
        r'\{[\s\S]*?\}',
    ]

    for pattern in json_patterns:
        json_matches = re.findall(pattern, response)
        for match in json_matches:
            try:
                result = json.loads(match)
                return result
            except (json.JSONDecodeError, AttributeError):
                continue

    return {}


def extract_structured_info(img_path: str,
                             file_type: str,
                             ollama_url: str = "http://192.168.1.26:11434",
                             model: str = "qwen3.5:0.8b",
                             think: bool = False,
                             timeout: int = 120) -> dict:
    """
    使用分类型专用提示词提取结构化信息

    Args:
        img_path: 图片路径
        file_type: 文件类型（如 INVO、CONT 等）
        ollama_url: Ollama 服务地址
        model: 模型名称
        think: 是否开启思考模式（结构化提取建议关闭）
        timeout: 超时时间

    Returns:
        结构化信息字典
    """
    # 读取图片并转为 base64
    with open(img_path, "rb") as f:
        img_base64 = base64.b64encode(f.read()).decode("utf-8")

    # 获取对应类型的提示词
    prompt = get_type_specific_prompt(file_type)

    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": prompt,
                "images": [img_base64]
            }
        ],
        "think": think,
        "format": "json",
        "stream": False
    }

    try:
        response = requests.post(
            f"{ollama_url}/api/chat",
            json=payload,
            timeout=timeout
        )
        if response.status_code == 200:
            result = response.json()
            raw_response = result["message"]["content"].strip()
            return parse_structured_response(raw_response)
        else:
            return {}
    except Exception:
        return {}


def generate_filename_from_info(file_type: str, info: dict) -> str:
    """
    根据结构化信息生成文件名的一部分

    Args:
        file_type: 文件类型
        info: 结构化信息字典

    Returns:
        文件名部分字符串
    """
    parts = []

    if file_type == "INVO":
        # 发票：发票号码 + 产品（多个合并）
        if info.get("invoice_number"):
            parts.append(info["invoice_number"])
        products = info.get("products", [])
        if products:
            # 最多取前3个产品，合并
            products = products[:3]
            if len(products) > 1:
                product_str = "-".join(products)
            else:
                product_str = products[0] if products else ""
            if product_str:
                parts.append(product_str)

    elif file_type == "CONT":
        # 合同：合同编号 + 产品
        if info.get("contract_number"):
            parts.append(info["contract_number"])
        products = info.get("products", [])
        if products:
            products = products[:3]
            if len(products) > 1:
                product_str = "-".join(products)
            else:
                product_str = products[0] if products else ""
            if product_str:
                parts.append(product_str)

    elif file_type == "CERT":
        # 证书：证书编号 + 产品名称
        if info.get("cert_number"):
            parts.append(info["cert_number"])
        if info.get("product_name"):
            parts.append(info["product_name"])

    elif file_type == "TEST":
        # 检测报告：报告编号 + 产品名称
        if info.get("report_number"):
            parts.append(info["report_number"])
        if info.get("product_name"):
            parts.append(info["product_name"])

    elif file_type == "LIC":
        # 许可证：许可证编号 + 产品名称
        if info.get("license_number"):
            parts.append(info["license_number"])
        if info.get("product_name"):
            parts.append(info["product_name"])

    elif file_type == "REPO":
        # 用户报告：客户名称 + 产品
        if info.get("customer_name"):
            parts.append(info["customer_name"])
        if info.get("product_name"):
            parts.append(info["product_name"])

    elif file_type == "PROC":
        # 工艺文档：文档类型 + 产品
        if info.get("doc_type"):
            parts.append(info["doc_type"])
        if info.get("product_name"):
            parts.append(info["product_name"])

    elif file_type == "IMG":
        # 产品图片：产品名称
        if info.get("product_name"):
            parts.append(info["product_name"])

    # 清理并返回
    result = "_".join(parts)
    # 移除特殊字符
    result = re.sub(r'[\\/:*?"<>|]', '', result)
    return result[:100]  # 限制长度


def key_to_category(key: str) -> str:
    """将类型KEY转换为中文类别名称"""
    return TYPE_KEYS.get(key.upper(), "未分类")


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("用法: python ollama_vision_classify.py <图片路径>")
        sys.exit(1)

    img_path = sys.argv[1]
    result = classify_image(img_path)
    print(f"类型: {result['key']} - {key_to_category(result['key'])}")
    print(f"文字: {result['image_text'][:100]}{'...' if len(result['image_text']) > 100 else ''}")

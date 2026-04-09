#!/usr/bin/env python3
"""
流水线调度器 - 使用 Ollama 视觉模型分类并整理文件

工作流程：
1. 遍历输入目录所有支持的文件
2. 判断文件类型：
   - 图片文件 (.jpg, .png 等) → 直接用 Ollama 分类
   - 文档文件 (.pdf, .docx) → 转换为第一页图片 → 用 Ollama 分类
3. 分类完成后重命名并移动到对应目录

用法：
    python scripts/pipeline.py -i ./客户原始数据 -o ./整理结果
"""

import argparse
import csv
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, List

# 添加脚本目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from ollama_vision_classify import (
    classify_image,
    is_image_file,
    key_to_category,
    TYPE_KEYS,
    extract_structured_info,
    generate_filename_from_info
)
from document_to_image import (
    convert_first_page_to_image,
    is_document_file
)
from rename_files import rename_single


# 支持的文件扩展名
SUPPORTED_EXTS = {'.pdf', '.docx', '.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.gif'}

# CSV 处理记录文件名
PROCESS_LOG_FILENAME = "process_log.csv"


class PipelineOrchestrator:
    """流水线调度器"""

    def __init__(self,
                 input_dir: str,
                 output_dir: str,
                 ollama_url: str = "http://localhost:11434",
                 model: str = "qwen3.5:0.8b",
                 think: bool = True,
                 copy_mode: bool = True,
                 skip_existing: bool = True):
        self.input_dir = input_dir
        self.output_dir = output_dir
        self.ollama_url = ollama_url
        self.model = model
        self.think = think
        self.copy_mode = copy_mode
        self.skip_existing = skip_existing

        # 分类报告路径
        self.report_path = os.path.join(output_dir, "classification_report.json")

        # 现有报告（用于增量处理）
        self.existing_report = self._load_existing_report()

        # 统计
        self.stats = {
            "total": 0,
            "skipped": 0,
            "converted": 0,
            "classified": 0,
            "renamed": 0,
            "errors": []
        }

        # 关键词兜底分类规则（用于 UNKN 时）
        self.keyword_fallback = {
            "INVO": ["发票", "增值税", "专用发票", "电子发票", "价税合计", "税额", "开票日期", "发票号码"],
            "CONT": ["合同", "协议书", "购销", "签订日期", "合同编号", "甲方", "乙方"],
            "TEST": ["检测", "检验", "质检", "报告", "化验", "合格", "不合格", "判定", "检验报告", "QC", "质量标准"],
            "CERT": ["证书", "认证", "资质", "iso", "3c", "ce", "授权", "认可", "新药证书"],
            "LIC": ["批文", "许可证", "生产许可", "注册证", "备案", "批准文号", "药品生产许可证"],
            "PROC": ["工艺", "流程", "工序", "配方", "生产", "制造", "工艺规程", "操作规程"],
            "REPO": ["使用报告", "用户反馈", "体验报告", "满意度", "客户反馈", "回访", "调查表"]
        }

    def _fallback_classify(self, image_text: str) -> str:
        """基于关键词的兜底分类"""
        if not image_text:
            return "UNKN"

        # 检查各分类关键词
        for key, keywords in self.keyword_fallback.items():
            for kw in keywords:
                if kw in image_text:
                    return key

        return "UNKN"

    def _extract_name_from_text(self, file_type: str, image_text: str) -> str:
        """从 image_text 提取关键信息用于命名"""
        if not image_text:
            return ""

        import re

        parts = []

        if file_type == "INVO":
            # 发票：发票号码 + 产品
            inv_num = re.search(r'发票号码[：:]\s*([0-9]+)', image_text)
            if inv_num:
                parts.append(inv_num.group(1))
            # 提取产品名称
            products = re.findall(r'[\*]*中成药\*?([^\s\d]+(?:?:颗粒|丸|糖浆|膏|片|口服液)?)', image_text)
            if products:
                unique_products = list(dict.fromkeys(products))[:3]  # 去重取前3
                if len(unique_products) > 1:
                    parts.append("-".join(unique_products))
                elif unique_products:
                    parts.append(unique_products[0])

        elif file_type == "CONT":
            # 合同：合同编号 + 产品
            cont_num = re.search(r'合同编号[：:]\s*([A-Z0-9]+)', image_text)
            if cont_num:
                parts.append(cont_num.group(1))
            # 提取产品
            products = re.findall(r'[\*]*中成药\*?([^\s\d]+(?:?:颗粒|丸|糖浆|膏|片)?)', image_text)
            if products:
                unique_products = list(dict.fromkeys(products))[:2]
                if len(unique_products) > 1:
                    parts.append("-".join(unique_products))
                elif unique_products:
                    parts.append(unique_products[0])

        elif file_type in ("CERT", "LIC"):
            # 证书/许可证：证书编号 + 产品名
            cert_num = re.search(r'证书编号[：:]\s*([A-Z0-9]+)', image_text)
            if cert_num:
                parts.append(cert_num.group(1))
            prod = re.search(r'产品名称[：:]\s*([^\s,，]+)', image_text)
            if prod:
                parts.append(prod.group(1))

        elif file_type == "TEST":
            # 检测报告：报告编号 + 产品名
            report_num = re.search(r'报告编号[：:]\s*([A-Z0-9\-]+)', image_text)
            if report_num:
                parts.append(report_num.group(1))
            prod = re.search(r'品名[：:]\s*([^\s,，]+)', image_text)
            if prod:
                parts.append(prod.group(1))

        elif file_type == "REPO":
            # 用户报告：客户名称
            customer = re.search(r'客户名称[：:]\s*([^\s,，]+)', image_text)
            if customer:
                parts.append(customer.group(1))

        elif file_type == "IMG":
            # 产品图片：尝试提取品牌或产品名称
            brand = re.search(r'(回音必|华佗|健康|制药)', image_text)
            if brand:
                parts.append(brand.group(1))

        # 清理特殊字符
        result = "_".join(parts)
        result = re.sub(r'[\\/:*?"<>|]', '', result)
        return result[:80]  # 限制长度

    def _load_existing_report(self) -> dict:
        """加载现有报告（用于增量处理）"""
        if os.path.exists(self.report_path):
            try:
                with open(self.report_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, Exception):
                pass
        return {"total_files": 0, "categories": {}}

    def _save_report(self):
        """保存报告"""
        with open(self.report_path, "w", encoding="utf-8") as f:
            json.dump(self.existing_report, f, ensure_ascii=False, indent=2)

    def _update_report(self, original_file: str, category: str):
        """增量更新报告"""
        if category not in self.existing_report["categories"]:
            self.existing_report["categories"][category] = {"count": 0, "files": []}

        # 避免重复添加
        if original_file not in self.existing_report["categories"][category]["files"]:
            self.existing_report["categories"][category]["count"] += 1
            self.existing_report["categories"][category]["files"].append(original_file)
            self.existing_report["total_files"] += 1

        self._save_report()

    def _get_process_log_path(self) -> str:
        """获取处理记录 CSV 路径（在输入目录）"""
        return os.path.join(self.input_dir, PROCESS_LOG_FILENAME)

    def _load_process_log(self) -> Dict[str, dict]:
        """加载处理记录，返回 {filename: {key, category, text, status}}"""
        log_path = self._get_process_log_path()
        records = {}

        if os.path.exists(log_path):
            try:
                with open(log_path, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        records[row['filename']] = {
                            'category_key': row.get('category_key', ''),
                            'category_name': row.get('category_name', ''),
                            'image_text': row.get('image_text', ''),
                            'status': row.get('status', ''),
                            'processed_at': row.get('processed_at', '')
                        }
            except Exception as e:
                print(f"  [警告] 读取处理记录失败: {e}")

        return records

    def _append_process_log(self, filename: str, category_key: str,
                          category_name: str, image_text: str, status: str,
                          final_path: str = ""):
        """追加处理记录到 CSV"""
        log_path = self._get_process_log_path()
        file_exists = os.path.exists(log_path)

        try:
            with open(log_path, 'a', encoding='utf-8', newline='') as f:
                writer = csv.writer(f, quoting=csv.QUOTE_ALL)

                # 如果文件不存在，写入表头
                if not file_exists:
                    writer.writerow(['filename', 'category_key', 'category_name',
                                   'image_text', 'processed_at', 'status', 'final_path'])

                # 清理 image_text 中的特殊字符
                clean_text = image_text.replace('"', "'").replace('\t', ' ')

                writer.writerow([
                    filename,
                    category_key,
                    category_name,
                    clean_text,
                    datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    status,
                    final_path
                ])
        except Exception as e:
            print(f"  [警告] 写入处理记录失败: {e}")

    def _classify_with_retry(self, img_path: str, max_retries: int = 3) -> dict:
        """
        带重试的分类调用

        Args:
            img_path: 图片路径
            max_retries: 最大重试次数

        Returns:
            分类结果 {"key": "...", "image_text": "..."}
        """
        for attempt in range(1, max_retries + 1):
            try:
                result = classify_image(
                    img_path,
                    ollama_url=self.ollama_url,
                    model=self.model,
                    think=self.think
                )

                key = result.get("key", "UNKN")
                image_text = result.get("image_text", "")
                error_msg = result.get("image_text", "")

                # 检查是否需要重试
                should_retry = False

                # HTTP 500 或其他错误
                if "HTTP 500" in error_msg or "HTTP 502" in error_msg or "HTTP 503" in error_msg:
                    print(f"    [重试 {attempt}/{max_retries}] HTTP 错误")
                    should_retry = True
                # image_text 为空（不管 key 是什么都要重试提取文本）
                elif not image_text:
                    print(f"    [重试 {attempt}/{max_retries}] image_text 为空")
                    should_retry = True
                # UNKN 不确定分类
                elif key == "UNKN":
                    print(f"    [重试 {attempt}/{max_retries}] UNKN 不确定分类")
                    should_retry = True

                if should_retry and attempt < max_retries:
                    import time
                    time.sleep(2)  # 等待 2 秒后重试
                    continue

                return result

            except Exception as e:
                error_str = str(e)
                print(f"    [重试 {attempt}/{max_retries}] 异常: {error_str}")
                if attempt < max_retries:
                    import time
                    time.sleep(2)
                    continue
                return {"key": "UNKN", "image_text": str(e)}

        return {"key": "UNKN", "image_text": "重试次数用尽"}

    def _process_single_file(self, file_path: str) -> Optional[str]:
        """
        处理单个文件

        Returns:
            分类结果 {"key": "...", "image_text": "..."}，失败返回 None
        """
        original_path = Path(file_path)
        filename = original_path.name
        ext = original_path.suffix.lower()
        temp_image_path = None

        try:
            # 检查是否已处理过（增量模式）- 从 CSV 读取
            if self.skip_existing:
                process_log = self._load_process_log()
                if filename in process_log:
                    status = process_log[filename].get('status', '')
                    existing_text = process_log[filename].get('image_text', '')
                    if status == 'done' and existing_text:
                        print(f"  [跳过] 已处理过 ({process_log[filename].get('category_key', '?')})")
                        self.stats["skipped"] += 1
                        return None

            # 判断文件类型并处理
            if is_image_file(file_path):
                # 图片文件：直接分类
                print(f"  [分类] 直接图片分类")
                result = self._classify_with_retry(file_path)
            elif is_document_file(file_path):
                # 文档文件：先转换为图片
                print(f"  [转换] 提取第一页为图片...")
                temp_image_path = convert_first_page_to_image(file_path)

                if not temp_image_path:
                    print(f"  [错误] 文档转换失败")
                    self._append_process_log(filename, "UNKN", "未分类", "", "error")
                    self.stats["errors"].append({
                        "file": file_path,
                        "error": "文档转换失败"
                    })
                    return None

                self.stats["converted"] += 1
                print(f"  [分类] 基于转换图片分类")

                # 使用转换后的图片进行分类
                result = self._classify_with_retry(temp_image_path)
            else:
                print(f"  [跳过] 不支持的格式 {ext}")
                self._append_process_log(filename, "UNKN", "未分类", "", "error")
                self.stats["errors"].append({
                    "file": file_path,
                    "error": f"不支持的格式 {ext}"
                })
                return None

            # 解析分类结果
            key = result.get("key", "UNKN")
            image_text = result.get("image_text", "")

            # 如果是 UNKN 但有文本内容，尝试关键词兜底分类
            if key == "UNKN" and image_text:
                fallback_key = self._fallback_classify(image_text)
                if fallback_key != "UNKN":
                    print(f"  [兜底] LLM UNKN -> 关键词匹配: {fallback_key}")
                    key = fallback_key

            category = key_to_category(key)

            print(f"  [结果] 类型: {key} - {category}")

            # 调用 LLM 提取结构化信息用于命名
            name_suffix = ""
            if key and key != "UNKN":
                name_img_path = temp_image_path if temp_image_path else file_path
                if os.path.exists(name_img_path):
                    try:
                        print(f"  [提取] 结构化信息...")
                        info = extract_structured_info(
                            name_img_path,
                            key,
                            ollama_url=self.ollama_url,
                            model=self.model,
                            think=False
                        )
                        if info:
                            name_suffix = generate_filename_from_info(key, info)
                            print(f"  [命名] 文件名部分: {name_suffix}")
                    except Exception as e:
                        print(f"  [警告] 结构化提取失败: {e}")

            # 重命名并移动文件
            rename_result = rename_single(
                file_path,
                category,
                self.output_dir,
                existing_report=self.existing_report,
                copy_mode=self.copy_mode,
                name_suffix=name_suffix
            )

            if rename_result["status"] == "success":
                self.stats["renamed"] += 1
                final_path = rename_result['new_path']
                print(f"  [完成] -> {Path(final_path).name}")
                # 记录到 CSV（包含最终路径）
                self._append_process_log(filename, key, category, image_text, "done", final_path)
            else:
                print(f"  [重命名失败] {rename_result.get('error', '未知错误')}")
                self.stats["errors"].append({
                    "file": file_path,
                    "error": rename_result.get("error", "重命名失败")
                })
                # 记录失败到 CSV
                self._append_process_log(filename, key, category, image_text, "error")

            self.stats["classified"] += 1
            return category

        finally:
            # 清理临时文件
            if temp_image_path and os.path.exists(temp_image_path):
                try:
                    os.unlink(temp_image_path)
                except Exception:
                    pass

    def run(self):
        """执行流水线"""
        # 收集所有待处理文件
        input_path = Path(self.input_dir)

        file_paths = []
        for ext in SUPPORTED_EXTS:
            # 排除 .doc（不支持）
            if ext == '.doc':
                continue
            file_paths.extend(input_path.rglob(f"*{ext}"))
        file_paths = [str(f) for f in file_paths]

        if not file_paths:
            print(f"在 {self.input_dir} 中未找到支持的文件格式")
            return

        self.stats["total"] = len(file_paths)

        # 确保输出目录存在
        os.makedirs(self.output_dir, exist_ok=True)

        print("=" * 60)
        print(f"流水线启动")
        print(f"  输入目录: {self.input_dir}")
        print(f"  输出目录: {self.output_dir}")
        print(f"  文件数量: {len(file_paths)}")
        print(f"  Ollama: {self.ollama_url}")
        print(f"  模型: {self.model}")
        print(f"  思考模式: {self.think}")
        print(f"  模式: {'复制' if self.copy_mode else '移动'}")
        print(f"  增量处理: {self.skip_existing}")
        print(f"  处理记录: {self._get_process_log_path()}")
        print("=" * 60)

        # 逐一处理文件
        for i, file_path in enumerate(file_paths, 1):
            print(f"\n[{i}/{len(file_paths)}] 处理: {Path(file_path).name}")
            self._process_single_file(file_path)

        # 输出最终统计
        print("\n" + "=" * 60)
        print("流水线完成")
        print(f"  总计: {self.stats['total']} 文件")
        print(f"  跳过: {self.stats['skipped']} | 转换: {self.stats['converted']} | 分类: {self.stats['classified']} | 重命名: {self.stats['renamed']}")
        if self.stats['errors']:
            print(f"  错误: {len(self.stats['errors'])}")
            for err in self.stats['errors'][:5]:
                print(f"    - {Path(err['file']).name}: {err['error']}")
        print(f"  报告: {self.report_path}")
        print("=" * 60)

        # 输出分类统计
        print("\n📊 分类统计:")
        for category, count in sorted(
            [(k, v.get("count", 0)) for k, v in self.existing_report.get("categories", {}).items()],
            key=lambda x: -x[1]
        ):
            abbr = {v: k for k, v in TYPE_KEYS.items()}.get(category, "???")
            print(f"  {abbr}: {count} 个文件")


def main():
    parser = argparse.ArgumentParser(
        description="流水线调度器 - 使用 Ollama 视觉模型分类并整理文件",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 基本用法
  python scripts/pipeline.py -i ./客户原始数据 -o ./整理结果

  # 指定 Ollama 地址和模型
  python scripts/pipeline.py -i ./客户原始数据 -o ./整理结果 --ollama-url http://localhost:11434 --model qwen3.5:0.8b

  # 禁用思考模式（更快）
  python scripts/pipeline.py -i ./客户原始数据 -o ./整理结果 --no-think

  # 移动文件（默认是复制）
  python scripts/pipeline.py -i ./客户原始数据 -o ./整理结果 --move

  # 重新处理所有文件（跳过增量模式）
  python scripts/pipeline.py -i ./客户原始数据 -o ./整理结果 --no-skip-existing
        """
    )

    parser.add_argument("-i", "--input", required=True,
                        help="输入目录（原始材料）")
    parser.add_argument("-o", "--output", required=True,
                        help="输出目录（分类整理后的文件）")
    parser.add_argument("--ollama-url", default="http://localhost:11434",
                        help="Ollama 服务地址 (默认: http://localhost:11434)")
    parser.add_argument("--model", default="qwen3.5:0.8b",
                        help="Ollama 模型名称 (默认: qwen3.5:0.8b)")
    parser.add_argument("--no-think", action="store_true",
                        help="禁用思考模式（响应更快）")
    parser.add_argument("--move", action="store_true",
                        help="移动文件（默认是复制）")
    parser.add_argument("--no-skip-existing", action="store_true",
                        help="禁用增量模式，重新处理所有文件")
    # 默认启用自动重处理空记录，不需要显式参数

    args = parser.parse_args()

    # 创建调度器
    orchestrator = PipelineOrchestrator(
        input_dir=args.input,
        output_dir=args.output,
        ollama_url=args.ollama_url,
        model=args.model,
        think=not args.no_think,
        copy_mode=not args.move,
        skip_existing=not args.no_skip_existing
    )

    orchestrator.run()


if __name__ == "__main__":
    main()

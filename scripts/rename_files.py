#!/usr/bin/env python3
"""
文件重命名脚本 - 根据分类类型将混乱的MD5文件名改为有意义的名字

输出格式: {类型缩写}_{序号}.{扩展名}
示例: IMG_001.jpg, CERT_001.png, TEST_003_检测报告.pdf
"""

import os
import json
import shutil
import argparse
from pathlib import Path
from typing import Dict, List
from collections import defaultdict


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

# 反向映射：缩写 -> 类型名
ABBREV_TO_TYPE = {v: k for k, v in TYPE_ABBREVIATIONS.items()}


def get_next_index(counter: Dict[str, int], category: str) -> int:
    """获取下一个序号"""
    counter[category] = counter.get(category, 0) + 1
    return counter[category]


def generate_new_filename(original_path: str, category: str, index: int, keyword: str = None) -> str:
    """
    生成新文件名

    Args:
        original_path: 原始文件路径
        category: 分类类型
        index: 序号
        keyword: 关键词（可选，用于生成描述性名称）

    Returns:
        新的文件名
    """
    ext = Path(original_path).suffix.lower()
    abbr = TYPE_ABBREVIATIONS.get(category, "UNKN")

    # 如果有关键词，保留一部分作为描述
    if keyword:
        # 截取关键词前4个字符
        keyword_part = keyword[:4]
        new_name = f"{abbr}_{index:03d}_{keyword_part}{ext}"
    else:
        new_name = f"{abbr}_{index:03d}{ext}"

    return new_name


def rename_and_organize(
    classified_files: Dict[str, List[str]],
    output_dir: str,
    copy_mode: bool = True
) -> Dict[str, List[Dict]]:
    """
    根据分类结果重命名并整理文件

    Args:
        classified_files: {分类类型: [文件路径列表]}
        output_dir: 输出目录
        copy_mode: True=复制, False=移动

    Returns:
        重命名结果报告
    """
    output_path = Path(output_dir)
    counters = {}  # 每个类型的计数器

    results = defaultdict(list)

    for category, files in classified_files.items():
        # 创建该类型的子目录
        category_dir = output_path / category
        category_dir.mkdir(parents=True, exist_ok=True)

        abbr = TYPE_ABBREVIATIONS.get(category, "UNKN")

        for i, original_file in enumerate(files, 1):
            if not os.path.exists(original_file):
                print(f"  ⚠️  文件不存在: {original_file}")
                continue

            original_path = Path(original_file)
            ext = original_path.suffix.lower()

            # 生成新文件名
            new_filename = generate_new_filename(original_file, category, i)
            new_file_path = category_dir / new_filename

            # 处理重名（如果已存在）
            counter = 1
            while new_file_path.exists():
                new_filename = generate_new_filename(original_file, category, i, f"v{counter}")
                new_file_path = category_dir / new_filename
                counter += 1

            # 复制或移动文件
            try:
                if copy_mode:
                    shutil.copy2(original_file, new_file_path)
                else:
                    shutil.move(original_file, new_file_path)

                results[category].append({
                    "original": original_file,
                    "renamed": str(new_file_path),
                    "status": "success"
                })

                print(f"  ✅ {abbr}_{i:03d} <- {original_path.name}")

            except Exception as e:
                results[category].append({
                    "original": original_file,
                    "error": str(e),
                    "status": "failed"
                })
                print(f"  ❌ {original_path.name}: {e}")

    return results


def rename_single(original_file: str, category: str, output_dir: str,
                 existing_report: dict = None, copy_mode: bool = True,
                 name_suffix: str = "") -> dict:
    """
    重命名单个文件（增量处理）

    Args:
        original_file: 原始文件路径
        category: 分类类型
        output_dir: 输出目录
        existing_report: 现有分类报告（用于获取序号计数器）
        copy_mode: True=复制, False=移动
        name_suffix: 文件名后缀（如发票号码+产品名）

    Returns:
        {"status": "success"/"failed", "new_path": str, "category_index": int, "error": str}
    """
    if not os.path.exists(original_file):
        return {"status": "failed", "original": original_file, "error": "文件不存在"}

    # 从现有 report 获取该 category 的当前计数
    counter = 0
    if existing_report and "categories" in existing_report:
        cat_data = existing_report["categories"].get(category, {})
        counter = cat_data.get("count", 0)

    # 生成新文件名
    abbr = TYPE_ABBREVIATIONS.get(category, "UNKN")
    new_index = counter + 1
    ext = Path(original_file).suffix.lower()

    if name_suffix:
        # 清理文件名后缀中的特殊字符
        safe_suffix = "".join(c for c in name_suffix if c.isalnum() or c in ('_', '-', ' ')).strip()
        safe_suffix = safe_suffix.replace(' ', '-')
        new_filename = f"{abbr}_{new_index:03d}_{safe_suffix}{ext}"
    else:
        new_filename = f"{abbr}_{new_index:03d}{ext}"

    # 创建目录并复制/移动
    category_dir = Path(output_dir) / category
    category_dir.mkdir(parents=True, exist_ok=True)
    new_path = category_dir / new_filename

    # 处理重名
    while new_path.exists():
        if name_suffix:
            new_filename = f"{abbr}_{new_index:03d}_{safe_suffix}_v2{ext}"
        else:
            new_filename = f"{abbr}_{new_index:03d}_v2{ext}"
        new_path = category_dir / new_filename
        new_index += 1

    try:
        if copy_mode:
            shutil.copy2(original_file, new_path)
        else:
            shutil.move(original_file, new_path)

        return {
            "status": "success",
            "original": original_file,
            "new_path": str(new_path),
            "category": category,
            "category_index": new_index
        }
    except Exception as e:
        return {"status": "failed", "original": original_file, "error": str(e)}


def save_rename_report(results: Dict[str, List[Dict]], output_path: str):
    """保存重命名报告"""
    report = {
        "total_files": sum(len(files) for files in results.values()),
        "successful": sum(1 for files in results.values() for f in files if f["status"] == "success"),
        "failed": sum(1 for files in results.values() for f in files if f["status"] == "failed"),
        "files": results
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"\n📄 重命名报告已保存: {output_path}")
    return report


def main():
    parser = argparse.ArgumentParser(
        description="文件重命名工具 - 根据分类重命名并整理文件"
    )
    parser.add_argument("-i", "--input", required=True, help="分类结果JSON文件路径")
    parser.add_argument("-o", "--output", required=True, help="输出目录路径")
    parser.add_argument("--move", action="store_true", help="移动文件（默认是复制）")
    parser.add_argument("--report", default="rename_report.json", help="报告输出路径")

    args = parser.parse_args()

    # 加载分类结果
    if not os.path.exists(args.input):
        print(f"错误: 文件不存在 {args.input}")
        return

    with open(args.input, "r", encoding="utf-8") as f:
        classification_data = json.load(f)

    print(f"📂 输入: {args.input}")
    print(f"📁 输出: {args.output}")
    print(f"📋 模式: {'移动' if args.move else '复制'}\n")

    # 转换分类数据结构：{类型: [{original_file}, ...]}
    classified_files = {}
    for category, data in classification_data.get("categories", {}).items():
        if isinstance(data, dict) and "files" in data:
            classified_files[category] = data["files"]
        elif isinstance(data, list):
            classified_files[category] = [f.get("original_file", f) if isinstance(f, dict) else f for f in data]

    # 执行重命名
    print("=" * 50)
    results = rename_and_organize(classified_files, args.output, copy_mode=not args.move)

    # 统计
    print("\n" + "=" * 50)
    print("📊 重命名统计:")
    total = 0
    for category in classified_files.keys():
        count = len(classified_files[category])
        abbr = TYPE_ABBREVIATIONS.get(category, "???")
        print(f"  {abbr}: {count} 个文件")
        total += count

    success = sum(1 for files in results.values() for f in files if f["status"] == "success")
    failed = sum(1 for files in results.values() for f in files if f["status"] == "failed")
    print(f"\n总计: {total} 文件 | ✅ {success} | ❌ {failed}")

    # 保存报告
    save_rename_report(results, args.report)


if __name__ == "__main__":
    main()

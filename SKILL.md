---
name: gaoqi-material-organizer
description: |
  高新技术企业材料整理智能体。当用户需要整理高企（高新技术企业）认定材料、归档证明文件、按产品分类整理材料时使用本技能。
  适用场景：整理评审材料、归档产品证书、整理产品资料、按产品线分类证明材料、整理客户原始数据。
  使用条件：已部署 Ollama 本地模型服务，地址：http://192.168.1.26:11434/
---

# 高企材料整理智能体

将客户提供的证明材料目录，自动识别并分类到8种固定产品类型，同时重命名混乱的文件名。

## 8种产品分类

| 类型 | 缩写 | 说明 |
|------|------|------|
| 产品图片 | IMG | 产品外观、实拍照片 |
| 产品证书 | CERT | 证书、认证、资质、ISO、3C等 |
| 产品生产批文 | LIC | 批文、许可、生产许可证、注册证 |
| 产品生产工艺及特色亮点 | PROC | 工艺流程、特点优势、配方技术参数 |
| 近三年产品检测报告 | TEST | 检测、检验、质检报告 |
| 近三年销售合同 | CONT | 合同、协议、采购订单 |
| 近三年销售发票 | INVO | 发票、增值税专用发票 |
| 用户使用报告 | REPO | 使用报告、用户反馈、体验报告 |

## 核心脚本

### pipeline.py - 主程序入口（推荐使用）

使用 Ollama 视觉模型进行智能分类的完整流水线。

**核心流程：**
1. 遍历输入目录所有支持的文件
2. 判断文件类型：
   - 图片文件 (.jpg, .png 等) → 直接用 Ollama 分类
   - 文档文件 (.pdf, .docx) → 转换为第一页图片 → 用 Ollama 分类
3. 分类完成后重命名并移动到对应目录

**使用方法：**
```bash
cd C:\Users\Administrator\.claude\skills\gaoqi-material-organizer
D:\Python311\python.exe scripts\pipeline.py -i "客户原始数据目录" -o "整理结果目录"
```

**参数说明：**
- `-i, --input`: 输入目录（客户原始数据）
- `-o, --output`: 输出目录（整理结果）
- `--copy-mode`: 复制模式（默认True，移动为False）
- `--skip-existing`: 跳过已处理文件（默认True）
- `--debug`: 调试模式

**示例：**
```bash
D:\Python311\python.exe scripts\pipeline.py -i "C:\Users\Administrator\Desktop\霍山回音必\客户原始数据" -o "C:\Users\Administrator\Desktop\霍山回音必\整理结果"
```

### ollama_vision_classify.py - Ollama视觉分类模块

使用 Ollama 视觉模型识别图片内容并分类：
- `classify_image()` - 核心分类函数
- `is_image_file()` - 判断是否为图片文件
- `key_to_category` - 类型关键词映射
- `extract_structured_info()` - 提取结构化信息
- `generate_filename_from_info()` - 生成规范化文件名

### document_to_image.py - 文档转图片模块

将 PDF/DOCX 文档转换为图片：
- `convert_first_page_to_image()` - 转换文档第一页为图片
- `is_document_file()` - 判断是否为文档文件

### rename_files.py - 文件重命名模块

命名规则：
```
{产品编号}_{类型缩写}_{序号}.{扩展名}
```

示例：
- `P001_CERT_001.pdf`
- `P002_TEST_001.pdf`

## 工作流程

1. **扫描源目录** → 读取所有文件
2. **初步分类** → 按扩展名和文件大小初步判断
3. **深度识别** → 使用 Ollama 分析内容
4. **确认分类** → 输出分类结果供确认
5. **执行整理** → 复制/移动到目标目录

## 使用方式

```
用户说："帮我整理这个目录的材料"
用户说："按照产品分类这些文件"
用户说："把高企认定材料归档"
```

## 目录结构

```
gaoqi-material-organizer/
├── SKILL.md
├── scripts/
│   ├── pipeline.py              # 主程序入口（推荐使用）
│   ├── ollama_vision_classify.py # Ollama视觉分类
│   ├── document_to_image.py      # 文档转图片
│   └── rename_files.py           # 文件重命名
└── references/
    └── 产品分类说明.md
```

## Python环境要求

- Python路径：`D:\Python311\python.exe`
- 或使用：`where python` 查找系统Python路径
- 必需依赖：pillow, pypdf 等（pip install pillow pypdf）

## 注意事项

- 处理前先备份原始数据
- 分类结果需用户确认后再执行移动
- 支持的文件格式：PDF, JPG, PNG, DOC, DOCX
- 最大支持文件：100MB

# CSV / XLSX 整理交付样例

全部样例数据为虚构，仅演示技术能力，没有真实客户、真实订单或收入。

将最多 5 份平面 CSV / XLSX 表合并，按约定规则整理为 Excel、CSV 和异常报告。样例字段为 `record_id, date, amount, currency, description`，可通过 `sample/config.json` 配置中英文列名、日期格式、支持币种和行数上限。

## 运行

在项目根目录（`revenue-250-20260907`）运行：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r service/requirements.txt
.venv/bin/python service/clean_tables.py service/sample/batch-a.csv service/sample/batch-b.csv --config service/sample/config.json --out service/my-demo-output
.venv/bin/python -m unittest discover -s service -p 'test_*.py' -v
```

输出目录必须不存在；不覆盖输入或上一次交付。程序运行期间不发送数据到网络，也不需要 AI API。依赖安装需要下载公开 Python 包。

## 预期样例结果

12 条输入 → 5 条接受 + 1 条重复隔离 + 6 条待复核。接受行的汇总为 USD 110.30、CNY 88.00。金额有冲突的 `0002` 两条记录均进入异常表；不擅自选较早、较晚或较大的一条。

| 文件 | 用途 |
|---|---|
| `cleaned.xlsx` | Clean / Duplicates / Exceptions / Summary 四个工作表 |
| `cleaned.csv` | 标准化数据，UTF-8 BOM 编码 |
| `duplicates.csv` | 重复行原值与保留行来源 |
| `exceptions.csv` | 异常原值、理由和来源记录编号 |
| `summary.json` | 记录数核对、分币种金额、输入和配置 SHA-256 |
| `report.html` | 可直接在浏览器打开的验收报告 |

## 清洗规则

- 标识符按文本处理，保留文本中的前导零。XLSX 中用数字单元格配合 `0000` 格式显示的标识符会进入异常，避免把 `0001` 静默改成 `1`。请先确认真实标识符规则。
- 表头必须唯一。必填字段是标识符、日期、金额、币种。`description` 可缺省。
- 只使用明确配置的日期格式。同一字符串能解析成两个不同日期时进入异常；不猜月/日顺序。
- 样例只接受至多 2 位小数、绝对值小于 10^12 的普通十进制金额，不猜分隔符、不擅自舍入。退款可为负数。其他币种精度需要单独配置和实现。
- 使用 Decimal 核对汇总，不合计不同币种，不做汇率转换。Excel 明细金额为数值单元格；精确汇总在 JSON 和 Summary 文本单元格中。
- `record_id` 是这份样例的全局唯一键。同键且五个标准字段一致才算重复；同键任一行无效或内容有差异，整组进入异常。实际项目若使用“平台 + 订单号”等复合键，需要先约定并调整实现。
- 输入空白记录不计入记录总数。CSV 的 `source_record` 是逻辑记录序号，表头为第 1 条；多行引号字段不按物理文本行数计数。
- 公式不求值。公式样式的文本不会作为 Excel 公式执行；CSV 里的危险文本加前导单引号，XLSX 强制文本类型。原值可由异常审计字段/未改动的原始文件复核。
- 未映射的额外列不进入标准结果。原始文件保持不变；异常表也保存原始列值与表头来源。

## 当前边界

不包含扫描件 OCR、PDF 表格识别、Google Sheets 账号连接、宏执行或现有复杂 Excel 模板的保真编辑。多工作表 XLSX 必须显式指定 `xlsx_sheet`；当前一次运行所有 XLSX 使用同名工作表。每个输入最多 10 MiB，总计最多 50,000 条非空记录。

发生异常不会自动改写客户数据；需要客户确认后再调整规则重跑。输出报告的金额只覆盖接受行，不能当成整个业务数据集已核对一致的证明。客户交付前还要用其脱敏样本和约定验收案例验证。

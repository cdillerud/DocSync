from pathlib import Path
import xml.etree.ElementTree as ET

TARGET = Path("bc-extension/zetadocs-replacement/src/reportlayout/GPIPrepaymentNotice.rdl")
NS = "http://schemas.microsoft.com/sqlserver/reporting/2016/01/reportdefinition"
RD = "http://schemas.microsoft.com/SQLServer/reporting/reportdesigner"
ET.register_namespace("", NS)
ET.register_namespace("rd", RD)


def q(tag):
    return f"{{{NS}}}{tag}"


def child(parent, tag, text=None, **attrs):
    node = ET.SubElement(parent, q(tag), attrs)
    if text is not None:
        node.text = text
    return node


def named(root, tag, name):
    for node in root.iter(q(tag)):
        if node.get("Name") == name:
            return node
    raise RuntimeError(f"{tag} {name} not found")


def set_text(node, tag, value):
    target = node.find(q(tag))
    if target is None:
        target = child(node, tag)
    target.text = value


def value_node(textbox):
    node = textbox.find(f".//{q('Value')}")
    if node is None:
        raise RuntimeError(f"Value missing on {textbox.get('Name')}")
    return node


def textbox(name, value, header=False, align="Center", font_size="7.4pt", bottom_border=False):
    tb = ET.Element(q("Textbox"), {"Name": name})
    child(tb, "CanGrow", "true")
    paragraphs = child(tb, "Paragraphs")
    paragraph = child(paragraphs, "Paragraph")
    runs = child(paragraph, "TextRuns")
    run = child(runs, "TextRun")
    child(run, "Value", value)
    if header:
        rs = child(run, "Style")
        child(rs, "FontWeight", "Bold")
    ps = child(paragraph, "Style")
    child(ps, "TextAlign", align)
    style = child(tb, "Style")
    child(style, "FontFamily", "Arial")
    child(style, "FontSize", font_size)
    if header:
        child(style, "BackgroundColor", "#D9D9D9")
    if bottom_border:
        border = child(style, "BottomBorder")
        child(border, "Style", "Solid")
        child(border, "Color", "#808080")
        child(border, "Width", "0.75pt")
    else:
        border = child(style, "Border")
        child(border, "Style", "None")
    for tag, val in (
        ("PaddingLeft", "2pt"),
        ("PaddingRight", "2pt"),
        ("PaddingTop", "3pt"),
        ("PaddingBottom", "2pt"),
    ):
        child(style, tag, val)
    return tb


def cell(tb):
    cell_node = ET.Element(q("TablixCell"))
    contents = child(cell_node, "CellContents")
    contents.append(tb)
    return cell_node


def summary_table():
    widths = ("1.05in", "1.25in", "1.55in", "1.5in", "2.45in")
    headers = ("Customer No.", "Customer P.O.", "Shipping Method", "FOB", "Terms")
    values = (
        '=First(Fields!CustomerNo.Value,"DataSet_Result")',
        '=First(Fields!CustomerPONo.Value,"DataSet_Result")',
        '=First(Fields!ShipmentMethodDescription.Value,"DataSet_Result")',
        '=First(Fields!FOBText.Value,"DataSet_Result")',
        '=First(Fields!PaymentTermsDescription.Value,"DataSet_Result")',
    )

    table = ET.Element(q("Tablix"), {"Name": "SummaryTable"})
    body = child(table, "TablixBody")
    columns = child(body, "TablixColumns")
    for width in widths:
        col = child(columns, "TablixColumn")
        child(col, "Width", width)

    rows = child(body, "TablixRows")
    header_row = child(rows, "TablixRow")
    child(header_row, "Height", "0.22in")
    header_cells = child(header_row, "TablixCells")
    for index, text in enumerate(headers, start=1):
        header_cells.append(cell(textbox(f"SH{index}", text, header=True)))

    value_row = child(rows, "TablixRow")
    child(value_row, "Height", "0.42in")
    value_cells = child(value_row, "TablixCells")
    for index, expression in enumerate(values, start=1):
        value_cells.append(cell(textbox(f"SV{index}", expression, bottom_border=True)))

    column_hierarchy = child(table, "TablixColumnHierarchy")
    members = child(column_hierarchy, "TablixMembers")
    for _ in widths:
        child(members, "TablixMember")

    row_hierarchy = child(table, "TablixRowHierarchy")
    row_members = child(row_hierarchy, "TablixMembers")
    child(row_members, "TablixMember")
    child(row_members, "TablixMember")

    child(table, "DataSetName", "DataSet_Result")
    child(table, "Top", "2.48in")
    child(table, "Left", "0in")
    child(table, "Height", "0.64in")
    child(table, "Width", "7.8in")
    style = child(table, "Style")
    border = child(style, "Border")
    child(border, "Style", "None")
    return table


tree = ET.parse(TARGET)
root = tree.getroot()

logo = named(root, "Image", "Logo")
set_text(logo, "Height", "0.58in")
set_text(logo, "Width", "2.55in")

tagline = named(root, "Textbox", "Tagline")
set_text(tagline, "Top", "0.64in")
set_text(tagline, "Left", "0.08in")
set_text(tagline, "Height", "0.18in")
set_text(tagline, "Width", "3.0in")
tagline_size = tagline.find(f".//{q('FontSize')}")
if tagline_size is not None:
    tagline_size.text = "8pt"

title = named(root, "Textbox", "Title")
set_text(title, "Top", "0.06in")
set_text(title, "Left", "4.35in")
set_text(title, "Height", "0.34in")
set_text(title, "Width", "3.45in")
title_size = title.find(f".//{q('FontSize')}")
title_color = title.find(f".//{q('Color')}")
if title_size is not None:
    title_size.text = "17pt"
if title_color is not None:
    title_color.text = "#8C8C8C"

order_info = named(root, "Textbox", "OrderInfo")
set_text(order_info, "Top", "0.72in")

bill_to = named(root, "Textbox", "BillToAddress")
ship_to = named(root, "Textbox", "ShipToAddress")
for block, prefix in ((bill_to, "BillTo"), (ship_to, "ShipTo")):
    set_text(block, "Top", "1.25in")
    set_text(block, "Height", "0.84in")
    value = value_node(block)
    old = f'IIF(First(Fields!{prefix}Country.Value,"DataSet_Result")="","",vbCrLf & First(Fields!{prefix}Country.Value,"DataSet_Result"))'
    new = (
        f'IIF(First(Fields!{prefix}Country.Value,"DataSet_Result")="" Or '
        f'UCase(First(Fields!{prefix}Country.Value,"DataSet_Result"))="US" Or '
        f'UCase(First(Fields!{prefix}Country.Value,"DataSet_Result"))="USA","",'
        f'vbCrLf & First(Fields!{prefix}Country.Value,"DataSet_Result"))'
    )
    if old not in value.text:
        raise RuntimeError(f"Country expression not found for {prefix}")
    value.text = value.text.replace(old, new)

for name in ("BillToLabel", "ShipToLabel", "RepInfo"):
    set_text(named(root, "Textbox", name), "Top", "1.25in")
set_text(named(root, "Textbox", "RepInfo"), "Height", "0.84in")
set_text(named(root, "Textbox", "ConfirmTo"), "Top", "2.18in")

report_items = root.find(f".//{q('Body')}/{q('ReportItems')}")
summary_bar = named(root, "Textbox", "SummaryBar")
insert_at = list(report_items).index(summary_bar)
report_items.remove(summary_bar)
report_items.insert(insert_at, summary_table())

lines = named(root, "Tablix", "LinesTable")
set_text(lines, "Top", "3.25in")
set_text(lines, "Height", "0.68in")
line_widths = ("1.25in", "2.95in", "0.5in", "0.45in", "0.7in", "0.85in", "1.1in")
columns = lines.find(f"{q('TablixBody')}/{q('TablixColumns')}")
for col, width in zip(list(columns), line_widths):
    set_text(col, "Width", width)

for name in ("D1", "D2", "D3", "D4", "D5", "D6", "D7"):
    tb = named(root, "Textbox", name)
    if tb.find(q("CanGrow")) is None:
        tb.insert(0, ET.Element(q("CanGrow")))
        tb.find(q("CanGrow")).text = "true"
    style = tb.find(q("Style"))
    if style is None:
        style = child(tb, "Style")
    existing = {node.tag.split("}")[-1] for node in list(style)}
    if "FontFamily" not in existing:
        child(style, "FontFamily", "Arial")
    if "FontSize" not in existing:
        child(style, "FontSize", "7.5pt")
    if "Border" not in existing:
        border = child(style, "Border")
        child(border, "Style", "None")
    for tag, val in (
        ("PaddingLeft", "2pt"),
        ("PaddingRight", "2pt"),
        ("PaddingTop", "3pt"),
        ("PaddingBottom", "2pt"),
    ):
        if tag not in existing:
            child(style, tag, val)

set_text(named(root, "Textbox", "Totals"), "Top", "4.70in")
set_text(named(root, "Textbox", "PrepaymentRequired"), "Top", "5.45in")
set_text(named(root, "Textbox", "AmountDue"), "Top", "5.80in")
set_text(named(root, "Textbox", "Instructions"), "Top", "6.18in")
set_text(named(root, "Textbox", "Instructions"), "Height", "1.10in")
set_text(named(root, "Textbox", "Contact"), "Top", "7.42in")

tree.write(TARGET, encoding="utf-8", xml_declaration=True)
print(f"Updated {TARGET}")

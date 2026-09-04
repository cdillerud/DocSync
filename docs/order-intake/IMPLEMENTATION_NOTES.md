# Implementation notes

The Giovanni workbook is a large historical worksheet. The parser should avoid repeated random access in openpyxl read-only mode; fixture validation should use normal workbook loading or a single-pass row iterator.

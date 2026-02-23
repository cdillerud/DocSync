import React, { useState, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { toast } from "sonner";
import { Upload, FileSpreadsheet, AlertCircle, CheckCircle2, Loader2, Download, ChevronRight, Info } from "lucide-react";
import api from "@/lib/api";

const INGESTION_TYPES = [
  { value: "sales_order", label: "Sales Orders", description: "Import customer POs as order headers and lines" },
  { value: "inventory_position", label: "Inventory Positions", description: "Import inventory snapshot data" },
  { value: "customer_item", label: "Customer Items", description: "Import customer SKU mappings" }
];

export default function FileImportPage() {
  const [file, setFile] = useState(null);
  const [ingestionType, setIngestionType] = useState("sales_order");
  const [sheetName, setSheetName] = useState("");
  const [sheets, setSheets] = useState([]);
  const [customerId, setCustomerId] = useState("");
  const [warehouseId, setWarehouseId] = useState("");
  const [loading, setLoading] = useState(false);
  const [importing, setImporting] = useState(false);
  const [parseResult, setParseResult] = useState(null);
  const [importResult, setImportResult] = useState(null);
  const [columnMappings, setColumnMappings] = useState(null);
  const [activeTab, setActiveTab] = useState("upload");

  // Fetch column mappings when ingestion type changes
  const fetchColumnMappings = useCallback(async (type) => {
    try {
      const response = await api.get(`/api/sales/file-import/column-mappings?ingestion_type=${type}`);
      setColumnMappings(response.data);
    } catch (err) {
      console.error("Failed to fetch column mappings:", err);
    }
  }, []);

  React.useEffect(() => {
    fetchColumnMappings(ingestionType);
  }, [ingestionType, fetchColumnMappings]);

  const handleFileChange = async (e) => {
    const selectedFile = e.target.files[0];
    if (!selectedFile) return;
    
    setFile(selectedFile);
    setParseResult(null);
    setImportResult(null);
    setSheets([]);
    setSheetName("");

    // For Excel files, get sheet names
    if (selectedFile.name.endsWith('.xlsx') || selectedFile.name.endsWith('.xls')) {
      try {
        const formData = new FormData();
        formData.append('file', selectedFile);
        const response = await api.post('/api/sales/file-import/excel-sheets', formData, {
          headers: { 'Content-Type': 'multipart/form-data' }
        });
        setSheets(response.data.sheets || []);
        if (response.data.sheets?.length > 0) {
          setSheetName(response.data.sheets[0]);
        }
      } catch (err) {
        console.error("Failed to get Excel sheets:", err);
      }
    }
  };

  const handleParse = async () => {
    if (!file) {
      toast.error("Please select a file first");
      return;
    }

    setLoading(true);
    setParseResult(null);
    setImportResult(null);

    try {
      const formData = new FormData();
      formData.append('file', file);
      formData.append('ingestion_type', ingestionType);
      if (sheetName) {
        formData.append('sheet_name', sheetName);
      }

      const response = await api.post('/api/sales/file-import/parse', formData, {
        headers: { 'Content-Type': 'multipart/form-data' }
      });

      setParseResult(response.data);
      setActiveTab("preview");
      
      if (response.data.success) {
        toast.success(`Parsed ${response.data.rows_valid} valid rows`);
      } else {
        toast.error(response.data.error || "Failed to parse file");
      }
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed to parse file");
    } finally {
      setLoading(false);
    }
  };

  const handleImport = async (dryRun = true) => {
    if (!file || !parseResult?.success) {
      toast.error("Please parse a valid file first");
      return;
    }

    setImporting(true);

    try {
      const formData = new FormData();
      formData.append('file', file);
      if (sheetName) formData.append('sheet_name', sheetName);
      formData.append('dry_run', dryRun);
      if (customerId) formData.append('customer_id', customerId);
      if (warehouseId) formData.append('warehouse_id', warehouseId);

      const endpoint = ingestionType === "sales_order" 
        ? '/api/sales/file-import/import-orders'
        : '/api/sales/file-import/import-inventory';

      const response = await api.post(endpoint, formData, {
        headers: { 'Content-Type': 'multipart/form-data' }
      });

      setImportResult(response.data);
      setActiveTab("result");

      if (response.data.success) {
        if (dryRun) {
          toast.success("Preview generated. Review and confirm to import.");
        } else {
          toast.success(`Successfully imported ${response.data.orders_created || response.data.positions_created || 0} records`);
        }
      } else {
        toast.error(response.data.error || "Import failed");
      }
    } catch (err) {
      toast.error(err.response?.data?.detail || "Import failed");
    } finally {
      setImporting(false);
    }
  };

  const renderColumnMappingGuide = () => {
    if (!columnMappings) return null;

    return (
      <Card className="mt-4">
        <CardHeader className="pb-3">
          <CardTitle className="text-sm flex items-center gap-2">
            <Info className="h-4 w-4" />
            Expected Columns for {INGESTION_TYPES.find(t => t.value === ingestionType)?.label}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <h4 className="font-medium text-sm text-red-400 mb-2">Required Columns</h4>
              <ul className="text-sm space-y-1">
                {columnMappings.required_columns?.map(col => (
                  <li key={col} className="flex items-center gap-2">
                    <Badge variant="destructive" className="text-xs">{col}</Badge>
                    <span className="text-muted-foreground text-xs">
                      ({columnMappings.known_column_aliases?.[col]?.slice(0, 3).join(', ')}...)
                    </span>
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <h4 className="font-medium text-sm text-green-400 mb-2">Optional Columns</h4>
              <ul className="text-sm space-y-1">
                {columnMappings.optional_columns?.slice(0, 5).map(col => (
                  <li key={col} className="text-muted-foreground">{col}</li>
                ))}
                {columnMappings.optional_columns?.length > 5 && (
                  <li className="text-muted-foreground">+{columnMappings.optional_columns.length - 5} more...</li>
                )}
              </ul>
            </div>
          </div>
        </CardContent>
      </Card>
    );
  };

  const renderPreviewTable = () => {
    if (!parseResult?.preview_data?.length) return null;

    const columns = Object.keys(parseResult.column_mapping || {});
    const data = parseResult.preview_data.slice(0, 20);

    return (
      <ScrollArea className="h-[400px]">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-10">#</TableHead>
              {columns.map(col => (
                <TableHead key={col} className="whitespace-nowrap">
                  {col}
                  <span className="text-xs text-muted-foreground block">
                    {parseResult.column_mapping[col]}
                  </span>
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.map((row, idx) => (
              <TableRow key={idx}>
                <TableCell className="text-muted-foreground">{idx + 1}</TableCell>
                {columns.map(col => (
                  <TableCell key={col} className="max-w-[200px] truncate">
                    {row[col] || '-'}
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
        {parseResult.preview_data.length > 20 && (
          <div className="text-center text-sm text-muted-foreground py-2">
            Showing 20 of {parseResult.preview_data.length} rows
          </div>
        )}
      </ScrollArea>
    );
  };

  const renderValidationErrors = () => {
    if (!parseResult?.validation_errors?.length) return null;

    return (
      <Alert variant="destructive" className="mt-4">
        <AlertCircle className="h-4 w-4" />
        <AlertDescription>
          <div className="font-medium mb-2">{parseResult.validation_errors.length} validation errors:</div>
          <ScrollArea className="h-[150px]">
            <ul className="text-sm space-y-1">
              {parseResult.validation_errors.slice(0, 20).map((err, idx) => (
                <li key={idx}>
                  Row {err.row}: <span className="text-red-400">{err.field}</span> - {err.error}
                </li>
              ))}
              {parseResult.validation_errors.length > 20 && (
                <li className="text-muted-foreground">
                  +{parseResult.validation_errors.length - 20} more errors...
                </li>
              )}
            </ul>
          </ScrollArea>
        </AlertDescription>
      </Alert>
    );
  };

  return (
    <div className="space-y-6" data-testid="file-import-page">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Sales File Import</h1>
          <p className="text-muted-foreground">Import sales orders and inventory from Excel/CSV files</p>
        </div>
      </div>

      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList>
          <TabsTrigger value="upload" data-testid="tab-upload">1. Upload</TabsTrigger>
          <TabsTrigger value="preview" data-testid="tab-preview" disabled={!parseResult}>2. Preview</TabsTrigger>
          <TabsTrigger value="result" data-testid="tab-result" disabled={!importResult}>3. Result</TabsTrigger>
        </TabsList>

        <TabsContent value="upload" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <FileSpreadsheet className="h-5 w-5" />
                Select File
              </CardTitle>
              <CardDescription>Upload an Excel (.xlsx) or CSV (.csv) file</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid gap-4 md:grid-cols-2">
                <div className="space-y-2">
                  <Label>Import Type</Label>
                  <Select value={ingestionType} onValueChange={setIngestionType}>
                    <SelectTrigger data-testid="select-ingestion-type">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {INGESTION_TYPES.map(type => (
                        <SelectItem key={type.value} value={type.value}>
                          <div>
                            <div>{type.label}</div>
                            <div className="text-xs text-muted-foreground">{type.description}</div>
                          </div>
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                <div className="space-y-2">
                  <Label>File</Label>
                  <Input
                    type="file"
                    accept=".csv,.xlsx,.xls"
                    onChange={handleFileChange}
                    data-testid="file-input"
                  />
                </div>

                {sheets.length > 0 && (
                  <div className="space-y-2">
                    <Label>Excel Sheet</Label>
                    <Select value={sheetName} onValueChange={setSheetName}>
                      <SelectTrigger data-testid="select-sheet">
                        <SelectValue placeholder="Select sheet" />
                      </SelectTrigger>
                      <SelectContent>
                        {sheets.map(sheet => (
                          <SelectItem key={sheet} value={sheet}>{sheet}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                )}

                {ingestionType === "sales_order" && (
                  <div className="space-y-2">
                    <Label>Default Customer ID (optional)</Label>
                    <Input
                      value={customerId}
                      onChange={(e) => setCustomerId(e.target.value)}
                      placeholder="cust_xxxxx"
                      data-testid="customer-id-input"
                    />
                  </div>
                )}

                {ingestionType === "inventory_position" && (
                  <>
                    <div className="space-y-2">
                      <Label>Default Customer ID (optional)</Label>
                      <Input
                        value={customerId}
                        onChange={(e) => setCustomerId(e.target.value)}
                        placeholder="cust_xxxxx"
                      />
                    </div>
                    <div className="space-y-2">
                      <Label>Default Warehouse ID (optional)</Label>
                      <Input
                        value={warehouseId}
                        onChange={(e) => setWarehouseId(e.target.value)}
                        placeholder="wh_xxxxx"
                      />
                    </div>
                  </>
                )}
              </div>

              {renderColumnMappingGuide()}

              <div className="flex justify-end">
                <Button
                  onClick={handleParse}
                  disabled={!file || loading}
                  data-testid="parse-btn"
                >
                  {loading ? (
                    <>
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      Parsing...
                    </>
                  ) : (
                    <>
                      <Upload className="mr-2 h-4 w-4" />
                      Parse File
                    </>
                  )}
                </Button>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="preview" className="space-y-4">
          {parseResult && (
            <>
              <div className="grid gap-4 md:grid-cols-4">
                <Card>
                  <CardContent className="pt-6">
                    <div className="text-2xl font-bold">{parseResult.rows_parsed}</div>
                    <div className="text-sm text-muted-foreground">Total Rows</div>
                  </CardContent>
                </Card>
                <Card>
                  <CardContent className="pt-6">
                    <div className="text-2xl font-bold text-green-500">{parseResult.rows_valid}</div>
                    <div className="text-sm text-muted-foreground">Valid Rows</div>
                  </CardContent>
                </Card>
                <Card>
                  <CardContent className="pt-6">
                    <div className="text-2xl font-bold text-red-500">{parseResult.rows_invalid}</div>
                    <div className="text-sm text-muted-foreground">Invalid Rows</div>
                  </CardContent>
                </Card>
                <Card>
                  <CardContent className="pt-6">
                    <div className="text-2xl font-bold">{Object.keys(parseResult.column_mapping || {}).length}</div>
                    <div className="text-sm text-muted-foreground">Mapped Columns</div>
                  </CardContent>
                </Card>
              </div>

              {parseResult.success ? (
                <Card>
                  <CardHeader>
                    <CardTitle>Data Preview</CardTitle>
                    <CardDescription>Review parsed data before importing</CardDescription>
                  </CardHeader>
                  <CardContent>
                    {renderPreviewTable()}
                  </CardContent>
                </Card>
              ) : (
                <Alert variant="destructive">
                  <AlertCircle className="h-4 w-4" />
                  <AlertDescription>{parseResult.error}</AlertDescription>
                </Alert>
              )}

              {renderValidationErrors()}

              {parseResult.warnings?.length > 0 && (
                <Alert>
                  <Info className="h-4 w-4" />
                  <AlertDescription>
                    <ul className="list-disc list-inside">
                      {parseResult.warnings.map((w, i) => <li key={i}>{w}</li>)}
                    </ul>
                  </AlertDescription>
                </Alert>
              )}

              <div className="flex justify-end gap-2">
                <Button variant="outline" onClick={() => setActiveTab("upload")}>
                  Back
                </Button>
                <Button
                  onClick={() => handleImport(true)}
                  disabled={!parseResult.success || importing}
                  variant="secondary"
                  data-testid="preview-import-btn"
                >
                  {importing ? (
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  ) : null}
                  Preview Import
                </Button>
                <Button
                  onClick={() => handleImport(false)}
                  disabled={!parseResult.success || importing}
                  data-testid="confirm-import-btn"
                >
                  {importing ? (
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  ) : (
                    <CheckCircle2 className="mr-2 h-4 w-4" />
                  )}
                  Confirm Import
                </Button>
              </div>
            </>
          )}
        </TabsContent>

        <TabsContent value="result" className="space-y-4">
          {importResult && (
            <>
              {importResult.success ? (
                <Alert className="border-green-500/50 bg-green-500/10">
                  <CheckCircle2 className="h-4 w-4 text-green-500" />
                  <AlertDescription>
                    {importResult.dry_run ? (
                      <span>Preview complete. {importResult.orders_created || importResult.positions_created} records would be created.</span>
                    ) : (
                      <span>Successfully imported {importResult.orders_created || importResult.positions_created} records!</span>
                    )}
                  </AlertDescription>
                </Alert>
              ) : (
                <Alert variant="destructive">
                  <AlertCircle className="h-4 w-4" />
                  <AlertDescription>{importResult.error}</AlertDescription>
                </Alert>
              )}

              <div className="grid gap-4 md:grid-cols-3">
                {ingestionType === "sales_order" && (
                  <>
                    <Card>
                      <CardContent className="pt-6">
                        <div className="text-2xl font-bold">{importResult.orders_created || 0}</div>
                        <div className="text-sm text-muted-foreground">Orders Created</div>
                      </CardContent>
                    </Card>
                    <Card>
                      <CardContent className="pt-6">
                        <div className="text-2xl font-bold">{importResult.lines_created || 0}</div>
                        <div className="text-sm text-muted-foreground">Order Lines</div>
                      </CardContent>
                    </Card>
                    <Card>
                      <CardContent className="pt-6">
                        <div className="text-2xl font-bold">{importResult.total_quantity?.toLocaleString() || 0}</div>
                        <div className="text-sm text-muted-foreground">Total Quantity</div>
                      </CardContent>
                    </Card>
                  </>
                )}
                {ingestionType === "inventory_position" && (
                  <>
                    <Card>
                      <CardContent className="pt-6">
                        <div className="text-2xl font-bold">{importResult.positions_created || 0}</div>
                        <div className="text-sm text-muted-foreground">Positions Created</div>
                      </CardContent>
                    </Card>
                    <Card>
                      <CardContent className="pt-6">
                        <div className="text-2xl font-bold">{importResult.total_on_hand?.toLocaleString() || 0}</div>
                        <div className="text-sm text-muted-foreground">Total On Hand</div>
                      </CardContent>
                    </Card>
                  </>
                )}
              </div>

              {importResult.preview && (
                <Card>
                  <CardHeader>
                    <CardTitle>Created Records Preview</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <pre className="text-xs bg-muted p-4 rounded overflow-auto max-h-[300px]">
                      {JSON.stringify(importResult.preview, null, 2)}
                    </pre>
                  </CardContent>
                </Card>
              )}

              <div className="flex justify-end gap-2">
                {importResult.dry_run ? (
                  <>
                    <Button variant="outline" onClick={() => setActiveTab("preview")}>
                      Back to Preview
                    </Button>
                    <Button onClick={() => handleImport(false)} disabled={importing} data-testid="final-import-btn">
                      {importing ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                      Confirm Import
                    </Button>
                  </>
                ) : (
                  <Button onClick={() => {
                    setFile(null);
                    setParseResult(null);
                    setImportResult(null);
                    setActiveTab("upload");
                  }}>
                    Import Another File
                  </Button>
                )}
              </div>
            </>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}

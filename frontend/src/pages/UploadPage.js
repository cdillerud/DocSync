import { useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { uploadDocument, getBcSalesOrders } from '../lib/api';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../components/ui/select';
import { toast } from 'sonner';
import { UploadCloud, FileText, X, CheckCircle2, Search, Loader2 } from 'lucide-react';

const DOC_TYPES = [
  { value: 'SalesOrder', label: 'Sales Order' },
  { value: 'SalesInvoice', label: 'Sales Invoice' },
  { value: 'PurchaseInvoice', label: 'Purchase Invoice' },
  { value: 'PurchaseOrder', label: 'Purchase Order' },
  { value: 'Shipment', label: 'Shipment' },
  { value: 'Receipt', label: 'Receipt' },
  { value: 'Other', label: 'Other' },
];

export default function UploadPage() {
  const [file, setFile] = useState(null);
  const [docType, setDocType] = useState('SalesOrder');
  const [bcOrderNo, setBcOrderNo] = useState('');
  const [uploading, setUploading] = useState(false);
  const [dragActive, setDragActive] = useState(false);
  const [searchResults, setSearchResults] = useState([]);
  const [searching, setSearching] = useState(false);
  const [selectedOrder, setSelectedOrder] = useState(null);
  const navigate = useNavigate();

  const handleDrag = useCallback((e) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(e.type === 'dragenter' || e.type === 'dragover');
  }, []);

  const handleDrop = useCallback((e) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    if (e.dataTransfer.files?.[0]) {
      setFile(e.dataTransfer.files[0]);
    }
  }, []);

  const handleFileSelect = (e) => {
    if (e.target.files?.[0]) {
      setFile(e.target.files[0]);
    }
  };

  const searchOrders = async () => {
    if (!bcOrderNo.trim()) return;
    setSearching(true);
    try {
      const res = await getBcSalesOrders(bcOrderNo);
      setSearchResults(res.data.orders || []);
      if (res.data.orders?.length === 0) {
        toast.info('No matching orders found. You can still type the order number and upload.');
      }
    } catch (err) {
      toast.warning('BC search unavailable — you can still type the order number manually and upload.', { duration: 5000 });
      setSearchResults([]);
    } finally {
      setSearching(false);
    }
  };

  const handleUpload = async () => {
    if (!file) {
      toast.error('Please select a file');
      return;
    }
    setUploading(true);
    try {
      const formData = new FormData();
      formData.append('file', file);
      formData.append('document_type', docType);
      if (selectedOrder) {
        formData.append('bc_record_id', selectedOrder.id);
        formData.append('bc_document_no', selectedOrder.number);
      } else if (bcOrderNo) {
        formData.append('bc_document_no', bcOrderNo);
      }
      formData.append('source', 'manual_upload');

      const res = await uploadDocument(formData);
      const status = res.data.document?.status;
      if (status === 'LinkedToBC') {
        toast.success('Document uploaded and linked to BC');
      } else if (status === 'Classified') {
        toast.success('Document uploaded to SharePoint. BC linking pending — can be retried later.');
      } else {
        toast.success('Document uploaded');
      }
      navigate(`/documents/${res.data.document.id}`);
    } catch (err) {
      toast.error('Upload failed: ' + (err.response?.data?.detail || err.message));
    } finally {
      setUploading(false);
    }
  };

  const formatSize = (bytes) => {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / 1048576).toFixed(1) + ' MB';
  };

  return (
    <div className="max-w-3xl mx-auto space-y-6" data-testid="upload-page">
      <div>
        <h2 className="text-2xl font-bold tracking-tight" style={{ fontFamily: 'Chivo, sans-serif' }}>Upload Document</h2>
        <p className="text-sm text-muted-foreground mt-1">Upload a file and link it to a Business Central record</p>
      </div>

      {/* File Drop Zone */}
      <Card className="border border-border" data-testid="upload-card">
        <CardContent className="p-6">
          <div
            className={`dropzone ${dragActive ? 'active' : ''}`}
            onDragEnter={handleDrag}
            onDragLeave={handleDrag}
            onDragOver={handleDrag}
            onDrop={handleDrop}
            onClick={() => document.getElementById('file-input').click()}
            data-testid="file-dropzone"
          >
            <input
              id="file-input"
              type="file"
              className="hidden"
              accept=".pdf,.png,.jpg,.jpeg,.tiff,.tif"
              onChange={handleFileSelect}
              data-testid="file-input"
            />
            {file ? (
              <div className="flex items-center gap-3 justify-center">
                <FileText className="w-8 h-8 text-primary" />
                <div className="text-left">
                  <p className="text-sm font-medium">{file.name}</p>
                  <p className="text-xs text-muted-foreground">{formatSize(file.size)}</p>
                </div>
                <Button
                  variant="ghost" size="icon" className="h-8 w-8 ml-2"
                  onClick={(e) => { e.stopPropagation(); setFile(null); }}
                  data-testid="remove-file-btn"
                >
                  <X className="w-4 h-4" />
                </Button>
              </div>
            ) : (
              <>
                <UploadCloud className="w-10 h-10 text-muted-foreground mx-auto mb-3" />
                <p className="text-sm font-medium">Drop a file here or click to browse</p>
                <p className="text-xs text-muted-foreground mt-1">PDF, PNG, JPG, TIFF accepted</p>
              </>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Document Type */}
      <Card className="border border-border" data-testid="doc-type-card">
        <CardHeader className="pb-3">
          <CardTitle className="text-base font-bold" style={{ fontFamily: 'Chivo, sans-serif' }}>Document Classification</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label>Document Type</Label>
            <Select value={docType} onValueChange={setDocType}>
              <SelectTrigger data-testid="doc-type-select">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {DOC_TYPES.map((t) => (
                  <SelectItem key={t.value} value={t.value} data-testid={`doc-type-option-${t.value}`}>{t.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </CardContent>
      </Card>

      {/* BC Record Linking */}
      <Card className="border border-border" data-testid="bc-linking-card">
        <CardHeader className="pb-3">
          <CardTitle className="text-base font-bold" style={{ fontFamily: 'Chivo, sans-serif' }}>Business Central Record</CardTitle>
          <CardDescription>Search for a BC Sales Order or type the number directly</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex gap-2">
            <div className="flex-1">
              <Input
                placeholder="Search by order number (e.g. SO-1001)"
                value={bcOrderNo}
                onChange={(e) => { setBcOrderNo(e.target.value); setSelectedOrder(null); }}
                onKeyDown={(e) => e.key === 'Enter' && searchOrders()}
                data-testid="bc-order-search-input"
              />
            </div>
            <Button variant="secondary" onClick={searchOrders} disabled={searching} data-testid="bc-order-search-btn">
              {searching ? <Loader2 className="w-4 h-4 animate-spin" /> : <Search className="w-4 h-4" />}
            </Button>
          </div>

          {searchResults.length > 0 && (
            <div className="border border-border rounded-lg divide-y divide-border" data-testid="bc-order-results">
              {searchResults.map((order) => (
                <button
                  key={order.id}
                  className={`w-full text-left px-4 py-3 hover:bg-accent transition-colors flex items-center justify-between ${selectedOrder?.id === order.id ? 'bg-primary/10 border-l-2 border-primary' : ''}`}
                  onClick={() => { setSelectedOrder(order); setBcOrderNo(order.number); }}
                  data-testid={`bc-order-item-${order.number}`}
                >
                  <div>
                    <span className="font-mono text-sm font-semibold">{order.number}</span>
                    <span className="text-sm text-muted-foreground ml-3">{order.customerName}</span>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="text-xs text-muted-foreground">{order.orderDate}</span>
                    {selectedOrder?.id === order.id && <CheckCircle2 className="w-4 h-4 text-primary" />}
                  </div>
                </button>
              ))}
            </div>
          )}

          {selectedOrder && (
            <div className="bg-muted/50 rounded-lg p-3 text-sm" data-testid="selected-order-info">
              <p className="font-medium">Selected: <span className="font-mono">{selectedOrder.number}</span></p>
              <p className="text-muted-foreground text-xs mt-0.5">{selectedOrder.customerName} &middot; {selectedOrder.status}</p>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Upload Button */}
      <div className="flex justify-end gap-3">
        <Button variant="secondary" onClick={() => navigate('/queue')} data-testid="cancel-upload-btn">Cancel</Button>
        <Button onClick={handleUpload} disabled={!file || uploading} data-testid="submit-upload-btn">
          {uploading ? (
            <span className="flex items-center gap-2">
              <Loader2 className="w-4 h-4 animate-spin" /> Processing...
            </span>
          ) : (
            <span className="flex items-center gap-2">
              <UploadCloud className="w-4 h-4" /> Upload & Process
            </span>
          )}
        </Button>
      </div>
    </div>
  );
}
